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
import subprocess
import re
import urllib.request

# 把项目根加入 path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
from src.log_writer import write as log_write

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
retry_file = os.path.join(os.path.dirname(queue_path) if os.path.dirname(queue_path) else "/db", "retry_counts.json")
MAX_RETRIES = 3
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".wmv", ".ts", ".m2ts", ".mov", ".flv")
MIN_VIDEO_FILE_SIZE = 10 * 1024 * 1024
MAGNET_COMPLETED = "completed"
MAGNET_PENDING = "pending"
MAGNET_FAILED = "failed"

logger.info(f"[Worker] save_path={save_path}")
logger.info(f"[Worker] queue_path={queue_path}")
logger.info(f"[Worker] db_path={downloaded_path}")
logger.info(f"[Worker] proxy={myproxy}")

# 工作锁文件（与 main.py 共用，确保单例下载）
work_lock = os.path.join(project_root, "work")
WEEKLY_JSON = os.path.join(save_path, "__weekly__", "weekly.json")

running = True


def signal_handler(sig, frame):
    global running
    logger.info("[Worker] Received signal, shutting down...")
    running = False


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def read_queue_first_line():
    """读取队列第一行并返回"""
    if not os.path.exists(queue_path):
        return None
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    return line
    except Exception as e:
        logger.error(f"[Worker] Error reading queue: {e}")
    return None


def remove_queue_first_line(avid):
    """从队列中移除指定的车牌号（只移除第一行匹配的）"""
    if not os.path.exists(queue_path):
        return
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        removed = False
        with open(queue_path, "w", encoding="utf-8") as f:
            for line in lines:
                if not removed and line.strip() == avid:
                    removed = True
                    continue
                f.write(line)
    except Exception as e:
        logger.error(f"[Worker] Error removing from queue: {e}")


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
        if os.path.exists(failed_queue_json_path):
            with open(failed_queue_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
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


def record_failed_download(avid):
    """记录最终失败，主存储为带时间戳的 failed_queue.json。"""
    code = avid.upper().strip()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    records = _load_failed_records()
    updated = False
    for item in records:
        if item["code"] == code:
            item["failed_at"] = now
            item["retries"] = get_retries(code)
            updated = True
            break
    if not updated:
        records.append({"code": code, "failed_at": now, "retries": get_retries(code)})

    os.makedirs(os.path.dirname(failed_queue_json_path), exist_ok=True)
    tmp = failed_queue_json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, failed_queue_json_path)


def _handle_failure(avid):
    """处理下载失败：记录重试次数，超过上限则放弃并通知飞书"""
    if has_active_qb_task(avid):
        logger.info(f"[Worker] {avid} qB 任务仍在进行，跳过失败记录和飞书通知")
        return False

    retries = incr_retry(avid)
    if retries >= MAX_RETRIES:
        logger.warning(f"[Worker] {avid} 失败 {retries} 次，放弃，写入失败队列")
        record_failed_download(avid)
        notify_feishu_all_failed(avid)
    else:
        logger.warning(f"[Worker] {avid} 失败 ({retries}/{MAX_RETRIES})，放回队列重试")
        with open(queue_path, "a", encoding="utf-8") as f:
            f.write(f"{avid}\n")
    return True

def _handle_magnet_unavailable(avid):
    """有磁链但 qB 没有接住时，只按磁链路径重试，不回退在线流。"""
    if has_active_qb_task(avid):
        logger.info(f"[Worker] {avid} qB 任务仍在进行，跳过在线流")
        log_write("Worker", f"{avid} qB已接管下载")
        return False

    retries = incr_retry(avid)
    if retries >= MAX_RETRIES:
        logger.warning(f"[Worker] {avid} 磁链处理异常 {retries} 次，放弃")
        record_failed_download(avid)
        log_write("Worker", f"{avid} 磁链处理异常，失败{retries}次已放弃")
        notify_feishu_all_failed(avid)
    else:
        logger.warning(f"[Worker] {avid} 磁链暂不可用 ({retries}/{MAX_RETRIES})，放回队列重试")
        log_write("Worker", f"{avid} 磁链暂不可用，等待重试({retries}/{MAX_RETRIES})")
        with open(queue_path, "a", encoding="utf-8") as f:
            f.write(f"{avid}\n")
    return True

def has_active_qb_task(avid):
    """如果 qB 中已有同番号或带数字前缀的活跃任务，不应当算作最终失败。"""
    try:
        torrents = qbittorrent_api("GET", "/api/v2/torrents/info?category=AV_GARDEN")
    except Exception:
        return False
    if not isinstance(torrents, list):
        return False

    target = avid.upper().strip()
    active_states = {"downloading", "stalledDL", "forcedDL", "metaDL", "queuedDL"}
    done_states = {"queuedUP", "uploading", "stalledUP", "pausedUP"}
    for torrent in torrents:
        state = str(torrent.get("state", ""))
        if state not in active_states and state not in done_states:
            continue
        fields = [
            torrent.get("name", ""),
            torrent.get("content_path", ""),
            torrent.get("save_path", ""),
        ]
        for field in fields:
            value = str(field).upper()
            if value == target or target in value or value.endswith(target):
                return True
    return False

def notify_feishu_all_failed(avid):
    """所有下载方式失败时通过飞书通知"""
    webhook = os.environ.get("FEISHU_WEBHOOK") or feishu_webhook
    if not webhook:
        return
    msg = f"AV/GARDEN 下载失败\n番号: {avid}\n原因: 所有下载源均失败(已重试3次)"
    try:
        data = json.dumps({"msg_type": "text", "content": {"text": msg}}).encode()
        req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"[Feishu] Sent all-failed notification for {avid}")
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
    try:
        if os.path.exists(retry_file):
            with open(retry_file, "r") as f:
                counts = json.load(f)
                return counts.get(avid.upper(), 0)
    except:
        pass
    return 0

def incr_retry(avid):
    counts = {}
    try:
        if os.path.exists(retry_file):
            with open(retry_file, "r") as f:
                counts = json.load(f)
    except:
        pass
    key = avid.upper()
    counts[key] = counts.get(key, 0) + 1
    with open(retry_file, "w") as f:
        json.dump(counts, f)
    return counts[key]

def clear_retry(avid):
    counts = {}
    try:
        if os.path.exists(retry_file):
            with open(retry_file, "r") as f:
                counts = json.load(f)
    except:
        pass
    counts.pop(avid.upper(), None)
    with open(retry_file, "w") as f:
        json.dump(counts, f)


def get_magnet_from_weekly(avid):
    """从 weekly.json 获取番号的磁链（优先中文字幕版），尝试原始番号和清理后的番号"""
    def missav_fallback():
        try:
            from src.weekly import sukebei
            sukebei.set_proxy(myproxy)
            magnet = sukebei.search_missav_magnet(avid)
            if magnet:
                logger.info(f"[Magnet] Found MissAV magnet for {avid}")
                log_write("Worker", f"{avid} MissAV找到磁链")
                return magnet
        except Exception as e:
            logger.warning(f"[Magnet] MissAV fallback failed for {avid}: {e}")
        return None

    if not os.path.exists(WEEKLY_JSON):
        logger.warning(f"[Magnet] weekly.json not found: {WEEKLY_JSON}")
        return missav_fallback()
    try:
        from metadata import clean_avid
        with open(WEEKLY_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 尝试匹配: 原始番号 + clean_avid 后的番号
        codes_to_try = {avid.upper()}
        cleaned = clean_avid(avid)
        if cleaned != avid.upper():
            codes_to_try.add(cleaned)
        for item in data:
            if item.get("id", "").upper() in codes_to_try:
                magnet = item.get("magnet", "")
                if magnet:
                    logger.info(f"[Magnet] Found magnet for {avid} (weekly id: {item['id']})")
                    return magnet
                else:
                    logger.warning(f"[Magnet] {avid} has no magnet in weekly.json")
                    log_write("Worker", f"{avid} weekly.json无磁链")
                    return missav_fallback()
        logger.warning(f"[Magnet] {avid} not found in weekly.json")
        log_write("Worker", f"{avid} 不在weekly.json中")
        return missav_fallback()
    except Exception as e:
        logger.error(f"[Magnet] Error reading weekly.json: {e}")
        return missav_fallback()


def notify_feishu_magnet_timeout(avid, magnet):
    """磁链超时时通过飞书机器人通知"""
    webhook = os.environ.get("FEISHU_WEBHOOK") or feishu_webhook
    if not webhook:
        return
    msg = f"AV/GARDEN 磁链下载超时\n车牌号: {avid}\n磁链: {magnet}\n请手动复制到迅雷下载"
    try:
        data = json.dumps({"msg_type": "text", "content": {"text": msg}}).encode()
        req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"[Feishu] Sent timeout notification for {avid}")
    except Exception as e:
        logger.error(f"[Feishu] Failed to send notification: {e}")


def qbittorrent_api(method, endpoint, data=None):
    """调用 qBittorrent Web API，自动处理登录和 cookie"""
    from src.comm import qb_url, qb_username, qb_password
    import http.cookiejar

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    # 登录
    login_url = f"{qb_url}/api/v2/auth/login"
    login_data = f"username={urllib.parse.quote(qb_username)}&password={urllib.parse.quote(qb_password)}".encode()
    try:
        resp = opener.open(urllib.request.Request(login_url, data=login_data), timeout=10)
        if resp.status != 200:
            logger.error(f"[QBittorrent] Login failed: {resp.status}")
            return None
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
            req = urllib.request.Request(full_url, data=data.encode() if data else None, headers=headers)
        resp = opener.open(req, timeout=30)
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
    except Exception as e:
        logger.error(f"[QBittorrent] API error {endpoint}: {e}")
        return None


def qbittorrent_post(endpoint, params):
    """发送 qBittorrent 表单 POST。"""
    return qbittorrent_api("POST", endpoint, urllib.parse.urlencode(params))


def apply_largest_video_only(avid, torrent_hash):
    """只保留种子里最大的一个视频文件下载。"""
    if not torrent_hash:
        return False

    files = qbittorrent_api("GET", "/api/v2/torrents/files?hash=" + urllib.parse.quote(torrent_hash))
    if not isinstance(files, list):
        return False
    if not files:
        logger.info(f"[Magnet] {avid} file list not ready, waiting...")
        return False

    candidates = []
    for item in files:
        name = str(item.get("name", ""))
        ext = os.path.splitext(name)[1].lower()
        size = int(item.get("size") or 0)
        index = item.get("index")
        if index is None:
            continue
        if ext in VIDEO_EXTENSIONS and size > MIN_VIDEO_FILE_SIZE:
            candidates.append((size, int(index), name))

    if not candidates:
        logger.warning(f"[Magnet] {avid} no video file found in torrent, keep original file priorities")
        return True

    candidates.sort(reverse=True)
    selected_size, selected_index, selected_name = candidates[0]
    skip_ids = []
    for item in files:
        index = item.get("index")
        if index is None or int(index) == selected_index:
            continue
        skip_ids.append(str(index))

    logger.info(
        f"[Magnet] {avid} selected largest video: {selected_name} "
        f"({selected_size/1024/1024:.1f} MB), disabling {len(skip_ids)} other files"
    )

    qbittorrent_post("/api/v2/torrents/pause", {"hashes": torrent_hash})
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
        qbittorrent_post("/api/v2/torrents/resume", {"hashes": torrent_hash})

    return True


def find_and_rename_output(save_dir, avid, qb_content_path=None):
    """
    qBittorrent 下载完成后，从 qb_content_path 找到最大视频，
    移到 save_dir/{avid}.mp4，不预先创建 save_dir。
    """
    search_dir = qb_content_path if qb_content_path and os.path.isdir(qb_content_path) else save_dir
    if not os.path.isdir(search_dir):
        return None

    candidates = []
    for root, dirs, files in os.walk(search_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                path = os.path.join(root, f)
                size = os.path.getsize(path)
                if size > 10 * 1024 * 1024:
                    candidates.append((size, path))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, src = candidates[0]
    os.makedirs(save_dir, exist_ok=True)
    dst = os.path.join(save_dir, f"{avid}.mp4")
    if src != dst:
        logger.info(f"[Magnet] Move {os.path.basename(src)} -> {avid}.mp4")
        os.rename(src, dst)
    return dst


def try_magnet_download(avid, save_dir, magnet=None):
    """
    尝试通过 qBittorrent 磁链下载。
    返回 MAGNET_COMPLETED / MAGNET_PENDING / MAGNET_FAILED。
    使用 weekly.json 中 sukebei 搜到的磁链（中文字幕版）

    策略：
    - 最多等 120 秒获取元数据（metadata）
    - 获取到元数据后继续下载，最长 2 小时
    - 已进入 qB 但未完成时返回 pending，不当作下载成功
    """
    if magnet is None:
        magnet = get_magnet_from_weekly(avid)
    if not magnet:
        logger.info(f"[Magnet] {avid} no magnet available, skip")
        return MAGNET_FAILED

    # 不预先创建 save_dir，等下载完再建，避免和 qB 目录冲突

    # 通过 qBittorrent API 添加磁链（不指定 savepath，用 qB 默认的 /data/）
    add_url = "/api/v2/torrents/add"
    add_data = f"urls={urllib.parse.quote(magnet)}&category=AV_GARDEN&autoTMM=false"
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
                return MAGNET_PENDING
            logger.warning(f"[Magnet] {avid} failed to add magnet to qBittorrent, fallback to stream")
            return MAGNET_FAILED

    logger.info(f"[Magnet] {avid} added to qBittorrent, waiting for metadata...")

    start = time.time()
    metadata_received = False
    last_downloaded = 0
    stale_count = 0
    torrent_hash = None
    file_selection_done = False

    while True:
        elapsed = time.time() - start

        # 查询所有 torrent 状态
        torrents = qbittorrent_api("GET", "/api/v2/torrents/info?category=AV_GARDEN")
        if torrents is None:
            time.sleep(5)
            continue

        # 找到我们的 torrent
        target = None
        for t in torrents:
            if t.get("save_path", "").rstrip("/") == save_dir.rstrip("/"):
                target = t
                break
        if target is None and torrents:
            # 可能 save_path 有尾部斜杠差异，用磁链匹配
            for t in torrents:
                if t.get("magnet_uri", "") == magnet:
                    target = t
                    break

        if target is None:
            # 还没出现在列表里，等 metadata
            if elapsed > 120:
                logger.warning(f"[Magnet] {avid} not found in qBittorrent after 120s, giving up")
                return MAGNET_FAILED
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
        if state in ("queuedUP", "uploading", "stalledUP", "pausedUP"):
            logger.info(f"[Magnet] {avid} qBittorrent state: {state}, checking file...")
            content_path = target.get("content_path", "")
            output_path = find_and_rename_output(save_dir, avid, content_path)
            if output_path and os.path.getsize(output_path) > 10 * 1024 * 1024:
                total_size = os.path.getsize(output_path)
                logger.info(f"[Magnet] {avid} download success ({elapsed:.0f}s, {total_size/1024/1024:.1f} MB)")
                if torrent_hash:
                    qbittorrent_api("POST", "/api/v2/torrents/delete?hashes=" + torrent_hash + "&deleteFiles=false")
                return MAGNET_COMPLETED

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
            break

        # ---- 超时判断 ----
        # 1. 元数据超时 (state 停在了 metaDL)
        if not metadata_received and elapsed > 120:
            logger.warning(f"[Magnet] {avid} no metadata after 120s, giving up")
            break

        if metadata_received:
            # 2. 完全没种 (availability=0): 等到有 metadata 后再等 5min
            if availability == 0 and elapsed > 300:
                logger.warning(f"[Magnet] {avid} no seeds (availability=0) for 5min, giving up")
                break

            # 3. 有种子但极慢: 速度 < 10KB/s 且无进度持续 30min (360 * 5s)
            if dlspeed < 10 * 1024 and stale_count > 360:
                logger.warning(f"[Magnet] {avid} stalled <10KB/s for 30min, giving up")
                break

        # 4. 总超时 2 小时
        if elapsed > 7200:
            logger.warning(f"[Magnet] {avid} total timeout (2h), downloaded: {downloaded/1024/1024:.1f} MB")
            break

        time.sleep(5)

    # 不删 qB 里的种子——让 qB 继续下载，状态由 qB/Queue API 侧暴露
    # 也不删文件——qB 可能还在写
    # 只在真正无望时才通知飞书

    if elapsed > 7200:
        notify_feishu_magnet_timeout(avid, magnet)

    return MAGNET_PENDING


def download_video(avid):
    """下载单个视频（逻辑移植自 main.py）"""
    avid = avid.upper().strip()
    logger.info(f"[Worker] 开始下载: {avid}")

    # 检查是否已在数据库
    data.initialize_db(downloaded_path, "MissAV")
    if data.find_in_db(avid, downloaded_path, "MissAV"):
        logger.info(f"[Worker] {avid} 已在数据库中，跳过")
        return True

    # 尝试获取锁
    if is_locked():
        logger.info(f"[Worker] 下载器忙，{avid} 保留在队列中")
        return False

    acquire_lock()
    logger.info(f"[Worker] 获得锁，开始执行: {avid}")
    log_write("Worker", f"{avid} 开始下载")

    try:
        # ======= 第一步：优先尝试磁链下载（中文字幕） =======
        save_dir = os.path.join(save_path, avid)
        magnet = get_magnet_from_weekly(avid)
        retries = get_retries(avid)
        if retries >= MAX_RETRIES and not magnet:
            logger.warning(f"[Worker] {avid} 已失败 {retries} 次，放弃，写入失败队列")
            record_failed_download(avid)
            log_write("Worker", f"{avid} 失败{retries}次已放弃")
            release_lock()
            return True
        if retries >= MAX_RETRIES and magnet:
            logger.info(f"[Worker] {avid} 已失败 {retries} 次，但找到磁链，尝试 qB")
        if magnet:
            magnet_status = try_magnet_download(avid, save_dir, magnet)
            if magnet_status == MAGNET_COMPLETED:
                gen_nfo()
                logger.info(f"[Worker] {avid} 磁链下载完成!")
                clear_retry(avid)
                log_write("Worker", f"{avid} 磁链下载完成")
                release_lock()
                return True
            if magnet_status == MAGNET_PENDING:
                # 磁链已加 qB（还在下载中），不 fallback 到在线流
                logger.info(f"[Worker] {avid} 磁链下载中(qB)，尚未完成")
                log_write("Worker", f"{avid} qB已接管下载")
                release_lock()
                return False

            _handle_magnet_unavailable(avid)
            release_lock()
            return False

        # ======= 第二步：无可用磁链，尝试在线流 =======
        logger.info(f"[Worker] {avid} 未找到磁链，尝试在线流...")
        log_write("Worker", f"{avid} 未找到磁链，转在线流")
        mgr = downloaderMgr.DownloaderMgr()

        if len(sorted_downloaders) == 0:
            raise ValueError("cfg没有配置下载器")

        downloaded = False
        count = 0
        for it in sorted_downloaders:
            count += 1
            downloader = mgr.GetDownloader(it["downloaderName"])
            if not downloader.setDomain(it["domain"]):
                logger.error(f"[Worker] 下载器 {downloader.getDownloaderName()} 域名未配置")
                continue
            if downloader is None:
                continue
            logger.info(f"[Worker] 尝试下载器: {downloader.getDownloaderName()}")

            info = downloader.downloadInfo(avid)
            if not info:
                logger.error(f"[Worker] {avid} 元数据获取失败 ({downloader.getDownloaderName()})")
                if count >= len(sorted_downloaders):
                    raise ValueError(f"{avid} 所有下载器均失败")
                continue

            if not downloader.downloadM3u8(info.m3u8, avid):
                logger.error(f"[Worker] {avid} 视频下载失败 ({downloader.getDownloaderName()})")
                if count >= len(sorted_downloaders):
                    raise ValueError(f"{avid} 所有下载器均失败")
                continue

            downloaded = True
            break

        if downloaded:
            logger.info(f"[Worker] {avid} 下载完成，开始刮削元数据")
            gen_nfo()
            clear_retry(avid)
            logger.info(f"[Worker] {avid} 全部完成!")
            log_write("Worker", f"{avid} 在线流下载完成")
        else:
            _handle_failure(avid)

    except ValueError as e:
        logger.error(f"[Worker] {e}")
        if _handle_failure(avid):
            log_write("Worker", f"{avid} 所有源均失败")
        else:
            log_write("Worker", f"{avid} qB已接管下载，跳过在线流")
    except Exception as e:
        logger.error(f"[Worker] 下载异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        _handle_failure(avid)
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

            avid = read_queue_first_line()
            if avid:
                empty_poll_count = 0
                logger.info(f"[Worker] 从队列取出: {avid}")
                remove_queue_first_line(avid)
                download_video(avid)
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
