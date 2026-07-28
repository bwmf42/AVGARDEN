import re


ACTIVE_QB_STATES = frozenset({
    "downloading", "stalledDL", "forcedDL", "metaDL", "queuedDL",
    "checkingDL", "allocating", "moving", "checkingResumeData",
})
DONE_QB_STATES = frozenset({
    "queuedUP", "uploading", "stalledUP", "pausedUP", "forcedUP",
})


def has_matching_qb_task(torrents, video_id, completed_validator=None):
    """Return whether an active or disk-backed completed qB task matches."""
    if not isinstance(torrents, list):
        return False

    target = str(video_id or "").upper().strip()
    if not target:
        return False
    boundary = re.compile(
        r'(?:^|[/\\\s\-_.,\[\](){}+@])'
        + re.escape(target)
        + r'(?:[/\\\s\-_.,\[\](){}+@]|$)'
    )

    for torrent in torrents:
        state = str(torrent.get("state", ""))
        if state not in ACTIVE_QB_STATES and state not in DONE_QB_STATES:
            continue
        tags = {
            tag.strip().upper()
            for tag in str(torrent.get("tags") or "").split(",")
            if tag.strip()
        }
        matched = target in tags
        for field in ("name", "content_path", "save_path"):
            value = str(torrent.get(field) or "").upper()
            if value == target or boundary.search(value):
                matched = True
                break
        if not matched:
            continue
        if state in ACTIVE_QB_STATES:
            return True
        if completed_validator is not None and completed_validator(target, torrent):
            return True
    return False
