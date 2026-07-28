import re

from video_id import local_video_id_aliases, normalize_video_id


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

    target = normalize_video_id(video_id) or str(video_id or "").upper().strip()
    target_aliases = set(local_video_id_aliases(target))
    if not target_aliases:
        target_aliases = {target} if target else set()
    if not target_aliases:
        return False
    boundaries = [
        re.compile(
            r'(?:^|[/\\\s\-_.,\[\](){}+@])'
            + re.escape(alias)
            + r'(?:[/\\\s\-_.,\[\](){}+@]|$)'
        )
        for alias in target_aliases
    ]

    for torrent in torrents:
        state = str(torrent.get("state", ""))
        if state not in ACTIVE_QB_STATES and state not in DONE_QB_STATES:
            continue
        torrent_aliases = set()
        for tag in str(torrent.get("tags") or "").split(","):
            torrent_aliases.update(local_video_id_aliases(tag.strip()))
        matched = bool(target_aliases.intersection(torrent_aliases))
        for field in ("name", "content_path", "save_path"):
            value = str(torrent.get(field) or "").upper()
            torrent_aliases = set(local_video_id_aliases(value))
            if target_aliases.intersection(torrent_aliases) or any(
                boundary.search(value) for boundary in boundaries
            ):
                matched = True
                break
        if not matched:
            continue
        if state in ACTIVE_QB_STATES:
            return True
        if completed_validator is not None and completed_validator(target, torrent):
            return True
    return False
