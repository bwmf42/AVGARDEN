#!/usr/bin/env python3
"""
AV/GARDEN Queue API v7 — 
下载管理（完整声明周期：排队→下载中→已完成，保留展示）
完成后自动更新 weekly.json + 写入 AV/GARDEN SQLite（让主页也可见）
"""
import os, sys, json, signal, time, subprocess, re, shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

QUEUE_PATH = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
STATE_PATH = os.environ.get("STATE_PATH", "/db/queue_state.json")
CURRENT_PATH = os.environ.get("CURRENT_PATH", "/db/current_download.txt")
LOCK_PATH = os.environ.get("LOCK_PATH", "/app/work")
SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
DB_PATH = os.environ.get("DB_PATH", "/db/downloaded.db")
HISTORY_PATH = os.environ.get("HISTORY_PATH", "/db/download_history.json")
HISTORY_RETENTION_DAYS = int(os.environ.get("HISTORY_RETENTION_DAYS", "7"))
FAILED_QUEUE_JSON_PATH = os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "failed_queue.json")
FAILED_QUEUE_PATH = os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "failed_queue.txt")
RETRY_PATH = os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "retry_counts.json")
WEEKLY_JSON = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
BLOCKED_ACTRESSES = set(
    name.strip() for name in os.environ.get("BLOCKED_ACTRESSES", "").split(",") if name.strip()
)
weekly_scrape_proc = None

def clean_avid(name):
    """从文件夹/种子名中提取标准车牌号（去掉 -C, ch, 中文字幕 等后缀）"""
    name = name.strip().upper()
    source_prefixed = re.match(r'^\d+([A-Z]{2,}\d*-\d+)', name)
    if source_prefixed:
        return source_prefixed.group(1)
    m = re.match(r'^([A-Z0-9]+-\d+)', name)
    if m:
        return m.group(1)
    for pat in [r'-C$', r'CH$', r'-中文字幕$', r'_FHD_CH$', r'_CH$', r'\(\d+\)$', r'\.MP4$']:
        c = re.sub(pat, '', name)
        if re.match(r'^[A-Z0-9]+-\d+$', c):
            return c
    search = re.search(r'([A-Za-z]{2,}\d*)-(\d+)', name)
    if search:
        return f"{search.group(1).upper()}-{search.group(2)}"
    return name

_speed_cache = {}

# qBittorrent 配置
QB_URL = os.environ.get("QBITTORRENT_URL", "http://127.0.0.1:8080")
QB_USERNAME = os.environ.get("QBITTORRENT_USERNAME", "admin")
QB_PASSWORD = os.environ.get("QBITTORRENT_PASSWORD", "adminadmin")

def log(msg):
    print(f"[QueueAPI] {msg}", flush=True)


def qb_api(endpoint):
    """调用 qBittorrent Web API，读取进度"""
    import urllib.request, http.cookiejar
    try:
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        login_url = f"{QB_URL}/api/v2/auth/login"
        login_data = f"username={urllib.parse.quote(QB_USERNAME)}&password={urllib.parse.quote(QB_PASSWORD)}".encode()
        resp = opener.open(urllib.request.Request(login_url, data=login_data), timeout=5)
        if resp.status != 200:
            return None
        resp = opener.open(urllib.request.Request(f"{QB_URL}{endpoint}"), timeout=10)
        return json.loads(resp.read().decode())
    except Exception as e:
        log(f"qB API error: {e}")
        return None


def get_qb_progress(save_dir):
    """从 qBittorrent 获取指定下载目录的进度 {size, speed, progress_pct}"""
    torrents = qb_api("/api/v2/torrents/info")
    if not torrents:
        return None
    code = os.path.basename(save_dir.rstrip("/")).upper()
    for t in torrents:
        cp = (t.get("content_path", "") or t.get("name", "")).upper()
        if code in cp:
            return {
                "size": t.get("completed", 0),
                "speed": t.get("dlspeed", 0),
                "progress_pct": int(t.get("progress", 0) * 100),
            }
    return None

def load_state():
    if not os.path.exists(STATE_PATH):
        return []
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except:
        return []

def save_state(items):
    with open(STATE_PATH, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r") as f:
            history = json.load(f)
        return prune_history(history)
    except:
        return []

def save_history(items):
    with open(HISTORY_PATH, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def parse_history_time(value):
    if not value:
        return None
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return time.mktime(time.strptime(value[:size], fmt))
        except:
            pass
    return None

def is_recent_timestamp(value):
    if not value:
        return True
    try:
        ts = float(value)
    except:
        return True
    if ts <= 0:
        return True
    return ts >= time.time() - HISTORY_RETENTION_DAYS * 86400

def prune_history(items):
    if not isinstance(items, list):
        return []
    cutoff = time.time() - HISTORY_RETENTION_DAYS * 86400
    kept = []
    changed = False
    for item in items:
        completed_at = parse_history_time(item.get("completed_at", ""))
        if completed_at is None or completed_at >= cutoff:
            kept.append(item)
        else:
            changed = True
    if changed:
        save_history(kept)
    return kept

def append_history(code, size):
    """追加一条完成记录（去重）"""
    history = load_history()
    if code in [h["code"] for h in history]:
        return
    history.append({
        "code": code,
        "size": size,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_history(history)

def is_weekly_scrape_running():
    global weekly_scrape_proc
    if weekly_scrape_proc and weekly_scrape_proc.poll() is None:
        return True
    weekly_scrape_proc = None
    return False

def start_weekly_scrape():
    global weekly_scrape_proc
    if is_weekly_scrape_running():
        return False
    weekly_scrape_proc = subprocess.Popen(
        ["/app/venv/bin/python3", "/app/weekly_updater.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    return True

def clear_failure_record(code):
    """重新入队时清理旧失败/重试记录，避免刚添加就显示失败。"""
    code = code.upper().strip()
    try:
        if os.path.exists(FAILED_QUEUE_JSON_PATH):
            with open(FAILED_QUEUE_JSON_PATH, "r", encoding="utf-8") as f:
                records = json.load(f)
            if isinstance(records, list):
                filtered = [r for r in records if str(r.get("code", "")).upper() != code]
                if len(filtered) != len(records):
                    with open(FAILED_QUEUE_JSON_PATH, "w", encoding="utf-8") as f:
                        json.dump(filtered, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Failed to clear failed_queue.json for {code}: {e}")

    try:
        if os.path.exists(FAILED_QUEUE_PATH):
            with open(FAILED_QUEUE_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            filtered = [line for line in lines if line.strip().upper() != code]
            if len(filtered) != len(lines):
                with open(FAILED_QUEUE_PATH, "w", encoding="utf-8") as f:
                    f.writelines(filtered)
    except Exception as e:
        log(f"Failed to clear failed_queue.txt for {code}: {e}")

    try:
        if os.path.exists(RETRY_PATH):
            with open(RETRY_PATH, "r", encoding="utf-8") as f:
                retries = json.load(f)
            if isinstance(retries, dict) and code in retries:
                retries.pop(code, None)
                with open(RETRY_PATH, "w", encoding="utf-8") as f:
                    json.dump(retries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Failed to clear retry count for {code}: {e}")


def load_failure_codes():
    codes = set()
    try:
        if os.path.exists(FAILED_QUEUE_JSON_PATH):
            with open(FAILED_QUEUE_JSON_PATH, "r", encoding="utf-8") as f:
                records = json.load(f)
            if isinstance(records, list):
                for item in records:
                    code = str(item.get("code", "")).upper().strip()
                    if code:
                        codes.add(code)
    except Exception as e:
        log(f"Failed to read failed_queue.json: {e}")

    try:
        if os.path.exists(FAILED_QUEUE_PATH):
            with open(FAILED_QUEUE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    code = line.strip().upper()
                    if code:
                        codes.add(code)
    except Exception as e:
        log(f"Failed to read failed_queue.txt: {e}")

    return codes

def get_lock():
    try:
        with open(LOCK_PATH, "r") as f:
            return f.read().strip() == "1"
    except:
        return False

def read_current_download():
    if not os.path.exists(CURRENT_PATH):
        return None
    try:
        with open(CURRENT_PATH, "r") as f:
            return f.read().strip()
    except:
        return None

def write_current_download(code):
    with open(CURRENT_PATH, "w") as f:
        f.write(code)

def clear_current_download():
    try:
        os.remove(CURRENT_PATH)
    except:
        pass

def get_code_dir(code):
    return os.path.join(SAVE_PATH, code.upper())

def find_ts_path(code):
    dir_path = get_code_dir(code)
    if not os.path.isdir(dir_path):
        return None
    for f in sorted(os.listdir(dir_path), reverse=True):
        path = os.path.join(dir_path, f)
        if f.endswith('.ts') and os.path.getsize(path) > 1024:
            return path
    return None

def find_mp4_path(code):
    """找到已下载完成的 .mp4（>10MB 且 60 秒内未修改，确保转换完成）"""
    dir_path = get_code_dir(code)
    if not os.path.isdir(dir_path):
        return None
    now = time.time()
    for f in os.listdir(dir_path):
        if f.endswith('.mp4'):
            path = os.path.join(dir_path, f)
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
            # 必须大于 10MB 且 60 秒未修改（确保 ffmpeg 转换完成）
            if size > 10 * 1024 * 1024 and (now - mtime) > 60:
                return path
    return None

def get_dir_size(path):
    try:
        r = subprocess.run(["du", "-sb", path], capture_output=True, text=True, timeout=5)
        return int(r.stdout.split()[0])
    except:
        return 0

def get_file_size(path):
    try:
        return os.path.getsize(path)
    except:
        return 0

def parse_duration_minutes(text):
    if not text:
        return None
    m = re.search(r'(\d+)\s*分鐘', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*min', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+):(\d+)', text)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    return None

def get_duration_from_weekly(code):
    if not os.path.exists(WEEKLY_JSON):
        return None
    try:
        with open(WEEKLY_JSON, "r") as f:
            items = json.load(f)
        for item in items:
            if item.get("id", "").upper() == code.upper():
                dur = item.get("duration", "")
                if dur:
                    mins = parse_duration_minutes(dur)
                    if mins:
                        return mins * 60
                return None
    except:
        pass
    return None

def get_ts_duration_seconds(ts_path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", ts_path],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and r.stdout.strip():
            val = float(r.stdout.strip())
            if val > 0:
                return val
    except:
        pass
    return None

def update_weekly_json_downloaded(code):
    """Update weekly.json: set downloaded=true for this code"""
    if not os.path.exists(WEEKLY_JSON):
        return False
    try:
        with open(WEEKLY_JSON, "r") as f:
            items = json.load(f)
        changed = False
        for item in items:
            if item.get("id", "").upper() == code.upper():
                item["downloaded"] = True
                changed = True
                break
        if changed:
            with open(WEEKLY_JSON, "w") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            log(f"Updated weekly.json: {code} downloaded=true")
            return True
    except Exception as e:
        log(f"Failed to update weekly.json: {e}")
    return False

def write_to_missav_db(code):
    """Write to AV/GARDEN SQLite MissAV table so it shows on homepage"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        
        # Check if already exists
        cur = conn.execute("SELECT bvid FROM MissAV WHERE bvid = ?", (code,))
        if cur.fetchone():
            log(f"{code} already in MissAV table")
            conn.close()
            return True
        
        # Get metadata from weekly.json
        title = code
        title_jp = ""
        actresses = "[]"
        genres = "[]"
        release_date = ""
        duration = ""
        
        if os.path.exists(WEEKLY_JSON):
            with open(WEEKLY_JSON, "r") as f:
                items = json.load(f)
            for item in items:
                if item.get("id", "").upper() == code.upper():
                    title = item.get("title", code)
                    title_jp = item.get("titleJp", "")
                    actresses = json.dumps(item.get("actresses", []), ensure_ascii=False)
                    genres = json.dumps(item.get("genres", []), ensure_ascii=False)
                    release_date = item.get("releaseDate", "")
                    duration = item.get("duration", "")
                    break

        # 屏蔽演员检查
        if BLOCKED_ACTRESSES:
            act_list = json.loads(actresses) if isinstance(actresses, str) else actresses
            if any(a in BLOCKED_ACTRESSES for a in act_list):
                log(f"Blocked: {code} (actress in blocklist)")
                conn.close()
                return False

        # Insert into MissAV table
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT OR REPLACE INTO MissAV 
            (bvid, title, title_jp, actresses, genres, release_date, duration, source, found_date, add_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, title, title_jp, actresses, genres, release_date, duration, "weekly_queue", now, now))
        conn.commit()
        conn.close()
        log(f"Wrote {code} to MissAV DB → homepage visible!")
        return True
    except Exception as e:
        log(f"Failed to write to MissAV DB: {e}")
        return False

def get_download_info(code):
    """Returns {size, speed, progress_pct}"""
    # qB 优先取实时速度
    save_dir = get_code_dir(code)
    qb_progress = get_qb_progress(save_dir)
    if qb_progress:
        return qb_progress

    mp4_path = find_mp4_path(code)
    if mp4_path:
        total = get_file_size(mp4_path)
        return {"size": total, "speed": 0, "progress_pct": 100}

    ts_path = find_ts_path(code)
    if ts_path:
        current = get_file_size(ts_path)
        current_sec = get_ts_duration_seconds(ts_path)
    else:
        # 没有 .ts 文件，尝试从 qBittorrent API 获取进度
        save_dir = get_code_dir(code)
        qb_progress = get_qb_progress(save_dir)
        if qb_progress:
            return qb_progress
        if os.path.isdir(save_dir):
            current = get_dir_size(save_dir)
            current_sec = None
        else:
            current = 0
            current_sec = None

    now = time.time()
    speed = 0
    if code in _speed_cache:
        prev_bytes, prev_time = _speed_cache[code]
        elapsed = now - prev_time
        if elapsed > 0 and current >= prev_bytes:
            speed = (current - prev_bytes) / elapsed
    _speed_cache[code] = (current, now)

    progress_pct = 0
    if current_sec and current_sec > 0:
        total_sec = get_duration_from_weekly(code)
        if total_sec and total_sec > 0:
            progress_pct = min(99, int(current_sec / total_sec * 100))
        else:
            est_total = 1.5 * 1024**3
            progress_pct = min(99, int(current / est_total * 100))
    elif current > 0:
        est_total = 1.5 * 1024**3
        progress_pct = min(99, int(current / est_total * 100))

    return {"size": current, "speed": speed, "progress_pct": progress_pct}

def read_queue_file():
    if not os.path.exists(QUEUE_PATH):
        return []
    try:
        with open(QUEUE_PATH, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []


class QueueHandler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        path = self.path.rstrip("/")
        if path != "/api/queue":
            self._json({"error": "not found"}, 404)
            return

        state = load_state()
        is_locked = get_lock()
        queue_codes = read_queue_file()
        current_code = read_current_download()
        failed_codes = load_failure_codes()
        
        result = {}
        
        # Items in queue.txt → queued（先用 qB 数据覆盖）
        for c in queue_codes:
            result[c] = {"code": c, "status": "queued", "size": 0, "speed": 0, "progress_pct": 0}
            qb_info = get_qb_progress(get_code_dir(c))
            if qb_info:
                result[c] = {"code": c, "status": "downloading", **qb_info}
        
        # Current download
        if is_locked and current_code:
            mp4 = find_mp4_path(current_code)
            if mp4:
                # Already done but current_download.txt not cleaned
                total = get_file_size(mp4)
                result[current_code] = {"code": current_code, "status": "done", "size": total, "speed": 0, "progress_pct": 100}
                if current_code.upper() in failed_codes:
                    clear_failure_record(current_code)
                    failed_codes.discard(current_code.upper())
                clear_current_download()
                log(f"Cleaned stale current_download {current_code} (already done)")
            else:
                info = get_download_info(current_code)
                result[current_code] = {"code": current_code, "status": "downloading", **info}
        elif is_locked and not current_code:
            # Scan state for downloading items
            for item in state:
                c = item["code"]
                if c not in queue_codes:
                    mp4 = find_mp4_path(c)
                    if mp4:
                        continue
                    has_ts = find_ts_path(c) is not None
                    if has_ts or get_dir_size(get_code_dir(c)) > 0:
                        info = get_download_info(c)
                        result[c] = {"code": c, "status": "downloading", **info}
                        write_current_download(c)
                        log(f"Discovered download from state: {c}")
                        break
            
            # If still no current download, scan disk for .ts files
            if not current_code and not any(r.get("status") == "downloading" for r in result.values()):
                if os.path.isdir(SAVE_PATH):
                    for d in sorted(os.listdir(SAVE_PATH), reverse=True):
                        dir_path = os.path.join(SAVE_PATH, d)
                        if not os.path.isdir(dir_path) or d.startswith("__"):
                            continue
                        has_ts = find_ts_path(d) is not None
                        if has_ts and not find_mp4_path(d):
                            # This directory has a .ts file but no .mp4 = active download
                            info = get_download_info(d)
                            if info["size"] > 1024 * 1024:  # > 1MB = actively downloading
                                result[d] = {"code": d, "status": "downloading", **info}
                                write_current_download(d)
                                # Also add to state so it persists
                                if d not in [s["code"] for s in state]:
                                    state.append({"code": d, "status": "downloading", "added_at": time.time()})
                                    save_state(state)
                                log(f"Discovered download from disk: {d}")
                                break

        # Scan qBittorrent for active downloads not in queue/state
        qb_torrents = qb_api("/api/v2/torrents/info?category=AV_GARDEN")
        if qb_torrents:
            for t in qb_torrents:
                if t.get("state") not in ("downloading", "stalledDL", "metaDL", "forcedDL", "queuedUP", "uploading", "stalledUP", "pausedUP"):
                    continue
                name = t.get("name", "")
                if not name:
                    continue
                # 用 clean_avid 标准化车号 (abf-348ch → ABF-348)
                code = clean_avid(name)
                sp = t.get("save_path", "").rstrip("/")
                if sp and sp != "/data":
                    sp_code = clean_avid(os.path.basename(sp))
                    if len(sp_code) > len(code):
                        code = sp_code

                # 检查 result 中是否已有相同车号（可能是 CH 后缀等变体）
                already = False
                for k in list(result.keys()):
                    if clean_avid(k) == code:
                        already = True
                        break
                if already:
                    continue

                size = t.get("completed", 0)
                progress_pct = int(t.get("progress", 0) * 100)
                torrent_state = t.get("state", "")
                status = "done" if torrent_state in ("queuedUP", "uploading", "stalledUP", "pausedUP") else "downloading"
                if status == "done" and not is_recent_timestamp(t.get("completion_on") or t.get("seen_complete") or t.get("added_on")):
                    continue
                result[code] = {
                    "code": code,
                    "status": status,
                    "size": size,
                    "speed": t.get("dlspeed", 0),
                    "progress_pct": min(99, progress_pct) if progress_pct < 100 else 99,
                }
                log(f"Discovered from qBittorrent: {name} -> {code} ({progress_pct}%)")

        # Items from state (including done)
        for item in state:
            c = item["code"]
            if c in result:
                continue  # Already in result from queue.txt or current download

            mp4 = find_mp4_path(c)
            if mp4:
                total = get_file_size(mp4)
                result[c] = {"code": c, "status": "done", "size": total, "speed": 0, "progress_pct": 100}
                if c.upper() in failed_codes:
                    clear_failure_record(c)
                    failed_codes.discard(c.upper())
            elif item.get("status") == "downloading" and not is_locked:
                # Stale download: no mp4, no active lock → assume failed/cleaned
                has_ts = find_ts_path(c) is not None
                dir_size = get_dir_size(get_code_dir(c)) if os.path.isdir(get_code_dir(c)) else 0
                if not has_ts and dir_size == 0:
                    log(f"Removing stale download state: {c} (no files, no lock)")
                    state = [s for s in state if s["code"] != c]
                    save_state(state)
                    continue
                else:
                    info = get_download_info(c)
                    result[c] = {"code": c, "status": item.get("status", "queued"), **info}
            elif item.get("status") == "queued" and c not in queue_codes:
                # queue.txt/qB/current are the live sources for queued work.
                # A queued state with only scraped sidecar files is an orphan.
                if find_ts_path(c) is None:
                    log(f"Removing stale queued state: {c} (not in queue/qB/current)")
                    state = [s for s in state if s["code"] != c]
                    save_state(state)
                    continue
                info = get_download_info(c)
                result[c] = {"code": c, "status": "queued", **info}
            else:
                info = get_download_info(c)
                result[c] = {"code": c, "status": item.get("status", "queued"), **info}
        
        # Check for newly completed items → trigger post-download actions
        for c in list(result.keys()):
            if result[c]["status"] == "done":
                # Update weekly.json + MissAV DB (only once)
                state_item = next((s for s in state if s["code"] == c), None)
                if state_item and not state_item.get("_post_done"):
                    log(f"Post-download actions for {c}")
                    update_weekly_json_downloaded(c)
                    write_to_missav_db(c)
                    if c.upper() in failed_codes:
                        clear_failure_record(c)
                        failed_codes.discard(c.upper())
                    # Save to permanent history
                    append_history(c, result[c].get("size", 0))
                    state_item["_post_done"] = True
                    save_state(state)
        
        # Merge history into result (persistent done items)
        history = load_history()
        log(f"History: {len(history)} items: {[h['code'] for h in history]}")
        for h in history:
            if h["code"] not in result:
                result[h["code"]] = {
                    "code": h["code"],
                    "status": "done",
                    "size": h.get("size", 0),
                    "speed": 0,
                    "progress_pct": 100,
                }
        
        # Sort: downloading, queued, done
        order = {"downloading": 0, "queued": 1, "done": 2}
        sorted_result = sorted(result.values(), key=lambda x: order.get(x["status"], 9))
        
        self._json(sorted_result)

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/api/weekly-scrape":
            if is_weekly_scrape_running():
                self._json({"ok": False, "running": True, "message": "周推荐刮削正在运行"}, 409)
                return
            if start_weekly_scrape():
                log("Manual weekly scrape started")
                self._json({"ok": True, "running": True, "message": "周推荐刮削已开始，请稍后刷新每日推荐"})
                return
            self._json({"ok": False, "message": "周推荐刮削启动失败"}, 500)
            return

        if path != "/api/queue":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else "{}"
        try:
            data = json.loads(body)
        except:
            data = {}
        code = data.get("code", "").strip().upper()
        if not code:
            self._json({"error": "code required"}, 400)
            return
        clear_failure_record(code)

        # 检查 qBittorrent 是否已在下载此车号
        qb_torrents = qb_api("/api/v2/torrents/info?category=AV_GARDEN")
        if qb_torrents:
            cleaned = clean_avid(code)
            for t in qb_torrents:
                t_code = clean_avid(t.get("name", ""))
                if t_code == cleaned:
                    self._json({"status": "already in qBittorrent", "code": code})
                    return

        existing = set()
        if os.path.exists(QUEUE_PATH):
            with open(QUEUE_PATH, "r") as f:
                for line in f:
                    existing.add(line.strip().upper())
        if code not in existing:
            with open(QUEUE_PATH, "a") as f:
                f.write(code + "\n")

        state = load_state()
        if code not in [s["code"] for s in state]:
            state.append({"code": code, "status": "queued", "added_at": time.time()})
            save_state(state)
            self._json({"status": "added", "code": code})
        else:
            self._json({"status": "already in queue", "code": code})

    def do_DELETE(self):
        path = self.path.rstrip("/")
        if not path.startswith("/api/queue/"):
            self._json({"error": "not found"}, 404)
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        code = path.replace("/api/queue/", "").strip().upper()
        if not code:
            self._json({"error": "code required"}, 400)
            return
        delete_files = "delete_files=1" in (parsed.query or "")
        
        state = [s for s in load_state() if s["code"] != code]
        save_state(state)
        
        if os.path.exists(QUEUE_PATH):
            with open(QUEUE_PATH, "r") as f:
                lines = [l for l in f if l.strip().upper() != code]
            with open(QUEUE_PATH, "w") as f:
                f.writelines(lines)
        
        if read_current_download() == code:
            clear_current_download()
        
        # 默认只移出队列/状态；显式 delete_files=1 才删除磁盘文件。
        if delete_files and os.path.exists(get_code_dir(code)):
            try:
                # 忽略系统目录
                code_dir = get_code_dir(code)
                dirname = os.path.basename(code_dir.rstrip("/"))
                if dirname in ("__weekly__", "thumb"):
                    log(f"Cannot delete system directory: {dirname}")
                else:
                    shutil.rmtree(code_dir)
                    log(f"Deleted files: {code_dir}")
            except Exception as e:
                log(f"Delete failed: {e}")
        
        self._json({"status": "removed", "code": code, "files_deleted": delete_files})

    def log_message(self, format, *args):
        pass


def main():
    port = int(os.environ.get("QUEUE_PORT", 31473))
    log(f"v7 starting: port={port}, lock={get_lock()}")
    
    # 启动自检：恢复残留锁、扫描未完成下载
    startup_recovery()
    
    server = HTTPServer(("0.0.0.0", port), QueueHandler)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

def startup_recovery():
    """
    启动自检：释放残留锁、恢复下载状态、重建 state
    在容器重启后自动执行，确保下载任务不丢失
    """
    log("=== Startup Recovery ===")
    
    # 1. 检查当前下载记录
    current = read_current_download()
    is_locked = get_lock()
    
    log(f"  current_download={current}, lock={is_locked}")
    
    # 2. 如果 lock=1 但没 worker（已重启），释放锁
    if is_locked:
        # 检查是否有真正的 downloader 进程在跑
        has_m3u8 = False
        try:
            r = subprocess.run(["pgrep", "-f", "m3u8-Downloader"], capture_output=True, timeout=3)
            has_m3u8 = r.returncode == 0
        except:
            pass
        
        if not has_m3u8:
            log("  No active downloader found, releasing stale lock")
            with open(LOCK_PATH, "w") as f:
                f.write("0")
            is_locked = False
            log("  Lock released")
    
    # 3. 扫描磁盘，找 .ts 文件（未完成下载）
    state = load_state()
    state_codes = {s["code"] for s in state}
    recovered = []
    
    if os.path.isdir(SAVE_PATH):
        for d in sorted(os.listdir(SAVE_PATH), reverse=True):
            dir_path = os.path.join(SAVE_PATH, d)
            if not os.path.isdir(dir_path) or d.startswith("__"):
                continue
            has_ts = False
            for f in os.listdir(dir_path):
                if f.endswith('.ts') and os.path.getsize(os.path.join(dir_path, f)) > 1024:
                    has_ts = True
                    break
            has_mp4 = False
            for f in os.listdir(dir_path):
                if f.endswith('.mp4'):
                    has_mp4 = True
                    break
            
            if has_ts and not has_mp4 and d not in state_codes:
                # Unfinished download - add to queue for re-download
                if not current or current != d:
                    recovered.append(d)
                    log(f"  Found unfinished: {d}")
    
    if recovered:
        # Add to queue.txt
        existing = set()
        if os.path.exists(QUEUE_PATH):
            with open(QUEUE_PATH, "r") as f:
                for line in f:
                    existing.add(line.strip().upper())
        with open(QUEUE_PATH, "a") as f:
            for code in recovered:
                if code.upper() not in existing:
                    f.write(code.upper() + "\n")
                    log(f"  Re-queued: {code}")
        
        # Add to state
        for code in recovered:
            if code not in [s["code"] for s in state]:
                state.append({"code": code.upper(), "status": "queued", "added_at": time.time()})
        save_state(state)
    
    # 4. 清理 current_download.txt（等 worker 重新拾取）
    if current and not is_locked:
        clear_current_download()
        log("  Cleared stale current_download")
    
    log(f"=== Recovery complete: {len(recovered)} re-queued ===")

if __name__ == "__main__":
    main()
