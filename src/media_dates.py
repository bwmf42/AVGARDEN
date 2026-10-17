"""Keep media-directory dates stable without changing video-file timestamps.

The NAS SMB share synthesizes creation time from POSIX timestamps. A persisted
anchor plus restoring both directory atime/mtime keeps that value stable after
metadata writes and Chinese merges. Release-date anchors are explicitly labelled.
"""
import functools
import json
import logging
import os
import stat
import time
from contextlib import contextmanager

from weekly_store import atomic_write_json, json_update_lock


def registry_path():
    return os.environ.get("MEDIA_DATES_PATH", "/db/media_directory_dates.json")


def _load():
    try:
        with open(registry_path(), encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return {"version": 1, "entries": {}}
    if value.get("version") != 1 or not isinstance(value.get("entries"), dict):
        raise ValueError("Invalid media-date registry")
    return value


def _directory(root, folder):
    if not folder or folder in (".", "..") or os.path.basename(folder) != folder or folder.startswith(("_", ".")):
        return None
    root = os.path.realpath(root)
    path = os.path.join(root, folder)
    if os.path.islink(path):
        return None
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return (path, info) if stat.S_ISDIR(info.st_mode) else None


def register_download(root, folder, code, timestamp_ns=None):
    """Record a first verified local completion; never replace historical anchors."""
    resolved = _directory(root, folder)
    if not resolved:
        return
    _, info = resolved
    with json_update_lock(registry_path()):
        store = _load()
        if folder not in store["entries"]:
            store["entries"][folder] = {
                "code": code,
                "timestamp_ns": timestamp_ns if timestamp_ns is not None else time.time_ns(),
                "basis": "download_completed",
                "root": os.path.realpath(root),
                "device": info.st_dev,
                "inode": info.st_ino,
            }
            atomic_write_json(registry_path(), store)


def restore_registered(root, folders=None):
    """Restore only the same registered directory inode, never its children."""
    root = os.path.realpath(root)
    entries = _load()["entries"]
    changed = []
    for folder in folders if folders is not None else entries:
        entry = entries.get(folder)
        if not entry or entry.get("root") != root:
            continue
        resolved = _directory(root, folder)
        if not resolved:
            continue
        path, info = resolved
        if (info.st_dev, info.st_ino) != (entry.get("device"), entry.get("inode")):
            logging.warning("Media-date inode changed, leaving directory untouched: %s", folder)
            continue
        timestamp = entry.get("timestamp_ns")
        if not isinstance(timestamp, int) or timestamp <= 0:
            raise ValueError("Invalid media-date anchor")
        # Use a directory descriptor so a concurrent rename/symlink replacement
        # cannot redirect utime to a different object after validation.
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                continue
            if current.st_mtime_ns != timestamp or current.st_atime_ns < timestamp:
                os.utime(fd, ns=(timestamp, timestamp))
                changed.append(folder)
        finally:
            os.close(fd)
    return changed


@contextmanager
def preserve_directory(path):
    """Protect an existing folder during scraping, including failure paths."""
    path = os.path.abspath(path)
    root, folder = os.path.split(path)
    resolved = _directory(root, folder)
    before = resolved[1] if resolved else None
    try:
        yield
    finally:
        try:
            restored = restore_registered(root, [folder])
            current = _directory(root, folder)
            if not restored and before and current:
                info = current[1]
                if (info.st_dev, info.st_ino) == (before.st_dev, before.st_ino):
                    # A registered anchor already matching its target needs no
                    # fallback to the newer pre-scrape snapshot.
                    entry = _load()["entries"].get(folder)
                    if not entry:
                        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns), follow_symlinks=False)
        except Exception:
            logging.exception("Could not preserve media directory date: %s", path)


def preserve_library_dates(function):
    """Restore registered library dates after the merge pass, even on failure."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        finally:
            try:
                restore_registered(function.__globals__.get("SAVE_PATH", "/data"))
            except Exception:
                logging.exception("Could not restore media directory dates after merge")
    return wrapped
