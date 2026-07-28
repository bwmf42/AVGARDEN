#!/usr/bin/env python3
"""Dry-run-first cleanup for unreferenced Weekly artwork directories."""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.maintenance.storage_cleanup import (
    atomic_json,
    file_record,
    gzip_copy,
    is_current_record,
    load_weekly_ids,
    safe_under,
    tree_record,
    utc_now,
)
from video_id import local_video_id_aliases, normalize_video_id


MANIFEST_KIND = "weekly-artwork-orphans"
MANIFEST_VERSION = 1


def directory_aliases(name):
    aliases = set(local_video_id_aliases(name))
    aliases.update(filter(None, (name.upper(), normalize_video_id(name))))
    return aliases


def build_manifest(save_path, db_dir, min_age_days=30, now=None):
    save_path = os.path.realpath(save_path)
    db_dir = os.path.realpath(db_dir)
    weekly_dir = os.path.join(save_path, "__weekly__")
    weekly_json = os.path.join(weekly_dir, "weekly.json")
    weekly_items, weekly_ids = load_weekly_ids(weekly_json)
    now = time.time() if now is None else float(now)
    cutoff = now - max(0, int(min_age_days)) * 24 * 60 * 60

    orphan_dirs = []
    for name in sorted(os.listdir(weekly_dir)):
        path = os.path.join(weekly_dir, name)
        if not os.path.isdir(path) or os.path.islink(path):
            continue
        if directory_aliases(name).intersection(weekly_ids):
            continue
        info = os.stat(path, follow_symlinks=False)
        if info.st_mtime > cutoff:
            continue
        record = tree_record(path, "Weekly artwork absent from current index beyond retention")
        record["directory_mtime_ns"] = info.st_mtime_ns
        orphan_dirs.append(record)

    return {
        "kind": MANIFEST_KIND,
        "version": MANIFEST_VERSION,
        "generated_at": utc_now(),
        "roots": {"save_path": save_path, "db_dir": db_dir},
        "min_age_days": max(0, int(min_age_days)),
        "counts": {
            "weekly_items": len(weekly_items),
            "orphan_dirs": len(orphan_dirs),
            "logical_bytes": sum(item["logical_bytes"] for item in orphan_dirs),
            "allocated_bytes": sum(item["allocated_bytes"] for item in orphan_dirs),
        },
        "guards": {"weekly_json": file_record(weekly_json, "current Weekly index")},
        "actions": {"remove_weekly_dirs": orphan_dirs},
    }


def rotate_backups(backup_dir):
    files = sorted(
        (
            os.path.join(backup_dir, name)
            for name in os.listdir(backup_dir)
            if name.startswith("weekly-cache-index-") and name.endswith(".json.gz")
        ),
        key=os.path.getmtime,
        reverse=True,
    )
    cutoff = time.time() - 30 * 24 * 60 * 60
    removed = []
    for index, path in enumerate(files):
        if index >= 3 and os.path.getmtime(path) < cutoff:
            os.remove(path)
            removed.append(path)
    return removed


def apply_manifest(manifest):
    if manifest.get("kind") != MANIFEST_KIND or manifest.get("version") != MANIFEST_VERSION:
        raise RuntimeError("unsupported Weekly maintenance manifest")

    roots = manifest["roots"]
    weekly_dir = os.path.join(roots["save_path"], "__weekly__")
    weekly_json = os.path.join(weekly_dir, "weekly.json")
    guard = manifest["guards"]["weekly_json"]
    if not is_current_record(guard):
        raise RuntimeError("weekly.json changed after manifest generation")
    _, weekly_ids = load_weekly_ids(weekly_json)

    for record in manifest["actions"]["remove_weekly_dirs"]:
        path = record["path"]
        name = os.path.basename(path)
        if (
            not safe_under(path, weekly_dir)
            or os.path.dirname(os.path.realpath(path)) != os.path.realpath(weekly_dir)
            or not is_current_record(record)
        ):
            raise RuntimeError(f"Weekly path guard changed: {path}")
        if directory_aliases(name).intersection(weekly_ids):
            raise RuntimeError(f"Weekly directory became referenced: {name}")
        if os.stat(path, follow_symlinks=False).st_mtime_ns != record["directory_mtime_ns"]:
            raise RuntimeError(f"Weekly directory timestamp changed: {path}")

    backup_dir = os.path.join(roots["db_dir"], "backups")
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(backup_dir, f"weekly-cache-index-{stamp}.json.gz")
    gzip_copy(weekly_json, backup)

    removed = []
    for record in manifest["actions"]["remove_weekly_dirs"]:
        shutil.rmtree(record["path"])
        removed.append(record["path"])
    return {
        "completed_at": utc_now(),
        "backup": backup,
        "removed_paths": removed,
        "rotated_backups": rotate_backups(backup_dir),
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-path", default=os.environ.get("SAVE_PATH", "/data"))
    parser.add_argument("--db-dir", default=os.path.dirname(os.environ.get("DB_PATH", "/db/downloaded.db")))
    parser.add_argument("--min-age-days", type=int, default=30)
    parser.add_argument("--manifest", help="write a dry-run manifest to this path")
    parser.add_argument("--apply", help="apply an existing manifest")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.apply:
        with open(args.apply, encoding="utf-8") as handle:
            manifest = json.load(handle)
        result = apply_manifest(manifest)
        result_path = args.apply + ".result.json"
        atomic_json(result_path, result)
        print(json.dumps({"result": result_path, **manifest["counts"]}, ensure_ascii=False, indent=2))
        return

    manifest = build_manifest(args.save_path, args.db_dir, args.min_age_days)
    path = args.manifest or os.path.join(
        args.db_dir,
        "maintenance",
        "manifests",
        f"weekly-cache-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
    )
    atomic_json(path, manifest)
    print(json.dumps({"manifest": path, **manifest["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
