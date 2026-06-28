#!/usr/bin/env python3
"""周推荐自动更新 — JavBus 主页 + 个体页补充细节"""
import json, os, sys, time, random, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.weekly import sources, javbus, sukebei, merge

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_DIR = os.path.join(SAVE_PATH, "__weekly__")
WEEKLY_JSON = os.path.join(WEEKLY_DIR, "weekly.json")
PROXY = os.environ.get("PROXY", "") or None
MAX_NEW = int(os.environ.get("WEEKLY_MAX_NEW", "20"))
MAX_AGE = int(os.environ.get("WEEKLY_MAX_AGE", "30"))
MAX_PAGES = int(os.environ.get("WEEKLY_MAX_PAGES", "3"))
LIST_ONLY = os.environ.get("WEEKLY_LIST_ONLY", "").strip().lower() in ("1", "true", "yes", "on")
DS_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DS_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

def log(msg):
    print(f"[WeeklyUpdater] {msg}", flush=True)

def batch_translate(items):
    """逐条翻译缺少 titleZh 的标题，避免批量翻译时相似标题串位"""
    to_translate = [i for i in items if not i.get("titleZh") and i.get("title")]
    if not to_translate:
        return
    total = len(to_translate)
    for idx, item in enumerate(to_translate):
        title = f"{item['id']}: {item['title']}"
        payload = json.dumps({
            "model": DS_MODEL,
            "messages": [
                {"role": "system", "content": "你是日语翻译助手。将以下日文成人影片标题翻译为简洁的中文，只输出翻译结果，不要任何解释。"},
                {"role": "user", "content": title}
            ],
            "max_tokens": 256,
            "temperature": 0.3
        }).encode()
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {DS_API_KEY}"}
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())
            zh = result["choices"][0]["message"]["content"].strip()
            if zh:
                item["titleZh"] = zh
            if (idx + 1) % 10 == 0:
                log(f"Translated {idx + 1}/{total}")
            time.sleep(0.5)
        except Exception as e:
            log(f"Translate {item['id']} failed: {e}")

def main():
    log("=== Start ===")
    sources.set_proxy(PROXY)
    javbus.set_proxy(PROXY)
    sukebei.set_proxy(PROXY)

    existing = json.load(open(WEEKLY_JSON)) if os.path.exists(WEEKLY_JSON) else []
    if not existing:
        existing = []
    existing_ids = {i["id"].upper() for i in existing if i.get("id")}
    log(f"Existing: {len(existing)}")

    # 1. 补封面
    if not LIST_ONLY:
        n = merge.fill_covers(existing, WEEKLY_DIR)
        if n:
            log(f"Filled {n} covers")

    # 2. JavBus 主页获取番号+封面+标题（一步到位）
    recent = sources.get_recent(MAX_PAGES)
    freshness_counts = {}
    for item in recent:
        marker = item.get("freshness") or "unknown"
        freshness_counts[marker] = freshness_counts.get(marker, 0) + 1
    log(f"JavBus homepage fresh items: {len(recent)} ({freshness_counts})")

    new_items = []
    for item in recent:
        avid = item["id"].upper()
        if avid in existing_ids:
            continue

        if LIST_ONLY:
            item.setdefault("title", avid)
            item.setdefault("titleZh", "")
            item.setdefault("titleJp", "")
            item.setdefault("poster", item.get("cover", ""))
            item.setdefault("duration", "")
            item.setdefault("size", "")
            item.setdefault("magnet", "")
            item.setdefault("actresses", [])
            item.setdefault("genres", [])
            item.setdefault("fanarts", [])
        else:
            # 个体页补充演员/标签/时长
            html = javbus.fetch_page(avid)
            detail = javbus.parse_page(html) if html else {}
            item.update({k: v for k, v in detail.items() if v})
            if not item.get("title"):
                item["title"] = avid

            item["cover"] = javbus.download_cover(avid, item.get("cover", ""), WEEKLY_DIR, force=javbus.cover_needs_refresh(avid, WEEKLY_DIR))
            item["magnet"] = sukebei.search(avid, html)
            # 补齐缺失字段
            for k in ["titleZh", "titleJp", "poster", "duration", "actresses", "genres", "fanarts", "size"]:
                item.setdefault(k, "")
            for k in ["actresses", "genres", "fanarts"]:
                item.setdefault(k, [])
        item.setdefault("hasChinese", False)
        item.setdefault("downloaded", False)

        new_items.append(item)
        log(f"  + {avid}: {item.get('title','')[:50]} ({item.get('releaseDate','')})")
        if len(new_items) >= MAX_NEW:
            break
        if not LIST_ONLY:
            time.sleep(random.uniform(5, 10))

    merged = merge.merge(existing, new_items, MAX_AGE) if new_items else existing

    # 统一修复字段类型（老数据可能有 "" 而不是 false）
    for item in merged:
        for k in ("downloaded", "hasChinese"):
            if item.get(k) != True:
                item[k] = False
        if not isinstance(item.get("actresses"), list): item["actresses"] = []
        if not isinstance(item.get("genres"), list): item["genres"] = []
        if not isinstance(item.get("fanarts"), list): item["fanarts"] = []

    # 3. DeepSeek 批量翻译缺少 titleZh 的 items
    if not LIST_ONLY:
        batch_translate(merged)

    os.makedirs(WEEKLY_DIR, exist_ok=True)
    tmp = WEEKLY_JSON + ".tmp"
    with open(tmp, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WEEKLY_JSON)
    log(f"=== Done: {len(merged)} items (+{len(new_items)} new) ===")

if __name__ == "__main__":
    main()
