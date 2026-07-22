"""DMM/FANZA CDN artwork probe (fallback when MGS has no product).

Builds common digital/mono cid patterns and probes package + sample stills
on pics.dmm.com / pics.dmm.co.jp. Rejects tiny / NOW PRINTING placeholders.
"""
import hashlib
import re
import struct

import os

from curl_cffi import requests

PROXY = os.environ.get("PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/*,*/*;q=0.8",
    "Referer": "https://www.dmm.co.jp/",
    "Cookie": "age_check_done=1",
}

# Minimum dimensions/bytes to treat a CDN response as a real cover/sample.
_MIN_BYTES = 8000
_MIN_SHORT = 200
_MIN_LONG = 300
_MAX_SAMPLE_PROBE = 12
# DMM generic "no package / NOW PRINTING" (also returned for missing cids).
_PLACEHOLDER_MD5 = {
    "8c6455760bf9c0c487142280fcef1877",  # 19378 bytes, ~590x800
}
_PLACEHOLDER_SIZES = {19378, 2732, 2588, 3424}


def set_proxy(proxy):
    global PROXY
    PROXY = proxy or None


def _proxies():
    p = PROXY or os.environ.get("PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    return {"http": p, "https": p} if p else None


def _norm_code(code):
    return (code or "").strip().upper()


def _jpg_dim(data):
    if not data or data[:2] != b"\xff\xd8" or len(data) < 10:
        return None
    i = 2
    end = min(len(data), 65536)
    while i < end - 8:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        if marker == 0xD9:
            break
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > len(data):
            break
        seglen = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + seglen
    return None


def is_placeholder_image(data) -> bool:
    """True for DMM NOW PRINTING / missing-cid stubs."""
    if not data:
        return True
    if len(data) in _PLACEHOLDER_SIZES:
        return True
    digest = hashlib.md5(data).hexdigest()
    if digest in _PLACEHOLDER_MD5:
        return True
    return False


def is_real_image(data):
    if not data or len(data) < _MIN_BYTES:
        return False
    if is_placeholder_image(data):
        return False
    dim = _jpg_dim(data)
    if not dim:
        return False
    w, h = dim
    # Real package covers are usually wider than 600 on the long side and >25KB
    if len(data) < 25000 and max(w, h) <= 600:
        return False
    return min(w, h) >= _MIN_SHORT and max(w, h) >= _MIN_LONG


def cid_candidates(code):
    """Generate likely DMM digital/mono content ids for a dashed code."""
    code = _norm_code(code)
    if not code or code.startswith("FC2"):
        return []
    cands = []

    m = re.fullmatch(r"(\d{3})([A-Z]{2,10})-(\d{2,5})", code)
    if m:
        num, maker, n = m.group(1), m.group(2).lower(), m.group(3)
        cands += [
            f"{num}{maker}{int(n):05d}",
            f"{maker}{int(n):05d}",
            f"1{maker}{int(n):05d}",
        ]

    m = re.fullmatch(r"([A-Z0-9]*[A-Z][A-Z0-9]*)-(\d{2,5})", code)
    if m:
        maker, n = m.group(1).lower(), m.group(2)
        ni = int(n)
        cands += [
            f"{maker}{ni:05d}",
            f"{maker}{n.zfill(5)}",
            f"{maker}{ni:03d}",
            f"1{maker}{ni:05d}",
            f"1{maker}{ni}",
            f"118{maker}{ni}",
            f"118{maker}{ni:03d}",
            f"118{maker}{ni}r",
            f"{maker}{ni}",
        ]

    out, seen = [], set()
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _cover_urls(cid):
    return [
        f"https://pics.dmm.com/digital/video/{cid}/{cid}pl.jpg",
        f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}pl.jpg",
        f"https://pics.dmm.co.jp/mono/movie/adult/{cid}/{cid}pl.jpg",
        f"https://pics.dmm.co.jp/mono/movie/{cid}/{cid}pl.jpg",
        f"https://awsimgsrc.dmm.com/pics_dig/digital/video/{cid}/{cid}pl.jpg",
    ]


def _sample_urls(cid, index):
    return [
        f"https://pics.dmm.com/digital/video/{cid}/{cid}jp-{index}.jpg",
        f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}jp-{index}.jpg",
        f"https://awsimgsrc.dmm.com/pics_dig/digital/video/{cid}/{cid}jp-{index}.jpg",
    ]


def _fetch_bytes(url, timeout=12):
    try:
        r = requests.get(
            url,
            proxies=_proxies(),
            headers=HEADERS,
            impersonate="chrome110",
            timeout=timeout,
        )
        if r.status_code < 400 and r.content:
            return r.content
    except Exception:
        return None
    return None


def _first_real(urls):
    for url in urls:
        data = _fetch_bytes(url)
        if data and is_real_image(data):
            return url, data
    return None, None


def probe_cid(cid, samples=True):
    cover_url, _ = _first_real(_cover_urls(cid))
    # Wrong cids return placeholder covers; do not also burn N sample probes.
    if not cover_url:
        return None
    sample_list = []
    if samples:
        for i in range(1, _MAX_SAMPLE_PROBE + 1):
            url, data = _first_real(_sample_urls(cid, i))
            if not url:
                if sample_list and i > len(sample_list) + 2:
                    break
                continue
            sample_list.append(url)
    return {
        "cid": cid,
        "cover": cover_url or "",
        "samples": sample_list,
    }


def fetch_cover_only(code):
    """Fast path: first working cover URL only (no sample jp-N probes)."""
    code = _norm_code(code)
    for cid in cid_candidates(code):
        cover_url, data = _first_real(_cover_urls(cid))
        if cover_url and data:
            print(f"[DMM] {code}: cid={cid} cover-only yes")
            return {
                "source": "dmm",
                "page": "",
                "cover": cover_url,
                "samples": [],
                "cid": cid,
            }
    return None


def fetch_artwork(code, samples=True):
    """Probe DMM CDN for cover/samples. Returns dict or None.

    samples=False: cover only (much faster for bulk backfill).
    """
    if not samples:
        return fetch_cover_only(code)
    code = _norm_code(code)
    cids = cid_candidates(code)
    if not cids:
        return None
    for cid in cids:
        hit = probe_cid(cid, samples=True)
        if hit and (hit.get("cover") or hit.get("samples")):
            print(
                f"[DMM] {code}: cid={cid} cover={'yes' if hit.get('cover') else 'no'} "
                f"samples={len(hit.get('samples') or [])}"
            )
            return {
                "source": "dmm",
                "page": "",
                "cover": hit.get("cover") or "",
                "samples": hit.get("samples") or [],
                "cid": cid,
            }
    return None
