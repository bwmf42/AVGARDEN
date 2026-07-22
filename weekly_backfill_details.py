#!/usr/bin/env python3
"""Backfill details for visible, unwatched weekly items."""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.log_writer import write as log_write
from src.weekly import artwork, enrich, javbus, sukebei

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_DIR = os.path.join(SAVE_PATH, "__weekly__")
WEEKLY_JSON = os.path.join(WEEKLY_DIR, "weekly.json")
SERVER_URL = os.environ.get("WEEKLY_BACKFILL_SERVER_URL", "http://127.0.0.1:31471")
PROXY = os.environ.get("PROXY", "") or None
MIN_DELAY = float(os.environ.get("WEEKLY_BACKFILL_MIN_DELAY", "1"))
MAX_DELAY = float(os.environ.get("WEEKLY_BACKFILL_MAX_DELAY", "10"))
LIMIT = int(os.environ.get("WEEKLY_BACKFILL_LIMIT", "0"))
DS_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def log(message):
    print(f"[WeeklyBackfill] {message}", flush=True)
    log_write("WeeklyBackfill", message)


def load_json_url(path, default):
    try:
        with urllib.request.urlopen(f"{SERVER_URL}{path}", timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log(f"Load {path} failed: {e}")
        return default


def load_weekly():
    with open(WEEKLY_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_weekly(items):
    tmp = WEEKLY_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WEEKLY_JSON)


def normalize_id(raw):
    return str(raw or "").strip().upper()


def queue_codes():
    queue = load_json_url("/api/queue/", [])
    if not isinstance(queue, list):
        return set()
    return {normalize_id(item.get("code")) for item in queue if normalize_id(item.get("code"))}


def visible_unwatched_ids():
    weekly = load_json_url("/api/weekly", [])
    watched = load_json_url("/api/weekly-watched", [])
    watched_set = {normalize_id(item) for item in watched if normalize_id(item)}
    queue_set = queue_codes()
    result = []
    seen = set()
    for item in weekly if isinstance(weekly, list) else []:
        avid = normalize_id(item.get("id"))
        if not avid or avid in seen:
            continue
        if item.get("downloaded") or avid in watched_set or avid in queue_set:
            continue
        seen.add(avid)
        result.append(avid)
    return result


def needs_backfill(item):
    cover = str(item.get("cover") or "")
    return (
        not item.get("magnet")
        or not item.get("duration")
        or not item.get("genres")
        or not item.get("fanarts")
        or has_remote_fanarts(item)
        or not item.get("titleZh")
        or not cover
        or cover.startswith("http")
    )


def has_remote_fanarts(item):
    return bool(remote_fanart_source(item))


def remote_fanart_source(item):
    for key in ("remoteFanarts", "fanarts"):
        fanarts = item.get(key)
        if isinstance(fanarts, list) and any(str(url or "").startswith("http") for url in fanarts):
            return fanarts
    return []


def missing_fields(item):
    missing = []
    cover = str(item.get("cover") or "")
    if not item.get("duration"):
        missing.append("duration")
    if not item.get("genres"):
        missing.append("genres")
    if not item.get("fanarts"):
        missing.append("fanarts")
    elif has_remote_fanarts(item):
        missing.append("fanarts_local")
    if not item.get("magnet"):
        missing.append("magnet")
    if not item.get("titleZh"):
        missing.append("titleZh")
    if not cover or cover.startswith("http"):
        missing.append("cover")
    return missing


def translate_title(item):
    if item.get("titleZh") or not item.get("title") or not DS_API_KEY:
        return False
    title = f"{item.get('id')}: {item.get('title')}"
    payload = json.dumps({
        "model": DS_MODEL,
        "messages": [
            {"role": "system", "content": "你是日语翻译助手。将以下日文成人影片标题翻译为简洁的中文，只输出翻译结果，不要任何解释。"},
            {"role": "user", "content": title},
        ],
        "max_tokens": 256,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {DS_API_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        zh = result["choices"][0]["message"]["content"].strip()
        if zh:
            item["titleZh"] = zh
            return True
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as e:
        log(f"{item.get('id')} translate failed: {e}")
    return False


def backfill_item(item):
    avid = normalize_id(item.get("id"))
    changed = False
    before = {
        "actresses": list(item.get("actresses") or []),
        "genres": list(item.get("genres") or []),
        "duration": item.get("duration") or "",
        "releaseDate": item.get("releaseDate") or "",
        "cover": item.get("cover") or "",
        "fanarts": list(item.get("fanarts") or []) if isinstance(item.get("fanarts"), list) else [],
        "title": item.get("title") or "",
    }

    if enrich.needs_enrich(item) or has_remote_fanarts(item) or not str(item.get("cover") or "").startswith("/file/"):
        enrich.enrich_item(
            item,
            save_dir=WEEKLY_DIR,
            download_images=True,
            force_images=javbus.cover_needs_refresh(avid, WEEKLY_DIR),
        )
        for k, v in before.items():
            if item.get(k) != v:
                changed = True

    if not item.get("magnet"):
        magnet = sukebei.search(avid, "")
        if magnet:
            item["magnet"] = magnet
            changed = True

    if translate_title(item):
        changed = True

    for key in ("actresses", "genres", "fanarts"):
        if not isinstance(item.get(key), list):
            item[key] = []
            changed = True
    for key in ("titleZh", "titleJp", "poster", "duration", "size", "magnet"):
        item.setdefault(key, "")
    item.setdefault("hasChinese", False)
    item.setdefault("downloaded", False)
    return changed


def main():
    javbus.set_proxy(PROXY)
    sukebei.set_proxy(PROXY)
    artwork.set_proxy(PROXY)
    enrich.set_proxy(PROXY)
    items = load_weekly()
    by_id = {normalize_id(item.get("id")): item for item in items if normalize_id(item.get("id"))}
    targets = [avid for avid in visible_unwatched_ids() if avid in by_id and needs_backfill(by_id[avid])]
    if LIMIT > 0:
        targets = targets[:LIMIT]

    log(f"Start visible-unwatched backfill: {len(targets)} items, delay {MIN_DELAY:g}-{MAX_DELAY:g}s")
    updated = 0
    for index, avid in enumerate(targets, 1):
        item = by_id[avid]
        try:
            changed = backfill_item(item)
            if changed:
                updated += 1
                save_weekly(items)
            missing = missing_fields(item)
            if changed:
                status = "updated"
            elif missing:
                status = "still_missing=" + ",".join(missing)
            else:
                status = "complete"
            log(f"{index}/{len(targets)} {avid} {status}")
        except Exception as e:
            log(f"{index}/{len(targets)} {avid} failed: {e}")
        if index < len(targets):
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    log(f"Done visible-unwatched backfill: updated {updated}/{len(targets)}")


if __name__ == "__main__":
    main()
