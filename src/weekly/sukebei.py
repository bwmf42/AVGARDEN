"""Sukebei/MissAV magnet search and deterministic candidate selection."""
import html
import logging
import re, urllib.parse
from datetime import datetime
from curl_cffi import requests

logger = logging.getLogger(__name__)

SEARCH_URLS = [
    "https://sukebei.nyaa.si/?q=",
    "https://nyaa.si/?q=",
]
SUKEBEI_SEARCH_URL = SEARCH_URLS[0]

CILI_URL = "https://cilisousuo.co/search?q="
MISSAV_HOSTS = [
    "missav.ws",
    "missav.ai",
]
MISSAV_PATHS = [
    "/en/{avid}",
    "/en/{avid}-chinese-subtitle",
    "/en/{avid}-uncensored-leak",
    "/cn/{avid}",
    "/cn/{avid}-chinese-subtitle",
    "/cn/{avid}-uncensored-leak",
]

def search_chinese(avid):
    """搜索中文字幕磁链，验证种子名含中文标记"""
    # 只从 sukebei/nyaa 拿（能看到标题验证），不 fallback 到 cilisousuo
    return _search_nyaa(avid, [f"{avid} 中文字幕", f"{avid} 中文"], require_cn=True)

def search_cili(avid):
    """从 cilisousuo 搜索磁链（用 -C/ch 后缀搜中文字幕版）"""
    base = re.sub(r'[-_]?(C|CH)$', '', avid, flags=re.IGNORECASE)
    queries = [f"{base}ch", f"{base}-C", f"{base} 中文字幕", avid]
    for q in queries:
        try:
            url = f"{CILI_URL}{urllib.parse.quote(q)}"
            r = requests.get(url, proxies=_proxies(), headers=HEADERS,
                           impersonate="chrome110", timeout=20)
            try:
                if r.status_code != 200:
                    continue
                # cilisousuo 磁链格式: href="/magnet/xxxx" → 点进去的页面有 magnet:?xt=...
                shortlinks = re.findall(r'href="(/magnet/[^"]+)"', r.text)
                if not shortlinks:
                    continue
                # 取第一个短链接,进去拿完整磁链
                try:
                    detail_url = f"https://cilisousuo.co{shortlinks[0]}"
                    rd = requests.get(detail_url, proxies=_proxies(), headers=HEADERS,
                                    impersonate="chrome110", timeout=15)
                    try:
                        m = re.search(r'(magnet:\?xt=[^"\'&\s]+[^"\'\s]*)', rd.text)
                        if m:
                            return m.group(1)
                    finally:
                        rd.close()
                except:
                    pass
            finally:
                r.close()
        except:
            pass
    return ""

def search_missav_magnet(avid):
    """从 MissAV 详情页的 Magnet 列表兜底搜索磁链。"""
    avid = avid.strip().upper()
    if not avid:
        return ""

    for host in MISSAV_HOSTS:
        for path_tpl in MISSAV_PATHS:
            url = f"https://{host}{path_tpl.format(avid=avid.lower())}"
            try:
                r = requests.get(
                    url,
                    proxies=_proxies(),
                    headers=HEADERS,
                    impersonate="chrome110",
                    timeout=20,
                )
                try:
                    if r.status_code != 200:
                        continue
                    best = _pick_missav_magnet(avid, r.text)
                    if best:
                        return best
                finally:
                    r.close()
            except:
                pass
    return ""

def _pick_missav_magnet(avid, page_html):
    magnets = []
    seen = set()
    for match in re.finditer(r'href=["\'](magnet:\?xt=urn:btih:[^"\']+)["\']', page_html, re.I):
        magnet = html.unescape(match.group(1))
        if magnet in seen:
            continue
        seen.add(magnet)
        row_start = page_html.rfind("<tr", 0, match.start())
        row_end = page_html.find("</tr>", match.end())
        if row_start == -1 or row_end == -1:
            row_start = max(0, match.start() - 800)
            row_end = min(len(page_html), match.end() + 800)
        row = html.unescape(page_html[row_start:row_end])
        text = re.sub(r"<[^>]+>", " ", row)
        text = re.sub(r"\s+", " ", text).strip()
        score = _missav_magnet_score(avid, text)
        magnets.append((score, magnet))

    if not magnets:
        loose = re.findall(r'(magnet:\?xt=urn:btih:[^"\'<>\s]+)', page_html, re.I)
        for magnet in loose:
            magnet = html.unescape(magnet)
            if magnet not in seen:
                magnets.append(((0, 0, ""), magnet))
                seen.add(magnet)

    if not magnets:
        return ""
    magnets.sort(reverse=True, key=lambda item: item[0])
    return magnets[0][1]

def _missav_magnet_score(avid, text):
    upper = text.upper()
    code_score = 1 if avid in upper or avid.replace("-", "") in upper else 0
    cn_score = 1 if any(k in upper for k in ["中文", "字幕", "-C", "-CH", "CHINESE"]) else 0
    size_score = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|TB)", upper)
    if m:
        size_score = float(m.group(1))
        unit = m.group(2)
        if unit == "TB":
            size_score *= 1024
        elif unit == "MB":
            size_score /= 1024
    date = ""
    date_m = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if date_m:
        date = date_m.group(1)
    return (code_score, cn_score, size_score, date)
PROXY = None
HEADERS = {"User-Agent": "Mozilla/5.0"}

def set_proxy(proxy):
    global PROXY
    PROXY = proxy

def _proxies():
    return {"http": PROXY, "https": PROXY} if PROXY else None

def _search_nyaa(avid, queries, require_cn=False):
    for q in queries:
        for base_url in SEARCH_URLS:
            try:
                url = f"{base_url}{urllib.parse.quote(q)}"
                r = requests.get(url, proxies=_proxies(), headers=HEADERS,
                               impersonate="chrome110", timeout=20)
                try:
                    if r.status_code != 200:
                        continue
                    candidates = _parse_nyaa_candidates(avid, r.text)
                    if require_cn:
                        candidates = [c for c in candidates if c["is_cn"]]
                    if candidates:
                        candidates.sort(key=_nyaa_candidate_score, reverse=True)
                        best = candidates[0]
                        logger.info(
                            "[Sukebei] selected %s view=%s trusted=%s seeds=%s size=%.1fGiB title=%s",
                            avid, best["view_id"], best["trusted"], best["seeds"],
                            best["size_gib"], best["title"][:120],
                        )
                        return best["magnet"]
                finally:
                    r.close()
            except:
                pass
    return ""

def _parse_nyaa_candidates(avid, page_html):
    candidates = []
    for index, match in enumerate(re.finditer(r'<tr class="([^"]+)">(.*?)</tr>', page_html, re.DOTALL)):
        row_class, row = match.group(1), match.group(2)
        if not any(cls in row_class.split() for cls in ("default", "success", "danger")):
            continue
        magnet_match = re.search(r'href="(magnet:\?xt=urn:btih:[^"]*)"', row)
        if not magnet_match:
            continue
        seeds_match = re.findall(r'<td class="text-center"[^>]*>(\d+)</td>', row)
        view_match = re.search(r'/view/(\d+)', row)
        title_match = re.search(r'/view/\d+"[^>]*title="([^"]*)"', row)
        title = html.unescape(title_match.group(1) if title_match else "")
        size_gib = _parse_nyaa_size_gib(row)
        published_ts, published_at = _parse_nyaa_date(row)
        candidates.append({
            "magnet": html.unescape(magnet_match.group(1)),
            "title": title,
            "view_id": view_match.group(1) if view_match else "",
            "row_class": row_class,
            "trusted": "success" in row_class.split(),
            "danger": "danger" in row_class.split(),
            "seeds": int(seeds_match[0]) if seeds_match else 0,
            "size_gib": size_gib,
            "is_exact": _title_has_exact_code(avid, title),
            "is_cn": _title_has_chinese_marker(avid, title),
            "published_ts": published_ts,
            "published_at": published_at,
            "index": index,
        })
    return candidates


def _title_has_exact_code(avid, title):
    code = str(avid or "").strip().upper()
    if not code:
        return False
    flexible = r"[\s._-]*".join(re.escape(part) for part in re.split(r"[-_]", code))
    return bool(re.search(
        rf"(?<![A-Z0-9]){flexible}(?:[\s._-]*(?:C|CH))?(?![A-Z0-9])",
        str(title or "").upper(),
    ))


def _title_has_chinese_marker(avid, title):
    upper = str(title or "").upper()
    if any(marker in upper for marker in ("中文字幕", "高清中文", "中文", "CHINESE", "FHD_CH")):
        return True
    code = str(avid or "").strip().upper()
    flexible = r"[\s._-]*".join(re.escape(part) for part in re.split(r"[-_]", code))
    return bool(re.search(rf"(?<![A-Z0-9]){flexible}[\s._-]*(?:C|CH)(?![A-Z0-9])", upper))


def _parse_nyaa_date(row):
    timestamp_match = re.search(r'data-timestamp=["\'](\d+)["\']', row, re.I)
    if timestamp_match:
        timestamp = int(timestamp_match.group(1))
        return timestamp, datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\b", row)
    if not date_match:
        return 0, ""
    value = date_match.group(1)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M" if " " in value else "%Y-%m-%d")
        return int(parsed.timestamp()), value
    except ValueError:
        return 0, value

def _parse_nyaa_size_gib(row):
    size_match = re.search(r'<td class="text-center"[^>]*>\s*(\d+(?:\.\d+)?)\s*([KMGT]iB)\s*</td>', row, re.I)
    if not size_match:
        return 0.0
    size = float(size_match.group(1))
    unit = size_match.group(2).lower()
    if unit == "tib":
        return size * 1024
    if unit == "gib":
        return size
    if unit == "mib":
        return size / 1024
    if unit == "kib":
        return size / (1024 * 1024)
    return 0.0

def _nyaa_candidate_score(candidate):
    return (
        1 if candidate["trusted"] else 0,
        0 if candidate["danger"] else 1,
        1 if candidate["is_exact"] else 0,
        1 if candidate["is_cn"] else 0,
        candidate["seeds"],
        candidate["size_gib"],
        -candidate["index"],
    )


def select_preferred_candidate(candidates):
    """Pick largest Chinese candidate, otherwise the earliest original."""
    exact = [candidate for candidate in candidates if candidate.get("is_exact") and candidate.get("magnet")]
    chinese = [candidate for candidate in exact if candidate.get("is_cn")]
    if chinese:
        return max(
            chinese,
            key=lambda candidate: (
                float(candidate.get("size_gib") or 0),
                -int(candidate.get("published_ts") or 0),
                int(candidate.get("index") or 0),
            ),
        )
    if not exact:
        return None
    dated = [candidate for candidate in exact if int(candidate.get("published_ts") or 0) > 0]
    if dated:
        return min(dated, key=lambda candidate: (int(candidate["published_ts"]), -int(candidate.get("index") or 0)))
    return max(exact, key=lambda candidate: int(candidate.get("index") or 0))


def search_preferred(avid):
    """Search Sukebei once and return the selected structured candidate."""
    code = str(avid or "").strip().upper()
    if not code:
        return None
    try:
        url = f"{SUKEBEI_SEARCH_URL}{urllib.parse.quote(code)}"
        response = requests.get(
            url,
            proxies=_proxies(),
            headers=HEADERS,
            impersonate="chrome110",
            timeout=20,
        )
        try:
            if response.status_code != 200:
                logger.info("[Sukebei] search %s returned HTTP %s", code, response.status_code)
                return None
            candidate = select_preferred_candidate(_parse_nyaa_candidates(code, response.text))
            if not candidate:
                logger.info("[Sukebei] no exact candidate for %s", code)
                return None
            logger.info(
                "[Sukebei] selected %s mode=%s size=%.1fGiB date=%s title=%s",
                code,
                "largest-chinese" if candidate.get("is_cn") else "earliest-original",
                candidate.get("size_gib") or 0,
                candidate.get("published_at") or "unknown",
                candidate.get("title", "")[:120],
            )
            return candidate
        finally:
            response.close()
    except Exception as exc:
        logger.info("[Sukebei] lookup failed for %s: %s", code, exc)
        return None

def search(avid, page_html=""):
    """Compatibility wrapper for the current Sukebei-only magnet lookup."""
    candidate = search_preferred(avid)
    return candidate.get("magnet", "") if candidate else ""
