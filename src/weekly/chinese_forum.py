"""Discuz 中文字幕板块：列表翻页 + 定向进帖抽 magnet。

访问策略：
- curl_cffi Chrome TLS 指纹
- 先过 _safe 安全门，会话复用
- 串行请求 + 随机长间隔
- 列表默认只翻 forum 页；进帖仅由调用方决定（库内缺中文命中）
"""
from __future__ import annotations

import os
import random
import re
import sys
import time
import html as html_lib
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from curl_cffi import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from video_id import normalize_video_id  # noqa: E402

PROXY = None
BASE = os.environ.get("CHINESE_FORUM_BASE", "https://plwt.kpqq4.com").rstrip("/")
FID = os.environ.get("CHINESE_FORUM_FID", "103")
IMPERSONATE = os.environ.get("CHINESE_FORUM_IMPERSONATE", "chrome120")
PAGE_DELAY_MIN = float(os.environ.get("CHINESE_FORUM_PAGE_DELAY_MIN", "12"))
PAGE_DELAY_MAX = float(os.environ.get("CHINESE_FORUM_PAGE_DELAY_MAX", "20"))
# 进帖比列表更敏感：默认更长间隔，避免连点详情被风控
THREAD_DELAY_MIN = float(os.environ.get("CHINESE_FORUM_THREAD_DELAY_MIN", "25"))
THREAD_DELAY_MAX = float(os.environ.get("CHINESE_FORUM_THREAD_DELAY_MAX", "40"))
MAX_PAGE_RETRIES = int(os.environ.get("CHINESE_FORUM_PAGE_RETRIES", "2"))
MAX_CONSEC_FAILS = int(os.environ.get("CHINESE_FORUM_MAX_CONSEC_FAILS", "3"))
DAILY_PAGES = int(os.environ.get("CHINESE_FORUM_DAILY_PAGES", "2"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_SKIP_TITLE_KEYWORDS = (
    "招聘",
    "白名单",
    "邀请码",
    "发布器",
    "二次验证",
    "安卓APP",
    "永久访问",
    "突破河南",
    "突破福建",
    "禁止申诉",
    "想得到邀请",
)

_NORMAL_TBODY = re.compile(
    r'<tbody\b[^>]*\bid="normalthread_(\d+)"[^>]*>(.*?)</tbody>',
    re.I | re.S,
)
_XST_LINK = re.compile(
    r'<a[^>]+href="(thread-\d+-1-\d+\.html)"[^>]*class="[^"]*\bxst\b[^"]*"[^>]*>(.*?)</a>',
    re.I | re.S,
)
_XST_LINK_ALT = re.compile(
    r'<a[^>]+class="[^"]*\bxst\b[^"]*"[^>]+href="(thread-\d+-1-\d+\.html)"[^>]*>(.*?)</a>',
    re.I | re.S,
)
_CATEGORY = re.compile(
    r'filter=typeid[^>]*>\s*(有码高清|无码高清)\s*<',
    re.I,
)
_DATE_TITLE = re.compile(r'<span[^>]+title="(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)"', re.I)
_CODE_CANDIDATE = re.compile(
    r"(?i)\b("
    r"FC2(?:\s*[-_]?\s*PPV)?\s*[-_]?\s*\d{5,8}"
    r"|[A-Z]{1,10}\d{0,4}\s*[-_]\s*\d{2,6}[A-Z]?"
    r"|\d{3,6}[A-Z]{2,10}\s*[-_]?\s*\d{2,6}"
    r")\b"
)
_MAGNET_RE = re.compile(r"(magnet:\?xt=urn:btih:[a-zA-Z0-9]{32,40}[^\s\"'<>]*)", re.I)


def set_proxy(proxy: Optional[str]):
    global PROXY
    PROXY = proxy or None


def _proxies():
    return {"http": PROXY, "https": PROXY} if PROXY else None


def _log(msg: str):
    print(f"[ChineseForum] {msg}", flush=True)


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _is_skipped_title(title: str) -> bool:
    t = title or ""
    return any(k in t for k in _SKIP_TITLE_KEYWORDS)


def parse_date_str(value: str) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def extract_video_id(title: str) -> str:
    """从帖子标题尽量抽出可归一化的番号；失败返回空串。"""
    if not title:
        return ""
    for m in _CODE_CANDIDATE.finditer(title):
        raw = m.group(1)
        code = normalize_video_id(raw)
        if code:
            return code
        compact = re.sub(r"\s+", "", raw.upper())
        code = normalize_video_id(compact)
        if code:
            return code
    head = title.strip().split()[0] if title.strip() else ""
    if head:
        code = normalize_video_id(head)
        if code:
            return code
    return ""


def parse_list_html(
    html: str,
    base: str = BASE,
    purpose: str = "chinese",
    fid: str = "",
) -> Tuple[List[dict], dict]:
    """解析板块列表页。返回 (items, stats)。不发起网络请求。

    purpose:
      - chinese: 中文字幕板（hasChinese + 中文字幕标签）
      - weekly: 每日推荐板 forum-37（不默认中文）
    """
    purpose = (purpose or "chinese").strip().lower()
    if purpose not in ("chinese", "weekly"):
        purpose = "chinese"
    fid = str(fid or "")
    stats = {
        "threads": 0,
        "with_id": 0,
        "skipped_announce": 0,
        "skipped_no_id": 0,
    }
    items: List[dict] = []
    today = date.today().isoformat()

    bodies = _NORMAL_TBODY.findall(html or "")
    if not bodies:
        bodies = [("", html or "")]

    for tid, body in bodies:
        stats["threads"] += 1
        m = _XST_LINK.search(body) or _XST_LINK_ALT.search(body)
        if not m:
            continue
        href, title_html = m.group(1), m.group(2)
        title = _strip_tags(title_html)
        if not title:
            continue
        if _is_skipped_title(title):
            stats["skipped_announce"] += 1
            continue
        avid = extract_video_id(title)
        if not avid:
            stats["skipped_no_id"] += 1
            continue

        cat_m = _CATEGORY.search(body)
        category = cat_m.group(1) if cat_m else ""
        dates = _DATE_TITLE.findall(body)
        # 作者列第一个 title 日期 = 发帖日（非最后回复）
        post_date = dates[0][:10] if dates else today

        if purpose == "weekly":
            item = {
                "id": avid,
                "title": title,
                "titleZh": "",
                "titleJp": "",
                "cover": "",
                "poster": "",
                "duration": "",
                "size": "",
                "magnet": "",
                "actresses": [],
                "genres": [category] if category else [],
                "fanarts": [],
                "releaseDate": post_date,
                "postDate": post_date,
                "hasChinese": False,
                "downloaded": False,
                "source": f"plwt-{fid}" if fid else "plwt",
                "forumUrl": urljoin(base + "/", href),
                "category": category,
                "freshness": f"forum-{fid}" if fid else "forum-list",
                "tid": tid,
            }
        else:
            item = {
                "id": avid,
                "title": title,
                "titleZh": title,
                "titleJp": "",
                "cover": "",
                "poster": "",
                "duration": "",
                "size": "",
                "magnet": "",
                "actresses": [],
                "genres": ["中文字幕"] + ([category] if category else []),
                "fanarts": [],
                "releaseDate": post_date,
                "postDate": post_date,
                "hasChinese": True,
                "downloaded": False,
                "source": "chinese_forum",
                "forumUrl": urljoin(base + "/", href),
                "category": category,
                "freshness": "chinese-forum-list",
                "tid": tid,
            }
        items.append(item)
        stats["with_id"] += 1

    return items, stats


def extract_magnets(html: str) -> List[str]:
    """从帖子 HTML 提取 magnet 列表（去重保序）。"""
    found = []
    seen = set()
    for m in _MAGNET_RE.finditer(html or ""):
        mag = m.group(1).strip()
        # 截断 HTML 实体尾巴
        mag = mag.split("&amp;")[0].split('"')[0].split("'")[0]
        key = mag.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(mag)
    return found


def extract_thread_images(value: str, base: str = BASE) -> List[str]:
    """Extract first-post attachment images, preferring full zoom/file URLs."""
    first_post = re.search(
        r'<td\b[^>]*\bid=["\']postmessage_\d+["\'][^>]*>(.*?)</td>',
        value or "",
        re.I | re.S,
    )
    scope = first_post.group(1) if first_post else (value or "")
    found = []
    seen = set()
    for tag in re.findall(r"<img\b[^>]*>", scope, re.I):
        if not re.search(r"\b(?:inpost|zoomfile|file)=", tag, re.I):
            continue
        selected = ""
        for key in ("zoomfile", "file", "src"):
            match = re.search(rf"\b{key}=[\"']([^\"']+)", tag, re.I)
            if match:
                selected = html_lib.unescape(match.group(1)).strip()
                if selected:
                    break
        if not selected:
            continue
        url = urljoin(base.rstrip("/") + "/", selected)
        path = url.split("?", 1)[0].lower()
        if not path.endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        if "static/image/" in path or url in seen:
            continue
        seen.add(url)
        found.append(url)
    return found


class ForumClient:
    """带安全门的串行客户端。"""

    def __init__(self, base: str = BASE, fid: str = FID):
        self.base = base.rstrip("/")
        self.fid = str(fid)
        self.session = requests.Session()
        self._safe_ok = False
        self._safe_token = ""
        self._last_url = f"{self.base}/forum-{self.fid}-1.html"

    def list_url(self, page: int) -> str:
        return f"{self.base}/forum-{self.fid}-{int(page)}.html"

    def _headers(self, referer: Optional[str] = None) -> dict:
        h = dict(HEADERS)
        h["Referer"] = referer or self._last_url
        return h

    def _is_safe_gate(self, html: str) -> bool:
        if not html:
            return True
        if "var safeid=" in html and "static/safe/js" in html:
            return True
        if len(html) < 5000 and re.search(r"<title>[^<]{1,40}</title>", html) and "Discuz" not in html:
            return "safeid" in html or "static/safe" in html
        return False

    def _extract_safeid(self, html: str) -> str:
        m = re.search(r"var safeid='([^']+)'", html or "")
        return m.group(1) if m else ""

    def ensure_safe(self) -> bool:
        url = self.list_url(1)
        r = self.session.get(
            url,
            headers=self._headers(self.base + "/"),
            proxies=_proxies(),
            impersonate=IMPERSONATE,
            timeout=25,
        )
        html = r.text or ""
        if not self._is_safe_gate(html) and "Discuz" in html:
            self._safe_ok = True
            self._last_url = url
            return True
        sid = self._extract_safeid(html)
        if not sid:
            _log(f"safe gate: no safeid (status={r.status_code}, len={len(html)})")
            return False
        host = re.sub(r"^https?://", "", self.base).split("/")[0]
        self.session.cookies.set("_safe", sid, domain=host, path="/")
        self._safe_token = sid
        r2 = self._raw_get(url, referer=self.base + "/")
        if r2 is None:
            return False
        if self._is_safe_gate(r2.text or ""):
            _log("safe gate still present after _safe cookie")
            return False
        self._safe_ok = True
        self._last_url = url
        _log("safe gate passed")
        return True

    def _cookie_header(self) -> str:
        parts = []
        seen = set()
        if self._safe_token:
            parts.append(f"_safe={self._safe_token}")
            seen.add("_safe")
        try:
            for c in self.session.cookies:
                if c.name in seen:
                    continue
                parts.append(f"{c.name}={c.value}")
                seen.add(c.name)
        except Exception:
            pass
        return "; ".join(parts)

    def _raw_get(self, url: str, referer: Optional[str] = None):
        h = self._headers(referer)
        ck = self._cookie_header()
        if ck:
            h["Cookie"] = ck
        return self.session.get(
            url,
            headers=h,
            proxies=_proxies(),
            impersonate=IMPERSONATE,
            timeout=25,
        )

    def _get_html(self, url: str) -> Optional[str]:
        if not self._safe_ok and not self.ensure_safe():
            return None
        last_err = None
        for attempt in range(MAX_PAGE_RETRIES + 1):
            try:
                r = self._raw_get(url, referer=self._last_url)
                html = r.text or ""
                if self._is_safe_gate(html):
                    _log("safe gate reappeared, re-auth")
                    self._safe_ok = False
                    if not self.ensure_safe():
                        last_err = "safe re-auth failed"
                        time.sleep(2 ** attempt + random.uniform(1, 2))
                        continue
                    r = self._raw_get(url, referer=self._last_url)
                    html = r.text or ""
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(2 ** attempt + random.uniform(1, 3))
                    continue
                if self._is_safe_gate(html):
                    last_err = "still safe gate"
                    time.sleep(2 ** attempt + random.uniform(1, 3))
                    continue
                self._last_url = url
                return html
            except Exception as e:
                last_err = str(e)
                time.sleep(2 ** attempt + random.uniform(1, 3))
        _log(f"get failed {url}: {last_err}")
        return None

    def fetch_list_page(self, page: int) -> Optional[str]:
        url = self.list_url(page)
        if "/thread-" in url:
            raise ValueError("refusing non-list URL")
        return self._get_html(url)

    def fetch_thread_html(self, forum_url: str) -> Optional[str]:
        """拉取帖子页 HTML（仅 thread- 路径）。"""
        url = (forum_url or "").strip()
        if url.startswith("/"):
            url = urljoin(self.base + "/", url.lstrip("/"))
        if not url.startswith("http"):
            url = urljoin(self.base + "/", url)
        # 只允许同站 thread 详情
        if not url.startswith(self.base):
            _log(f"refuse off-site thread: {url}")
            return None
        if "/thread-" not in url and "mod=viewthread" not in url:
            _log(f"refuse non-thread URL: {url}")
            return None
        return self._get_html(url)

    def fetch_thread_magnet(self, forum_url: str) -> str:
        html = self.fetch_thread_html(forum_url)
        if not html:
            return ""
        magnets = extract_magnets(html)
        if not magnets:
            return ""
        return magnets[0]

    def fetch_thread_artwork(self, forum_url: str) -> dict | None:
        html = self.fetch_thread_html(forum_url)
        images = extract_thread_images(html or "", forum_url or self.base)
        if not images:
            return None
        return {
            "source": "forum",
            "page": forum_url,
            "cover": images[0],
            "samples": images[1:],
        }


def fetch_thread_artwork(forum_url: str) -> dict | None:
    """Fetch final-fallback artwork from an already-known same-site thread."""
    if not forum_url:
        return None
    return ForumClient().fetch_thread_artwork(forum_url)


def get_list_until(
    stop_date: Optional[str] = None,
    max_pages: int = 0,
    client: Optional[ForumClient] = None,
    fid: Optional[str] = None,
    purpose: str = "chinese",
) -> List[dict]:
    """从第 1 页往旧翻列表。

    stop_date: YYYY-MM-DD，帖子发帖日 < 该日则停（当日仍保留）。
    max_pages: >0 时最多翻这么多页；0 表示不限制页数（必须有 stop_date 才安全）。
    fid: 板块 id，默认中文板 CHINESE_FORUM_FID；周推传 37。
    purpose: chinese | weekly（影响解析字段）。
    """
    stop = parse_date_str(stop_date) if stop_date else None
    max_pages = int(max_pages or 0)
    purpose = (purpose or "chinese").strip().lower()
    if stop is None and max_pages <= 0:
        max_pages = DAILY_PAGES
        _log(f"no stop_date; default max_pages={max_pages}")

    own_client = client is None
    use_fid = str(fid if fid is not None else FID)
    client = client or ForumClient(fid=use_fid)
    if client.fid != use_fid and fid is not None:
        client = ForumClient(base=client.base, fid=use_fid)
        own_client = True
    if own_client and not client.ensure_safe():
        _log("abort: cannot pass safe gate")
        return []
    if not client._safe_ok and not client.ensure_safe():
        _log("abort: cannot pass safe gate")
        return []

    by_id: Dict[str, dict] = {}
    consec_fail = 0
    pages_ok = 0
    page = 0
    hard_cap = max_pages if max_pages > 0 else 5000  # 安全硬顶
    _log(f"list start: fid={client.fid} purpose={purpose} max_pages={max_pages or '∞'} stop={stop}")

    while page < hard_cap:
        page += 1
        html = client.fetch_list_page(page)
        if html is None:
            consec_fail += 1
            if consec_fail >= MAX_CONSEC_FAILS:
                _log(f"stop: {consec_fail} consecutive page failures")
                break
            delay = random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
            _log(f"page {page}: fail, sleep {delay:.1f}s")
            time.sleep(delay)
            continue

        consec_fail = 0
        pages_ok += 1
        items, stats = parse_list_html(
            html, base=client.base, purpose=purpose, fid=client.fid
        )

        page_dates = [parse_date_str(i.get("postDate") or "") for i in items]
        page_dates = [d for d in page_dates if d]
        oldest_on_page = min(page_dates) if page_dates else None

        new_on_page = 0
        reached_stop = False
        for item in items:
            pd = parse_date_str(item.get("postDate") or "")
            if stop and pd and pd < stop:
                reached_stop = True
                continue
            avid = item["id"]
            if avid in by_id:
                continue
            by_id[avid] = item
            new_on_page += 1

        _log(
            f"page {page}: threads={stats['threads']} with_id={stats['with_id']} "
            f"new={new_on_page} oldest={oldest_on_page} stop={stop} "
            f"unique_total={len(by_id)}"
        )

        if max_pages > 0 and page >= max_pages:
            _log(f"stop: reached max_pages={max_pages}")
            break
        if stop and oldest_on_page and oldest_on_page < stop:
            _log(f"stop: page oldest {oldest_on_page} < stop_date {stop}")
            break
        if stop and reached_stop and oldest_on_page and oldest_on_page <= stop:
            # 本页已裁切完更旧条目
            if oldest_on_page < stop:
                break

        # 若整页都没有可解析日期且无条目，避免死循环
        if stats["with_id"] == 0 and not page_dates:
            _log("stop: empty parseable page")
            break

        if page < hard_cap and (max_pages <= 0 or page < max_pages):
            # 若下一页还要翻
            will_continue = True
            if max_pages > 0 and page >= max_pages:
                will_continue = False
            if stop and oldest_on_page and oldest_on_page < stop:
                will_continue = False
            if will_continue:
                delay = random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
                _log(f"sleep {delay:.1f}s before next page")
                time.sleep(delay)

    result = list(by_id.values())
    _log(f"list done: unique={len(result)} pages_ok={pages_ok}")
    return result


def get_list(
    max_pages: int = 20,
    fid: Optional[str] = None,
    purpose: str = "chinese",
) -> List[dict]:
    """兼容旧接口：固定页数列表。"""
    return get_list_until(
        stop_date=None,
        max_pages=max(1, int(max_pages)),
        fid=fid,
        purpose=purpose,
    )


def get_weekly_list(max_pages: int = 3, fid: Optional[str] = None) -> List[dict]:
    """每日推荐：98堂 forum-37 列表（默认 3 页）。"""
    weekly_fid = str(fid or os.environ.get("WEEKLY_FORUM_FID", "37"))
    pages = max(1, int(max_pages or 3))
    return get_list(max_pages=pages, fid=weekly_fid, purpose="weekly")


def fetch_magnets_for_targets(
    items: List[dict],
    target_ids: set,
    client: Optional[ForumClient] = None,
) -> Dict[str, dict]:
    """对 target_ids 中出现在列表的条目进帖抽 magnet。

    返回 {AVID: {magnet, forumUrl, title, target meta...}}
    """
    targets = {str(x).upper() for x in (target_ids or set())}
    own = client is None
    client = client or ForumClient()
    if own and not client.ensure_safe():
        return {}

    # 保序：列表已是新→旧；每个 id 只进一次帖
    hits = []
    seen = set()
    for item in items:
        avid = (item.get("id") or "").upper()
        if not avid or avid not in targets or avid in seen:
            continue
        if not item.get("forumUrl"):
            continue
        seen.add(avid)
        hits.append(item)

    _log(f"thread targets: {len(hits)} (from {len(targets)} missing_cn)")
    out: Dict[str, dict] = {}
    for idx, item in enumerate(hits):
        avid = item["id"].upper()
        url = item["forumUrl"]
        _log(f"thread {idx + 1}/{len(hits)}: {avid} -> {url}")
        magnet = client.fetch_thread_magnet(url)
        if magnet:
            out[avid] = {
                "id": avid,
                "magnet": magnet,
                "forumUrl": url,
                "title": item.get("titleZh") or item.get("title") or "",
                "postDate": item.get("postDate") or "",
            }
            _log(f"  magnet ok ({magnet[:60]}...)")
        else:
            _log(f"  no magnet in thread")
        if idx + 1 < len(hits):
            delay = random.uniform(THREAD_DELAY_MIN, THREAD_DELAY_MAX)
            _log(f"  sleep {delay:.1f}s before next thread")
            time.sleep(delay)
    return out
