# -*- coding: utf-8 -*-
"""
AV/GARDEN Worker — 常驻下载队列轮询服务

从队列文件中读取车牌号，逐个下载、转码、刮削元数据。
与 Go 后端通过共享的队列文件 + SQLite 通信。
"""
import os
import sys
import time
import json
import signal
import shutil
import subprocess
import re
import urllib.request

# 把项目根加入 path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
from src.log_writer import write as log_write
from main_video import find_main_video
from process_control import clear_cancel_request, is_cancel_requested, terminate_active_process
from qb_file_selection import strict_priority_plan
from qb_task_guard import has_matching_qb_task, magnet_watch_interrupt
from queue_store import (
    append_unique,
    clear_if_matches,
    clear_download_target,
    get_download_target,
    pop_first,
    read_json,
    read_queue,
    update_json,
    write_queue,
)
from video_id import local_video_id_aliases, normalize_video_id, safe_video_dir

# 从 comm 加载配置
from src.comm import *
from src import downloaderMgr, data
from metadata import gen_nfo

# 环境变量覆盖配置
env_save_path = os.environ.get("SAVE_PATH")
env_queue_path = os.environ.get("QUEUE_PATH")
env_db_path = os.environ.get("DB_PATH")
env_proxy = os.environ.get("PROXY")

if env_save_path:
    save_path = env_save_path
if env_queue_path:
    queue_path = env_queue_path
if env_db_path:
    downloaded_path = env_db_path
if env_proxy:
    myproxy = env_proxy

queue_dir = os.path.dirname(queue_path) if os.path.dirname(queue_path) else "/db"
failed_queue_path = os.path.join(queue_dir, "failed_queue.txt")
failed_queue_json_path = os.path.join(queue_dir, "failed_queue.json")
download_targets_path = os.environ.get(
    "DOWNLOAD_TARGETS_PATH", os.path.join(queue_dir, "download_targets.json")
)
retry_file = os.path.join(os.path.dirname(queue_path) if os.path.dirname(queue_path) else "/db", "retry_counts.json")
MAX_RETRIES = 3
MAGNET_COMPLETED = "completed"
MAGNET_PENDING = "pending"
MAGNET_FAILED = "failed"
MAGNET_CANCELLED = "cancelled"

logger.info(f"[Worker] save_path={save_path}")
logger.info(f"[Worker] queue_path={queue_path}")
logger.info(f"[Worker] db_path={downloaded_path}")
logger.info(f"[Worker] proxy={myproxy}")

# 工作锁文件（与 main.py 共用，确保单例下载）
work_lock = os.path.join(project_root, "work")
current_download_path = os.environ.get("CURRENT_PATH", os.path.join(queue_dir, "current_download.txt"))

running = True


def signal_handler(sig, frame):
    global running
    logger.info("[Worker] Received signal, shutting down...")
    running = False
    terminate_active_process()


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def read_queue_first_line():
    """读取队列第一行并返回"""
    try:
        return pop_first(queue_path)
    except Exception as e:
        logger.error(f"[Worker] Error reading queue: {e}")
        return None


def set_current_download(avid):
    write_queue(current_download_path, [avid])


def clear_current_download(avid):
    clear_if_matches(current_download_path, avid)


def is_locked():
    """检查下载锁"""
    if not os.path.exists(work_lock):
        return False
    try:
        with open(work_lock, "r") as f:
            return f.read().strip() == "1"
    except:
        return False


def _load_failed_records():
    records = []
    try:
        data = read_json(failed_queue_json_path, [])
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code", "")).strip().upper()
                if not code:
                    continue
                records.append({
                    "code": code,
                    "failed_at": item.get("failed_at") or item.get("time") or "",
                    "retries": item.get("retries", MAX_RETRIES),
                })
            return records
    except Exception as e:
        logger.error(f"[Worker] Error reading failed queue json: {e}")

    if os.path.exists(failed_queue_path):
        try:
            mtime = os.path.getmtime(failed_queue_path)
            failed_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
            with open(failed_queue_path, "r", encoding="utf-8") as f:
                for line in f:
                    code = line.strip().upper()
                    if code:
                        records.append({
                            "code": code,
                            "failed_at": failed_at,
                            "retries": MAX_RETRIES,
                        })
        except Exception as e:
            logger.error(f"[Worker] Error reading legacy failed queue: {e}")
    return records


def record_failed_download(avid, reason="", recoverable=None):
    """记录最终失败，主存储为带时间戳的 failed_queue.json。"""
    from src.failure_recovery import is_transient_reason

    code = avid.upper().strip()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    retries = get_retries(code)
    reason = str(reason or "").strip()
    if recoverable is None:
        recoverable = is_transient_reason(reason)

    def record(records):
        records = records if isinstance(records, list) else []
        for item in records:
            if isinstance(item, dict) and str(item.get("code", "")).upper() == code:
                item["failed_at"] = now
                item["retries"] = retries
                item["reason"] = reason
                item["recoverable"] = bool(recoverable)
                break
        else:
            records.append({
                "code": code,
                "failed_at": now,
                "retries": retries,
                "reason": reason,
                "recoverable": bool(recoverable),
            })
        return records

    update_json(failed_queue_json_path, [], record)


def _handle_failure(avid, reason="下载失败"):
    """处理下载失败：记录重试次数，超过上限则放弃并通知飞书。

    前台 log_write 仅在最终放弃时写一条；中间重试只打 logger。
    瞬时/系统异常会标记 recoverable，启动与 heal 会自动捞回重试。
    """
    if has_active_qb_task(avid):
        logger.info(f"[Worker] {avid} qB 任务仍在进行，跳过失败记录和飞书通知")
        return False

    retries = incr_retry(avid)
    if retries >= MAX_RETRIES:
        logger.warning(f"[Worker] {avid} 失败 {retries} 次，放弃，写入失败队列 ({reason})")
        record_failed_download(avid, reason=reason)
        log_write("Worker", f"{avid} 失败: {reason}（已重试{retries}次）")
        notify_feishu_all_failed(avid, reason=reason)
    else:
        logger.warning(f"[Worker] {avid} 失败 ({retries}/{MAX_RETRIES})，放回队列重试 ({reason})")
        append_unique(queue_path, avid)
    return True

def _handle_magnet_unavailable(avid, reason="磁链暂不可用"):
    """有磁链但 qB 没有接住时，只按磁链路径重试，不回退在线流。"""
    if has_active_qb_task(avid):
        logger.info(f"[Worker] {avid} qB 任务仍在进行，跳过在线流")
        log_write("Worker", f"{avid} 已交 qB 后台继续下载")
        return False

    retries = incr_retry(avid)
    if retries >= MAX_RETRIES:
        logger.warning(f"[Worker] {avid} 磁链处理异常 {retries} 次，放弃 ({reason})")
        record_failed_download(avid, reason=reason)
        log_write("Worker", f"{avid} 失败: {reason}（已重试{retries}次）")
        notify_feishu_all_failed(avid, reason=reason)
    else:
        logger.warning(f"[Worker] {avid} 磁链暂不可用 ({retries}/{MAX_RETRIES})，放回队列重试 ({reason})")
        append_unique(queue_path, avid)
    return True

def has_active_qb_task(avid):
    """如果 qB 任意分类中已有同番号任务，不应再启动在线下载。"""
    try:
        torrents = qbittorrent_api("GET", "/api/v2/torrents/info")
    except Exception:
        return False
    if not isinstance(torrents, list):
        return False

    return has_matching_qb_task(torrents, avid, _completed_qb_task_has_main_video)


def _completed_qb_task_has_main_video(avid, torrent):
    candidates = [os.path.join(save_path, avid)]
    content_path = str(torrent.get("content_path") or "").strip()
    torrent_save_path = str(torrent.get("save_path") or "").strip()
    torrent_name = str(torrent.get("name") or "").strip()
    if content_path:
        candidates.append(content_path if os.path.isabs(content_path) else os.path.join(torrent_save_path, content_path))
    if torrent_save_path and os.path.basename(torrent_save_path.rstrip(os.sep)).upper() == avid:
        candidates.append(torrent_save_path)
    if torrent_save_path and torrent_name:
        candidates.append(os.path.join(torrent_save_path, torrent_name))

    root = os.path.realpath(save_path)
    target_aliases = set(local_video_id_aliases(avid))
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if os.path.isdir(path) and target_aliases.intersection(local_video_id_aliases(name)):
                candidates.append(path)
    except OSError:
        pass
    for path in candidates:
        real_path = os.path.realpath(path)
        try:
            if os.path.commonpath([root, real_path]) != root:
                continue
        except ValueError:
            continue
        if find_main_video(real_path):
            return True
    return False

def notify_feishu_all_failed(avid, reason=""):
    """最终失败时通过飞书通知（带真实原因，瞬时错误会标注可自动重试）。"""
    webhook = os.environ.get("FEISHU_WEBHOOK") or feishu_webhook
    if not webhook:
        return
    from src.failure_recovery import is_transient_reason

    reason = str(reason or "").strip() or "所有下载源均失败"
    if is_transient_reason(reason):
        detail = f"{reason}（系统/瞬时错误，启动或自愈将自动重试）"
    else:
        detail = f"{reason}（已重试{MAX_RETRIES}次）"
    msg = f"AV/GARDEN 下载失败\n番号: {avid}\n原因: {detail}"
    try:
        data = json.dumps({"msg_type": "text", "content": {"text": msg}}).encode()
        req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        try:
            resp.read()
            logger.info(f"[Feishu] Sent all-failed notification for {avid}")
        finally:
            resp.close()
    except Exception as e:
        logger.error(f"[Feishu] Failed to send notification: {e}")

def acquire_lock():
    """获取下载锁"""
    with open(work_lock, "w") as f:
        f.write("1")


def release_lock():
    """释放下载锁"""
    with open(work_lock, "w") as f:
        f.write("0")

def get_retries(avid):
    counts = read_json(retry_file, {})
    return counts.get(avid.upper(), 0) if isinstance(counts, dict) else 0

def incr_retry(avid):
    key = avid.upper()
    def increment(counts):
        counts = counts if isinstance(counts, dict) else {}
        counts[key] = counts.get(key, 0) + 1
        return counts
    counts = update_json(retry_file, {}, increment)
    return counts[key]

def clear_retry(avid):
    key = avid.upper()
    def clear(counts):
        counts = counts if isinstance(counts, dict) else {}
        counts.pop(key, None)
        return counts
    update_json(retry_file, {}, clear)


def get_magnet_from_weekly(avid):
    """Compatibility wrapper around the shared download-source resolver."""
    from download_source import resolve_download_source

    source = resolve_download_source(avid, proxy=myproxy)
    magnet = (source.get("magnet") or "").strip()
    size = float(source.get("size_gib") or 0)
    logger.info(
        f"[DownloadSource] {avid} selected {source.get('source') or 'unknown'}"
        + (f" ({size:.1f} GiB)" if size else "")
    )
    return magnet


def notify_feishu_magnet_timeout(avid, magnet):
    """磁链超时时通过飞书机器人通知"""
    webhook = os.environ.get("FEISHU_WEBHOOK") or feishu_webhook
    if not webhook:
        return
    msg = f"AV/GARDEN 磁链下载超时\n车牌号: {avid}\n磁链: {magnet}\n请手动复制到迅雷下载"
    try:
        data = json.dumps({"msg_type": "text", "content": {"text": msg}}).encode()
        req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        try:
            resp.read()
            logger.info(f"[Feishu] Sent timeout notification for {avid}")
        finally:
            resp.close()
    except Exception as e:
        logger.error(f"[Feishu] Failed to send notification: {e}")


def qbittorrent_api(method, endpoint, data=None):
    """调用 qBittorrent Web API，自动处理登录和 cookie"""
    from src.comm import qb_url, qb_username, qb_password
    import http.cookiejar

    if not qb_password:
        logger.error("[QBittorrent] QBITTORRENT_PASSWORD is not configured")
        return None
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    # 登录
    login_url = f"{qb_url}/api/v2/auth/login"
    login_data = f"username={urllib.parse.quote(qb_username)}&password={urllib.parse.quote(qb_password)}".encode()
    try:
        resp = opener.open(urllib.request.Request(login_url, data=login_data), timeout=10)
        try:
            if resp.status != 200:
                logger.error(f"[QBittorrent] Login failed: {resp.status}")
                return None
        finally:
            resp.close()
    except Exception as e:
        logger.error(f"[QBittorrent] Login error: {e}")
        return None

    # 执行实际请求
    full_url = f"{qb_url}{endpoint}"
    try:
        if method == "GET":
            req = urllib.request.Request(full_url)
        else:
            headers = {"Content-Type": "application/x-www-form-urlencoded"} if data else {}
            req = urllib.request.Request(full_url, data=data.encode() if data else b"", headers=headers, method="POST")
        resp = opener.open(req, timeout=30)
        try:
            body = resp.read().decode()
            # qB API 部分端点返回纯文本 "Ok." / "Fails."
            body_text = body.strip()
            if body_text == "Ok.":
                return True
            if body_text == "Fails.":
                return None
            if not body_text and method != "GET":
                return True
            return json.loads(body)
        finally:
            resp.close()
    except Exception as e:
        logger.error(f"[QBittorrent] API error {endpoint}: {e}")
        return None


def qbittorrent_post(endpoint, params):
    """发送 qBittorrent 表单 POST。"""
    return qbittorrent_api("POST", endpoint, urllib.parse.urlencode(params))


def qbittorrent_set_running(torrent_hash, running):
    """Support qB v5 start/stop and older resume/pause endpoints."""
    endpoints = ("start", "resume") if running else ("stop", "pause")
    for action in endpoints:
        result = qbittorrent_post(f"/api/v2/torrents/{action}", {"hashes": torrent_hash})
        if result is True:
            return True
    return False


def cancel_qb_tasks(avid, delete_files=False):
    """Cancel qBittorrent tasks for a video ID with safety checks."""
    torrents = qbittorrent_api("GET", "/api/v2/torrents/info?category=AV_GARDEN")
    if not isinstance(torrents, list):
        return False
    hashes = []
    for torrent in torrents:
        tags = {tag.strip().upper() for tag in str(torrent.get("tags", "")).split(",") if tag.strip()}
        candidates = set()
        for value in (torrent.get("name", ""), torrent.get("save_path", ""), torrent.get("content_path", "")):
            for token in re.findall(r"[A-Z0-9]+(?:[-_][A-Z0-9]+){0,2}", str(value).upper()):
                for variant in (token, re.sub(r"(?:[-_](?:C|CH)|CH)$", "", token)):
                    normalized = normalize_video_id(variant)
                    if normalized:
                        candidates.add(normalized)
        if avid in tags or avid in candidates:
            torrent_hash = str(torrent.get("hash", "")).strip()
            if torrent_hash:
                # Safety check before allowing file deletion
                if delete_files:
                    state = str(torrent.get("state", ""))
                    content_path = str(torrent.get("content_path", ""))

                    # Refuse deletion if torrent is active or seeding
                    if state in ("downloading", "stalledDL", "metaDL", "checkingDL", "checkingResumeData", "uploading", "stalledUP", "queuedUP", "checkingUP", "forcedUP"):
                        logger.warning(f"[Worker] Refuse to delete files for active/seeding torrent {avid} (state={state})")
                        continue

                    # Verify content_path is within save_path
                    if content_path:
                        try:
                            real_save = os.path.realpath(save_path)
                            real_content = os.path.realpath(content_path)
                            if os.path.commonpath([real_save, real_content]) != real_save:
                                logger.warning(f"[Worker] Refuse to delete files outside save_path: {content_path}")
                                delete_files = False
                        except (ValueError, OSError) as e:
                            logger.warning(f"[Worker] Path validation failed for {content_path}: {e}")
                            delete_files = False

                    # Check if content_path is used by other torrents
                    if content_path and delete_files:
                        for other in torrents:
                            if other.get("hash") == torrent_hash:
                                continue
                            other_path = str(other.get("content_path", ""))
                            if other_path and os.path.realpath(other_path) == os.path.realpath(content_path):
                                logger.warning(f"[Worker] Refuse to delete {content_path}: shared by torrent {other.get('hash', 'unknown')[:12]}")
                                delete_files = False
                                break

                hashes.append(torrent_hash)
    if not hashes:
        return False

    # Audit log before deletion
    if delete_files:
        logger.warning(f"[Worker] AUDIT: Deleting files for {avid}, hashes={','.join(h[:12] for h in hashes)}")

    result = bool(qbittorrent_post(
        "/api/v2/torrents/delete",
        {"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"},
    ))
    if delete_files and result:
        logger.info(f"[Worker] Deleted qB task(s) for {avid} with files (hashes={len(hashes)})")
        log_write("Cleanup", f"{avid} qB任务及文件已删除 (hashes={len(hashes)})")
    return result


def apply_largest_video_only(avid, torrent_hash):
    """严格只保留种子里最大的一个 MP4，其他文件全部禁用。"""
    if not torrent_hash:
        return False

    files = qbittorrent_api("GET", "/api/v2/torrents/files?hash=" + urllib.parse.quote(torrent_hash))
    if not isinstance(files, list):
        return False
    if not files:
        logger.info(f"[Magnet] {avid} file list not ready, waiting...")
        return False

    plan = strict_priority_plan(files)
    if not plan:
        logger.warning(f"[Magnet] {avid} no video file found in torrent, keep original file priorities")
        return True
    selected = plan["selected"]
    selected_index = selected["index"]
    skip_ids = [str(index) for index in plan["disabled"]]

    logger.info(
        f"[Magnet] {avid} selected strict largest video: {selected['name']} "
        f"({selected['size']/1024/1024:.1f} MB), disabling {len(skip_ids)} other files"
    )

    if not qbittorrent_set_running(torrent_hash, False):
        logger.warning(f"[Magnet] {avid} failed to stop torrent before strict file selection")
        return False
    try:
        if skip_ids:
            result = qbittorrent_post(
                "/api/v2/torrents/filePrio",
                {"hash": torrent_hash, "id": "|".join(skip_ids), "priority": "0"},
            )
            if result is None:
                logger.warning(f"[Magnet] {avid} failed to disable non-video files, will retry")
                return False

        result = qbittorrent_post(
            "/api/v2/torrents/filePrio",
            {"hash": torrent_hash, "id": str(selected_index), "priority": "1"},
        )
        if result is None:
            logger.warning(f"[Magnet] {avid} failed to keep selected video priority, will retry")
            return False
    finally:
        if not qbittorrent_set_running(torrent_hash, True):
            logger.error(f"[Magnet] {avid} failed to restart torrent after strict file selection")

    return True


def find_and_rename_output(save_dir, avid, qb_content_path=None):
    """
    qBittorrent 下载完成后，从 qb_content_path 找到最大视频，
    移到 save_dir/{avid}.mp4，不预先创建 save_dir。
    """
    search_dir = qb_content_path if qb_content_path and os.path.isdir(qb_content_path) else save_dir
    if not os.path.isdir(search_dir):
        return None

    src = find_main_video(search_dir)
    if not src:
        return None
    os.makedirs(save_dir, exist_ok=True)
    dst = os.path.join(save_dir, f"{avid}.mp4")
    src_real = os.path.realpath(src)
    dst_real = os.path.realpath(dst)
    if src_real != dst_real:
        if os.path.exists(dst):
            try:
                if os.path.samefile(src, dst):
                    return dst
            except OSError:
                pass
            logger.error(f"[Magnet] Refusing to overwrite existing output: {dst}")
            return None
        logger.info(f"[Magnet] Move {os.path.basename(src)} -> {avid}.mp4")
        shutil.move(src, dst)
    return dst


# 最近一次磁链路径的简短原因（供前台失败文案；明细仍在 logger）
_last_magnet_reason = ""


def try_magnet_download(avid, save_dir, magnet=None, target="qb"):
    """
    磁链下载：按用户选择的 target 分流。
    - target=qb  → 仅 qBittorrent
    - target=115 → 仅 115 云端离线（成功 PENDING；失败不回退 qB）

    返回 (status, torrent_hash)，status 为 MAGNET_* 。
    115 成功时 hash 为 None（本地由极空间备份）。
    """
    global _last_magnet_reason
    _last_magnet_reason = ""
    if is_cancel_requested(avid):
        cancel_qb_tasks(avid)
        _last_magnet_reason = "已取消"
        return (MAGNET_CANCELLED, None)
    if magnet is None:
        magnet = get_magnet_from_weekly(avid)
    if not magnet:
        logger.info(f"[Magnet] {avid} no magnet available, skip")
        _last_magnet_reason = "无可用磁链"
        return (MAGNET_FAILED, None)

    target = (target or "qb").strip().lower()
    if target == "115":
        try:
            from src import p115_offline as p115

            ok, probe_msg = p115.probe_cached()
            pub = p115.public_config()
            p115_cfg = p115.load_config()
            if not p115_cfg.get("cookies"):
                _last_magnet_reason = "未配置 115 Cookie"
                logger.warning(f"[Magnet] {avid} 115: no cookies")
                return (MAGNET_FAILED, None)
            if not p115_cfg.get("enabled"):
                _last_magnet_reason = "115 离线未启用（设置页）"
                logger.warning(f"[Magnet] {avid} 115: not enabled")
                return (MAGNET_FAILED, None)
            if not ok or not pub.get("verified"):
                _last_magnet_reason = probe_msg or "115 Cookie 已失效（设置页重新测试）"
                logger.warning(f"[Magnet] {avid} 115: not verified ({_last_magnet_reason})")
                return (MAGNET_FAILED, None)
            save_to = p115_cfg.get("save_path") or "/艾薇"
            logger.info(f"[Magnet] {avid} 115 offline → {save_to}")
            ok, msg, raw = p115.submit_magnet(magnet)
            if ok:
                logger.info(f"[Magnet] {avid} 115 ok: {msg} raw={str(raw)[:200]}")
                _last_magnet_reason = msg or f"已提交 115 离线 → {save_to}"
                log_write("Worker", f"{avid} {_last_magnet_reason}")
                return (MAGNET_PENDING, None)
            logger.warning(f"[Magnet] {avid} 115 cloud failed: {msg}")
            _last_magnet_reason = f"115 云下载失败: {msg}"
            return (MAGNET_FAILED, None)
        except Exception as e:
            logger.warning(f"[Magnet] {avid} 115 path error: {e}")
            _last_magnet_reason = f"115 云下载异常: {e}"
            return (MAGNET_FAILED, None)

    # ----- qB only -----
    # 不预先创建 save_dir，等下载完再建，避免和 qB 目录冲突

    # 通过 qBittorrent API 添加磁链（不指定 savepath，用 qB 默认的 /data/）
    add_url = "/api/v2/torrents/add"
    add_data = urllib.parse.urlencode({
        "urls": magnet,
        "category": "AV_GARDEN",
        "tags": avid,
        "autoTMM": "false",
    })
    result = qbittorrent_api("POST", add_url, add_data)
    # result=None 可能是添加失败或已存在(重复)，检查 qB 中是否已有该磁链的种子
    if result is None:
        existing = qbittorrent_api("GET", "/api/v2/torrents/info?category=AV_GARDEN")
        found = False
        if existing and isinstance(existing, list):
            for t in existing:
                if t.get("magnet_uri", "") == magnet:
                    logger.info(f"[Magnet] {avid} already in qBittorrent, monitoring existing torrent")
                    found = True
                    break
        if not found:
            if has_active_qb_task(avid):
                logger.info(f"[Magnet] {avid} already has active qB task, keep monitoring via Queue API")
                _last_magnet_reason = "qB 已有任务"
                return (MAGNET_PENDING, None)
            logger.warning(f"[Magnet] {avid} failed to add magnet to qBittorrent, fallback to stream")
            _last_magnet_reason = "无法加入 qB"
            return (MAGNET_FAILED, None)

    logger.info(f"[Magnet] {avid} added to qBittorrent, waiting for metadata...")

    start = time.time()
    metadata_received = False
    last_downloaded = 0
    stale_count = 0
    torrent_hash = None
    file_selection_done = False
    pending_reason = "已交 qB 后台继续下载"

    while True:
        interrupt = magnet_watch_interrupt(is_cancel_requested(avid), running)
        if interrupt == "cancel":
            logger.info(f"[Magnet] {avid} cancelled")
            if torrent_hash:
                qbittorrent_post("/api/v2/torrents/delete", {"hashes": torrent_hash, "deleteFiles": "false"})
            else:
                cancel_qb_tasks(avid)
            _last_magnet_reason = "已取消"
            return (MAGNET_CANCELLED, torrent_hash)
        if interrupt == "leave":
            # docker restart / SIGTERM：qB 自己继续下，不要当成用户取消去删种
            logger.info(f"[Magnet] {avid} worker stopping, leave qB torrent running")
            _last_magnet_reason = "worker 重启，qB 继续下载"
            return (MAGNET_PENDING, torrent_hash)
        elapsed = time.time() - start

        # 查询所有 torrent 状态
        torrents = qbittorrent_api("GET", "/api/v2/torrents/info?category=AV_GARDEN")
        if torrents is None:
            time.sleep(5)
            continue

        # 找到我们的 torrent：tags=番号 / magnet / save_path 子目录
        target = None
        avid_u = avid.upper().strip()
        for t in torrents:
            tags = {x.strip().upper() for x in str(t.get("tags") or "").split(",") if x.strip()}
            if avid_u in tags:
                target = t
                break
        if target is None and torrents:
            for t in torrents:
                if t.get("magnet_uri", "") == magnet:
                    target = t
                    break
        if target is None and torrents:
            for t in torrents:
                if t.get("save_path", "").rstrip("/") == save_dir.rstrip("/"):
                    target = t
                    break
        if target is None and torrents:
            # 名称里带番号（+++ [FHD] ABF-372 ...）
            import re as _re
            pat = _re.compile(
                r"(?:^|[/\s\-_.,\[\]+])" + _re.escape(avid_u) + r"(?:[/\s\-_.,\[\]]|$)"
            )
            for t in torrents:
                if pat.search(str(t.get("name") or "").upper()):
                    target = t
                    break

        if target is None:
            # 还没出现在列表里，等 metadata
            if elapsed > 60:
                logger.warning(f"[Magnet] {avid} not found in qBittorrent after 60s, giving up")
                pending_reason = "元数据超时（qB 中未出现）"
                # Return hash if available for cleanup
                if torrent_hash:
                    cancel_qb_tasks(avid, delete_files=False)
                break
            time.sleep(5)
            continue

        torrent_hash = target.get("hash", "")
        state = target.get("state", "")
        size = target.get("size", 0)
        downloaded = target.get("completed", 0)
        progress = target.get("progress", 0)
        dlspeed = target.get("dlspeed", 0)
        availability = target.get("availability", 0)

        # 检查是否获取到元数据 (state 不再是 metaDL)
        if state not in ("metaDL", "missingFiles", "error", "unknown"):
            metadata_received = True

        if metadata_received and not file_selection_done:
            file_selection_done = apply_largest_video_only(avid, torrent_hash)

        # 检查是否完成
        if state in ("queuedUP", "uploading", "stalledUP", "pausedUP", "stoppedUP"):
            logger.info(f"[Magnet] {avid} qBittorrent state: {state}, checking file...")
            content_path = target.get("content_path", "")
            output_path = find_and_rename_output(save_dir, avid, content_path)
            if output_path and find_main_video(output_path):
                total_size = os.path.getsize(output_path)
                logger.info(f"[Magnet] {avid} download success ({elapsed:.0f}s, {total_size/1024/1024:.1f} MB)")
                if torrent_hash:
                    qbittorrent_api("POST", "/api/v2/torrents/delete?hashes=" + torrent_hash + "&deleteFiles=false")
                return (MAGNET_COMPLETED, torrent_hash)

        # 进度日志
        if metadata_received:
            if downloaded > last_downloaded:
                stale_count = 0
                last_downloaded = downloaded
                logger.info(f"[Magnet] {avid} downloading: {downloaded/1024/1024:.1f}/{size/1024/1024:.1f} MB ({progress*100:.0f}%) speed={dlspeed/1024:.0f} KB/s avail={availability}")
            else:
                stale_count += 1

        # 检查错误状态
        if state in ("error", "missingFiles"):
            logger.warning(f"[Magnet] {avid} qBittorrent state: {state}, giving up")
            pending_reason = f"qB 状态异常 ({state})"
            break

        # ---- 超时判断 ----
        # 1. 元数据超时 (state 停在了 metaDL) - 从 120s 缩短到 60s
        if not metadata_received and elapsed > 60:
            logger.warning(f"[Magnet] {avid} no metadata after 60s, giving up")
            pending_reason = "元数据超时"
            break

        if metadata_received:
            # 2. 完全没种 (availability=0): 等到有 metadata 后再等 5min
            if availability == 0 and elapsed > 300:
                logger.warning(f"[Magnet] {avid} no seeds (availability=0) for 5min, giving up")
                pending_reason = "无种子 5 分钟 (availability=0)"
                break

            # 3. 有种子但极慢: 速度 < 10KB/s 且无进度持续 10min - 从 30min 缩短到 10min
            if dlspeed < 10 * 1024 and stale_count > 120:  # 120 * 5s = 10min
                logger.warning(f"[Magnet] {avid} stalled <10KB/s for 10min, giving up")
                pending_reason = "速度过慢（10 分钟几乎无进度）"
                break

        # 4. 总超时 2 小时
        if elapsed > 7200:
            logger.warning(f"[Magnet] {avid} total timeout (2h), downloaded: {downloaded/1024/1024:.1f} MB")
            pending_reason = "下载超时 2 小时"
            break

        time.sleep(5)

    # 不删 qB 里的种子——让 qB 继续下载，状态由 qB/Queue API 侧暴露
    # 也不删文件——qB 可能还在写
    # 只在真正无望时才通知飞书

    if elapsed > 7200:
        notify_feishu_magnet_timeout(avid, magnet)

    _last_magnet_reason = pending_reason
    return (MAGNET_PENDING, torrent_hash)


def download_video(avid):
    """下载单个视频（逻辑移植自 main.py）"""
    avid = normalize_video_id(avid)
    if not avid:
        logger.error("[Worker] Invalid video ID discarded")
        return False
    if is_cancel_requested(avid):
        logger.info(f"[Worker] {avid} 已取消，跳过")
        cancel_qb_tasks(avid)
        clear_cancel_request(avid)
        return False
    logger.info(f"[Worker] 开始下载: {avid}")

    # 检查是否已在数据库
    existing_main_video = find_main_video(os.path.join(save_path, avid))
    try:
        data.initialize_db(downloaded_path, "MissAV")
        in_database = data.find_in_db(avid, downloaded_path, "MissAV")
    except Exception as exc:
        logger.error(f"[Worker] {avid} 数据库查询失败，任务重新排队: {exc}")
        log_write("Worker", f"{avid} 数据库暂时不可用，已保留任务等待重试")
        append_unique(queue_path, avid)
        return False
    if existing_main_video:
        if not in_database:
            if not data.batch_insert_bvids([avid], downloaded_path, "MissAV"):
                logger.error(f"[Worker] {avid} 正片存在但数据库记录修复失败，任务重新排队")
                append_unique(queue_path, avid)
                return False
            logger.info(f"[Worker] {avid} 正片已存在，已补数据库记录")
            log_write("Worker", f"{avid} 正片已存在，已修复媒体库记录")
        else:
            logger.info(f"[Worker] {avid} 已在数据库中，跳过")
        return True
    if in_database:
        logger.warning(f"[Worker] {avid} 数据库有记录但磁盘无有效正片，继续恢复下载")

    # qB 可能由旧版本、手动任务或其他分类接管。即使 weekly 暂时没有磁链，
    # 也不能再回退在线流，否则同一番号会生成两份正片。
    if has_active_qb_task(avid):
        logger.info(f"[Worker] {avid} qB 已有任务，跳过重复下载")
        log_write("Worker", f"{avid} 已在 qB 下载或保种，跳过重复下载")
        return False

    # 尝试获取锁
    if is_locked():
        logger.info(f"[Worker] 下载器忙，{avid} 保留在队列中")
        append_unique(queue_path, avid)
        return False

    acquire_lock()
    logger.info(f"[Worker] 获得锁，开始执行: {avid}")
    log_write("Worker", f"{avid} 开始下载")

    try:
        # ======= 第一步：共享解析器优先选择磁链 =======
        save_dir = safe_video_dir(save_path, avid)
        magnet = get_magnet_from_weekly(avid)
        retries = get_retries(avid)
        if retries >= MAX_RETRIES and not magnet:
            logger.warning(f"[Worker] {avid} 已失败 {retries} 次，放弃，写入失败队列")
            record_failed_download(avid, reason="无可用源")
            log_write("Worker", f"{avid} 失败: 无可用源（已重试{retries}次）")
            release_lock()
            return True
        if retries >= MAX_RETRIES and magnet:
            logger.info(f"[Worker] {avid} 已失败 {retries} 次，但找到磁链，尝试 qB")
        state_target = ""
        try:
            from queue_store import read_json as _read_json

            for item in _read_json(os.environ.get("STATE_PATH", "/db/queue_state.json"), []):
                if isinstance(item, dict) and str(item.get("code") or "").upper() == avid.upper():
                    state_target = str(item.get("target") or "")
                    break
        except Exception:
            state_target = ""
        download_target = get_download_target(
            download_targets_path, avid, default=state_target or "qb"
        )
        if magnet:
            magnet_status, torrent_hash = try_magnet_download(
                avid, save_dir, magnet, target=download_target
            )
            if magnet_status == MAGNET_CANCELLED:
                logger.info(f"[Worker] {avid} 下载已取消")
                log_write("Worker", f"{avid} 失败: 已取消")
                clear_cancel_request(avid)
                clear_download_target(download_targets_path, avid)
                return False
            if magnet_status == MAGNET_COMPLETED:
                gen_nfo()
                logger.info(f"[Worker] {avid} 磁链下载完成!")
                clear_retry(avid)
                clear_download_target(download_targets_path, avid)
                log_write("Worker", f"{avid} 下载完成")
                release_lock()
                return True
            if magnet_status == MAGNET_PENDING:
                # 115 离线或 qB 后台：不 fallback 到在线流
                logger.info(
                    f"[Worker] {avid} 磁链已交后台 target={download_target} ({_last_magnet_reason})"
                )
                if torrent_hash:
                    logger.info(f"[Worker] {avid} qB hash: {torrent_hash}")
                # 115 路径已在 try_magnet_download 内 log_write；qB 在此补一条
                if download_target != "115":
                    log_write(
                        "Worker",
                        f"{avid} 已交 qB 后台继续下载"
                        + (f"（{_last_magnet_reason}）" if _last_magnet_reason else ""),
                    )
                clear_download_target(download_targets_path, avid)
                release_lock()
                return False

            _handle_magnet_unavailable(avid, _last_magnet_reason or "磁链下载失败")
            if download_target != "115":
                clear_download_target(download_targets_path, avid)
            release_lock()
            return False

        # target=115 但无磁链：不能回退在线流（语义是云端离线）
        if download_target == "115":
            logger.warning(f"[Worker] {avid} 选择 115 但无可用磁链")
            _handle_magnet_unavailable(avid, "无可用磁链（115）")
            clear_download_target(download_targets_path, avid)
            release_lock()
            return False

        # ======= 第二步：无可用磁链，尝试在线流 =======
        logger.info(f"[Worker] {avid} 98堂/Sukebei 未找到磁链，尝试在线流...")
        mgr = downloaderMgr.DownloaderMgr()

        if len(sorted_downloaders) == 0:
            raise ValueError("cfg没有配置下载器")

        downloaded = False
        count = 0
        for it in sorted_downloaders:
            if is_cancel_requested(avid) or not running:
                logger.info(f"[Worker] {avid} 下载已取消")
                log_write("Worker", f"{avid} 失败: 已取消")
                clear_cancel_request(avid)
                return False
            count += 1
            downloader = mgr.GetDownloader(it["downloaderName"])
            if downloader is None:
                logger.error(f"[Worker] 未知下载器: {it['downloaderName']}")
                continue
            if not downloader.setDomain(it["domain"]):
                logger.error(f"[Worker] 下载器 {downloader.getDownloaderName()} 域名未配置")
                continue
            logger.info(f"[Worker] 尝试下载器: {downloader.getDownloaderName()}")

            info = downloader.downloadInfo(avid)
            if not info:
                logger.error(f"[Worker] {avid} 元数据获取失败 ({downloader.getDownloaderName()})")
                if count >= len(sorted_downloaders):
                    raise ValueError(f"{avid} 98堂、Sukebei 和在线流均无可用源")
                continue

            if not downloader.downloadM3u8(info.m3u8, avid):
                if is_cancel_requested(avid) or not running:
                    logger.info(f"[Worker] {avid} 下载已取消")
                    log_write("Worker", f"{avid} 失败: 已取消")
                    clear_cancel_request(avid)
                    return False
                logger.error(f"[Worker] {avid} 视频下载失败 ({downloader.getDownloaderName()})")
                if count >= len(sorted_downloaders):
                    raise ValueError(f"{avid} 98堂、Sukebei 和在线流均无可用源")
                continue

            downloaded = True
            break

        if downloaded:
            logger.info(f"[Worker] {avid} 下载完成，开始刮削元数据")
            gen_nfo()
            clear_retry(avid)
            logger.info(f"[Worker] {avid} 全部完成!")
            log_write("Worker", f"{avid} 下载完成")
        else:
            _handle_failure(avid, "在线流失败")

    except ValueError as e:
        logger.error(f"[Worker] {e}")
        if is_cancel_requested(avid) or not running:
            clear_cancel_request(avid)
            return False
        if not _handle_failure(avid, "98堂、Sukebei 和在线流均无可用源"):
            log_write("Worker", f"{avid} 已交 qB 后台继续下载")
    except Exception as e:
        logger.error(f"[Worker] 下载异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        if not is_cancel_requested(avid) and running:
            _handle_failure(avid, f"异常: {e}")
        else:
            clear_cancel_request(avid)
    finally:
        release_lock()
        logger.info(f"[Worker] 锁已释放")

    return True


def worker_loop():
    """主循环：不断轮询队列并下载"""
    logger.info("[Worker] 下载队列服务启动，开始轮询...")
    empty_poll_count = 0

    while running:
        try:
            # 初始化 DB（每次循环都确保）
            data.initialize_db(downloaded_path, "MissAV")

            raw_avid = read_queue_first_line()
            if raw_avid:
                empty_poll_count = 0
                logger.info(f"[Worker] 从队列取出: {raw_avid}")
                avid = normalize_video_id(raw_avid)
                if not avid:
                    logger.error(f"[Worker] 丢弃非法队列项: {raw_avid!r}")
                    continue
                set_current_download(avid)
                try:
                    download_video(avid)
                finally:
                    clear_current_download(avid)
                # 下载完后短暂等待再取下一个
                time.sleep(3)
            else:
                empty_poll_count += 1
                if empty_poll_count % 10 == 0:
                    logger.debug(f"[Worker] 队列为空，等待中... (第{empty_poll_count}次)")
                # 队列空时等 30 秒再查
                time.sleep(30)

        except Exception as e:
            logger.error(f"[Worker] 循环异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            time.sleep(30)

    logger.info("[Worker] 服务已停止")


if __name__ == "__main__":
    worker_loop()
