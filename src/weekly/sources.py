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


def _plwt_list_item(it, fid):
    return {
        "id": it.get("id", "").upper(),
        "title": it.get("title") or it.get("id", ""),
        "cover": it.get("cover") or "",
        "releaseDate": it.get("releaseDate") or it.get("postDate") or "",
        "freshness": it.get("freshness") or f"forum-{fid}",
        "source": it.get("source") or f"plwt-{fid}",
        "forumUrl": it.get("forumUrl") or "",
        "postDate": it.get("postDate") or "",
    }


def get_recent_plwt(max_pages=3):
    """98堂 forum-37 列表（每日推荐默认源）。"""
    fid = os.environ.get("WEEKLY_FORUM_FID", WEEKLY_FID)
    pages = max(1, int(max_pages or 3))
    print(f"[Sources] plwt forum-{fid} pages={pages}", flush=True)
    items = chinese_forum.get_weekly_list(max_pages=pages, fid=fid)
    return [_plwt_list_item(it, fid) for it in items]


def get_recent_plwt_until(stop_date, max_pages=0):
    """forum-37 从第 1 页翻到发帖日早于 stop_date（YYYY-MM-DD）。"""
    fid = os.environ.get("WEEKLY_FORUM_FID", WEEKLY_FID)
    print(f"[Sources] plwt forum-{fid} until {stop_date}", flush=True)
    items = chinese_forum.get_list_until(
        stop_date=stop_date,
        max_pages=max_pages,
        fid=fid,
        purpose="weekly",
    )
    return [_plwt_list_item(it, fid) for it in items]


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
            try:
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
            finally:
                r.close()
        except Exception as e:
            print(f"[Sources] JavBus page {page}: {e}")
            break
    return items


def _fallback_source():
    """plwt 失败时的备用源。WEEKLY_LIST_FALLBACK=none 可关闭。"""
    raw = os.environ.get("WEEKLY_LIST_FALLBACK", "javbus").strip().lower()
    if raw in ("0", "none", "off", "false", "no", ""):
        return ""
    return raw


def get_recent(max_pages=3):
    """每日推荐列表：默认 98堂 forum-37；失败自动重试并回退 JavBus。

    环境变量：
      WEEKLY_LIST_SOURCE=plwt|javbus  主源（默认 plwt）
      WEEKLY_LIST_FALLBACK=javbus|none  plwt 失败回退（默认 javbus）
      WEEKLY_PLWT_ATTEMPTS=3          plwt 外层重试次数
    """
    src = _list_source()
    if src in ("javbus", "jav", "bus"):
        print("[Sources] list source=javbus (explicit)", flush=True)
        return get_recent_javbus(max_pages)

    # Default 2: SSL 全挂时尽快回退 javbus；偶发抖动仍有一次复试
    attempts = max(1, int(os.environ.get("WEEKLY_PLWT_ATTEMPTS", "2") or "2"))
    last_err = None
    for i in range(1, attempts + 1):
        try:
            items = get_recent_plwt(max_pages)
            if items:
                if i > 1:
                    print(f"[Sources] plwt ok on attempt {i}/{attempts}: {len(items)} items", flush=True)
                return items
            print(f"[Sources] plwt empty (attempt {i}/{attempts})", flush=True)
            last_err = "empty list"
        except Exception as e:
            last_err = e
            print(f"[Sources] plwt attempt {i}/{attempts} failed: {e}", flush=True)
        if i < attempts:
            delay = min(15.0, 2.0 ** i + random.uniform(0, 1.5))
            print(f"[Sources] retry plwt in {delay:.1f}s", flush=True)
            time.sleep(delay)

    fb = _fallback_source()
    if not fb:
        print(f"[Sources] plwt failed ({last_err}); fallback disabled", flush=True)
        return []

    print(f"[Sources] plwt failed ({last_err}); fallback -> {fb}", flush=True)
    if fb in ("javbus", "jav", "bus"):
        try:
            # 回退时多翻一页，补偿「今日新種」过滤
            pages = max(int(max_pages or 1), 2)
            # 无标记时扫整页，否则 fallback 经常 0 条
            old = os.environ.get("WEEKLY_SCAN_ALL_CARDS")
            if not (old or "").strip():
                os.environ["WEEKLY_SCAN_ALL_CARDS"] = "1"
            try:
                items = get_recent_javbus(pages)
            finally:
                if old is None:
                    os.environ.pop("WEEKLY_SCAN_ALL_CARDS", None)
                else:
                    os.environ["WEEKLY_SCAN_ALL_CARDS"] = old
            print(f"[Sources] javbus fallback: {len(items)} items", flush=True)
            return items
        except Exception as e:
            print(f"[Sources] javbus fallback failed: {e}", flush=True)
            return []

    print(f"[Sources] unknown fallback {fb!r}", flush=True)
    return []
