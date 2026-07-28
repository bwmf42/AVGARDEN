import os
import re


MAIN_VIDEO_MIN_SIZE = 100 * 1024 * 1024
MAIN_VIDEO_MIN_ALLOCATED_PERCENT = 95

_MULTIPART_SUFFIX = re.compile(r"^(.*?)[-_. ](?:CD|PART)?([1-9])$", re.IGNORECASE)


def has_sufficient_allocated_bytes(size, allocated):
    return size <= 0 or allocated * 100 >= size * MAIN_VIDEO_MIN_ALLOCATED_PERCENT


def has_sufficient_allocation(stat_result):
    blocks = getattr(stat_result, "st_blocks", None)
    if blocks is None:
        return True
    return has_sufficient_allocated_bytes(stat_result.st_size, blocks * 512)


def _candidate(path):
    try:
        if os.path.islink(path):
            return None
        stat_result = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    if not os.path.isfile(path) or not path.lower().endswith(".mp4"):
        return None
    if stat_result.st_size < MAIN_VIDEO_MIN_SIZE or not has_sufficient_allocation(stat_result):
        return None

    stem = os.path.splitext(os.path.basename(path))[0]
    match = _MULTIPART_SUFFIX.match(stem)
    return {
        "path": path,
        "size": stat_result.st_size,
        "part_group": match.group(1).upper() if match else "",
        "part": int(match.group(2)) if match else 0,
    }


def collect_main_video_candidates(path):
    if os.path.isfile(path):
        candidate = _candidate(path)
        return [candidate] if candidate else []
    if not os.path.isdir(path):
        return []

    candidates = []
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            candidate = _candidate(os.path.join(root, name))
            if candidate:
                candidates.append(candidate)
    return candidates


def choose_main_video_candidate(candidates):
    if not candidates:
        return None

    parts_by_group = {}
    for candidate in candidates:
        group = candidate.get("part_group") or ""
        part = int(candidate.get("part") or 0)
        if group and part:
            parts_by_group.setdefault(group, set()).add(part)

    part_one = [
        candidate
        for candidate in candidates
        if int(candidate.get("part") or 0) == 1
        and len(parts_by_group.get(candidate.get("part_group") or "", ())) > 1
    ]
    eligible = part_one or candidates
    return max(eligible, key=lambda item: (int(item.get("size") or 0), str(item.get("path") or "")))


def find_main_video(path):
    selected = choose_main_video_candidate(collect_main_video_candidates(path))
    return selected["path"] if selected else None
