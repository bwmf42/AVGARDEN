#!/usr/bin/env python3
"""Expire watched Weekly entries and remove artwork for blocked entries."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.weekly import blocking
from tools.maintenance.storage_cleanup import (
    file_record,
    gzip_copy,
    is_current_record,
    safe_under,
    tree_record,
    utc_now,
)
from video_id import local_video_id_aliases, normalize_video_id
from weekly_store import atomic_write_json, json_update_lock, weekly_update_lock
from weekly_watched_store import load_records, normalize_record, write_records


MANIFEST_KIND = "weekly-retention"
MANIFEST_VERSION = 1
DEFAULT_RETENTION_DAYS = 30


def parse_timestamp(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                parsed = datetime.strptime(raw[:10], fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.timestamp()


def first_seen(item, fallback):
    for key in ("postDate", "releaseDate"):
        parsed = parse_timestamp(item.get(key))
        if parsed is not None:
            return datetime.fromtimestamp(parsed).astimezone().isoformat(timespec="seconds")
    return datetime.fromtimestamp(fallback).astimezone().isoformat(timespec="seconds")


def directory_aliases(name):
    aliases = set(local_video_id_aliases(name))
    aliases.update(filter(None, (name.upper(), normalize_video_id(name))))
    return aliases


def _load_weekly(path):
    with open(path, encoding="utf-8") as handle:
        items = json.load(handle)
    if not isinstance(items, list):
        raise RuntimeError("weekly.json must contain a list")
    return items


def _guarded_filter_files(db_dir):
    names = (
        "blocked_actresses.txt",
        "blocked_genres.txt",
        "blocked_keywords.txt",
        "favorite_actresses.txt",
        "actress_ages.json",
    )
    return [
        file_record(os.path.join(db_dir, name), "Weekly filter input")
        for name in names
        if os.path.isfile(os.path.join(db_dir, name))
    ]


def _routine_file_records(db_dir, cutoff):
    candidates = []
    locations = (
        (os.path.join(db_dir, "backups"), ("weekly-retention-", "weekly-cache-index-")),
        (os.path.join(db_dir, "maintenance", "manifests"), ("weekly-retention-", "weekly-cache-")),
    )
    for root, prefixes in locations:
        if not os.path.isdir(root):
            continue
        files = [
            os.path.join(root, name)
            for name in os.listdir(root)
            if os.path.isfile(os.path.join(root, name)) and name.startswith(prefixes)
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        for index, path in enumerate(files):
            if index >= 3 and os.path.getmtime(path) < cutoff:
                candidates.append(file_record(path, "routine maintenance record older than 30 days"))
    return candidates


def build_manifest(save_path, db_dir, retention_days=DEFAULT_RETENTION_DAYS, now=None):
    save_path = os.path.realpath(save_path)
    db_dir = os.path.realpath(db_dir)
    weekly_dir = os.path.join(save_path, "__weekly__")
    weekly_json = os.path.join(weekly_dir, "weekly.json")
    watched_path = os.path.join(db_dir, "weekly_watched.json")
    now = time.time() if now is None else float(now)
    cutoff = now - max(1, int(retention_days)) * 86400

    items = _load_weekly(weekly_json)
    records = load_records(watched_path)
    rules = blocking.load_rules()
    by_code = {
        normalize_video_id(item.get("id")): item
        for item in items
        if isinstance(item, dict) and normalize_video_id(item.get("id"))
    }

    blocked = []
    effective_records = dict(records)
    for code, item in by_code.items():
        reason = blocking.match_reason(item, rules)
        if not reason:
            continue
        blocked.append({"id": code, "reason": reason})
        if code not in effective_records:
            effective_records[code] = normalize_record({
                "id": code,
                "watched_at": first_seen(item, now),
                "reason": reason,
            })

    expired_ids = sorted(
        code
        for code, record in effective_records.items()
        if (parse_timestamp(record.get("watched_at")) or now) < cutoff
    )
    expired_set = set(expired_ids)
    blocked_ids = {item["id"] for item in blocked}
    artwork_remove_ids = expired_set | blocked_ids

    artwork_dirs = []
    for name in sorted(os.listdir(weekly_dir)):
        path = os.path.join(weekly_dir, name)
        if not os.path.isdir(path) or os.path.islink(path):
            continue
        if directory_aliases(name).intersection(artwork_remove_ids):
            artwork_dirs.append(tree_record(path, "expired watched or blocked Weekly artwork"))

    routine_files = _routine_file_records(db_dir, cutoff)
    return {
        "kind": MANIFEST_KIND,
        "version": MANIFEST_VERSION,
        "generated_at": utc_now(),
        "retention_days": max(1, int(retention_days)),
        "cutoff_epoch": cutoff,
        "roots": {"save_path": save_path, "db_dir": db_dir},
        "guards": {
            "weekly_json": file_record(weekly_json, "current Weekly index"),
            "watched_json": file_record(watched_path, "current watched state"),
            "filter_files": _guarded_filter_files(db_dir),
        },
        "counts": {
            "weekly_before": len(items),
            "watched_before": len(records),
            "blocked_items": len(blocked),
            "expired_weekly_items": sum(code in by_code for code in expired_set),
            "expired_watched_records": len(expired_ids),
            "artwork_dirs": len(artwork_dirs),
            "artwork_files": sum(item["files"] for item in artwork_dirs),
            "artwork_logical_bytes": sum(item["logical_bytes"] for item in artwork_dirs),
            "artwork_allocated_bytes": sum(item["allocated_bytes"] for item in artwork_dirs),
            "routine_files": len(routine_files),
        },
        "actions": {
            "mark_blocked": blocked,
            "expire_ids": expired_ids,
            "remove_artwork_dirs": artwork_dirs,
            "remove_routine_files": routine_files,
        },
    }


def _verify_manifest(manifest):
    if manifest.get("kind") != MANIFEST_KIND or manifest.get("version") != MANIFEST_VERSION:
        raise RuntimeError("unsupported Weekly retention manifest")
    guards = manifest["guards"]
    for record in [guards["weekly_json"], guards["watched_json"], *guards.get("filter_files", [])]:
        if not is_current_record(record):
            raise RuntimeError(f"guard changed: {record['path']}")
    for record in [
        *manifest["actions"]["remove_artwork_dirs"],
        *manifest["actions"]["remove_routine_files"],
    ]:
        if not is_current_record(record):
            raise RuntimeError(f"cleanup target changed: {record['path']}")


def apply_manifest(manifest):
    roots = manifest["roots"]
    weekly_dir = os.path.join(roots["save_path"], "__weekly__")
    weekly_json = os.path.join(weekly_dir, "weekly.json")
    watched_path = os.path.join(roots["db_dir"], "weekly_watched.json")
    expired = set(manifest["actions"]["expire_ids"])
    blocked = {item["id"]: item["reason"] for item in manifest["actions"]["mark_blocked"]}

    with weekly_update_lock(weekly_json):
        with json_update_lock(watched_path):
            _verify_manifest(manifest)
            items = _load_weekly(weekly_json)
            records = load_records(watched_path)
            now_value = datetime.now().astimezone().isoformat(timespec="seconds")
            by_id = {normalize_video_id(item.get("id")): item for item in items if isinstance(item, dict)}
            for code, reason in blocked.items():
                if code not in records:
                    records[code] = normalize_record({
                        "id": code,
                        "watched_at": first_seen(by_id.get(code, {}), time.time()),
                        "reason": reason,
                    }, fallback_time=now_value)
            kept_items = []
            for item in items:
                code = normalize_video_id(item.get("id")) if isinstance(item, dict) else ""
                if code in expired:
                    continue
                if code in blocked:
                    blocking.strip_expensive_fields(item)
                kept_items.append(item)
            for code in expired:
                records.pop(code, None)

            backup_dir = os.path.join(roots["db_dir"], "backups")
            os.makedirs(backup_dir, mode=0o700, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            weekly_backup = os.path.join(backup_dir, f"weekly-retention-index-{stamp}.json.gz")
            watched_backup = os.path.join(backup_dir, f"weekly-retention-watched-{stamp}.json.gz")
            gzip_copy(weekly_json, weekly_backup)
            gzip_copy(watched_path, watched_backup)
            atomic_write_json(weekly_json, kept_items)
            write_records(watched_path, records)

    removed_dirs = []
    for record in manifest["actions"]["remove_artwork_dirs"]:
        path = record["path"]
        if not safe_under(path, weekly_dir) or os.path.dirname(path) != os.path.realpath(weekly_dir):
            raise RuntimeError(f"unsafe Weekly artwork path: {path}")
        shutil.rmtree(path)
        removed_dirs.append(path)

    removed_files = []
    for record in manifest["actions"]["remove_routine_files"]:
        path = record["path"]
        if not safe_under(path, roots["db_dir"]):
            raise RuntimeError(f"unsafe maintenance path: {path}")
        os.remove(path)
        removed_files.append(path)

    return {
        "completed_at": utc_now(),
        "weekly_after": len(kept_items),
        "watched_after": len(records),
        "removed_artwork_dirs": removed_dirs,
        "removed_routine_files": removed_files,
        "backups": [weekly_backup, watched_backup],
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-path", default=os.environ.get("SAVE_PATH", "/data"))
    parser.add_argument("--db-dir", default=os.path.dirname(os.environ.get("DB_PATH", "/db/downloaded.db")))
    parser.add_argument("--retention-days", type=int, default=int(os.environ.get("WEEKLY_RETENTION_DAYS", "30")))
    parser.add_argument("--manifest")
    parser.add_argument("--apply")
    parser.add_argument("--auto", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.apply:
        with open(args.apply, encoding="utf-8") as handle:
            manifest = json.load(handle)
        result = apply_manifest(manifest)
        result_path = args.apply + ".result.json"
        atomic_write_json(result_path, result)
        print(json.dumps({"result": result_path, **manifest["counts"], **result}, ensure_ascii=False, indent=2))
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = args.manifest or os.path.join(
        args.db_dir, "maintenance", "manifests", f"weekly-retention-{stamp}.json"
    )
    manifest = build_manifest(args.save_path, args.db_dir, args.retention_days)
    atomic_write_json(path, manifest)
    if args.auto:
        result = apply_manifest(manifest)
        result_path = path + ".result.json"
        atomic_write_json(result_path, result)
        print(json.dumps({"manifest": path, "result": result_path, **manifest["counts"], **result}, ensure_ascii=False, indent=2))
        return
    print(json.dumps({"manifest": path, **manifest["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
