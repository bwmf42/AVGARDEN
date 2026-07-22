"""每日推荐列表源：98堂 forum-37（可回退 JavBus）。

默认：plwt.kpqq4.com/forum-37-N.html，WEEKLY_MAX_PAGES 页。
环境变量 WEEKLY_LIST_SOURCE=javbus 可切回旧 JavBus 今日新種逻辑。
"""
import os
import re
import time
import random

from curl_cffi import requests

from . import chinese_forum

DOMAIN = "www.javbus.com"
PROXY = None
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
    "Cookie": "age=verified; existmag=mag",
}
DEFAULT_FRESHNESS_MARKERS = ("今日新種",)
WEEKLY_FID = os.environ.get("WEEKLY_FORUM_FID", "37")


def set_proxy(proxy):
    global PROXY
    PROXY = proxy
    chinese_forum.set_proxy(proxy)


def _proxies():
    return {"http": PROXY, "https": PROXY} if PROXY else None


def _list_source():
    return os.environ.get("WEEKLY_LIST_SOURCE", "plwt").strip().lower()


def _freshness_markers():
    raw = os.environ.get("WEEKLY_FRESHNESS_MARKERS", "")
    markers = [m.strip() for m in raw.split(",") if m.strip()]
    return markers or list(DEFAULT_FRESHNESS_MARKERS)


def _scan_all_cards():
    return os.environ.get("WEEKLY_SCAN_ALL_CARDS", "").strip().lower() in ("1", "true", "yes", "on")


def _card_freshness(body, markers):
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", "", text)
    for marker in markers:
        if marker in text:
            return marker
    return ""


def get_recent_plwt(max_pages=3):
    """98堂 forum-37 列表（每日推荐默认源）。"""
    fid = os.environ.get("WEEKLY_FORUM_FID", WEEKLY_FID)
    pages = max(1, int(max_pages or 3))
    print(f"[Sources] plwt forum-{fid} pages={pages}", flush=True)
    items = chinese_forum.get_weekly_list(max_pages=pages, fid=fid)
    # 对齐 weekly_updater 最小字段
    out = []
    for it in items:
        out.append({
            "id": it.get("id", "").upper(),
            "title": it.get("title") or it.get("id", ""),
            "cover": it.get("cover") or "",
            "releaseDate": it.get("releaseDate") or it.get("postDate") or "",
            "freshness": it.get("freshness") or f"forum-{fid}",
            "source": it.get("source") or f"plwt-{fid}",
            "forumUrl": it.get("forumUrl") or "",
            "postDate": it.get("postDate") or "",
        })
    return out


def get_recent_javbus(max_pages=1):
    """从 JavBus 主页/翻页获取最新番号列表（备用）。"""
    items = []
    markers = _freshness_markers()
    scan_all_cards = _scan_all_cards()
    for page in range(1, max_pages + 1):
        url = f"https://{DOMAIN}/page/{page}" if page > 1 else f"https://{DOMAIN}/"
        try:
            h = dict(HEADERS)
            h["Referer"] = f"https://{DOMAIN}/"
            r = requests.get(
                url,
                proxies=_proxies(),
                headers=h,
                impersonate="chrome110",
                timeout=15,
                allow_redirects=False,
            )
            if "Age Verification" in r.text[:500]:
                break

            cards = re.findall(
                r'<a class="movie-box" href="https?://[^"]*?/([A-Z0-9]+-\d+)"[^>]*>'
                r'(.*?)</a>',
                r.text,
                re.DOTALL,
            )
            for avid, body in cards:
                freshness = _card_freshness(body, markers)
                if not freshness and not scan_all_cards:
                    continue
                if not freshness:
                    freshness = "page-scan"
                title_m = re.search(r'<img[^>]*title="([^"]*)"', body)
                title = title_m.group(1).strip() if title_m else avid
                cover_m = re.search(r'<img[^>]*src="([^"]*)"', body)
                cover = cover_m.group(1) if cover_m else ""
                if cover and not cover.startswith("http"):
                    cover = (
                        f"https://{DOMAIN}{cover}"
                        if cover.startswith("/")
                        else f"https://{DOMAIN}/{cover}"
                    )
                date_m = re.search(r'<date>(\d{4}-\d{2}-\d{2})</date>', body)
                items.append({
                    "id": avid.upper(),
                    "title": title,
                    "cover": cover,
                    "releaseDate": date_m.group(1) if date_m else "",
                    "freshness": freshness,
                    "source": "javbus",
                })
            if not cards:
                break
            time.sleep(random.uniform(5, 10) if page > 1 else 0)
        except Exception as e:
            print(f"[Sources] JavBus page {page}: {e}")
            break
    return items


def get_recent(max_pages=3):
    """每日推荐列表：默认 98堂 forum-37；WEEKLY_LIST_SOURCE=javbus 回退。"""
    src = _list_source()
    if src in ("javbus", "jav", "bus"):
        return get_recent_javbus(max_pages)
    return get_recent_plwt(max_pages)
