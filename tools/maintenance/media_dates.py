#!/usr/bin/env python3
"""Reviewable, reversible media-directory date repair; never changes video files."""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.media_dates import _directory, _load, registry_path, restore_registered
from weekly_store import atomic_write_json, json_update_lock


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def plan(root, proposed):
    root = os.path.realpath(root)
    entries = []
    seen = set()
    for row in proposed:
        folder = row["folder"]
        if folder in seen:
            raise ValueError("Duplicate folder")
        seen.add(folder)
        resolved = _directory(root, folder)
        if not resolved:
            raise ValueError("Not a regular media directory: " + folder)
        path, info = resolved
        if row["basis"] not in ("release_date", "download_completed"):
            raise ValueError("Unverified date basis")
        target = datetime.fromisoformat(row["date"])
        if target.tzinfo is None or target.timestamp() <= 0 or target.timestamp() > datetime.now().timestamp():
            raise ValueError("Date must have a timezone and be in the past")
        if not row.get("source"):
            raise ValueError("Missing date evidence")
        files = sorted((e.name, e.stat(follow_symlinks=False).st_size, e.stat(follow_symlinks=False).st_mtime_ns)
                       for e in os.scandir(path))
        info = os.stat(path, follow_symlinks=False)
        entries.append({**row, "root": root, "device": info.st_dev, "inode": info.st_ino,
                        "timestamp_ns": int(target.timestamp()) * 1_000_000_000,
                        "before_atime_ns": info.st_atime_ns, "before_mtime_ns": info.st_mtime_ns,
                        "files_signature": digest(files)})
    manifest = {"version": 1, "root": root, "entries": entries}
    return {**manifest, "sha256": digest(manifest)}


def apply(manifest, result_path):
    if os.path.exists(result_path):
        raise ValueError("Result/backup already exists; do not overwrite it")
    unsigned = {k: v for k, v in manifest.items() if k != "sha256"}
    if manifest.get("sha256") != digest(unsigned):
        raise ValueError("Manifest signature mismatch")
    root = manifest["root"]
    # Validate the whole batch before publishing any anchors or touching dates.
    for entry in manifest["entries"]:
        resolved = _directory(root, entry["folder"])
        if not resolved:
            raise ValueError("Directory disappeared")
        path, info = resolved
        if (info.st_dev, info.st_ino, info.st_mtime_ns) != (entry["device"], entry["inode"], entry["before_mtime_ns"]):
            raise ValueError("Directory changed: " + entry["folder"])
        files = sorted((e.name, e.stat(follow_symlinks=False).st_size, e.stat(follow_symlinks=False).st_mtime_ns)
                       for e in os.scandir(path))
        if digest(files) != entry["files_signature"]:
            raise ValueError("Directory contents changed: " + entry["folder"])
    with json_update_lock(registry_path()):
        store = _load()
        if any(entry["folder"] in store["entries"] for entry in manifest["entries"]):
            raise ValueError("Existing anchor requires a separate reviewed correction")
        result = {"status": "applying", "manifest": manifest, "registry_before": store}
        atomic_write_json(result_path, result)
        updated = {**store, "entries": dict(store["entries"])}
        for entry in manifest["entries"]:
            updated["entries"][entry["folder"]] = dict(entry)
        atomic_write_json(registry_path(), updated)
        changed = restore_registered(root, [e["folder"] for e in manifest["entries"]])
        result.update(status="applied", changed=changed)
        atomic_write_json(result_path, result)
    return result


def rollback(result_path):
    result = json.loads(Path(result_path).read_text())
    manifest = result["manifest"]
    if manifest.get("sha256") != digest({k: v for k, v in manifest.items() if k != "sha256"}):
        raise ValueError("Manifest signature mismatch")
    with json_update_lock(registry_path()):
        store = _load()
        for entry in manifest["entries"]:
            if store["entries"].get(entry["folder"]) != entry:
                raise ValueError("Anchor changed; rollback refused")
            resolved = _directory(manifest["root"], entry["folder"])
            if not resolved or (resolved[1].st_dev, resolved[1].st_ino) != (entry["device"], entry["inode"]):
                raise ValueError("Directory replaced; rollback refused")
        # Retain unrelated anchors added since this batch.
        for entry in manifest["entries"]:
            previous = result["registry_before"]["entries"].get(entry["folder"])
            if previous:
                store["entries"][entry["folder"]] = previous
            else:
                store["entries"].pop(entry["folder"], None)
        atomic_write_json(registry_path(), store)
        for entry in manifest["entries"]:
            path = os.path.join(manifest["root"], entry["folder"])
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) != (entry["device"], entry["inode"]):
                    raise ValueError("Directory replaced during rollback")
                os.utime(fd, ns=(entry["before_atime_ns"], entry["before_mtime_ns"]))
            finally:
                os.close(fd)
        result["status"] = "rolled_back"
        atomic_write_json(result_path, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("SAVE_PATH", "/data"))
    parser.add_argument("--dates", help="Reviewed JSON proposals, including source URLs")
    parser.add_argument("--manifest")
    parser.add_argument("--apply")
    parser.add_argument("--rollback")
    args = parser.parse_args()
    if args.rollback:
        rollback(args.rollback)
    elif args.apply:
        result = apply(json.loads(Path(args.apply).read_text()), args.apply + ".result.json")
        print(json.dumps({"status": result["status"], "count": len(result["changed"])}))
    elif args.dates and args.manifest:
        manifest = plan(args.root, json.loads(Path(args.dates).read_text()))
        atomic_write_json(args.manifest, manifest)
        print(json.dumps({"count": len(manifest["entries"]), "sha256": manifest["sha256"]}))
    else:
        parser.error("Use --dates and --manifest, --apply, or --rollback")


if __name__ == "__main__":
    main()
