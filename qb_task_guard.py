import re

from video_id import local_video_id_aliases, normalize_video_id


ACTIVE_QB_STATES = frozenset({
    "downloading", "stalledDL", "forcedDL", "metaDL", "queuedDL",
    "pausedDL", "stoppedDL", "checkingDL", "allocating", "moving", "checkingResumeData",
})
DONE_QB_STATES = frozenset({
    "queuedUP", "uploading", "stalledUP", "pausedUP", "stoppedUP", "forcedUP",
})


def torrent_matches_video_id(torrent, video_id):
    """Match a torrent to a canonical video ID, including source suffixes."""
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

    torrent_aliases = set()
    for tag in str(torrent.get("tags") or "").split(","):
        torrent_aliases.update(local_video_id_aliases(tag.strip()))
    if target_aliases.intersection(torrent_aliases):
        return True
    for field in ("name", "content_path", "save_path"):
        value = str(torrent.get(field) or "").upper()
        torrent_aliases = set(local_video_id_aliases(value))
        if target_aliases.intersection(torrent_aliases) or any(
            boundary.search(value) for boundary in boundaries
        ):
            return True
    return False


def matching_qb_tasks(torrents, video_id, include_broken=False):
    if not isinstance(torrents, list):
        return []
    matches = []
    for torrent in torrents:
        state = str(torrent.get("state", ""))
        if not include_broken and state not in ACTIVE_QB_STATES and state not in DONE_QB_STATES:
            continue
        if torrent_matches_video_id(torrent, video_id):
            matches.append(torrent)
    return matches


def has_matching_qb_task(torrents, video_id, completed_validator=None):
    """Return whether an active or disk-backed completed qB task matches."""
    target = normalize_video_id(video_id) or str(video_id or "").upper().strip()
    for torrent in matching_qb_tasks(torrents, target):
        state = str(torrent.get("state", ""))
        if state in ACTIVE_QB_STATES:
            return True
        if completed_validator is not None and completed_validator(target, torrent):
            return True
    return False
