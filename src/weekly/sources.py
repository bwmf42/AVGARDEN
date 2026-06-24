"""数据源：JavBus 主页获取最新番号 + 封面 + 标题"""
import os, re, time, urllib.parse, random
from curl_cffi import requests

DOMAIN = "www.javbus.com"
PROXY = None
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
    "Cookie": "age=verified; existmag=mag",
}
DEFAULT_FRESHNESS_MARKERS = ("今日新種", "昨日新種")

def set_proxy(proxy):
    global PROXY
    PROXY = proxy

def _proxies():
    return {"http": PROXY, "https": PROXY} if PROXY else None

def _freshness_markers():
    raw = os.environ.get("WEEKLY_FRESHNESS_MARKERS", "")
    markers = [m.strip() for m in raw.split(",") if m.strip()]
    return markers or list(DEFAULT_FRESHNESS_MARKERS)

def _card_freshness(body, markers):
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", "", text)
    for marker in markers:
        if marker in text:
            return marker
    return ""

def get_recent(max_pages=1):
    """从 JavBus 主页/翻页获取最新番号列表，附带标题和封面"""
    items = []
    markers = _freshness_markers()
    for page in range(1, max_pages + 1):
        url = f"https://{DOMAIN}/page/{page}" if page > 1 else f"https://{DOMAIN}/"
        try:
            h = dict(HEADERS)
            h["Referer"] = f"https://{DOMAIN}/"
            r = requests.get(url, proxies=_proxies(), headers=h,
                           impersonate="chrome110", timeout=15,
                           allow_redirects=False)
            if "Age Verification" in r.text[:500]:
                break

            # 解析 movie-box 卡片
            cards = re.findall(
                r'<a class="movie-box" href="https?://[^"]*?/([A-Z0-9]+-\d+)"[^>]*>'
                r'(.*?)</a>', r.text, re.DOTALL
            )
            for avid, body in cards:
                freshness = _card_freshness(body, markers)
                if not freshness:
                    continue
                title_m = re.search(r'<img[^>]*title="([^"]*)"', body)
                title = title_m.group(1).strip() if title_m else avid
                cover_m = re.search(r'<img[^>]*src="([^"]*)"', body)
                cover = cover_m.group(1) if cover_m else ""
                if cover and not cover.startswith("http"):
                    cover = f"https://{DOMAIN}{cover}" if cover.startswith("/") else f"https://{DOMAIN}/{cover}"
                date_m = re.search(r'<date>(\d{4}-\d{2}-\d{2})</date>', body)
                items.append({
                    "id": avid.upper(),
                    "title": title,
                    "cover": cover,
                    "releaseDate": date_m.group(1) if date_m else "",
                    "freshness": freshness,
                })
            if not cards:
                break
            time.sleep(random.uniform(5, 10) if page > 1 else 0)
        except Exception as e:
            print(f"[Sources] Page {page}: {e}")
            break
    return items
