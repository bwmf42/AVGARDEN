#!/usr/bin/env python3
"""Backfill details for visible, unwatched weekly items."""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.log_writer import write as log_write
from src.weekly import artwork, enrich, javbus, mgs, sukebei
from weekly_store import atomic_write_json, weekly_update_lock

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
    atomic_write_json(WEEKLY_JSON, items)


def normalize_id(raw):
    return str(raw or "").strip().upper()


def _local_file(url, min_bytes):
    value = str(url or "")
    if not value.startswith("/file/"):
        return False
    relative = urllib.parse.unquote(value[len("/file/") :]).lstrip("/")
    path = os.path.normpath(os.path.join(SAVE_PATH, relative))
    root = os.path.normpath(SAVE_PATH) + os.sep
    if not path.startswith(root):
        return False
    try:
        return os.path.isfile(path) and os.path.getsize(path) > min_bytes
    except OSError:
        return False


def has_local_cover(item):
    return _local_file(item.get("cover"), 8000)


def has_local_fanarts(item):
    values = item.get("fanarts") if isinstance(item.get("fanarts"), list) else []
    return any(_local_file(value, 3000) for value in values)


def needs_metadata(item):
    return (
        not item.get("actresses")
        or not item.get("genres")
        or not item.get("duration")
        or not item.get("releaseDate")
    )


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
    return bool(missing_fields(item))


def missing_fields(item):
    missing = []
    if not item.get("actresses"):
        missing.append("actresses")
    if not item.get("duration"):
        missing.append("duration")
    if not item.get("genres"):
        missing.append("genres")
    if not item.get("releaseDate"):
        missing.append("releaseDate")
    if not has_local_fanarts(item):
        missing.append("fanarts")
    if not item.get("magnet"):
        missing.append("magnet")
    if not item.get("titleZh"):
        missing.append("titleZh")
    if not has_local_cover(item):
        missing.append("cover")
    return missing


def normalize_existing_actresses(items):
    changed = 0
    for item in items:
        values = item.get("actresses")
        if not isinstance(values, list) or not values:
            continue
        normalized = mgs.normalize_actresses(values)
        if normalized != values:
            item["actresses"] = normalized
            changed += 1
    return changed


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

    need_meta = needs_metadata(item)
    need_images = not has_local_cover(item) or not has_local_fanarts(item)
    if need_meta or need_images:
        enrich.enrich_item(
            item,
            save_dir=WEEKLY_DIR,
            download_images=need_images,
            force_images=(
                need_images and javbus.cover_needs_refresh(avid, WEEKLY_DIR)
            ),
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


def _main_locked():
    javbus.set_proxy(PROXY)
    sukebei.set_proxy(PROXY)
    artwork.set_proxy(PROXY)
    enrich.set_proxy(PROXY)
    items = load_weekly()
    normalized = normalize_existing_actresses(items)
    if normalized:
        save_weekly(items)
    log(f"Normalized actress labels: {normalized}")

    by_id = {normalize_id(item.get("id")): item for item in items if normalize_id(item.get("id"))}
    targets = [avid for avid in visible_unwatched_ids() if avid in by_id and needs_backfill(by_id[avid])]
    if LIMIT > 0:
        targets = targets[:LIMIT]

    log(f"Start visible-unwatched backfill: {len(targets)} items, delay {MIN_DELAY:g}-{MAX_DELAY:g}s")
    updated = 0
    improved = 0
    completed = 0
    unchanged = 0
    failed = 0
    source_counts = Counter()
    failure_reasons = Counter()
    for index, avid in enumerate(targets, 1):
        item = by_id[avid]
        before_missing = set(missing_fields(item))
        try:
            changed = backfill_item(item)
            if changed:
                updated += 1
                save_weekly(items)
            missing = set(missing_fields(item))
            if len(missing) < len(before_missing):
                improved += 1
            if not missing:
                completed += 1
                status = "complete"
            elif changed:
                status = "updated still_missing=" + ",".join(sorted(missing))
            else:
                unchanged += 1
                status = "still_missing=" + ",".join(sorted(missing))
            if item.get("metaSource"):
                source_counts[item["metaSource"]] += 1
            if missing & {"actresses", "duration", "genres", "releaseDate"}:
                failure_reasons["metadata_not_found"] += 1
            if missing & {"cover", "fanarts"}:
                failure_reasons["artwork_not_found"] += 1
            if "magnet" in missing:
                failure_reasons["magnet_not_found"] += 1
            if "titleZh" in missing:
                failure_reasons["translation_failed"] += 1
            log(f"{index}/{len(targets)} {avid} {status}")
        except Exception as e:
            failed += 1
            failure_reasons["exception"] += 1
            log(f"{index}/{len(targets)} {avid} failed: {e}")
        if index < len(targets):
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    remaining = Counter()
    for avid in targets:
        remaining.update(missing_fields(by_id[avid]))
    log(
        "Done visible-unwatched backfill: "
        f"targets={len(targets)} updated={updated} improved={improved} "
        f"complete={completed} unchanged={unchanged} failed={failed}"
    )
    log(f"Remaining fields: {dict(sorted(remaining.items()))}")
    log(f"Metadata sources: {dict(sorted(source_counts.items()))}")
    log(f"Failure reasons: {dict(sorted(failure_reasons.items()))}")


def main():
    with weekly_update_lock(WEEKLY_JSON):
        _main_locked()


if __name__ == "__main__":
    main()
