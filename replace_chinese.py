#!/usr/bin/env python3
"""扫描本地库，用中文字幕论坛补中文版磁链并替换。

模式：
- 日常（默认）：论坛最新 CHINESE_FORUM_DAILY_PAGES 页（默认 2），命中缺中文则进帖拿链
- 一次性回补 CHINESE_FORUM_BACKFILL=1：按库 NFO 最早作品日停列表，再定向进帖
不再使用 sukebei 搜中文字幕。
"""
import json, os, re, time, random, shutil, subprocess, sys, urllib.parse
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.log_writer import write as log_write, cleanup as log_cleanup
from main_video import (
    MAIN_VIDEO_MIN_SIZE,
    collect_main_video_candidates,
    find_main_video,
)
from video_id import normalize_local_video_id
from weekly_store import update_json as update_weekly_json

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
PROXY = os.environ.get("PROXY", "") or None
MAX_AGE = int(os.environ.get("REPLACE_MAX_AGE", "30"))  # 保留兼容，主路径不再用 mtime 截断
QB_URL = os.environ.get("QBITTORRENT_URL", "http://127.0.0.1:8080")
QB_USER = os.environ.get("QBITTORRENT_USERNAME", "admin")
QB_PASS = os.environ.get("QBITTORRENT_PASSWORD", "adminadmin")
PENDING_FILE = os.environ.get("CHINESE_PENDING_FILE", "/db/chinese_pending.json")
MEDIA_PROVENANCE_FILE = ".av_garden_media.json"
BACKFILL = os.environ.get("CHINESE_FORUM_BACKFILL", "").strip().lower() in ("1", "true", "yes", "on")
DAILY_PAGES = int(os.environ.get("CHINESE_FORUM_DAILY_PAGES", "2"))
BACKFILL_MAX_PAGES = int(os.environ.get("CHINESE_FORUM_MAX_PAGES", "0"))  # 0=只靠日期
DRY_RUN = os.environ.get("CHINESE_FORUM_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
SKIP_WEEKLY_REFILL = os.environ.get("REPLACE_SKIP_WEEKLY_REFILL", "").strip().lower() in ("1", "true", "yes", "on")

CN_MARKER_PATTERNS = [
    re.compile(r"中文字幕", re.I),
    re.compile(r"中文", re.I),
    re.compile(r"CHINESE", re.I),
    re.compile(r"(?<![A-Z0-9])-C(?![A-Z0-9])", re.I),
    re.compile(r"(?<![A-Z0-9])-CH(?![A-Z0-9])", re.I),
    re.compile(r"(?<![A-Z0-9])_CH(?![A-Z0-9])", re.I),
    re.compile(r"(?<![A-Z0-9])FHD_CH(?![A-Z0-9])", re.I),
    re.compile(r"(?<![A-Z0-9])CH(?![A-Z0-9])", re.I),
]


def has_cn_marker(text):
    text = text or ""
    return any(pattern.search(text) for pattern in CN_MARKER_PATTERNS)


def has_cn_marker_for_avid(text, avid):
    if has_cn_marker(text):
        return True
    upper = (text or "").upper()
    stem = re.sub(r"\.(MP4|MKV|AVI|MOV|M4V)\b", "", upper)
    compact = re.sub(r"[^A-Z0-9]", "", stem)
    for variant in code_variants(avid):
        code = variant.replace("-", "")
        if code and re.search(rf"{re.escape(code)}(?:C|CH)(?![A-Z0-9])", compact):
            return True
        if variant and re.search(rf"{re.escape(variant)}[\s._-]*(?:C|CH)(?=$|[^A-Z0-9])", stem):
            return True
    return False


def code_variants(avid):
    up = (avid or "").upper()
    return {up, up.replace("-", "")}


def text_has_avid(text, avid):
    up = (text or "").upper()
    compact = re.sub(r"[^A-Z0-9]", "", up)
    variants = code_variants(avid)
    return any(v and (v in up or v.replace("-", "") in compact) for v in variants)


def clean_avid(name):
    """Extract the searchable code from folder/torrent names like 857OMG-032."""
    return normalize_local_video_id(name) or (name or "").strip().upper()


def format_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024


def select_qb_main_file(files):
    """Select the exact main MP4 from qB's torrent file list."""
    candidates = []
    for item in files if isinstance(files, list) else []:
        name = str(item.get("name") or "")
        size = int(item.get("size") or 0)
        index = item.get("index")
        if index is None or not name.lower().endswith(".mp4") or size < MAIN_VIDEO_MIN_SIZE:
            continue
        candidates.append({
            "index": int(index),
            "name": name,
            "size": size,
            "progress": float(item.get("progress") or 0),
        })
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["size"], item["name"]))


def qb_torrent_files(opener, torrent_hash):
    import urllib.request

    endpoint = f"{QB_URL}/api/v2/torrents/files?hash={urllib.parse.quote(torrent_hash)}"
    response = opener.open(urllib.request.Request(endpoint), timeout=10)
    return json.loads(response.read().decode())


def remove_qb_torrent_record(opener, torrent_hash):
    """Remove qB state without allowing qB to recursively delete a media directory."""
    import urllib.request

    data = urllib.parse.urlencode({
        "hashes": torrent_hash,
        "deleteFiles": "false",
    }).encode()
    opener.open(
        urllib.request.Request(f"{QB_URL}/api/v2/torrents/delete", data=data),
        timeout=10,
    ).read()


def resolve_qb_file_path(torrent, selected_file):
    """Resolve a qB file-list entry without guessing from file timestamps."""
    save_path = os.path.realpath(str(torrent.get("save_path") or SAVE_PATH))
    relative = str(selected_file.get("name") or "").lstrip("/\\")
    if os.path.normpath(relative) == os.pardir or os.path.normpath(relative).startswith(os.pardir + os.sep):
        return None
    candidate = os.path.realpath(os.path.join(save_path, relative))
    try:
        if os.path.commonpath((save_path, candidate)) == save_path and os.path.isfile(candidate):
            return candidate
    except ValueError:
        return None

    content_path = os.path.realpath(str(torrent.get("content_path") or ""))
    if os.path.isfile(content_path):
        return content_path if os.path.basename(content_path) == os.path.basename(relative) else None
    fallback = os.path.realpath(os.path.join(content_path, os.path.basename(relative)))
    try:
        if content_path and os.path.commonpath((content_path, fallback)) == content_path and os.path.isfile(fallback):
            return fallback
    except ValueError:
        pass
    return None


def validate_video_file(path):
    if find_main_video(path) != path:
        return False
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        log("  ffprobe unavailable; refusing destructive Chinese merge cleanup")
        return False
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=nw=1:nk=1",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.returncode == 0 and "video" in (result.stdout or "").lower()


def _atomic_write_json(path, payload):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp_path = f"{path}.tmp-{os.getpid()}-{time.time_ns()}"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def write_media_provenance(target_dir, avid, torrent_hash, selected_file, destination):
    relative = os.path.relpath(destination, target_dir)
    payload = {
        "version": 1,
        "updatedAt": datetime.now().astimezone().isoformat(),
        "chineseMain": {
            "videoId": avid,
            "path": relative,
            "size": os.path.getsize(destination),
            "source": "forum-103",
            "torrentHash": torrent_hash,
            "torrentFileIndex": selected_file["index"],
            "torrentFilePath": selected_file["name"],
        },
    }
    _atomic_write_json(os.path.join(target_dir, MEDIA_PROVENANCE_FILE), payload)


def recorded_chinese_main(dpath):
    path = os.path.join(dpath, MEDIA_PROVENANCE_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        relative = str(payload.get("chineseMain", {}).get("path") or "")
        if not relative or os.path.isabs(relative):
            return None
        target = os.path.realpath(os.path.join(dpath, relative))
        if os.path.commonpath((os.path.realpath(dpath), target)) != os.path.realpath(dpath):
            return None
        return target if find_main_video(target) == target else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def qb_protected_media_dirs(torrents, save_path=None, exclude_hashes=None):
    """Return media directories currently owned by any healthy qB task."""
    save_path = os.path.realpath(save_path or SAVE_PATH)
    excluded = {str(value) for value in (exclude_hashes or ())}
    protected = set()
    for torrent in torrents if isinstance(torrents, list) else []:
        if str(torrent.get("hash") or "") in excluded:
            continue
        if str(torrent.get("state") or "") in ("missingFiles", "error", "unknown"):
            continue
        content_path = str(torrent.get("content_path") or "")
        if not content_path:
            content_path = os.path.join(str(torrent.get("save_path") or save_path), str(torrent.get("name") or ""))
        real = os.path.realpath(content_path)
        try:
            relative = os.path.relpath(real, save_path)
        except ValueError:
            continue
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            continue
        first = relative.split(os.sep, 1)[0]
        if first and first not in (".", "__weekly__", "__online__", "thumb"):
            protected.add(os.path.realpath(os.path.join(save_path, first)))
    return protected

def qb_login():
    import urllib.request, http.cookiejar
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    login_data = f"username={urllib.parse.quote(QB_USER)}&password={urllib.parse.quote(QB_PASS)}".encode()
    opener.open(urllib.request.Request(f"{QB_URL}/api/v2/auth/login", data=login_data), timeout=5)
    return opener

def load_pending():
    try:
        if os.path.exists(PENDING_FILE):
            with open(PENDING_FILE) as f:
                return json.load(f)
    except:
        pass
    return {}

def save_pending(pending):
    _atomic_write_json(PENDING_FILE, pending)

def update_weekly_magnet(avid, magnet):
    """更新 weekly.json 里该番号的 magnet 字段"""
    weekly_path = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
    try:
        if not os.path.exists(weekly_path):
            return
        def update(items):
            for item in items if isinstance(items, list) else []:
                if item.get("id", "").upper() == avid.upper():
                    item["magnet"] = magnet
                    break
            return items

        update_weekly_json(weekly_path, [], update)
        log(f"  Updated weekly.json magnet for {avid}")
    except Exception as e:
        log(f"  Update weekly magnet error: {e}")

def qb_has_cn_avid(avid):
    """检查 qB 里是否已有该番号的种子（只跳过已有中文字幕版的）"""
    import urllib.request, http.cookiejar
    try:
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        login_data = f"username={urllib.parse.quote(QB_USER)}&password={urllib.parse.quote(QB_PASS)}".encode()
        opener.open(urllib.request.Request(f"{QB_URL}/api/v2/auth/login", data=login_data), timeout=5)
        resp = opener.open(urllib.request.Request(f"{QB_URL}/api/v2/torrents/info"), timeout=10)
        torrents = json.loads(resp.read().decode())
        for t in torrents:
            name = t.get("name", "")
            sp = t.get("save_path", "")
            content_path = t.get("content_path", "")
            probe = " ".join([name, sp, content_path])
            if text_has_avid(probe, avid):
                # 已有中文字幕版 → 跳过；普通版 → 可以替换
                if has_cn_marker_for_avid(probe, avid):
                    return True
        return False
    except:
        return False

def qb_add_magnet(magnet):
    """加磁链到 qB，返回 torrent hash 或 None"""
    import urllib.request, http.cookiejar
    try:
        opener = qb_login()
        # 记录当前 hash 集合
        before = set()
        try:
            resp0 = opener.open(urllib.request.Request(f"{QB_URL}/api/v2/torrents/info"), timeout=10)
            before = {t["hash"] for t in json.loads(resp0.read().decode())}
        except:
            pass
        add_data = f"urls={urllib.parse.quote(magnet)}&category=AV_GARDEN".encode()
        resp = opener.open(urllib.request.Request(f"{QB_URL}/api/v2/torrents/add", data=add_data), timeout=10)
        if resp.read().decode().strip() != "Ok.":
            return None
        time.sleep(2)
        # 找到新增的 torrent hash
        resp2 = opener.open(urllib.request.Request(f"{QB_URL}/api/v2/torrents/info"), timeout=10)
        for t in json.loads(resp2.read().decode()):
            if t["hash"] not in before:
                return t["hash"]
        return None
    except Exception as e:
        log(f"  qB add error: {e}")
        return None

def log(msg):
    print(f"[ReplaceCN] {msg}", flush=True)


def dir_has_cn_video(dpath, dirname, mp4_files, avid=None):
    avid = avid or clean_avid(dirname)
    if has_cn_marker_for_avid(dirname, avid):
        return True
    if recorded_chinese_main(dpath):
        return True
    for filename in mp4_files:
        if has_cn_marker_for_avid(filename, avid):
            return True
    # Legacy markers remain compatible only while a real main video exists.
    if os.path.exists(os.path.join(dpath, ".av_garden_chinese")) and collect_main_video_candidates(dpath):
        return True
    for filename in os.listdir(dpath):
        if filename.lower().endswith(".nfo"):
            try:
                with open(os.path.join(dpath, filename), encoding="utf-8", errors="ignore") as f:
                    if has_cn_marker_for_avid(f.read(), avid):
                        return True
            except:
                pass
    return False


# 只取作品发行日字段，不用 plot
_NFO_DATE = re.compile(
    r"<(premiered|releasedate)\b[^>]*>\s*(\d{4}-\d{2}-\d{2})",
    re.I,
)


def read_nfo_premiered(dpath):
    """读目录内 NFO 作品发行日 YYYY-MM-DD，没有则 None。"""
    try:
        names = os.listdir(dpath)
    except OSError:
        return None
    for filename in names:
        if not filename.lower().endswith(".nfo"):
            continue
        try:
            with open(os.path.join(dpath, filename), encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        m = _NFO_DATE.search(text)
        if m:
            return m.group(2)
    return None


def scan_library(save_path=None):
    """扫描本地媒体库：earliest NFO 作品日 + 缺中文目录。"""
    save_path = save_path or SAVE_PATH
    earliest = None
    missing = {}  # avid -> {target_dir, premiered}
    existing_cn = 0
    total_with_video = 0
    no_nfo_date = 0

    try:
        entries = sorted(os.listdir(save_path))
    except OSError as e:
        log(f"Cannot list SAVE_PATH {save_path}: {e}")
        return {"earliest": None, "missing": {}, "existing_cn": 0, "total": 0, "no_nfo_date": 0}

    for d in entries:
        if d.startswith("_") or d.startswith(".") or d in ("thumb",):
            continue
        dpath = os.path.join(save_path, d)
        if not os.path.isdir(dpath):
            continue
        candidates = collect_main_video_candidates(dpath)
        if not candidates:
            continue
        mp4_files = [os.path.relpath(item["path"], dpath) for item in candidates]

        total_with_video += 1
        search_avid = clean_avid(d)
        premiered = read_nfo_premiered(dpath)
        if premiered:
            try:
                pd = datetime.strptime(premiered, "%Y-%m-%d").date()
                if earliest is None or pd < earliest:
                    earliest = pd
            except ValueError:
                no_nfo_date += 1
        else:
            no_nfo_date += 1

        if dir_has_cn_video(dpath, d, mp4_files, search_avid):
            existing_cn += 1
            continue

        key = (search_avid or d).upper()
        # 同一番号多目录时保留第一个
        if key not in missing:
            missing[key] = {
                "avid": key,
                "target_dir": d,
                "premiered": premiered or "",
            }

    return {
        "earliest": earliest,
        "missing": missing,
        "existing_cn": existing_cn,
        "total": total_with_video,
        "no_nfo_date": no_nfo_date,
    }

def merge_completed_chinese():
    """检查已下载完成的中文字幕版，合并到原文件夹"""
    import urllib.request
    pending = load_pending()
    if not pending:
        return
    try:
        opener = qb_login()
        resp = opener.open(urllib.request.Request(f"{QB_URL}/api/v2/torrents/info"), timeout=10)
        torrents = json.loads(resp.read().decode())
    except Exception as e:
        log(f"  Merge check qB error: {e}")
        return

    merged = 0
    for hash_str, pending_info in list(pending.items()):
        if isinstance(pending_info, dict):
            avid = pending_info.get("avid", "")
            target_dirname = pending_info.get("target_dir", avid)
        else:
            avid = pending_info
            target_dirname = pending_info
        # 找到对应的 qB 种子
        t_info = None
        for t in torrents:
            if t.get("hash", "") == hash_str:
                t_info = t
                break
        if not t_info:
            # 种子已被删除(已合并过)，清理 pending
            del pending[hash_str]
            save_pending(pending)
            continue

        state = t_info.get("state", "")
        # completed states in qB
        if state not in ("uploading", "stalledUP", "pausedUP", "queuedUP", "checkingUP"):
            continue

        log(f"  Merging {avid}: torrent={t_info.get('name','')}")

        try:
            files = qb_torrent_files(opener, hash_str)
            selected = select_qb_main_file(files)
            if not selected:
                log(f"  No main MP4 in qB file list for {avid}; keep torrent and pending record")
                continue
            if selected["progress"] < 0.999:
                log(f"  qB selected file is incomplete for {avid}: {selected['progress'] * 100:.1f}%")
                continue

            if not isinstance(pending_info, dict):
                pending_info = {"avid": avid, "target_dir": target_dirname}
            pending_info["selected_file"] = {
                "index": selected["index"],
                "name": selected["name"],
                "size": selected["size"],
            }
            pending[hash_str] = pending_info
            save_pending(pending)

            src = resolve_qb_file_path(t_info, selected)
            if not src or not validate_video_file(src):
                log(f"  qB reports complete but exact source file is missing/invalid for {avid}; no cleanup")
                continue

            target_dir = os.path.join(SAVE_PATH, target_dirname)
            os.makedirs(target_dir, exist_ok=True)
            dst = os.path.join(target_dir, f"{avid}-C.mp4")
            if os.path.exists(dst) and os.path.realpath(dst) != os.path.realpath(src):
                if not validate_video_file(dst) or os.path.getsize(dst) != selected["size"]:
                    log(f"  Refusing to overwrite existing {dst}; keep torrent for review")
                    continue
            elif os.path.realpath(src) != os.path.realpath(dst):
                shutil.move(src, dst)
                log(f"  Moved exact qB file {selected['name']} -> {dst}")

            if not validate_video_file(dst):
                log(f"  Validation failed after moving {avid}; keep torrent and skip cleanup")
                continue

            write_media_provenance(target_dir, avid, hash_str, selected, dst)
            marker_path = os.path.join(target_dir, ".av_garden_chinese")
            with open(marker_path, "w", encoding="utf-8") as handle:
                handle.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            protected_dirs = qb_protected_media_dirs(torrents, exclude_hashes={hash_str})
            cleanup_original(
                avid,
                target_dirname,
                keep_paths=[dst],
                force=True,
                protected_dirs=protected_dirs,
            )

            try:
                remove_qb_torrent_record(opener, hash_str)
            except Exception as e:
                log(f"  qB record removal failed for {avid}: {e}; provenance retained")
                continue

            del pending[hash_str]
            save_pending(pending)
            merged += 1
            log_write("ReplaceCN", f"{avid} 中文字幕版已合并")
        except Exception as e:
            log(f"  Merge {avid} error: {e}")

    if merged:
        log(f"  Merged {merged} Chinese torrent(s)")
    # 历史目录只在 qB 状态可确认时清理；活跃/做种目录全部保护。
    try:
        response = opener.open(urllib.request.Request(f"{QB_URL}/api/v2/torrents/info"), timeout=10)
        current_torrents = json.loads(response.read().decode())
        sweep_leftover_non_chinese(protected_dirs=qb_protected_media_dirs(current_torrents))
    except Exception as e:
        log(f"  Sweep skipped because qB protection could not be verified: {e}")

_VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".ts")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_KEEP_DOTFILES = {".av_garden_chinese", ".nassav_chinese", MEDIA_PROVENANCE_FILE}

# 允许保留的元数据图（Jellyfin / 本项目刮削命名）
_ALLOWED_IMAGE_NAME = re.compile(
    r"(?i)("
    r"poster|fanart|cover|landscape|thumb|folder|backdrop|banner|clearart|logo|disc"
    r"|-poster\b|-fanart(?:-\d+)?\b|-thumb\b|-landscape\b|-cover\b"
    r")"
)

# 种子里常见的广告/推广片（非正片），有中文正片后一律删
_PROMO_NAME_PATTERNS = [
    re.compile(r"游戏大全", re.I),
    re.compile(r"直播大秀", re.I),
    re.compile(r"强\s*力\s*推\s*荐", re.I),
    re.compile(r"苍\s*老\s*师", re.I),
    re.compile(r"社\s*區\s*最\s*新\s*情\s*報", re.I),
    re.compile(r"社\s*区\s*最\s*新\s*情\s*报", re.I),
    re.compile(r"台湾uu美少女", re.I),
    re.compile(r"免费18禁手游", re.I),
    re.compile(r"赌场", re.I),
    re.compile(r"推广", re.I),
    re.compile(r"广告", re.I),
    re.compile(r"(?<![a-z])preview(?![a-z])", re.I),
    re.compile(r"(?<![a-z])sample(?![a-z])", re.I),
    re.compile(r"(?<![a-z])trailer(?![a-z])", re.I),
]


def is_video_filename(name):
    n = (name or "").lower()
    return n.endswith(_VIDEO_EXTS) and not name.startswith("._")


def is_image_filename(name):
    n = (name or "").lower()
    return n.endswith(_IMAGE_EXTS) and not name.startswith("._")


def is_promo_video(name):
    text = name or ""
    return any(p.search(text) for p in _PROMO_NAME_PATTERNS)


def is_allowed_media_image(name):
    """封面 / 预览 fanart 等；广告图、随机截图不在此列。"""
    base = os.path.basename(name or "")
    if not is_image_filename(base):
        return False
    return bool(_ALLOWED_IMAGE_NAME.search(base))


def is_allowed_nfo(name):
    return (name or "").lower().endswith(".nfo") and not name.startswith("._")


def iter_all_files(dpath):
    """递归列出目录内所有文件 (abs_path, rel_path)。"""
    for root, dirs, files in os.walk(dpath):
        dirs[:] = [d for d in dirs if not d.startswith("._")]
        for f in files:
            abs_path = os.path.join(root, f)
            rel = os.path.relpath(abs_path, dpath)
            yield abs_path, rel


def iter_videos(dpath):
    """递归列出目录内视频文件 (abs_path, rel_path)。"""
    for abs_path, rel in iter_all_files(dpath):
        if is_video_filename(os.path.basename(abs_path)):
            yield abs_path, rel


def should_keep_file(abs_path, rel, avid, keep_video_paths, delete_untracked_videos=True):
    """合并后白名单：中文正片 + NFO + poster/fanart 封面预览 + 标记文件。"""
    name = os.path.basename(abs_path)
    # macOS 垃圾
    if name.startswith("._"):
        return False
    # 内部标记
    if name in _KEEP_DOTFILES or name == ".av_garden_chinese":
        return True
    if name.startswith("."):
        return False

    try:
        real = os.path.realpath(abs_path)
    except OSError:
        real = abs_path

    # 中文正片（刚迁入的 keep 路径，或文件名带中文标记）
    if is_video_filename(name):
        if is_promo_video(name) or is_promo_video(rel):
            return False
        if real in keep_video_paths:
            return True
        if has_cn_marker_for_avid(name, avid) or has_cn_marker_for_avid(rel, avid):
            return True
        return not delete_untracked_videos

    # NFO
    if is_allowed_nfo(name):
        return True

    # 封面 / 预览图
    if is_allowed_media_image(name):
        return True

    # 其它一律不要（.url .html .txt 种子说明、广告图、字幕包外的杂项等）
    return False


def cleanup_original(
    avid,
    target_dirname=None,
    keep_paths=None,
    force=False,
    protected_dirs=None,
    delete_untracked_videos=True,
):
    """合并后整理目录：只留中文视频、NFO、封面/预览图。

    keep_paths: 刚合并进来的中文正片绝对路径，即使文件名无 -C 也保留。
    force: 保留参数兼容旧调用；合并后始终按白名单清理。
    """
    target_dirname = target_dirname or avid
    dpath = os.path.join(SAVE_PATH, target_dirname)
    if not os.path.isdir(dpath):
        return []
    protected = {os.path.realpath(path) for path in (protected_dirs or ())}
    if os.path.realpath(dpath) in protected:
        log(f"  Skip cleanup for qB-owned directory: {target_dirname}")
        return []

    keep_videos = set()
    for p in (keep_paths or []):
        if p:
            try:
                keep_videos.add(os.path.realpath(p))
            except OSError:
                keep_videos.add(p)

    deleted = []
    for abs_path, rel in list(iter_all_files(dpath)):
        if should_keep_file(
            abs_path,
            rel,
            avid,
            keep_videos,
            delete_untracked_videos=delete_untracked_videos,
        ):
            continue
        try:
            os.remove(abs_path)
            deleted.append(rel)
        except Exception as e:
            log(f"  Delete {rel} error: {e}")

    if deleted:
        # 日志过长时截断
        preview = ", ".join(deleted[:12])
        if len(deleted) > 12:
            preview += f" ... (+{len(deleted) - 12})"
        log(f"  Cleaned {avid}: {preview}")

    # 删空子目录（广告解压目录等）
    for root, dirs, files in os.walk(dpath, topdown=False):
        if root == dpath:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass

    return deleted


def sweep_leftover_non_chinese(save_path=None, protected_dirs=None):
    """Clean verified Chinese media sets without inferring identity from mtime."""
    save_path = save_path or SAVE_PATH
    if protected_dirs is None:
        log("  Sweep skipped: qB protection was not supplied")
        return 0
    protected = {os.path.realpath(path) for path in (protected_dirs or ())}
    swept = 0
    deleted_total = 0
    try:
        entries = os.listdir(save_path)
    except OSError as e:
        log(f"Sweep list error: {e}")
        return 0

    for d in entries:
        if d.startswith("_") or d.startswith(".") or d == "thumb":
            continue
        dpath = os.path.join(save_path, d)
        if not os.path.isdir(dpath):
            continue
        if os.path.realpath(dpath) in protected:
            log(f"  Sweep skip qB-owned directory: {d}")
            continue
        avid = clean_avid(d)
        videos = list(iter_videos(dpath))
        has_marker_file = os.path.exists(os.path.join(dpath, ".av_garden_chinese"))
        recorded = recorded_chinese_main(dpath)
        cn_videos = []
        for abs_path, rel in videos:
            name = os.path.basename(abs_path)
            if is_promo_video(name) or is_promo_video(rel):
                continue
            if has_cn_marker_for_avid(name, avid) or has_cn_marker_for_avid(rel, avid):
                cn_videos.append(abs_path)

        candidates = collect_main_video_candidates(dpath)
        if not recorded and not cn_videos and not (has_marker_file and candidates):
            continue

        if recorded:
            keep = {os.path.realpath(recorded)}
            delete_untracked = True
        elif cn_videos:
            keep = {os.path.realpath(path) for path in cn_videos}
            delete_untracked = True
        else:
            # A legacy marker proves intent, not which file was Chinese. Keep all
            # valid main videos and only remove known promo/non-media junk.
            keep = {os.path.realpath(item["path"]) for item in candidates}
            delete_untracked = False
        deleted = cleanup_original(
            avid,
            d,
            keep_paths=keep,
            force=True,
            protected_dirs=protected,
            delete_untracked_videos=delete_untracked,
        )
        if deleted:
            swept += 1
            deleted_total += len(deleted)
            if not has_marker_file:
                try:
                    with open(os.path.join(dpath, ".av_garden_chinese"), "w") as f:
                        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                except OSError:
                    pass

    if swept:
        log(f"  Sweep media-set: {swept} dirs, {deleted_total} files removed")
    else:
        log("  Sweep media-set: nothing to clean")
    return deleted_total

def _refill_weekly_gaps():
    """可选：补 weekly 空字段（JavBus）。日常可关。"""
    if SKIP_WEEKLY_REFILL:
        log("Skip weekly fanart refill (REPLACE_SKIP_WEEKLY_REFILL)")
        return 0
    weekly_path = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
    if not os.path.exists(weekly_path):
        return 0
    from src.weekly import javbus as jb
    jb.set_proxy(PROXY)
    with open(weekly_path) as f:
        all_items = json.load(f)
    refilled = 0
    for item in all_items:
        avid = item.get("id", "")
        if not item.get("fanarts") and not item.get("actresses"):
            log(f"  Refilling {avid}...")
            html = jb.fetch_page(avid)
            info = jb.parse_page(html) if html else {}
            if info.get("fanarts") or info.get("actresses"):
                for k in ["fanarts", "actresses", "genres", "duration"]:
                    if info.get(k):
                        item[k] = info[k]
                if info.get("title") and item.get("title") == avid:
                    item["title"] = info["title"]
                refilled += 1
                log(f"  Refilled {avid}: fanarts={len(info.get('fanarts',[]))}, actresses={info.get('actresses',[])}")
            time.sleep(random.uniform(3, 6))
    if refilled:
        with open(weekly_path, "w") as f:
            json.dump(all_items, f, ensure_ascii=False, indent=2)
        log(f"  Refilled {refilled} videos")
    else:
        log("  No videos need refill")
    return refilled


def main():
    from src.weekly import chinese_forum  # lazy: merge/sweep 不依赖论坛模块

    mode = "backfill" if BACKFILL else "daily"
    log(f"=== Start mode={mode} dry_run={DRY_RUN} ===")
    log(f"SAVE_PATH={SAVE_PATH}")
    chinese_forum.set_proxy(PROXY)

    # 0. 先合并已完成的中文字幕版
    if not DRY_RUN:
        merge_completed_chinese()
    else:
        log("DRY_RUN: skip merge_completed_chinese")

    # 1. 扫本地库
    lib = scan_library(SAVE_PATH)
    missing = lib["missing"]
    existing_cn = lib["existing_cn"]
    earliest = lib["earliest"]
    log(
        f"Library: total_video_dirs={lib['total']} existing_cn={existing_cn} "
        f"missing_cn={len(missing)} no_nfo_date={lib['no_nfo_date']} "
        f"earliest_premiered={earliest.isoformat() if earliest else None}"
    )

    if not missing:
        log("No missing Chinese items in library; done")
        try:
            log_write("ReplaceCN", f"mode={mode} 无缺中文条目")
            log_cleanup()
        except Exception:
            pass
        return

    # 2. 论坛列表
    stop_date = None
    max_pages = DAILY_PAGES
    if BACKFILL:
        if earliest is None:
            log("BACKFILL abort: no NFO premiered dates in library (cannot set stop date)")
            try:
                log_write("ReplaceCN", "backfill中止: 库内无NFO作品日")
                log_cleanup()
            except Exception:
                pass
            return
        stop_date = earliest.isoformat()
        max_pages = BACKFILL_MAX_PAGES  # 0 = only stop by date
        log(f"BACKFILL: list until postDate >= {stop_date}, max_pages={max_pages or 'unlimited'}")
    else:
        log(f"DAILY: list first {max_pages} page(s)")

    client = chinese_forum.ForumClient()
    if not client.ensure_safe():
        log("Forum safe gate failed; abort")
        return

    list_items = chinese_forum.get_list_until(
        stop_date=stop_date,
        max_pages=max_pages,
        client=client,
    )
    log(f"Forum list unique codes: {len(list_items)}")

    # 3. 列表 ∩ 缺中文
    missing_ids = set(missing.keys())
    hits = []
    for item in list_items:
        avid = (item.get("id") or "").upper()
        if avid in missing_ids:
            hits.append(item)
    # 去重保序
    seen = set()
    unique_hits = []
    for item in hits:
        avid = item["id"].upper()
        if avid in seen:
            continue
        seen.add(avid)
        unique_hits.append(item)
    log(f"Forum hits for missing_cn: {len(unique_hits)}")

    # 4. 定向进帖拿 magnet
    magnets = chinese_forum.fetch_magnets_for_targets(
        unique_hits,
        {i["id"].upper() for i in unique_hits},
        client=client,
    )
    log(f"Magnets fetched: {len(magnets)}")

    # 5. 加入 qB
    added = 0
    existing_qb = 0
    add_failed = 0
    no_magnet = 0
    for item in unique_hits:
        avid = item["id"].upper()
        target_dirname = missing[avid]["target_dir"]
        info = magnets.get(avid)
        if not info or not info.get("magnet"):
            no_magnet += 1
            continue
        magnet = info["magnet"]
        if DRY_RUN:
            log(f"DRY_RUN would add {avid}: {magnet[:70]}...")
            added += 1
            continue
        if qb_has_cn_avid(avid):
            existing_qb += 1
            log(f"  Skip {avid}: already in qB")
            continue
        torrent_hash = qb_add_magnet(magnet)
        if torrent_hash:
            log(f"  {avid}: added Chinese magnet to qB ({torrent_hash[:12]})")
            update_weekly_magnet(avid, magnet)
            pending = load_pending()
            pending[torrent_hash] = {
                "avid": avid,
                "target_dir": target_dirname,
                "source": "forum-103",
                "added_at": datetime.now().astimezone().isoformat(),
            }
            save_pending(pending)
            added += 1
        else:
            add_failed += 1
            log(f"  {avid}: failed to add to qB")
        time.sleep(random.uniform(2, 5))

    log(
        f"=== Done mode={mode}: list={len(list_items)} hits={len(unique_hits)} "
        f"added={added} qb_skip={existing_qb} no_magnet={no_magnet} fail={add_failed} ==="
    )

    # 6. 可选 weekly 补字段（回补时默认跳过以省时间，可用 env 打开）
    refilled = 0
    if not BACKFILL and not DRY_RUN:
        refilled = _refill_weekly_gaps()

    try:
        summary = (
            f"mode={mode} 缺中文{len(missing)} 论坛列表{len(list_items)} 命中{len(unique_hits)} "
            f"新增任务{added} qB已有{existing_qb} 无磁链{no_magnet} 失败{add_failed} "
            f"earliest={earliest.isoformat() if earliest else '-'} 补刮{refilled}"
        )
        log_write("ReplaceCN", summary)
        log_cleanup()
    except Exception:
        pass


if __name__ == "__main__":
    main()
