"""Artwork resolution: javdatabase -> MGS images -> DMM CDN -> caller URLs.

Primary cover/samples: javdatabase. MGS product images are a fast single-page
fallback (also used for tags via enrich). DMM multi-cid probe is last (slow).
"""
import os

from . import dmm, javbus, javdatabase, mgs


def set_proxy(proxy):
    javdatabase.set_proxy(proxy)
    dmm.set_proxy(proxy)
    javbus.set_proxy(proxy)
    mgs.set_proxy(proxy)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def resolve(code, proxy=None):
    """Resolve remote cover + sample URLs. javdatabase -> MGS -> DMM."""
    if proxy is not None:
        set_proxy(proxy)
    code = (code or "").strip().upper()
    if not code:
        return None
    skip_jdb = _env_flag("ARTWORK_SKIP_JAVDATABASE")
    skip_dmm = _env_flag("ARTWORK_SKIP_DMM")
    use_mgs_img = not _env_flag("ARTWORK_SKIP_MGS_IMAGES")

    if not skip_jdb:
        art = javdatabase.fetch_artwork(code)
        if art and art.get("cover") and art.get("samples"):
            return art
        if art and (art.get("cover") or art.get("samples")):
            # Partial: try MGS then DMM to fill the missing side
            if use_mgs_img:
                try:
                    mgs_art = mgs.fetch_artwork(code)
                except Exception:
                    mgs_art = None
                if mgs_art:
                    merged = dict(art)
                    if not merged.get("cover") and mgs_art.get("cover"):
                        merged["cover"] = mgs_art["cover"]
                    if not merged.get("samples") and mgs_art.get("samples"):
                        merged["samples"] = mgs_art["samples"]
                    if merged.get("cover") and merged.get("samples"):
                        merged["source"] = "javdatabase+mgs"
                        return merged
                    art = merged
            if not skip_dmm and art.get("cover") and not art.get("samples"):
                dmm_art = dmm.fetch_artwork(code, samples=True)
                if dmm_art and dmm_art.get("samples"):
                    merged = dict(art)
                    merged["samples"] = dmm_art["samples"]
                    merged["source"] = "javdatabase+dmm"
                    return merged
            if not skip_dmm and art.get("samples") and not art.get("cover"):
                dmm_art = dmm.fetch_artwork(code, samples=False)
                if dmm_art and dmm_art.get("cover"):
                    merged = dict(art)
                    merged["cover"] = dmm_art["cover"]
                    merged["source"] = "javdatabase+dmm"
                    return merged
            return art

    if use_mgs_img:
        try:
            art = mgs.fetch_artwork(code)
            if art and (art.get("cover") or art.get("samples")):
                return art
        except Exception as e:
            print(f"[artwork] MGS image {code}: {e}")

    if not skip_dmm:
        art = dmm.fetch_artwork(code)
        if art and (art.get("cover") or art.get("samples")):
            return art
    return None


def prefer_urls(code, cover="", fanarts=None, proxy=None):
    """Return (cover_url, sample_urls, source) preferring javdatabase/DMM over JavBus."""
    fanarts = list(fanarts or []) if isinstance(fanarts, list) else []
    art = resolve(code, proxy=proxy)
    if not art:
        return cover or "", fanarts, ""
    src = art.get("source") or ""
    out_cover = art.get("cover") or cover or ""
    out_samples = art.get("samples") or []
    if not out_samples:
        out_samples = fanarts
    return out_cover, out_samples, src


def _local_fanart_count(avid, save_dir):
    code = (avid or "").upper()
    folder = os.path.join(save_dir, code)
    if not os.path.isdir(folder):
        return 0
    n = 0
    prefix = f"{code}-fanart-"
    for name in os.listdir(folder):
        if name.startswith(prefix) and name.lower().endswith((".jpg", ".jpeg", ".webp", ".png")):
            path = os.path.join(folder, name)
            try:
                if os.path.getsize(path) > 3000:
                    n += 1
            except OSError:
                pass
    return n


def download_for_item(item, save_dir, force_cover=False, force_fanarts=False, limit=0, proxy=None):
    """Resolve javdatabase/DMM then download cover + fanarts into save_dir.

    Mutates item keys: cover, fanarts, remoteFanarts, artworkSource.
    Falls back to existing item cover/fanarts URLs when both sources miss.
    Does not re-download solid local files unless force_* or refresh needed.
    """
    if proxy is not None:
        set_proxy(proxy)
    avid = (item.get("id") or item.get("avid") or "").strip().upper()
    if not avid:
        return item

    existing_cover = item.get("cover") or ""
    existing_fanarts = item.get("remoteFanarts") if isinstance(item.get("remoteFanarts"), list) else None
    if existing_fanarts is None:
        existing_fanarts = item.get("fanarts") if isinstance(item.get("fanarts"), list) else []
    fallback_fanarts = [
        u for u in existing_fanarts
        if isinstance(u, str) and u and not u.startswith("/file/")
    ]

    cover_url, sample_urls, source = prefer_urls(
        avid,
        cover=existing_cover if isinstance(existing_cover, str) and existing_cover.startswith("http") else "",
        fanarts=fallback_fanarts,
    )
    if not cover_url and isinstance(existing_cover, str):
        cover_url = existing_cover
    if not sample_urls:
        sample_urls = fallback_fanarts

    if source:
        item["artworkSource"] = source

    need_cover = (
        force_cover
        or not existing_cover
        or (isinstance(existing_cover, str) and existing_cover.startswith("http"))
        or javbus.cover_needs_refresh(avid, save_dir)
    )
    if need_cover and cover_url:
        item["cover"] = javbus.download_cover(
            avid, cover_url, save_dir, force=force_cover or need_cover
        )
    elif cover_url and not item.get("cover"):
        item["cover"] = cover_url

    if sample_urls:
        item["remoteFanarts"] = sample_urls
        local_n = _local_fanart_count(avid, save_dir)
        fanarts_val = item.get("fanarts")
        need_fanarts = (
            force_fanarts
            or local_n == 0
            or not fanarts_val
            or (
                isinstance(fanarts_val, list)
                and fanarts_val
                and all(isinstance(u, str) and u.startswith("http") for u in fanarts_val)
            )
        )
        if need_fanarts:
            item["fanarts"] = javbus.download_fanarts(
                avid, sample_urls, save_dir, force=force_fanarts, limit=limit
            )
        elif not item.get("fanarts"):
            item["fanarts"] = sample_urls

    return item
