"""Match Weekly metadata against the same persistent filters as the Go API."""

from __future__ import annotations

import json
import os

from . import actresses as actress_util
from . import genre_zh


def _db_file(env_name, default_name):
    configured = (os.environ.get(env_name) or "").strip()
    if configured:
        return configured
    db_path = (os.environ.get("DB_PATH") or "/db/downloaded.db").strip()
    return os.path.join(os.path.dirname(db_path) or "/db", default_name)


def _lines(path, env_name=""):
    values = []
    try:
        with open(path, encoding="utf-8") as handle:
            values.extend(line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#"))
    except FileNotFoundError:
        pass
    if env_name:
        values.extend(value.strip() for value in os.environ.get(env_name, "").split(",") if value.strip())
    return list(dict.fromkeys(values))


def _load_actress_years():
    path = _db_file("ACTRESS_AGES_FILE", "actress_ages.json")
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_rules():
    actress_util.load_blocked_actresses(force=True)
    genre_zh.load_blocked_genres(force=True)
    favorites = _lines(_db_file("FAV_ACTRESSES_FILE", "favorite_actresses.txt"))
    return {
        "favorite_actress_folds": {actress_util.fold_actress_key(value) for value in favorites},
        "blocked_genres": set(_lines(_db_file("BLOCKED_GENRES_FILE", "blocked_genres.txt"), "BLOCKED_GENRES")),
        "blocked_keywords": _lines(_db_file("BLOCKED_KEYWORDS_FILE", "blocked_keywords.txt")),
        "actress_years": _load_actress_years(),
    }


def _has_old_actress(values, years):
    from datetime import datetime

    current_year = datetime.now().year
    for name in values:
        try:
            if name in years and current_year - int(years[name]) > 45:
                return True
        except (TypeError, ValueError):
            continue
    return False


def match_reason(item, rules=None):
    """Return a stable reason string when the item should be hidden."""
    rules = rules or load_rules()
    actresses = [str(value).strip() for value in item.get("actresses") or [] if str(value).strip()]
    genres = [str(value).strip() for value in item.get("genres") or [] if str(value).strip()]

    if any(actress_util.is_blocked_actress(name) for name in actresses):
        return "blocked_actress"

    has_favorite = any(
        actress_util.fold_actress_key(name) in rules["favorite_actress_folds"] for name in actresses
    )
    if not has_favorite:
        if any(genre_zh.snap_to_blocked(name) in rules["blocked_genres"] for name in genres):
            return "blocked_genre"

    title = str(item.get("title") or "")
    if any(keyword in title for keyword in rules["blocked_keywords"]):
        return "blocked_keyword"

    if _has_old_actress(actresses, rules["actress_years"]):
        return "blocked_age"
    return ""


def strip_expensive_fields(item):
    """Keep matching metadata but remove artwork, translation, and download data."""
    for key in ("cover", "poster", "titleZh", "magnet", "artworkSource", "remoteFanarts"):
        item.pop(key, None)
    item["fanarts"] = []
    item["downloaded"] = False
    return item
