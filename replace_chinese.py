#!/usr/bin/env python3
"""扫描已下载 mp4，搜索中文字幕版磁链，有则替换"""
import json, os, re, time, random, sys, urllib.parse
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.weekly import sukebei
from src.log_writer import write as log_write, cleanup as log_cleanup

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
PROXY = os.environ.get("PROXY", "") or None
MAX_AGE = int(os.environ.get("REPLACE_MAX_AGE", "30"))
QB_URL = os.environ.get("QBITTORRENT_URL", "http://127.0.0.1:8080")
QB_USER = os.environ.get("QBITTORRENT_USERNAME", "admin")
QB_PASS = os.environ.get("QBITTORRENT_PASSWORD", "adminadmin")
PENDING_FILE = os.environ.get("CHINESE_PENDING_FILE", "/db/chinese_pending.json")

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
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2)

def update_weekly_magnet(avid, magnet):
    """更新 weekly.json 里该番号的 magnet 字段"""
    weekly_path = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
    try:
        if not os.path.exists(weekly_path):
            return
        with open(weekly_path) as f:
            items = json.load(f)
        for item in items:
            if item.get("id", "").upper() == avid.upper():
                item["magnet"] = magnet
                break
        with open(weekly_path, "w") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
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


def dir_has_cn_video(dpath, dirname, mp4_files):
    if has_cn_marker_for_avid(dirname, dirname):
        return True
    for filename in mp4_files:
        if has_cn_marker_for_avid(filename, dirname):
            return True
    for filename in os.listdir(dpath):
        if filename.lower().endswith(".nfo"):
            try:
                with open(os.path.join(dpath, filename), encoding="utf-8", errors="ignore") as f:
                    if has_cn_marker_for_avid(f.read(), dirname):
                        return True
            except:
                pass
    return False

def merge_completed_chinese():
    """检查已下载完成的中文字幕版，合并到原文件夹"""
    import urllib.request, http.cookiejar, shutil
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
    for hash_str, avid in list(pending.items()):
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

        # 完成！合并
        save_path = t_info.get("save_path", "")
        content_path = t_info.get("content_path", "")
        full_path = os.path.join(save_path, content_path) if content_path else save_path

        log(f"  Merging {avid}: torrent={t_info.get('name','')} from {full_path}")

        # 先清理原文件夹的旧非中文文件
        cleanup_original(avid)

        target_dir = os.path.join(SAVE_PATH, avid)
        os.makedirs(target_dir, exist_ok=True)

        try:
            # 移动 mp4 文件到原文件夹
            moved_files = []
            if os.path.isdir(full_path):
                for f in os.listdir(full_path):
                    if f.endswith(".mp4") and not f.startswith("._"):
                        src = os.path.join(full_path, f)
                        dst = os.path.join(target_dir, f)
                        shutil.move(src, dst)
                        moved_files.append(f)
                        log(f"  Moved {f} -> {target_dir}")
            elif os.path.isfile(full_path) and full_path.endswith(".mp4"):
                dst = os.path.join(target_dir, os.path.basename(full_path))
                shutil.move(full_path, dst)
                moved_files.append(os.path.basename(full_path))
                log(f"  Moved {os.path.basename(full_path)} -> {target_dir}")

            if moved_files:
                marker_path = os.path.join(target_dir, ".av_garden_chinese")
                with open(marker_path, "w") as f:
                    f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            # 删掉 torrent 和临时文件夹/文件
            try:
                opener.open(urllib.request.Request(
                    f"{QB_URL}/api/v2/torrents/delete",
                    data=f"hashes={hash_str}&deleteFiles=true".encode()
                ), timeout=10)
            except:
                pass
            # 删空文件夹
            if os.path.isdir(full_path):
                try:
                    shutil.rmtree(full_path)
                except:
                    pass
            elif os.path.isfile(full_path):
                try:
                    os.remove(full_path)
                except:
                    pass

            del pending[hash_str]
            save_pending(pending)
            merged += 1
            log_write("ReplaceCN", f"{avid} 中文字幕版已合并")
        except Exception as e:
            log(f"  Merge {avid} error: {e}")

    if merged:
        log(f"  Merged {merged} Chinese torrent(s)")

def cleanup_original(avid):
    """删除原文件夹里非中文字幕的 mp4，保留 NFO/封面等元数据。"""
    import shutil
    dpath = os.path.join(SAVE_PATH, avid)
    if not os.path.isdir(dpath):
        return
    d_up = dpath.upper()
    if d_up.endswith("-C") or d_up.endswith("CH") or "中文字幕" in d_up or "中文" in d_up:
        return
    deleted = []
    for f in os.listdir(dpath):
        fp = os.path.join(dpath, f)
        if os.path.isfile(fp) and f.lower().endswith(".mp4") and not has_cn_marker_for_avid(f, avid):
            try:
                os.remove(fp)
                deleted.append(f)
            except Exception as e:
                log(f"  Delete {f} error: {e}")
    if deleted:
        log(f"  Cleaned {avid}: {', '.join(deleted)}")
    # 如果文件夹空了，删除它
    try:
        remaining = [x for x in os.listdir(dpath) if not x.startswith(".")]
        if not remaining:
            shutil.rmtree(dpath)
            log(f"  Removed empty dir: {avid}")
    except:
        pass

def main():
    log("=== Start ===")
    sukebei.set_proxy(PROXY)

    # 0. 先合并已完成的中文字幕版
    merge_completed_chinese()

    # 1. 扫最近 30 天的 mp4
    cutoff = datetime.now() - timedelta(days=MAX_AGE)
    candidates = []
    existing_cn = 0
    for d in sorted(os.listdir(SAVE_PATH)):
        dpath = os.path.join(SAVE_PATH, d)
        if not os.path.isdir(dpath) or d.startswith("_") or d == "thumb":
            continue
        mp4_files = [f for f in os.listdir(dpath) if f.endswith(".mp4")]
        if not mp4_files:
            continue
        # 跳过已有中文字幕标记的目录、视频或 sidecar 标记。
        if dir_has_cn_video(dpath, d, mp4_files):
            existing_cn += 1
            continue
        mtime = os.path.getmtime(os.path.join(dpath, mp4_files[0]))
        mdt = datetime.fromtimestamp(mtime)
        if mdt > cutoff:
            candidates.append((d, mdt))
            log(f"  Candidate: {d} ({mdt.strftime('%Y-%m-%d')})")

    log(f"Found {len(candidates)} candidates")

    # 2. 逐个搜中文字幕磁链
    added = 0
    existing_qb = 0
    add_failed = 0
    no_magnet = 0
    for avid, mdt in sorted(candidates, key=lambda x: x[1], reverse=True):
        # 跳过 qB 里已有的
        if qb_has_cn_avid(avid):
            existing_qb += 1
            log(f"  Skip {avid}: already in qB")
            continue

        log(f"Searching {avid}...")
        magnet = sukebei.search_chinese(avid)
        if not magnet:
            no_magnet += 1
            log(f"  {avid}: no Chinese magnet")
            continue

        # 3. 加 qB下载 + 更新 weekly.json + 记录 pending
        torrent_hash = qb_add_magnet(magnet)
        if torrent_hash:
            log(f"  {avid}: added Chinese magnet to qB ({torrent_hash[:12]})")
            update_weekly_magnet(avid, magnet)
            pending = load_pending()
            pending[torrent_hash] = avid
            save_pending(pending)
            added += 1
        elif torrent_hash is None:
            add_failed += 1
            log(f"  {avid}: failed to add to qB")
        time.sleep(random.uniform(5, 10))

    log(f"=== Done: {added} qB tasks added ===")

    # 4. 补刮空字段（JavBus 后来填了数据）
    from src.weekly import javbus as jb
    jb.set_proxy(PROXY)
    weekly_path = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
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
        log(f"  No videos need refill")

    try:
        summary = (
            f"扫描{len(candidates)}个候选, 新增{added}部中文字幕任务, "
            f"已存在{existing_cn + existing_qb}部, 未找到{no_magnet}部, "
            f"添加失败{add_failed}部, 补刮{refilled}部空数据"
        )
        log_write("ReplaceCN", summary)
        log_cleanup()
    except:
        pass

if __name__ == "__main__":
    main()
