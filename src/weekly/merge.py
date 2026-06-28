import time, random, re
from datetime import datetime, timedelta

_DATE_FORMATS = [
    "%Y-%m-%d",       # 2026-06-20
    "%Y/%m/%d",       # 2026/06/20
    "%Y.%m.%d",       # 2026.06.20
    "%Y年%m月%d日",    # 2026年6月20日
    "%Y%m%d",         # 20260620
    "%Y-%m-%d %H:%M", # 2026-06-20 14:30
    "%Y/%m/%d %H:%M", # 2026/06/20 14:30
]

def _parse_date(d):
    """兼容多种日期格式，返回 datetime 或 None"""
    d = d.strip()
    if not d:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(d, fmt)
        except ValueError:
            continue
    # 兜底：从字符串里提取 YYYY-MM-DD 片段
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", d)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None

def is_recent(item, days=30):
    """判断是否为最近 N 天内的新片"""
    d = item.get("releaseDate", "")
    if not d:
        return False
    rd = _parse_date(d)
    if rd is None:
        return False
    return rd >= datetime.now() - timedelta(days=days)

def merge(existing, new_items, max_days=30):
    """合并：长期保留未下载的，已下载只保留近期，新片按窗口纳入"""
    merged = {}
    for item in existing:
        avid = item.get("id", "").upper()
        if not avid:
            continue
        if item.get("downloaded"):
            if not is_recent(item, 7):
                continue
        merged[avid] = item
    for item in new_items:
        avid = item.get("id", "").upper()
        if not avid or avid in merged:
            continue
        if is_recent(item, max_days):
            merged[avid] = item
    return sorted(merged.values(), key=lambda x: x.get("releaseDate", ""), reverse=True)

def fill_covers(items, save_dir):
    """给远程 URL 或无封面的项目下载封面到本地"""
    from . import javbus
    remote = [
        i for i in items
        if not i.get("cover")
        or i["cover"].startswith("http")
        or javbus.cover_needs_refresh(i.get("id", ""), save_dir)
    ]
    for item in remote:
        avid = item["id"]
        force = bool(item.get("cover")) and not item["cover"].startswith("http")
        if force:
            html = javbus.fetch_page(avid)
            detail = javbus.parse_page(html) if html else {}
            if detail.get("cover"):
                item["cover"] = detail["cover"]
        item["cover"] = javbus.download_cover(avid, item.get("cover", ""), save_dir, force=force)
        time.sleep(random.uniform(5, 10))
    return len(remote)
