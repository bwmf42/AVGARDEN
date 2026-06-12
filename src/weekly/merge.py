import time, random
from datetime import datetime, timedelta

def is_recent(item, days=30):
    """判断是否为最近 N 天内的新片"""
    d = item.get("releaseDate", "")
    if not d:
        return False
    try:
        rd = datetime.strptime(d, "%Y-%m-%d")
        return rd >= datetime.now() - timedelta(days=days)
    except:
        return True

def merge(existing, new_items, max_days=30):
    """合并：保留未下载的 + 新片，去重，按日期排序"""
    merged = {}
    for item in existing:
        avid = item.get("id", "").upper()
        if not avid:
            continue
        if item.get("downloaded"):
            if not is_recent(item, 7):
                continue
        else:
            if not is_recent(item, max_days):
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
    remote = [i for i in items if not i.get("cover") or i["cover"].startswith("http")]
    for item in remote:
        avid = item["id"]
        item["cover"] = javbus.download_cover(avid, item.get("cover", ""), save_dir)
        time.sleep(random.uniform(5, 10))
    return len(remote)
