import os

from main_video import MAIN_VIDEO_MIN_SIZE


SUPPORTED_VIDEO_EXTENSIONS = (".mp4",)


def select_strict_largest_video(files):
    """Select exactly one playable video from a qB torrent file list."""
    candidates = []
    for item in files if isinstance(files, list) else []:
        name = str(item.get("name") or "")
        size = int(item.get("size") or 0)
        index = item.get("index")
        if index is None:
            continue
        if os.path.splitext(name)[1].lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            continue
        if size < MAIN_VIDEO_MIN_SIZE:
            continue
        candidates.append({
            "index": int(index),
            "name": name,
            "size": size,
            "progress": float(item.get("progress") or 0),
        })
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["size"], item["name"]))


def strict_priority_plan(files):
    """Return the selected video and every other file index to disable."""
    selected = select_strict_largest_video(files)
    if not selected:
        return None
    disabled = []
    for item in files:
        index = item.get("index")
        if index is None or int(index) == selected["index"]:
            continue
        disabled.append(int(index))
    return {
        "selected": selected,
        "disabled": sorted(disabled),
    }
