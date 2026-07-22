"""MGStage product detail: artwork + metadata (SOAV-style fields).

Parses product_detail/{code}/ for cover/samples and table fields:
出演 / ジャンル / 収録時間 / 配信開始日 / メーカー / シリーズ / レーベル.
"""
import os
import re
import urllib.parse

from curl_cffi import requests

PROXY = os.environ.get("PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None
DOMAIN = "www.mgstage.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    "Cookie": "adc=1",
    "Referer": "https://www.mgstage.com/",
}

_COVER_RANK = {
    "pb_e": 100,
    "pf_e": 90,
    "pb_p": 70,
    "pf_o1": 40,
    "pb_t1": 20,
    "pf_t1": 10,
}

_ROW_RE = re.compile(
    r"<tr[^>]*>(?:<!--.*?-->|\s)*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*</tr>",
    re.I | re.S,
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE_RE = re.compile(r"<title>([^<]+)", re.I)


def set_proxy(proxy):
    global PROXY
    PROXY = proxy or None


def _proxies():
    p = PROXY or os.environ.get("PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    return {"http": p, "https": p} if p else None


def _norm_code(code):
    return (code or "").strip().upper()


def _code_token(code):
    return _norm_code(code).lower()


def product_url(code):
    code = _norm_code(code)
    if not code:
        return ""
    return f"https://{DOMAIN}/product/product_detail/{urllib.parse.quote(code)}/"


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _cell_texts(td_html: str):
    """Prefer <a> link texts; else plain cell text."""
    links = re.findall(r"<a[^>]*>(.*?)</a>", td_html or "", re.I | re.S)
    texts = []
    for raw in links:
        t = _strip_tags(raw)
        if t:
            texts.append(t)
    if texts:
        return texts
    plain = _strip_tags(td_html)
    return [plain] if plain else []


def _normalize_label(th_html: str) -> str:
    t = _strip_tags(th_html)
    t = t.replace("：", "").replace(":", "").strip()
    return t


def _parse_duration(text: str) -> str:
    """Normalize to e.g. 66分钟 / 130分钟."""
    t = (text or "").strip()
    if not t:
        return ""
    m = re.search(r"(\d+)\s*(?:min|分|分钟|分鐘)", t, re.I)
    if m:
        return f"{int(m.group(1))}分钟"
    m = re.search(r"(\d+)\s*小时|(\d+)\s*h", t, re.I)
    if m:
        h = int(m.group(1) or m.group(2) or 0)
        return f"{h * 60}分钟" if h else ""
    if re.fullmatch(r"\d+", t):
        return f"{int(t)}分钟"
    return t


def _parse_date(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"(\d{4})[./年-](\d{1,2})[./月-](\d{1,2})", t)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _extract_urls(html):
    found = set()
    for m in re.finditer(
        r'(?:https?:)?//image\.mgstage\.com/[^"\'\s<>]+\.(?:jpe?g|webp)',
        html,
        re.I,
    ):
        u = m.group(0)
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("http://"):
            u = "https://" + u[len("http://") :]
        u = re.sub(r"(https://image\.mgstage\.com)/+", r"\1/", u)
        found.add(u)
    return found


def _classify(urls, code):
    token = _code_token(code)
    if not token:
        return None, []
    needle = token.replace("_", "-")
    covers = []
    samples = {}
    for url in urls:
        name = url.rsplit("/", 1)[-1].lower()
        if needle not in name:
            continue
        m = re.search(r"cap_e_(\d+)_", name)
        if m:
            samples[int(m.group(1))] = url
            continue
        m = re.search(r"^(pb_e|pf_e|pb_p|pf_o1|pb_t1|pf_t1)_", name)
        if m:
            kind = m.group(1)
            covers.append((_COVER_RANK.get(kind, 0), kind, url))
    covers.sort(reverse=True)
    cover = covers[0][2] if covers else None
    sample_list = [samples[i] for i in sorted(samples)]
    if not cover and not sample_list:
        return None, []
    return cover, sample_list


def fetch_page(code):
    """Return product HTML or None.

    When PROXY is set, use Japan proxy only (NAS direct gets 403; do not try direct).
    Without PROXY (local dev), fall back to direct.
    """
    code = _norm_code(code)
    url = product_url(code)
    if not url:
        return None
    p = _proxies()
    # Prefer Japan proxy only; skip direct when proxy is configured.
    proxy_opts = [p] if p else [None]
    last_err = None
    for proxies in proxy_opts:
        try:
            r = requests.get(
                url,
                proxies=proxies,
                headers=HEADERS,
                impersonate="chrome110",
                timeout=20,
            )
            if r.status_code < 400 and r.text and len(r.text) > 2000:
                return r.text
            last_err = f"status {r.status_code} len={len(r.text or '')}"
        except Exception as e:
            last_err = e
            continue
    print(f"[MGS] Fetch {code}: {last_err}")
    return None


def parse_detail_rows(html: str) -> dict:
    """Parse <th>/<td> product table into label -> list[str]."""
    rows = {}
    for m in _ROW_RE.finditer(html or ""):
        label = _normalize_label(m.group(1))
        if not label:
            continue
        # skip navigation block "ジャンルから探す"
        if "から探す" in label:
            continue
        texts = _cell_texts(m.group(2))
        if texts:
            rows[label] = texts
    return rows


def parse_metadata(html: str, code: str = "") -> dict:
    """Full SOAV-style metadata from MGS product HTML (no network)."""
    if not html:
        return {}
    code = _norm_code(code)
    rows = parse_detail_rows(html)

    def first(label_options):
        for lab in label_options:
            vals = rows.get(lab)
            if vals:
                return vals
        return []

    genres = first(["ジャンル"])
    actresses = first(["出演", "出演者"])
    # actress cell may be plain "しおり 21歳 ファミレスでバイト" without <a>
    if not actresses:
        for lab, vals in rows.items():
            if lab.startswith("出演"):
                actresses = vals
                break

    duration_raw = (first(["収録時間"]) or [""])[0]
    date_raw = (first(["配信開始日", "商品発売日", "発売日"]) or [""])[0]
    maker = (first(["メーカー"]) or [""])[0]
    series = (first(["シリーズ"]) or [""])[0]
    label = (first(["レーベル"]) or [""])[0]
    sku = (first(["品番"]) or [""])[0]

    title = ""
    h1 = _H1_RE.search(html or "")
    if h1:
        title = _strip_tags(h1.group(1))
    if not title:
        tm = _TITLE_RE.search(html or "")
        if tm:
            title = tm.group(1).split("：")[0].split(":")[0].strip()
            for suffix in (" - MGS", "｜MGS", "| MGS", "エロ動画"):
                if suffix in title:
                    title = title.split(suffix)[0].strip()

    cover, samples = _classify(_extract_urls(html), code)

    # Drop device / review noise from actresses if misparsed
    actresses = [a for a in actresses if a and "Windows" not in a and "レビュー" not in a]

    out = {
        "source": "mgs",
        "page": product_url(code) if code else "",
        "code": sku or code,
        "title": title,
        "cover": cover or "",
        "samples": samples or [],
        "actresses": actresses,
        "genres": genres,  # Japanese; caller translates
        "duration": _parse_duration(duration_raw),
        "releaseDate": _parse_date(date_raw),
        "maker": maker,
        "series": series,
        "label": label,
    }
    # empty cleanup
    if not out["cover"] and not out["samples"] and not out["genres"] and not out["actresses"]:
        # might be empty product / age wall
        if "product_detail" not in (html or "") and "detail_data" not in (html or ""):
            return {}
    return out


def parse_artwork(html, code):
    """Backward-compatible cover/samples only."""
    meta = parse_metadata(html, code)
    if not meta:
        return None
    if not meta.get("cover") and not meta.get("samples"):
        return None
    return {
        "source": "mgs",
        "page": meta.get("page") or product_url(code),
        "cover": meta.get("cover") or "",
        "samples": meta.get("samples") or [],
    }


def fetch_artwork(code):
    """Artwork only (cover + samples)."""
    code = _norm_code(code)
    if not code or code.startswith("FC2"):
        return None
    html = fetch_page(code)
    art = parse_artwork(html, code)
    if art:
        print(
            f"[MGS] {code}: cover={'yes' if art.get('cover') else 'no'} "
            f"samples={len(art.get('samples') or [])}"
        )
    return art


def fetch_detail(code):
    """Full metadata + artwork from MGS product page."""
    code = _norm_code(code)
    if not code or code.startswith("FC2"):
        return None
    html = fetch_page(code)
    meta = parse_metadata(html, code)
    if not meta:
        return None
    print(
        f"[MGS] {code}: cover={'yes' if meta.get('cover') else 'no'} "
        f"samples={len(meta.get('samples') or [])} "
        f"genres={len(meta.get('genres') or [])} "
        f"act={len(meta.get('actresses') or [])} "
        f"dur={meta.get('duration') or '-'} date={meta.get('releaseDate') or '-'}"
    )
    return meta
