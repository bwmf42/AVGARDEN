"""SOAV-style weekly item enrichment: MGS/JavBus metadata + artwork download.

Metadata: MGS (tags/actresses/duration) → JavBus gaps.
Images: artwork module (javdatabase → DMM → existing URLs). MGS is not used for images.
"""
from __future__ import annotations

import os
from typing import Optional

from . import genre_zh, javbus, mgs


def set_proxy(proxy):
    mgs.set_proxy(proxy)
    javbus.set_proxy(proxy)
    try:
        from . import artwork

        artwork.set_proxy(proxy)
    except Exception:
        pass


def _as_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    return [s] if s else []


def _merge_unique(base, extra):
    out = list(base or [])
    seen = set(out)
    for x in extra or []:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def apply_mgs_meta(item: dict, meta: dict) -> bool:
    """Apply MGS detail fields onto item. Returns True if anything changed."""
    if not meta:
        return False
    changed = False
    avid = (item.get("id") or "").upper()

    if meta.get("title") and (not item.get("title") or item.get("title") == avid):
        item["title"] = meta["title"]
        changed = True

    if meta.get("actresses"):
        before = list(item.get("actresses") or [])
        item["actresses"] = _merge_unique(before, meta["actresses"])
        if item["actresses"] != before:
            changed = True

    if meta.get("genres"):
        # MGS ジャンル is Japanese → Chinese; do not re-translate JavBus tags
        before = list(item.get("genres") or [])
        zh = genre_zh.translate_genres(meta["genres"])
        item["genres"] = _merge_unique(zh, before)
        if item["genres"] != before:
            changed = True

    if meta.get("duration") and not item.get("duration"):
        item["duration"] = meta["duration"]
        changed = True

    if meta.get("releaseDate"):
        # Prefer MGS delivery date when missing or forum-only postDate style
        if not item.get("releaseDate") or item.get("source", "").startswith("plwt"):
            if item.get("releaseDate") != meta["releaseDate"]:
                item["releaseDate"] = meta["releaseDate"]
                changed = True

    if meta.get("maker"):
        item["maker"] = meta["maker"]
        changed = True
    if meta.get("series"):
        item["series"] = meta["series"]
        changed = True
    if meta.get("label"):
        item["label"] = meta["label"]
        changed = True

    # Images intentionally not applied from MGS (javdatabase/DMM via artwork).

    item["metaSource"] = "mgs"
    return changed


def apply_javbus_meta(item: dict, detail: dict) -> bool:
    if not detail:
        return False
    changed = False
    avid = (item.get("id") or "").upper()

    if detail.get("title") and (not item.get("title") or item.get("title") == avid):
        item["title"] = detail["title"]
        changed = True

    for key in ("actresses",):
        if detail.get(key):
            before = list(item.get(key) or [])
            item[key] = _merge_unique(before, detail[key])
            if item[key] != before:
                changed = True

    if detail.get("genres"):
        # JavBus genres are already Chinese (or site-native) — keep as-is, no JP map
        before = list(item.get("genres") or [])
        item["genres"] = _merge_unique(before, detail["genres"])
        if item["genres"] != before:
            changed = True

    if detail.get("duration") and not item.get("duration"):
        import re

        dur = str(detail["duration"]).strip()
        if "分" not in dur:
            m = re.search(r"(\d+)", dur)
            if m:
                dur = f"{m.group(1)}分钟"
        item["duration"] = dur
        changed = True

    if detail.get("releaseDate") and not item.get("releaseDate"):
        item["releaseDate"] = detail["releaseDate"]
        changed = True

    if detail.get("cover") and not item.get("cover"):
        item["cover"] = detail["cover"]
        changed = True

    if detail.get("fanarts"):
        if not item.get("remoteFanarts"):
            item["remoteFanarts"] = list(detail["fanarts"])
            changed = True
        if not item.get("fanarts"):
            item["fanarts"] = list(detail["fanarts"])
            changed = True

    return changed


def enrich_item(
    item: dict,
    save_dir: Optional[str] = None,
    proxy=None,
    download_images: bool = True,
    force_images: bool = False,
) -> dict:
    """Fill SOAV-style fields on item in place.

    Order: MGS detail (tags/meta) → JavBus gaps → artwork download
    (javdatabase → DMM → existing URLs).
    """
    if proxy is not None:
        set_proxy(proxy)

    avid = (item.get("id") or item.get("avid") or "").strip().upper()
    if not avid:
        return item
    item["id"] = avid

    skip_mgs = os.environ.get("ARTWORK_SKIP_MGS", "").strip().lower() in ("1", "true", "yes", "on")

    # 1) MGS metadata only (genres/actresses/duration/date) — not images
    if not skip_mgs:
        try:
            meta = mgs.fetch_detail(avid)
            if meta:
                apply_mgs_meta(item, meta)
        except Exception as e:
            print(f"[Enrich] MGS {avid}: {e}")

    # 2) JavBus for metadata gaps (and weak image URL fallback before download)
    need_jb = (
        not item.get("actresses")
        or not item.get("genres")
        or not item.get("duration")
        or not item.get("cover")
        or not item.get("fanarts")
    )
    if need_jb:
        try:
            html = javbus.fetch_page(avid)
            detail = javbus.parse_page(html) if html else {}
            apply_javbus_meta(item, detail)
        except Exception as e:
            print(f"[Enrich] JavBus {avid}: {e}")

    # 3) Download images: javdatabase → DMM → item/JavBus URLs
    if download_images and save_dir:
        from . import artwork

        artwork.set_proxy(proxy if proxy is not None else None)
        artwork.download_for_item(
            item,
            save_dir,
            force_cover=force_images,
            force_fanarts=force_images,
        )

    # defaults
    for k in ("actresses", "genres", "fanarts"):
        if not isinstance(item.get(k), list):
            item[k] = []
    for k in ("titleZh", "titleJp", "poster", "duration", "size", "magnet", "releaseDate"):
        item.setdefault(k, "")
    item.setdefault("hasChinese", False)
    item.setdefault("downloaded", False)
    if item.get("cover") and not item.get("poster"):
        item["poster"] = item["cover"]

    return item


def needs_enrich(item: dict) -> bool:
    """True if missing core SOAV fields."""
    if not item.get("actresses"):
        return True
    genres = item.get("genres") or []
    if not genres:
        return True
    # Only treat leftover Japanese kana as incomplete (MGS ジャンル not yet mapped)
    import re

    for g in genres:
        if re.search(r"[\u3040-\u30ff]", str(g)):
            return True
    if not item.get("duration"):
        return True
    if not item.get("releaseDate"):
        return True
    cover = str(item.get("cover") or "")
    if not cover or cover.startswith("http"):
        return True
    return False
