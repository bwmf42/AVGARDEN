#!/usr/bin/env python3
"""Add exact 98堂 Chinese magnets to unwatched Weekly entries only.

This job never creates download tasks and never touches media files. Its only
write target is ``weekly.json`` and only the Chinese magnet status fields.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from download_source import _mark_plwt_rate_limited, _plwt_search_slot
from queue_store import read_json as read_locked_json, read_queue
from src.log_writer import write as log_write
from src.scrape_pipeline import PHASE_UNWATCHED_CN, set_phase, set_progress, write_status
from video_id import normalize_video_id
from weekly_store import atomic_write_json, weekly_update_lock
from weekly_watched_store import load_records

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_JSON = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
WATCHED_JSON = os.environ.get("WEEKLY_WATCHED_FILE", "/db/weekly_watched.json")
QUEUE_PATH = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
STATE_PATH = os.environ.get("STATE_PATH", "/db/queue_state.json")
CURRENT_PATH = os.environ.get("CURRENT_PATH", "/db/current_download.txt")
PROXY = os.environ.get("PROXY", "") or None
FORCE_ALL = os.environ.get("UNWATCHED_CN_FORCE_ALL", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

CN_MARKERS = (
    re.compile(r"中文字幕", re.I),
    re.compile(r"中文", re.I),
    re.compile(r"CHINESE", re.I),
    re.compile(r"(?<![A-Z0-9])-C(?![A-Z0-9])", re.I),
    re.compile(r"(?<![A-Z0-9])-CH(?![A-Z0-9])", re.I),
)


def log(msg: str) -> None:
    print(f"[UnwatchedCN] {msg}", flush=True)


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        if not isinstance(exc, FileNotFoundError):
            log(f"load {path}: {exc}")
        return default


def load_watched_ids() -> Set[str]:
    return set(load_records(WATCHED_JSON))


def load_active_queue_ids() -> Set[str]:
    """Read the queue registration sources without creating or changing tasks."""
    result: Set[str] = set()
    try:
        from queue_api import codes_in_qb, qb_api

        torrents = qb_api("/api/v2/torrents/info")
        if isinstance(torrents, list):
            result.update(codes_in_qb(torrents))
    except Exception as exc:
        log(f"qB status unavailable; use registration files: {exc}")
    for raw in read_queue(QUEUE_PATH):
        code = normalize_video_id(raw)
        if code:
            result.add(code)
    state = read_locked_json(STATE_PATH, [])
    if isinstance(state, list):
        for item in state:
            if not isinstance(item, dict) or str(item.get("status") or "").lower() == "done":
                continue
            code = normalize_video_id(item.get("code") or item.get("id") or "")
            if code:
                result.add(code)
    try:
        with open(CURRENT_PATH, encoding="utf-8") as handle:
            code = normalize_video_id(handle.read().strip())
            if code:
                result.add(code)
    except OSError:
        pass
    return result


def load_downloaded_ids() -> Set[str]:
    try:
        from queue_api import get_main_video_index

        return {
            code
            for raw in get_main_video_index()
            for code in [normalize_video_id(raw)]
            if code
        }
    except Exception as exc:
        log(f"media index unavailable; use weekly downloaded flags: {exc}")
        return set()


def has_cn_text(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in CN_MARKERS)


def item_already_chinese(item: dict) -> bool:
    if item.get("hasChinese") or item.get("isChinese"):
        return True
    if has_cn_text(str(item.get("title") or "")):
        return True
    source = str(item.get("source") or "").lower()
    chinese_source = str(item.get("chineseSource") or "").lower()
    return (
        "chinese" in source
        or "forum-103" in source
        or chinese_source == "plwt_chinese"
    )


def list_unwatched_needing_cn(
    weekly: list,
    watched: Set[str],
    active_queue: Optional[Set[str]] = None,
    downloaded: Optional[Set[str]] = None,
    block_rules: Optional[dict] = None,
) -> List[dict]:
    from src.weekly import blocking

    active_queue = active_queue or set()
    downloaded = downloaded or set()
    result = []
    for item in weekly:
        if not isinstance(item, dict):
            continue
        code = normalize_video_id(item.get("id") or item.get("code") or "")
        if (
            not code
            or code in watched
            or code in active_queue
            or code in downloaded
            or item.get("downloaded")
        ):
            continue
        if block_rules is not None and blocking.match_reason(item, block_rules):
            continue
        if not FORCE_ALL and item_already_chinese(item):
            continue
        result.append(item)
    return result


def apply_chinese_magnet(code: str, magnet: str, source: str) -> bool:
    """Update only the five approved Chinese magnet fields in weekly.json."""
    code = normalize_video_id(code)
    magnet = str(magnet or "").strip()
    if not code or not magnet.lower().startswith("magnet:") or source != "plwt_chinese":
        return False

    # Search slots can wait for minutes. Recheck visibility immediately before
    # writing so a newly watched, queued, blocked, or downloaded item is skipped.
    if (
        code in load_watched_ids()
        or code in load_active_queue_ids()
        or code in load_downloaded_ids()
    ):
        return False

    with weekly_update_lock(WEEKLY_JSON):
        items = _load_json(WEEKLY_JSON, [])
        if not isinstance(items, list):
            raise RuntimeError("weekly.json 格式无效")
        target = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and normalize_video_id(item.get("id") or item.get("code") or "") == code
            ),
            None,
        )
        if target is None:
            return False
        from src.weekly import blocking

        if blocking.match_reason(target, blocking.load_rules()):
            return False
        changed = (
            str(target.get("magnet") or "").strip() != magnet
            or target.get("hasChinese") is not True
            or target.get("isChinese") is not True
            or target.get("chineseSource") != source
            or not target.get("chineseUpdatedAt")
        )
        if not changed:
            return False
        target["magnet"] = magnet
        target["hasChinese"] = True
        target["isChinese"] = True
        target["chineseSource"] = source
        target["chineseUpdatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
        atomic_write_json(WEEKLY_JSON, items)
        return True


def search_chinese_magnet(code: str, client) -> Tuple[Optional[str], str]:
    """Return one exact forum-103 magnet and its normalized source tag."""
    from src.weekly import chinese_forum

    with _plwt_search_slot():
        hit = chinese_forum.search_exact_chinese(code, client=client)
    if not hit:
        return None, ""
    if hit.get("_rate_limited") and not hit.get("magnet"):
        _mark_plwt_rate_limited()
        return None, "rate_limited"
    if normalize_video_id(hit.get("id") or "") != normalize_video_id(code):
        return None, ""
    magnet = str(hit.get("magnet") or "").strip()
    if not magnet.lower().startswith("magnet:"):
        return None, ""
    return magnet, "plwt_chinese"


def run_refill() -> Dict[str, Any]:
    from src.weekly import blocking, chinese_forum

    stats = {
        "candidates": 0,
        "checked": 0,
        "updated": 0,
        "already": 0,
        "not_found": 0,
        "rate_limited": 0,
        "errors": 0,
    }

    weekly = _load_json(WEEKLY_JSON, None)
    if not isinstance(weekly, list):
        raise RuntimeError("weekly.json 不存在或格式无效")

    candidates = list_unwatched_needing_cn(
        weekly,
        load_watched_ids(),
        load_active_queue_ids(),
        load_downloaded_ids(),
        blocking.load_rules(),
    )
    stats["candidates"] = len(candidates)
    log(f"unwatched needing CN check: {len(candidates)} (force_all={FORCE_ALL})")
    set_phase(PHASE_UNWATCHED_CN, current=0, total=len(candidates))

    if not candidates:
        write_status({"last_summary": "未看作品无需补中文磁链", "stats": stats})
        return stats

    chinese_forum.set_proxy(PROXY)
    client = chinese_forum.ForumClient()
    if not client.ensure_safe():
        raise RuntimeError("98堂安全验证失败")

    for index, item in enumerate(candidates, start=1):
        code = normalize_video_id(item.get("id") or item.get("code") or "")
        set_progress(index, len(candidates), code)
        try:
            magnet, source = search_chinese_magnet(code, client)
            stats["checked"] += 1
            if source == "rate_limited":
                stats["rate_limited"] += 1
                log(f"{code}: rate limited; next shared slot will wait 60s")
                continue
            if not magnet:
                stats["not_found"] += 1
                log(f"{code}: no exact Chinese magnet")
                continue
            if apply_chinese_magnet(code, magnet, source):
                stats["updated"] += 1
                log(f"{code}: Chinese magnet updated")
                log_write("UnwatchedCN", f"{code} 未看已补中文磁链")
            else:
                stats["already"] += 1
        except Exception as exc:
            stats["errors"] += 1
            log(f"{code}: error {exc}")

    summary = (
        f"未看中文补链：候选 {stats['candidates']}，检查 {stats['checked']}，"
        f"更新 {stats['updated']}，未找到 {stats['not_found']}，"
        f"限速 {stats['rate_limited']}，异常 {stats['errors']}"
    )
    log(summary)
    log_write("UnwatchedCN", summary)
    write_status({"last_summary": summary, "stats": stats})
    return stats


def main() -> int:
    log("=== start unwatched Chinese refill ===")
    try:
        run_refill()
        return 0
    except Exception as exc:
        log(f"fatal: {exc}")
        write_status({"last_error": str(exc)[:300]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
