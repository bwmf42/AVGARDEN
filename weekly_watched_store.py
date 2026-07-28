"""Cross-process watched-state storage shared by Worker maintenance jobs."""

from __future__ import annotations

import json
import os
from datetime import datetime

from video_id import normalize_video_id
from weekly_store import atomic_write_json, json_update_lock


def now_rfc3339():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_record(raw, fallback_time=None):
    fallback_time = fallback_time or now_rfc3339()
    if isinstance(raw, str):
        code = normalize_video_id(raw)
        return {"id": code, "watched_at": fallback_time, "reason": "manual"} if code else None
    if not isinstance(raw, dict):
        return None
    code = normalize_video_id(raw.get("id"))
    if not code:
        return None
    return {
        "id": code,
        "watched_at": str(raw.get("watched_at") or fallback_time),
        "reason": str(raw.get("reason") or "manual"),
    }


def load_records(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    rows = value.get("items", []) if isinstance(value, dict) else value
    records = {}
    for raw in rows if isinstance(rows, list) else []:
        record = normalize_record(raw)
        if record:
            records[record["id"]] = record
    return records


def write_records(path, records):
    ordered = sorted(
        records.values(),
        key=lambda record: (record.get("watched_at") or "", record["id"]),
        reverse=True,
    )
    atomic_write_json(path, {"items": ordered})
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def mark_many(path, entries):
    normalized = []
    for entry in entries or []:
        code = normalize_video_id(entry.get("id"))
        if code:
            normalized.append({
                "id": code,
                "watched_at": entry.get("watched_at") or now_rfc3339(),
                "reason": entry.get("reason") or "manual",
            })
    if not normalized:
        return 0
    with json_update_lock(path):
        records = load_records(path)
        added = 0
        for entry in normalized:
            existing = records.get(entry["id"])
            if existing:
                if entry["reason"].startswith("blocked_") and not existing.get("reason", "").startswith("blocked_"):
                    existing["reason"] = entry["reason"]
                    added += 1
                continue
            records[entry["id"]] = entry
            added += 1
        if added:
            write_records(path, records)
    return added


def mark_watched(path, code, watched_at=None, reason="manual"):
    return bool(mark_many(path, [{"id": code, "watched_at": watched_at, "reason": reason}]))
