import json
import os
import tempfile
from contextlib import contextmanager


try:
    import fcntl
except ImportError:  # pragma: no cover - production runs on Linux
    fcntl = None


@contextmanager
def _locked(path):
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_unlocked(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]


def _write_unlocked(path, items):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            for item in items:
                file.write(str(item).strip() + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _write_json_unlocked(path, value):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def read_json(path, default):
    with _locked(path):
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, ValueError):
            return default


def write_json(path, value):
    with _locked(path):
        _write_json_unlocked(path, value)


def write_queue(path, items):
    with _locked(path):
        _write_unlocked(path, items)


def update_json(path, default, updater):
    with _locked(path):
        value = default
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    value = json.load(file)
            except (OSError, ValueError):
                value = default
        updated = updater(value)
        _write_json_unlocked(path, updated)
        return updated


def read_queue(path):
    with _locked(path):
        return _read_unlocked(path)


def append_unique(path, item):
    value = str(item).strip()
    if not value:
        return False
    with _locked(path):
        items = _read_unlocked(path)
        if value.upper() in {existing.upper() for existing in items}:
            return False
        items.append(value)
        _write_unlocked(path, items)
        return True


def normalize_download_target(target, default="qb"):
    value = str(target or default).strip().lower()
    if value in ("115", "p115"):
        return "115"
    if value in ("qb", "qbit", "qbittorrent", ""):
        return "qb"
    return None


def set_download_target(path, code, target):
    """Store per-code download target (qb|115) in download_targets.json."""
    code = str(code or "").strip()
    target = normalize_download_target(target)
    if not code or not target:
        return False

    def updater(data):
        if not isinstance(data, dict):
            data = {}
        # Drop case-variant keys for the same code
        upper = code.upper()
        for key in list(data.keys()):
            if str(key).upper() == upper:
                del data[key]
        data[code] = target
        return data

    update_json(path, {}, updater)
    return True


def get_download_target(path, code, default="qb"):
    code = str(code or "").strip()
    if not code:
        return default
    data = read_json(path, {})
    if not isinstance(data, dict):
        return default
    upper = code.upper()
    for key, value in data.items():
        if str(key).upper() == upper:
            normalized = normalize_download_target(value, default=default)
            return normalized or default
    return default


def clear_download_target(path, code):
    code = str(code or "").strip()
    if not code:
        return

    def updater(data):
        if not isinstance(data, dict):
            return {}
        upper = code.upper()
        for key in list(data.keys()):
            if str(key).upper() == upper:
                del data[key]
        return data

    update_json(path, {}, updater)


def append_many_unique(path, values):
    added = []
    with _locked(path):
        items = _read_unlocked(path)
        existing = {item.upper() for item in items}
        for value in values:
            value = str(value).strip()
            if value and value.upper() not in existing:
                items.append(value)
                existing.add(value.upper())
                added.append(value)
        if added:
            _write_unlocked(path, items)
    return added


def remove_code(path, code):
    target = str(code).strip().upper()
    with _locked(path):
        items = _read_unlocked(path)
        filtered = [item for item in items if item.upper() != target]
        if len(filtered) == len(items):
            return False
        _write_unlocked(path, filtered)
        return True


def pop_first(path):
    with _locked(path):
        items = _read_unlocked(path)
        if not items:
            return None
        first = items[0]
        _write_unlocked(path, items[1:])
        return first
