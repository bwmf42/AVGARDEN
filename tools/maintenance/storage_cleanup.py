#!/usr/bin/env python3
"""Create and apply an exact manifest for A/GARDEN runtime cleanup."""

import argparse
import gzip
import hashlib
import http.cookiejar
import json
import os
import shutil
import sqlite3
import stat
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from main_video import MAIN_VIDEO_MIN_SIZE, find_main_video
from queue_store import append_unique, read_json, update_json
from video_id import local_video_id_aliases, normalize_local_video_id, normalize_video_id


MANIFEST_VERSION = 1
TARGET_CATEGORY = "AV_GARDEN"
RECOVERY_CODES = {"MIKR-109", "PRED-886", "SNOS-264"}
EXPECTED_BASELINE = {
    "weekly_items": 1811,
    "watched_items": 2017,
    "weekly_orphan_dirs": 1237,
    "media_missing_posters": 11,
    "media_sparse_residue_dirs": 7,
    "media_metadata_only_dirs": 10,
    "qb_missing_files": 160,
    "qb_false_completed": 3,
}

ACTIVE_QB_STATES = {
    "downloading", "stalledDL", "forcedDL", "metaDL", "queuedDL",
    "checkingDL", "allocating", "moving", "checkingResumeData",
}
DONE_QB_STATES = {
    "queuedUP", "uploading", "stalledUP", "pausedUP", "forcedUP", "checkingUP",
}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_under(path, root):
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    try:
        return os.path.commonpath([real_root, real_path]) == real_root
    except ValueError:
        return False


def tree_record(path, reason):
    digest = hashlib.sha256()
    logical = 0
    allocated = 0
    files = 0
    for root, dirs, names in os.walk(path, followlinks=False):
        dirs.sort()
        names.sort()
        for name in names:
            item = os.path.join(root, name)
            relative = os.path.relpath(item, path)
            info = os.lstat(item)
            digest.update(relative.encode("utf-8", "surrogateescape"))
            digest.update(f"\0{info.st_mode}\0{info.st_size}\0{info.st_mtime_ns}\n".encode())
            logical += info.st_size
            allocated += getattr(info, "st_blocks", 0) * 512
            files += 1
    return {
        "path": os.path.realpath(path),
        "reason": reason,
        "logical_bytes": logical,
        "allocated_bytes": allocated,
        "files": files,
        "signature": digest.hexdigest(),
    }


def file_record(path, reason):
    info = os.stat(path, follow_symlinks=False)
    return {
        "path": os.path.realpath(path),
        "reason": reason,
        "logical_bytes": info.st_size,
        "allocated_bytes": getattr(info, "st_blocks", 0) * 512,
        "mtime_ns": info.st_mtime_ns,
    }


def is_current_record(record):
    path = record["path"]
    if not os.path.exists(path):
        return False
    if "signature" in record:
        return tree_record(path, record["reason"])["signature"] == record["signature"]
    info = os.stat(path, follow_symlinks=False)
    return info.st_size == record["logical_bytes"] and info.st_mtime_ns == record["mtime_ns"]


def load_weekly_ids(path):
    with open(path, encoding="utf-8") as handle:
        items = json.load(handle)
    if not isinstance(items, list):
        raise RuntimeError("weekly.json must contain a list")
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("id") or "").strip().upper()
        normalized = normalize_video_id(raw)
        if raw:
            ids.add(raw)
        if normalized:
            ids.add(normalized)
    return items, ids


def load_watched_count(path):
    value = read_json(path, [])
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return len(value["items"])
    raise RuntimeError("unsupported weekly watched format")


def has_poster(media_dir):
    try:
        return any(name.lower().endswith("-poster.jpg") for name in os.listdir(media_dir))
    except OSError:
        return False


def best_weekly_poster(weekly_dir, code):
    if not os.path.isdir(weekly_dir):
        return ""
    names = [name for name in os.listdir(weekly_dir) if os.path.isfile(os.path.join(weekly_dir, name))]
    preferred = [
        f"{code}-poster.jpg",
        f"{code}-cover.jpg",
    ]
    lowered = {name.lower(): name for name in names}
    for name in preferred:
        if name.lower() in lowered:
            return os.path.join(weekly_dir, lowered[name.lower()])
    for suffix in ("-poster.jpg", "-cover.jpg"):
        for name in sorted(names):
            if name.lower().endswith(suffix):
                return os.path.join(weekly_dir, name)
    return ""


def sparse_large_mp4s(path):
    found = []
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in files:
            item = os.path.join(root, name)
            if not name.lower().endswith(".mp4") or os.path.islink(item):
                continue
            try:
                info = os.stat(item, follow_symlinks=False)
            except OSError:
                continue
            allocated = getattr(info, "st_blocks", 0) * 512
            if info.st_size >= MAIN_VIDEO_MIN_SIZE and allocated * 100 < info.st_size * 95:
                found.append(item)
    return found


def code_from_torrent(torrent):
    for tag in str(torrent.get("tags") or "").split(","):
        normalized = normalize_video_id(tag.strip())
        if normalized:
            return normalized
    for value in (torrent.get("name"), torrent.get("content_path"), torrent.get("save_path")):
        normalized = normalize_local_video_id(value)
        if normalized:
            return normalized
    return ""


class QBClient:
    def __init__(self):
        self.url = os.environ.get("QBITTORRENT_URL", "").rstrip("/")
        self.username = os.environ.get("QBITTORRENT_USERNAME", "")
        self.password = os.environ.get("QBITTORRENT_PASSWORD", "")
        if not self.url:
            raise RuntimeError("QBITTORRENT_URL is required")
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._post("/api/v2/auth/login", {"username": self.username, "password": self.password})

    def _post(self, endpoint, data):
        request = urllib.request.Request(
            self.url + endpoint,
            data=urllib.parse.urlencode(data).encode(),
            method="POST",
        )
        with self.opener.open(request, timeout=15) as response:
            body = response.read().decode().strip()
        if endpoint.endswith("/login") and body != "Ok.":
            raise RuntimeError("qBittorrent login failed")
        if body == "Fails.":
            raise RuntimeError(f"qBittorrent request failed: {endpoint}")
        return body

    def torrents(self):
        with self.opener.open(self.url + "/api/v2/torrents/info", timeout=20) as response:
            return json.load(response)

    def delete(self, hashes):
        self._post("/api/v2/torrents/delete", {"hashes": "|".join(hashes), "deleteFiles": "false"})

    def set_category(self, hashes, category):
        self._post("/api/v2/torrents/setCategory", {"hashes": "|".join(hashes), "category": category})


def runtime_codes(db_dir, torrents):
    codes = set()
    for path in (os.path.join(db_dir, "download_queue.txt"),):
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    normalized = normalize_video_id(line.strip())
                    if normalized:
                        codes.add(normalized)
        except FileNotFoundError:
            pass
    try:
        with open(os.path.join(db_dir, "current_download.txt"), encoding="utf-8") as handle:
            normalized = normalize_video_id(handle.read().strip())
            if normalized:
                codes.add(normalized)
    except FileNotFoundError:
        pass
    for torrent in torrents:
        if str(torrent.get("state") or "") in ACTIVE_QB_STATES:
            code = code_from_torrent(torrent)
            if code:
                codes.add(code)
    return codes


def build_manifest(save_path, db_dir, cfg_path, log_dir, torrents, generated_at=None):
    save_path = os.path.realpath(save_path)
    db_dir = os.path.realpath(db_dir)
    weekly_dir = os.path.join(save_path, "__weekly__")
    weekly_json = os.path.join(weekly_dir, "weekly.json")
    watched_path = os.path.join(db_dir, "weekly_watched.json")
    weekly_items, weekly_ids = load_weekly_ids(weekly_json)
    watched_count = load_watched_count(watched_path)
    active_codes = runtime_codes(db_dir, torrents)

    media_by_code = {}
    media_main_video = {}
    missing_posters = []
    sparse_residue = []
    metadata_only = []
    poster_copies = []
    preserved_no_main = []

    media_dirs = []
    for name in sorted(os.listdir(save_path)):
        path = os.path.join(save_path, name)
        if not os.path.isdir(path) or name.startswith("__") or name == "thumb":
            continue
        code = normalize_local_video_id(name) or name.upper()
        media_dirs.append((name, path, code))
        aliases = local_video_id_aliases(name) or (code,)
        for alias in aliases:
            media_by_code.setdefault(alias, []).append(path)
        main_video = find_main_video(path)
        media_main_video[path] = main_video
        if main_video and not has_poster(path) and not set(aliases).intersection(active_codes):
            source = best_weekly_poster(os.path.join(weekly_dir, code), code)
            missing_posters.append(code)
            if source:
                poster_copies.append({
                    "code": code,
                    "source": os.path.realpath(source),
                    "source_size": os.path.getsize(source),
                    "destination": os.path.join(path, f"{name}-poster.jpg"),
                })

    false_completed = []
    missing_qb = []
    category_updates = []
    for torrent in torrents:
        state = str(torrent.get("state") or "")
        code = code_from_torrent(torrent)
        has_media = bool(code and any(media_main_video.get(path) for path in media_by_code.get(code, [])))
        item = {
            "hash": str(torrent.get("hash") or ""),
            "state": state,
            "code": code,
        }
        if state == "missingFiles":
            missing_qb.append({**item, "reason": "qB state missingFiles", "delete_files": False})
            continue
        if code in RECOVERY_CODES and state in DONE_QB_STATES and not has_media:
            false_completed.append({**item, "reason": "completed qB task has no valid main video", "delete_files": False})
            continue
        valid = state in ACTIVE_QB_STATES or (state in DONE_QB_STATES and has_media)
        if valid and str(torrent.get("category") or "") != TARGET_CATEGORY:
            category_updates.append({"hash": item["hash"], "code": code, "target": TARGET_CATEGORY})

    for name, path, code in media_dirs:
        if media_main_video[path]:
            continue
        sparse = sparse_large_mp4s(path)
        aliases = set(local_video_id_aliases(name) or (code,))
        if aliases.intersection(active_codes) or aliases.intersection(RECOVERY_CODES):
            preserved_no_main.append({"path": path, "code": code, "reason": "active or recovery task"})
        elif sparse:
            record = tree_record(path, "large sparse MP4 without an active qB task")
            record["code"] = code
            sparse_residue.append(record)
        else:
            record = tree_record(path, "metadata-only media directory without a playable main video")
            record["code"] = code
            metadata_only.append(record)

    orphan_dirs = []
    for name in sorted(os.listdir(weekly_dir)):
        path = os.path.join(weekly_dir, name)
        if not os.path.isdir(path):
            continue
        aliases = set(local_video_id_aliases(name))
        aliases.update(filter(None, (name.upper(), normalize_video_id(name))))
        if not aliases.intersection(weekly_ids):
            orphan_dirs.append(tree_record(path, "Weekly artwork directory absent from current weekly.json"))

    remove_files = []
    for name in sorted(os.listdir(weekly_dir)):
        path = os.path.join(weekly_dir, name)
        if os.path.isfile(path) and name.startswith("weekly.json.backup-"):
            remove_files.append(file_record(path, "legacy Weekly JSON backup"))

    log_cutoff = time.time() - 30 * 24 * 60 * 60
    if os.path.isdir(log_dir):
        for name in sorted(os.listdir(log_dir)):
            path = os.path.join(log_dir, name)
            if not os.path.isfile(path):
                continue
            if name in {"prefetch_weekly_fanarts.py", "prefetch_weekly_fanarts_41.py"}:
                remove_files.append(file_record(path, "one-time script misplaced in logs"))
            elif os.path.getmtime(path) < log_cutoff:
                remove_files.append(file_record(path, "log older than 30 days"))

    online_expired = []
    online_dir = os.path.join(save_path, "__online__")
    online_cutoff = time.time() - 24 * 60 * 60
    if os.path.isdir(online_dir):
        for name in sorted(os.listdir(online_dir)):
            path = os.path.join(online_dir, name)
            if os.path.isdir(path) and not os.path.islink(path) and os.path.getmtime(path) < online_cutoff:
                online_expired.append(tree_record(path, "online detail cache older than 24 hours"))

    counts = {
        "weekly_items": len(weekly_items),
        "watched_items": watched_count,
        "weekly_orphan_dirs": len(orphan_dirs),
        "media_missing_posters": len(missing_posters),
        "media_sparse_residue_dirs": len(sparse_residue),
        "media_metadata_only_dirs": len(metadata_only),
        "qb_missing_files": len(missing_qb),
        "qb_false_completed": len(false_completed),
        "qb_category_updates": len(category_updates),
        "online_expired_dirs": len(online_expired),
        "exact_files": len(remove_files),
    }
    mismatches = {
        key: {"expected": expected, "actual": counts.get(key)}
        for key, expected in EXPECTED_BASELINE.items()
        if counts.get(key) != expected
    }
    if len(poster_copies) != len(missing_posters):
        mismatches["poster_sources"] = {"expected": len(missing_posters), "actual": len(poster_copies)}
    found_recovery = {item["code"] for item in false_completed}
    if found_recovery != RECOVERY_CODES:
        mismatches["recovery_codes"] = {"expected": sorted(RECOVERY_CODES), "actual": sorted(found_recovery)}

    return {
        "version": MANIFEST_VERSION,
        "generated_at": generated_at or utc_now(),
        "roots": {
            "save_path": save_path,
            "db_dir": db_dir,
            "cfg_path": os.path.realpath(cfg_path),
            "log_dir": os.path.realpath(log_dir),
        },
        "counts": counts,
        "baseline_mismatches": mismatches,
        "guards": {
            "weekly_json": file_record(weekly_json, "current Weekly index"),
            "weekly_watched": file_record(watched_path, "current watched history"),
        },
        "preserved": {
            "active_codes": sorted(active_codes),
            "no_main_media": preserved_no_main,
        },
        "actions": {
            "copy_posters": poster_copies,
            "remove_weekly_dirs": orphan_dirs,
            "remove_media_dirs": sparse_residue + metadata_only,
            "remove_online_dirs": online_expired,
            "remove_files": remove_files,
            "qb_remove_missing": missing_qb,
            "qb_remove_false_completed": false_completed,
            "qb_set_category": category_updates,
            "requeue_codes": sorted(RECOVERY_CODES),
        },
    }


def atomic_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def gzip_copy(source, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(source, "rb") as src, gzip.open(destination, "wb") as dst:
        shutil.copyfileobj(src, dst)
    os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)


def backup_runtime(manifest):
    roots = manifest["roots"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(roots["db_dir"], "backups")
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    backups = []
    for label, source in (
        ("weekly", os.path.join(roots["save_path"], "__weekly__", "weekly.json")),
        ("weekly-watched", os.path.join(roots["db_dir"], "weekly_watched.json")),
        ("configs", roots["cfg_path"]),
    ):
        if os.path.isfile(source):
            destination = os.path.join(backup_dir, f"{label}-{stamp}.json.gz")
            gzip_copy(source, destination)
            backups.append(destination)

    database = os.path.join(roots["db_dir"], "downloaded.db")
    if os.path.isfile(database):
        temp_db = os.path.join(backup_dir, f"downloaded-{stamp}.db")
        source_conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        target_conn = sqlite3.connect(temp_db)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
            source_conn.close()
        destination = temp_db + ".gz"
        gzip_copy(temp_db, destination)
        os.remove(temp_db)
        backups.append(destination)
    return backups


def rotate_backups(db_dir):
    backup_dir = os.path.join(db_dir, "backups")
    if not os.path.isdir(backup_dir):
        return []
    files = sorted(
        (os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if os.path.isfile(os.path.join(backup_dir, name))),
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


def verify_qb_actions(current, actions, save_path):
    by_hash = {str(item.get("hash") or ""): item for item in current}
    current_missing = {
        torrent_hash
        for torrent_hash, item in by_hash.items()
        if str(item.get("state") or "") == "missingFiles"
    }
    expected_missing = {action["hash"] for action in actions["qb_remove_missing"]}
    if current_missing != expected_missing:
        raise RuntimeError("qB missingFiles set changed after manifest generation")
    for action in actions["qb_remove_missing"]:
        item = by_hash.get(action["hash"])
        if item is None or str(item.get("state") or "") != "missingFiles":
            raise RuntimeError(f"qB missingFiles guard changed for {action['hash']}")
    for action in actions["qb_remove_false_completed"]:
        item = by_hash.get(action["hash"])
        if item is None or str(item.get("state") or "") not in DONE_QB_STATES:
            raise RuntimeError(f"qB false-completion guard changed for {action['code']}")
        for name in os.listdir(save_path):
            path = os.path.join(save_path, name)
            if (
                os.path.isdir(path)
                and action["code"] in local_video_id_aliases(name)
                and find_main_video(path)
            ):
                raise RuntimeError(f"qB task gained a valid main video: {action['code']}")


def post_queue(code):
    payload = json.dumps({"code": code}).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:31473/api/queue/",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"failed to requeue {code}: HTTP {response.status}")


def apply_manifest(manifest, qb_client):
    if manifest.get("version") != MANIFEST_VERSION:
        raise RuntimeError("unsupported manifest version")
    if manifest.get("baseline_mismatches"):
        raise RuntimeError(f"manifest has baseline mismatches: {manifest['baseline_mismatches']}")

    roots = manifest["roots"]
    actions = manifest["actions"]
    current_torrents = qb_client.torrents()
    verify_qb_actions(current_torrents, actions, roots["save_path"])
    for guard in manifest["guards"].values():
        if not is_current_record(guard):
            raise RuntimeError(f"runtime guard changed: {guard['path']}")
    current_active_codes = runtime_codes(roots["db_dir"], current_torrents)
    for record in actions["remove_media_dirs"]:
        aliases = set(local_video_id_aliases(record.get("code")) or (record.get("code"),))
        if aliases.intersection(current_active_codes):
            raise RuntimeError(f"media directory became active: {record['code']}")
    for group in ("remove_weekly_dirs", "remove_media_dirs", "remove_online_dirs", "remove_files"):
        for record in actions[group]:
            expected_root = roots["log_dir"] if record["path"].startswith(roots["log_dir"] + os.sep) else roots["save_path"]
            if not safe_under(record["path"], expected_root) or not is_current_record(record):
                raise RuntimeError(f"path guard changed: {record['path']}")

    backups = backup_runtime(manifest)
    result = {
        "started_at": utc_now(),
        "backups": backups,
        "copied_posters": [],
        "removed_paths": [],
        "qb_removed": [],
        "qb_categories_updated": [],
        "requeued": [],
    }

    for action in actions["copy_posters"]:
        source = action["source"]
        destination = action["destination"]
        if not safe_under(source, os.path.join(roots["save_path"], "__weekly__")):
            raise RuntimeError(f"poster source escaped Weekly root: {source}")
        if not safe_under(destination, roots["save_path"]):
            raise RuntimeError(f"poster destination escaped media root: {destination}")
        if os.path.getsize(source) != action["source_size"]:
            raise RuntimeError(f"poster source changed: {source}")
        if not os.path.exists(destination):
            shutil.copy2(source, destination)
        result["copied_posters"].append(destination)

    for group in ("remove_media_dirs", "remove_weekly_dirs", "remove_online_dirs"):
        for record in actions[group]:
            shutil.rmtree(record["path"])
            result["removed_paths"].append(record)
    for record in actions["remove_files"]:
        os.remove(record["path"])
        result["removed_paths"].append(record)

    missing_hashes = [item["hash"] for item in actions["qb_remove_missing"]]
    false_hashes = [item["hash"] for item in actions["qb_remove_false_completed"]]
    if missing_hashes:
        qb_client.delete(missing_hashes)
        result["qb_removed"].extend(missing_hashes)
    if false_hashes:
        qb_client.delete(false_hashes)
        result["qb_removed"].extend(false_hashes)
    category_hashes = [item["hash"] for item in actions["qb_set_category"]]
    if category_hashes:
        qb_client.set_category(category_hashes, TARGET_CATEGORY)
        result["qb_categories_updated"].extend(category_hashes)

    for code in actions["requeue_codes"]:
        post_queue(code)
        result["requeued"].append(code)

    cfg_path = roots["cfg_path"]
    if os.path.isfile(cfg_path):
        os.chmod(cfg_path, 0o600)
        os.chmod(os.path.dirname(cfg_path), 0o700)
    result["rotated_backups"] = rotate_backups(roots["db_dir"])
    result["completed_at"] = utc_now()
    return result


def summary(manifest):
    actions = manifest["actions"]
    logical = sum(
        record["logical_bytes"]
        for group in ("remove_weekly_dirs", "remove_media_dirs", "remove_online_dirs", "remove_files")
        for record in actions[group]
    )
    allocated = sum(
        record["allocated_bytes"]
        for group in ("remove_weekly_dirs", "remove_media_dirs", "remove_online_dirs", "remove_files")
        for record in actions[group]
    )
    return {
        "counts": manifest["counts"],
        "baseline_mismatches": manifest["baseline_mismatches"],
        "delete_logical_bytes": logical,
        "delete_allocated_bytes": allocated,
        "requeue_codes": actions["requeue_codes"],
        "preserved_active_codes": manifest["preserved"]["active_codes"],
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-path", default=os.environ.get("SAVE_PATH", "/data"))
    parser.add_argument("--db-dir", default=os.path.dirname(os.environ.get("DB_PATH", "/db/downloaded.db")))
    parser.add_argument("--cfg-path", default=os.environ.get("CONFIG_PATH", "/app/cfg/configs.json"))
    parser.add_argument("--log-dir", default=os.environ.get("LOG_DIR", "/app/logs"))
    parser.add_argument("--manifest", help="write a dry-run manifest to this path")
    parser.add_argument("--apply", help="apply an existing manifest")
    return parser.parse_args()


def main():
    args = parse_args()
    qb_client = QBClient()
    if args.apply:
        with open(args.apply, encoding="utf-8") as handle:
            manifest = json.load(handle)
        result = apply_manifest(manifest, qb_client)
        result_path = args.apply + ".result.json"
        atomic_json(result_path, result)
        print(json.dumps({"result": result_path, **summary(manifest)}, ensure_ascii=False, indent=2))
        return

    manifest = build_manifest(
        args.save_path,
        args.db_dir,
        args.cfg_path,
        args.log_dir,
        qb_client.torrents(),
    )
    path = args.manifest or os.path.join(
        args.db_dir,
        "maintenance",
        "manifests",
        f"storage-cleanup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
    )
    atomic_json(path, manifest)
    print(json.dumps({"manifest": path, **summary(manifest)}, ensure_ascii=False, indent=2))
    if manifest["baseline_mismatches"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
