"""Shared resolver for the queue, online search, and Worker download path."""
from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager

from queue_store import read_json, update_json
from video_id import normalize_video_id


SOURCE_CACHE_PATH = os.environ.get("DOWNLOAD_SOURCE_CACHE_PATH", "/db/download_source_cache.json")
SOURCE_CACHE_TTL_SECONDS = int(os.environ.get("DOWNLOAD_SOURCE_CACHE_TTL_SECONDS", "86400"))
PLWT_RATE_PATH = os.environ.get("PLWT_SEARCH_RATE_PATH", "/db/plwt_search_rate.json")
PLWT_SEARCH_INTERVAL_SECONDS = float(os.environ.get("PLWT_SEARCH_INTERVAL_SECONDS", "31"))


def _now():
    return time.time()


def _cache_path(path=None):
    return path or SOURCE_CACHE_PATH


def _valid_cached(item, code, now=None):
    if not isinstance(item, dict) or item.get("code") != code:
        return False
    resolved_at = float(item.get("resolved_at") or 0)
    current = _now() if now is None else now
    return resolved_at > 0 and current - resolved_at <= SOURCE_CACHE_TTL_SECONDS


def get_cached_source(raw_code, path=None, now=None):
    code = normalize_video_id(raw_code)
    if not code:
        return None
    cache = read_json(_cache_path(path), {})
    item = cache.get(code) if isinstance(cache, dict) else None
    return dict(item) if _valid_cached(item, code, now=now) else None


def save_cached_source(raw_code, source, path=None, now=None):
    code = normalize_video_id(raw_code)
    if not code:
        return None
    value = dict(source or {})
    value["code"] = code
    value["resolved_at"] = float(_now() if now is None else now)

    def save(cache):
        cache = cache if isinstance(cache, dict) else {}
        cutoff = value["resolved_at"] - SOURCE_CACHE_TTL_SECONDS
        cache = {
            key: item for key, item in cache.items()
            if isinstance(item, dict) and float(item.get("resolved_at") or 0) >= cutoff
        }
        cache[code] = value
        return cache

    update_json(_cache_path(path), {}, save)
    return dict(value)


def delete_cached_source(raw_code, path=None):
    code = normalize_video_id(raw_code)
    if not code:
        return False
    removed = False

    def remove(cache):
        nonlocal removed
        cache = cache if isinstance(cache, dict) else {}
        removed = cache.pop(code, None) is not None
        return cache

    update_json(_cache_path(path), {}, remove)
    return removed


def cleanup_expired_sources(path=None, now=None):
    current = _now() if now is None else now
    cutoff = current - SOURCE_CACHE_TTL_SECONDS
    removed = []

    def cleanup(cache):
        cache = cache if isinstance(cache, dict) else {}
        kept = {}
        for code, item in cache.items():
            if isinstance(item, dict) and float(item.get("resolved_at") or 0) >= cutoff:
                kept[code] = item
            else:
                removed.append(code)
        return kept

    update_json(_cache_path(path), {}, cleanup)
    return removed


@contextmanager
def _mark_plwt_rate_limited(path=None):
    """Mark that search was rate-limited, extending next interval to 60s."""
    path = path or PLWT_RATE_PATH
    update_json(path, {}, lambda s: {**s, "rate_limited": True})


def _plwt_search_slot(path=None):
    path = path or PLWT_RATE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".slot.lock", "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        state = read_json(path, {})
        last_search = float(state.get("last_search") or 0) if isinstance(state, dict) else 0
        rate_limited = bool(state.get("rate_limited")) if isinstance(state, dict) else False
        interval = 60.0 if rate_limited else PLWT_SEARCH_INTERVAL_SECONDS
        delay = interval - (_now() - last_search)
        if delay > 0:
            time.sleep(delay)
        update_json(path, {}, lambda _: {"last_search": _now(), "rate_limited": False})
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def resolve_download_source(raw_code, proxy=None, cache_path=None, force=False):
    """Resolve 98堂中文 -> largest Sukebei Chinese -> earliest original -> stream."""
    code = normalize_video_id(raw_code)
    if not code:
        raise ValueError("invalid video ID")
    if not force:
        cached = get_cached_source(code, path=cache_path)
        if cached:
            return cached

    from src.weekly import chinese_forum, sukebei

    chinese_forum.set_proxy(proxy)
    sukebei.set_proxy(proxy)
    forum_item = None
    with _plwt_search_slot():
        forum_item = chinese_forum.search_exact_chinese(code)
    if forum_item and forum_item.get("_rate_limited") and not forum_item.get("magnet"):
        _mark_plwt_rate_limited()
    if forum_item and forum_item.get("magnet"):
        return save_cached_source(code, {
            "kind": "magnet",
            "source": "plwt_chinese",
            "magnet": forum_item["magnet"],
            "title": forum_item.get("title") or "",
            "forum_url": forum_item.get("forumUrl") or "",
            "size_gib": 0,
            "published_at": forum_item.get("postDate") or "",
        }, path=cache_path)

    candidate = sukebei.search_preferred(code)
    if candidate and candidate.get("magnet"):
        return save_cached_source(code, {
            "kind": "magnet",
            "source": "sukebei_chinese" if candidate.get("is_cn") else "sukebei_original",
            "magnet": candidate["magnet"],
            "title": candidate.get("title") or "",
            "view_id": candidate.get("view_id") or "",
            "size_gib": float(candidate.get("size_gib") or 0),
            "published_at": candidate.get("published_at") or "",
        }, path=cache_path)

    return save_cached_source(code, {
        "kind": "stream",
        "source": "online_stream",
        "magnet": "",
        "title": "",
        "size_gib": 0,
        "published_at": "",
    }, path=cache_path)
