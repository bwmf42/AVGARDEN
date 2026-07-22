"""javdatabase.com artwork: cover + sample stills by DVD code.

URL pattern: https://www.javdatabase.com/movies/{code-lower}/
No age cookie required. Cloudflare scripts present but do not block HTML (as of 2026-07).
"""
from __future__ import annotations

import os
import re
import time

from curl_cffi import requests

# Prefer explicit set_proxy(); else inherit container PROXY (NAS cannot reach site direct).
PROXY = os.environ.get("PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.javdatabase.com/",
}

_BASE = "https://www.javdatabase.com"
_LAST_FETCH = 0.0


def set_proxy(proxy):
    global PROXY
    PROXY = proxy or None


def _proxies():
    p = PROXY or os.environ.get("PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    return {"http": p, "https": p} if p else None


def _norm_code(code: str) -> str:
    return (code or "").strip().upper()


def slug_for(code: str) -> str:
    """DVD code → path segment (TENN-049 → tenn-049)."""
    return _norm_code(code).lower()


def _delay():
    """Polite gap between requests (env JAVDATABASE_DELAY seconds, default 0.4)."""
    global _LAST_FETCH
    raw = os.environ.get("JAVDATABASE_DELAY", "0.4").strip()
    try:
        delay = float(raw) if raw else 0.0
    except ValueError:
        delay = 0.4
    if delay <= 0:
        return
    now = time.time()
    wait = delay - (now - _LAST_FETCH)
    if wait > 0:
        time.sleep(wait)
    _LAST_FETCH = time.time()


def parse_artwork(html: str, code: str = "") -> dict | None:
    """Parse movie detail HTML into cover + samples. Pure function for tests."""
    if not html or len(html) < 500:
        return None
    low = html.lower()
    if "page not found" in low and "jav database" in low:
        # 404 template still long; require missing movie markers
        if re.search(r"<title>\s*Page Not Found", html, re.I):
            return None

    # Cover: prefer DMM pl.jpg on page, then og:image, then self-hosted full cover
    pl = re.findall(
        r'https?://(?:pics\.dmm\.co\.jp|pics\.dmm\.com)/digital/video/[^"\'\s<>]+pl\.jpg',
        html,
        re.I,
    )
    og = re.search(
        r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
        html,
        re.I,
    )
    hosted = re.findall(
        r'https?://www\.javdatabase\.com/covers/full/[^"\'\s<>]+',
        html,
        re.I,
    )

    cover = ""
    if pl:
        cover = pl[0]
    elif og:
        cover = og.group(1).strip()
    elif hosted:
        cover = hosted[0]

    samples = re.findall(
        r'https?://(?:pics\.dmm\.co\.jp|pics\.dmm\.com)/digital/video/[^"\'\s<>]+jp-\d+\.jpg',
        html,
        re.I,
    )
    # de-dupe preserve order; sort by jp-N when same cid
    seen = set()
    sample_list = []
    for u in samples:
        if u not in seen:
            seen.add(u)
            sample_list.append(u)

    def _jp_key(u: str):
        m = re.search(r"jp-(\d+)\.jpg", u, re.I)
        return int(m.group(1)) if m else 0

    sample_list.sort(key=_jp_key)

    cid_m = re.search(
        r"<b>\s*Content\s*ID\s*:\s*</b>\s*([a-zA-Z0-9_]+)",
        html,
        re.I,
    )
    cid = cid_m.group(1).strip() if cid_m else ""

    if not cover and not sample_list:
        return None

    return {
        "source": "javdatabase",
        "page": f"{_BASE}/movies/{slug_for(code)}/" if code else "",
        "cover": cover or "",
        "samples": sample_list,
        "cid": cid,
    }


def fetch_page(code: str, timeout: int = 15) -> str | None:
    code = _norm_code(code)
    if not code or code.startswith("FC2"):
        return None
    slug = slug_for(code)
    url = f"{_BASE}/movies/{slug}/"
    _delay()
    try:
        r = requests.get(
            url,
            proxies=_proxies(),
            headers=HEADERS,
            impersonate="chrome110",
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code == 404:
            return None
        if r.status_code >= 400 or not r.text:
            return None
        # real 404 template
        if re.search(r"<title>\s*Page Not Found", r.text, re.I):
            return None
        return r.text
    except Exception as e:
        print(f"[javdatabase] fetch {code}: {e}")
        return None


def fetch_artwork(code: str) -> dict | None:
    """Cover + samples for a DVD code, or None if missing."""
    code = _norm_code(code)
    if not code:
        return None
    html = fetch_page(code)
    if not html:
        return None
    art = parse_artwork(html, code)
    if not art:
        return None
    print(
        f"[javdatabase] {code}: cover={'yes' if art.get('cover') else 'no'} "
        f"samples={len(art.get('samples') or [])} cid={art.get('cid') or '-'}"
    )
    return art
