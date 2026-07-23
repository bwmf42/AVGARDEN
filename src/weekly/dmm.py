"""DMM/FANZA artwork lookup (fallback when MGS has no product).

Searches the header's all-category results for an exact product first, then
falls back to common cid patterns. Package and sample probes reject tiny /
NOW PRINTING placeholders.
"""
import hashlib
import html as html_lib
import re
import struct
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlparse

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
_ALL_SEARCH_URL = "https://www.dmm.co.jp/search/=/searchstr={}/limit=30/sort=rankprofile"
_GRAPHQL_URL = "https://api.video.dmm.co.jp/graphql"
_DIGITAL_FIELDS = """
id
floor
title
deliveryStartDate
duration
actresses { name }
amateurActress { name }
genres { name }
packageImage { largeUrl mediumUrl }
sampleImages { number imageUrl largeImageUrl }
makerContentId
"""
_DIGITAL_QUERY = (
    "query Content($id: ID!) { ppvContent(id: $id) {"
    + _DIGITAL_FIELDS
    + "} }"
)
_MONO_DETAIL_CID_RE = re.compile(r"/mono/dvd/-/detail/=/cid=([^/?#\"']+)", re.I)
_DETAIL_ROW_RE = re.compile(
    r"<td\b(?=[^>]*\bclass=[\"'][^\"']*\bnw\b[^\"']*[\"'])[^>]*>"
    r"(.*?)</td>\s*<td[^>]*>(.*?)</td>",
    re.I | re.S,
)
_PROMO_GENRE_RE = re.compile(r"セール|キャンペーン|対象商品|\d+％オフ|\d+%オフ", re.I)
_DIGITAL_DETAIL_CACHE = {}


class _AllSearchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current_href = ""
        self.results = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == "a":
            self.current_href = values.get("href") or ""
        elif tag.lower() == "img" and self.current_href:
            src = values.get("src") or ""
            if src:
                self.results.append((self.current_href, src))

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            self.current_href = ""


def set_proxy(proxy):
    global PROXY
    PROXY = proxy or None


def _proxies():
    p = PROXY or os.environ.get("PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    return {"http": p, "https": p} if p else None


def _norm_code(code):
    return (code or "").strip().upper()


def _strip_tags(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _cell_texts(value):
    links = [
        _strip_tags(raw)
        for raw in re.findall(r"<a[^>]*>(.*?)</a>", value or "", re.I | re.S)
    ]
    links = [text for text in links if text]
    if links:
        return links
    text = _strip_tags(value)
    return [text] if text else []


def _parse_detail_rows(value):
    rows = {}
    for match in _DETAIL_ROW_RE.finditer(value or ""):
        label = _strip_tags(match.group(1)).replace("：", "").replace(":", "").strip()
        texts = _cell_texts(match.group(2))
        if label and texts:
            rows[label] = texts
    return rows


def _parse_duration(value):
    match = re.search(r"(\d+)\s*(?:分|min|分钟|分鐘)", str(value or ""), re.I)
    return f"{int(match.group(1))}分钟" if match else ""


def _parse_date(value):
    match = re.search(r"(\d{4})[./年-](\d{1,2})[./月-](\d{1,2})", str(value or ""))
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def parse_metadata(value, code="", page="", cid=""):
    """Parse a classic DMM exact-product page into metadata fields."""
    rows = _parse_detail_rows(value)

    def first(labels):
        for label in labels:
            values = rows.get(label)
            if values:
                return values
        return []

    actresses = first(("出演者", "出演"))
    genres = [
        genre for genre in first(("ジャンル",))
        if not _PROMO_GENRE_RE.search(genre)
    ]
    duration = _parse_duration((first(("収録時間",)) or [""])[0])
    release_date = _parse_date((first(("発売日", "配信開始日", "商品発売日")) or [""])[0])
    if not actresses and not genres and not duration and not release_date:
        return None
    return {
        "source": "dmm",
        "page": page or "",
        "code": _norm_code(code),
        "cid": cid or "",
        "actresses": actresses,
        "genres": genres,
        "duration": duration,
        "releaseDate": release_date,
    }


def _digital_release_date(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone(timedelta(hours=9)))
        return parsed.date().isoformat()
    except ValueError:
        return _parse_date(text)


def _digital_duration(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return _parse_duration(value)
    return f"{seconds // 60}分钟" if seconds > 0 else ""


def parse_digital_metadata(payload, code="", page="", cid=""):
    """Parse the GraphQL response used by DMM's JavaScript amateur page."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    content = data.get("ppvContent") if isinstance(data, dict) else None
    if not isinstance(content, dict):
        return None

    expected_code = _norm_code(code)
    maker_code = _norm_code(content.get("makerContentId"))
    if expected_code and maker_code != expected_code:
        return None

    actresses = []
    for actress in content.get("actresses") or []:
        name = actress.get("name") if isinstance(actress, dict) else ""
        name = str(name or "").strip()
        if name and name not in actresses:
            actresses.append(name)
    amateur_actress = content.get("amateurActress")
    amateur_name = amateur_actress.get("name") if isinstance(amateur_actress, dict) else ""
    amateur_name = str(amateur_name or "").strip()
    if amateur_name and amateur_name not in actresses:
        actresses.append(amateur_name)
    genres = []
    for genre in content.get("genres") or []:
        name = genre.get("name") if isinstance(genre, dict) else ""
        name = str(name or "").strip()
        if name and not _PROMO_GENRE_RE.search(name) and name not in genres:
            genres.append(name)

    package = content.get("packageImage")
    package = package if isinstance(package, dict) else {}
    cover = package.get("largeUrl") or package.get("mediumUrl") or ""
    samples = []
    sample_rows = content.get("sampleImages") or []
    sample_rows = [row for row in sample_rows if isinstance(row, dict)]
    sample_rows.sort(key=lambda row: int(row.get("number") or 0))
    for row in sample_rows:
        url = row.get("largeImageUrl") or row.get("imageUrl") or ""
        if url and url not in samples:
            samples.append(url)

    return {
        "source": "dmm",
        "page": page or "",
        "code": expected_code,
        "cid": cid or str(content.get("id") or ""),
        "actresses": actresses,
        "genres": genres,
        "duration": _digital_duration(content.get("duration")),
        "releaseDate": _digital_release_date(content.get("deliveryStartDate")),
        "cover": cover,
        "samples": samples,
    }


def _digital_headers():
    headers = dict(HEADERS)
    headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": "https://video.dmm.co.jp/",
        "fanza-device": "BROWSER",
    })
    return headers


def _cache_digital(key, value):
    if len(_DIGITAL_DETAIL_CACHE) >= 256:
        _DIGITAL_DETAIL_CACHE.clear()
    _DIGITAL_DETAIL_CACHE[key] = value


def _fetch_digital_metadata(cid, code="", page=""):
    key = (str(cid or "").lower(), _norm_code(code))
    if key in _DIGITAL_DETAIL_CACHE:
        return _DIGITAL_DETAIL_CACHE[key]

    try:
        response = requests.post(
            _GRAPHQL_URL,
            json={
                "operationName": "Content",
                "query": _DIGITAL_QUERY,
                "variables": {"id": str(cid or "").lower()},
            },
            proxies=_proxies(),
            headers=_digital_headers(),
            impersonate="chrome110",
            timeout=20,
        )
        if response.status_code >= 400:
            return None
        meta = parse_digital_metadata(response.json(), code, page, cid)
        _cache_digital(key, meta)
        return meta
    except Exception:
        return None


def fetch_digital_metadata_candidates(code, cids, page=""):
    """Resolve several likely content IDs in one request, with exact code checks."""
    code = _norm_code(code)
    candidates = []
    for cid in cids or []:
        value = str(cid or "").strip().lower()
        if value and value not in candidates:
            candidates.append(value)
    if not code or not candidates:
        return None

    pending = []
    for cid in candidates:
        key = (cid, code)
        if key in _DIGITAL_DETAIL_CACHE:
            meta = _DIGITAL_DETAIL_CACHE[key]
            if meta:
                return meta
        else:
            pending.append(cid)
    if not pending:
        return None

    variables = {f"id{index}": cid for index, cid in enumerate(pending)}
    declarations = ", ".join(f"$id{index}: ID!" for index in range(len(pending)))
    selections = " ".join(
        f"c{index}: ppvContent(id: $id{index}) {{ {_DIGITAL_FIELDS} }}"
        for index in range(len(pending))
    )
    query = f"query CandidateContent({declarations}) {{ {selections} }}"
    try:
        response = requests.post(
            _GRAPHQL_URL,
            json={
                "operationName": "CandidateContent",
                "query": query,
                "variables": variables,
            },
            proxies=_proxies(),
            headers=_digital_headers(),
            impersonate="chrome110",
            timeout=20,
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        first = None
        for index, cid in enumerate(pending):
            content = data.get(f"c{index}")
            meta = parse_digital_metadata(
                {"data": {"ppvContent": content}}, code, page, cid
            )
            _cache_digital((cid, code), meta)
            if first is None and meta:
                first = meta
        return first
    except Exception:
        return None


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


def _detail_cid(url):
    match = _MONO_DETAIL_CID_RE.search(str(url or ""))
    return match.group(1).lower() if match else ""


def _cid_matches_code(cid, code):
    """Match a DMM cid to the searched display code without fuzzy titles."""
    code = _norm_code(code)
    match = re.fullmatch(r"([A-Z0-9]*[A-Z][A-Z0-9]*)-(\d{1,8})", code)
    if not match:
        return False
    maker = match.group(1).lower()
    number = str(int(match.group(2)))
    compact_cid = re.sub(r"[^a-z0-9]", "", str(cid or "").lower())
    return bool(re.search(rf"{re.escape(maker)}0*{re.escape(number)}[a-z]*$", compact_cid))


def _search_product(url, cover=""):
    cid = _detail_cid(url)
    if cid:
        return {"kind": "mono", "cid": cid, "page": str(url), "cover": cover or ""}

    parsed = urlparse(str(url or ""))
    if parsed.hostname != "video.dmm.co.jp" or not parsed.path.endswith("/content/"):
        return None
    content_id = (parse_qs(parsed.query).get("id") or [""])[0].lower()
    if not content_id:
        return None
    return {
        "kind": "digital",
        "cid": content_id,
        "page": str(url),
        "cover": cover or "",
    }


def parse_all_search_products(html, code, final_url=""):
    """Extract exact products and thumbnails from the header's all-category search."""
    candidates = []
    redirected = _search_product(final_url)
    if redirected:
        candidates.append(redirected)

    parser = _AllSearchParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass
    for href, cover in parser.results:
        product = _search_product(href, cover)
        if product:
            candidates.append(product)

    out, seen = [], set()
    for product in candidates:
        cid = product["cid"]
        key = (product["kind"], cid)
        if key not in seen and _cid_matches_code(cid, code):
            seen.add(key)
            out.append(product)
    return out


def search_all_products(code, with_status=False):
    """Use the header's all-category search to resolve exact DMM products."""
    code = _norm_code(code)
    if not code or code.startswith("FC2"):
        return ([], True) if with_status else []
    url = _ALL_SEARCH_URL.format(quote(code, safe=""))
    headers = dict(HEADERS)
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    try:
        response = requests.get(
            url,
            proxies=_proxies(),
            headers=headers,
            impersonate="chrome110",
            allow_redirects=True,
            timeout=15,
        )
        if response.status_code >= 400:
            return ([], False) if with_status else []
        if "お住まいの地域から" in response.text:
            return ([], False) if with_status else []
        products = parse_all_search_products(response.text, code, str(response.url))
        if products:
            summary = ",".join(f"{item['kind']}:{item['cid']}" for item in products)
            print(f"[DMM] {code}: all-category search={summary}")
        return (products, True) if with_status else products
    except Exception:
        return ([], False) if with_status else []


def _fetch_detail_html(url, timeout=20):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if not (
        host == "dmm.co.jp"
        or host.endswith(".dmm.co.jp")
        or host == "dmm.com"
        or host.endswith(".dmm.com")
    ):
        return None
    headers = dict(HEADERS)
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    try:
        response = requests.get(
            url,
            proxies=_proxies(),
            headers=headers,
            impersonate="chrome110",
            allow_redirects=True,
            timeout=timeout,
        )
        if response.status_code >= 400 or not response.text:
            return None
        return response.text
    except Exception:
        return None


def fetch_metadata(code):
    """Fetch metadata from exact search or verified GraphQL CID candidates."""
    code = _norm_code(code)
    if not code or code.startswith("FC2"):
        return None
    products = search_all_products(code)
    for product in products:
        page = product.get("page") or ""
        cid = product.get("cid") or ""
        if product.get("kind") == "digital":
            meta = _fetch_digital_metadata(cid, code, page)
        else:
            value = _fetch_detail_html(page)
            meta = parse_metadata(value or "", code, page, cid)
        if meta:
            print(
                f"[DMM] {code}: metadata genres={len(meta.get('genres') or [])} "
                f"act={len(meta.get('actresses') or [])} "
                f"dur={meta.get('duration') or '-'} date={meta.get('releaseDate') or '-'}"
            )
            return meta
    meta = fetch_digital_metadata_candidates(code, cid_candidates(code))
    if meta:
        print(
            f"[DMM] {code}: candidate cid={meta.get('cid') or '-'} "
            f"genres={len(meta.get('genres') or [])} "
            f"act={len(meta.get('actresses') or [])} "
            f"dur={meta.get('duration') or '-'} date={meta.get('releaseDate') or '-'}"
        )
        return meta
    return None


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


def _first_real(urls, timeout=12):
    for url in urls:
        if not url:
            continue
        data = _fetch_bytes(url, timeout=timeout)
        if data and is_real_image(data):
            return url, data
    return None, None


def _digital_artwork(detail, product=None, samples=False):
    product = product or {}
    detail = detail or {}
    cover_candidates = [
        url for url in (detail.get("cover") or "", product.get("cover") or "") if url
    ]
    cover_url, data = _first_real(cover_candidates)
    sample_urls = []
    if samples:
        for candidate in detail.get("samples") or []:
            sample_url, sample_data = _first_real([candidate])
            if sample_url and sample_data:
                sample_urls.append(sample_url)
    if not cover_url and not sample_urls:
        return None
    return {
        "source": "dmm",
        "page": product.get("page") or detail.get("page") or "",
        "cover": cover_url or "",
        "samples": sample_urls,
        "cid": product.get("cid") or detail.get("cid") or "",
    }


def _search_artwork(code, samples=False):
    products, search_ok = search_all_products(code, with_status=True)
    for product in products:
        cid = product["cid"]
        if product["kind"] == "mono":
            hit = probe_cid(cid, samples=samples)
            if hit:
                return {
                    "source": "dmm",
                    "page": product.get("page") or "",
                    "cover": hit.get("cover") or "",
                    "samples": hit.get("samples") or [],
                    "cid": cid,
                }, search_ok

        detail = (
            _fetch_digital_metadata(cid, code, product.get("page") or "")
            if samples else None
        )
        art = _digital_artwork(detail, product, samples=samples)
        if art:
            return art, search_ok

    detail = fetch_digital_metadata_candidates(code, cid_candidates(code))
    art = _digital_artwork(detail, samples=samples)
    if art:
        return art, search_ok
    return None, search_ok


def _fallback_cover_urls(cid):
    """Small fallback set used only when the all-category search is unavailable."""
    return [
        f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}pl.jpg",
        f"https://pics.dmm.co.jp/mono/movie/adult/{cid}/{cid}pl.jpg",
        f"https://awsimgsrc.dmm.com/pics_dig/digital/video/{cid}/{cid}pl.jpg",
    ]


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
    search_hit, search_ok = _search_artwork(code, samples=False)
    if search_hit:
        print(f"[DMM] {code}: search cid={search_hit['cid']} cover-only yes")
        return search_hit
    if search_ok:
        return None
    for cid in cid_candidates(code)[:2]:
        cover_url, data = _first_real(_fallback_cover_urls(cid), timeout=6)
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
    search_hit, search_ok = _search_artwork(code, samples=True)
    if search_hit:
        print(
            f"[DMM] {code}: search cid={search_hit['cid']} cover=yes "
            f"samples={len(search_hit.get('samples') or [])}"
        )
        return search_hit
    if search_ok:
        return None
    cids = cid_candidates(code)[:2]
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
