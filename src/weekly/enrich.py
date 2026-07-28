"""SOAV-style weekly item enrichment: exact metadata + artwork download.

Metadata: MGS with genres, then exact DMM, then exact javdatabase fallback.
Images: artwork module (javdatabase → MGS → DMM → forum → existing URLs).
"""
from __future__ import annotations

import os
from typing import Optional

from . import actresses as actress_util
from . import dmm, genre_zh, javbus, javdatabase, mgs


def set_proxy(proxy):
    mgs.set_proxy(proxy)
    dmm.set_proxy(proxy)
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


def _merge_actresses(base, extra):
    """Merge actress lists, drop placeholders like ----."""
    return actress_util.clean_actresses(_merge_unique(base, extra))


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
        item["actresses"] = _merge_actresses(before, meta["actresses"])
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

    if changed:
        item["metaSource"] = "mgs"
    return changed


def apply_javbus_meta(item: dict, detail: dict) -> bool:
    """Retained for an explicit future fallback; not in the active source chain."""
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
            item[key] = _merge_actresses(before, detail[key])
            if item[key] != before:
                changed = True

    if detail.get("genres"):
        # Still run through genre_zh (memory + map) so leftover JP becomes ZH
        before = list(item.get("genres") or [])
        item["genres"] = _merge_unique(
            before, genre_zh.translate_genres(detail["genres"], persist=False)
        )
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


def apply_dmm_meta(item: dict, meta: dict) -> bool:
    """Fill only empty metadata fields from an exact DMM product."""
    if not meta:
        return False
    changed = False

    if meta.get("actresses"):
        before = list(item.get("actresses") or [])
        merged = _merge_actresses(before, meta["actresses"])
        # only fill when empty or previous was junk
        if not actress_util.clean_actresses(before) and merged:
            item["actresses"] = merged
            changed = True
        elif merged and before != merged and not actress_util.clean_actresses(before):
            item["actresses"] = merged
            changed = True
    if meta.get("genres") and not item.get("genres"):
        item["genres"] = genre_zh.translate_genres(meta["genres"])
        changed = True
    if meta.get("duration") and not item.get("duration"):
        item["duration"] = meta["duration"]
        changed = True
    if meta.get("releaseDate"):
        # Forum list dates are post dates, not official product release dates.
        if not item.get("releaseDate") or item.get("source", "").startswith("plwt"):
            if item.get("releaseDate") != meta["releaseDate"]:
                item["releaseDate"] = meta["releaseDate"]
                changed = True

    if changed:
        current = item.get("metaSource") or ""
        item["metaSource"] = "mgs+dmm" if current == "mgs" else "dmm"
    return changed


def apply_javdatabase_meta(item: dict, meta: dict) -> bool:
    """Final exact-page fallback after both MGS and DMM have no metadata."""
    if not meta:
        return False
    changed = False
    if meta.get("actresses"):
        before = list(item.get("actresses") or [])
        if not actress_util.clean_actresses(before):
            merged = actress_util.clean_actresses(meta["actresses"])
            if merged:
                item["actresses"] = merged
                changed = True
    if meta.get("genres") and not item.get("genres"):
        item["genres"] = genre_zh.translate_genres(meta["genres"])
        changed = True
    if meta.get("duration") and not item.get("duration"):
        item["duration"] = meta["duration"]
        changed = True
    if meta.get("releaseDate") and not item.get("releaseDate"):
        item["releaseDate"] = meta["releaseDate"]
        changed = True
    if changed:
        current = item.get("metaSource") or ""
        item["metaSource"] = (
            "mgs+javdatabase" if current == "mgs" else "javdatabase"
        )
    return changed


def enrich_item(
    item: dict,
    save_dir: Optional[str] = None,
    proxy=None,
    download_images: bool = True,
    force_images: bool = False,
) -> dict:
    """Fill SOAV-style fields on item in place.

    Order: MGS detail → exact DMM/JAV Database gaps → artwork.
    """
    if proxy is not None:
        set_proxy(proxy)

    avid = (item.get("id") or item.get("avid") or "").strip().upper()
    if not avid:
        return item
    item["id"] = avid

    skip_mgs = os.environ.get("ARTWORK_SKIP_MGS", "").strip().lower() in ("1", "true", "yes", "on")

    # 1) MGS metadata only (genres/actresses/duration/date) — not images.
    mgs_has_genres = False
    if not skip_mgs:
        try:
            meta = mgs.fetch_detail(avid)
            if meta:
                apply_mgs_meta(item, meta)
                mgs_has_genres = bool(meta.get("genres"))
        except Exception as e:
            print(f"[Enrich] MGS {avid}: {e}")

    # 2) DMM is a whole-source fallback. Never merge DMM tags when MGS has tags.
    if not mgs_has_genres:
        dmm_meta = None
        javdatabase_meta = None
        try:
            dmm_meta = dmm.fetch_metadata(avid)
        except Exception as e:
            print(f"[Enrich] DMM {avid}: {e}")
        if not dmm_meta:
            try:
                javdatabase_meta = javdatabase.fetch_detail(avid)
                cid = (javdatabase_meta or {}).get("cid") or ""
                if cid:
                    dmm_meta = dmm.fetch_digital_metadata_candidates(
                        avid, [cid], page=(javdatabase_meta or {}).get("page") or ""
                    )
            except Exception as e:
                print(f"[Enrich] JAV Database {avid}: {e}")
        if dmm_meta:
            apply_dmm_meta(item, dmm_meta)
        elif javdatabase_meta:
            apply_javdatabase_meta(item, javdatabase_meta)

    # 3) Download images with the independent established artwork source order.
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

    # Always normalize genres via static map + persistent memory (no per-scrape AI)
    genre_zh.normalize_item_genres(item)

    # Drop ---- placeholders; fall back to trailing names on JP title
    actress_util.ensure_actresses(item)

    return item


def needs_enrich(item: dict) -> bool:
    """True if missing core SOAV fields."""
    if not actress_util.clean_actresses(item.get("actresses") or []):
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
