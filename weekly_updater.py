#!/usr/bin/env python3
"""周推荐自动更新 — 98堂 forum-37 列表 + 个体页/图源补充细节"""
import json, os, sys, time, random, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.weekly import sources, javbus, sukebei, merge, artwork, enrich
from weekly_store import atomic_write_json, weekly_update_lock

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
# Per-title retries + exponential backoff on 429/5xx
DS_TRANSLATE_RETRIES = int(os.environ.get("DS_TRANSLATE_RETRIES", "4"))
DS_TRANSLATE_TIMEOUT = float(os.environ.get("DS_TRANSLATE_TIMEOUT", "45"))
DS_TRANSLATE_SLEEP = float(os.environ.get("DS_TRANSLATE_SLEEP", "0.6"))
DS_TRANSLATE_PASSES = int(os.environ.get("DS_TRANSLATE_PASSES", "2"))

def log(msg):
    print(f"[WeeklyUpdater] {msg}", flush=True)


def _http_status(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return None


def translate_title_once(avid, title):
    """Call DeepSeek for one title. Returns zh string or raises."""
    if not DS_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    text = f"{avid}: {title}"
    payload = json.dumps({
        "model": DS_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是日语翻译助手。将以下日文成人影片标题翻译为简洁的中文，"
                    "只输出翻译结果，不要任何解释。"
                ),
            },
            {"role": "user", "content": text},
        ],
        "max_tokens": 256,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DS_API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=DS_TRANSLATE_TIMEOUT) as resp:
        result = json.loads(resp.read().decode())
    zh = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
    zh = (zh or "").strip()
    if not zh:
        raise RuntimeError("empty translation")
    return zh


def translate_title_with_retry(avid, title):
    """Retry with exponential backoff on 429/5xx and transient errors."""
    last_err = None
    for attempt in range(1, DS_TRANSLATE_RETRIES + 1):
        try:
            return translate_title_once(avid, title)
        except Exception as e:
            last_err = e
            code = _http_status(e)
            retriable = code in (429, 500, 502, 503, 504) or code is None
            if not retriable or attempt >= DS_TRANSLATE_RETRIES:
                break
            # 503/429: longer backoff
            base = 2.0 if code in (429, 503) else 1.0
            delay = min(60.0, base * (2 ** (attempt - 1)) + random.uniform(0, 0.5))
            log(
                f"Translate {avid} attempt {attempt}/{DS_TRANSLATE_RETRIES} "
                f"failed ({e}); retry in {delay:.1f}s"
            )
            time.sleep(delay)
    raise last_err


def batch_translate(items, passes=None):
    """Translate missing titleZh with per-item retry; optional second pass for leftovers.

    Returns (ok_count, fail_count).
    """
    if passes is None:
        passes = max(1, DS_TRANSLATE_PASSES)
    if not DS_API_KEY:
        log("Skip translate: DEEPSEEK_API_KEY not set")
        return 0, 0

    total_ok = total_fail = 0
    for pass_i in range(1, passes + 1):
        to_translate = [
            i for i in items
            if not str(i.get("titleZh") or "").strip() and str(i.get("title") or "").strip()
        ]
        if not to_translate:
            if pass_i == 1:
                log("Translate: nothing missing")
            break
        log(f"Translate pass {pass_i}/{passes}: {len(to_translate)} titles")
        ok = fail = 0
        n = len(to_translate)
        for idx, item in enumerate(to_translate):
            avid = (item.get("id") or "").upper()
            title = item.get("title") or ""
            try:
                item["titleZh"] = translate_title_with_retry(avid, title)
                ok += 1
            except Exception as e:
                fail += 1
                log(f"Translate {avid} failed after retries: {e}")
            if (idx + 1) % 10 == 0 or (idx + 1) == n:
                log(f"Translated {idx + 1}/{n} (ok={ok} fail={fail})")
            time.sleep(DS_TRANSLATE_SLEEP)
        total_ok += ok
        total_fail += fail
        if fail == 0:
            break
        if pass_i < passes:
            wait = min(30.0, 3.0 * pass_i + random.uniform(0, 2))
            log(f"Translate pass {pass_i} left {fail} failures; wait {wait:.1f}s before next pass")
            time.sleep(wait)
    log(f"Translate done: ok={total_ok} fail={total_fail}")
    return total_ok, total_fail
def _main_locked():
    log("=== Start ===")
    sources.set_proxy(PROXY)
    javbus.set_proxy(PROXY)
    sukebei.set_proxy(PROXY)
    artwork.set_proxy(PROXY)
    enrich.set_proxy(PROXY)

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

    # 2. 98堂 forum-37 列表获取番号+标题（默认 3 页；封面稍后 MGS/DMM）
    recent = sources.get_recent(MAX_PAGES)
    freshness_counts = {}
    for item in recent:
        marker = item.get("freshness") or item.get("source") or "unknown"
        freshness_counts[marker] = freshness_counts.get(marker, 0) + 1
    log(f"Weekly list items: {len(recent)} ({freshness_counts})")

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
            # Exact source ordering is owned by enrich.py and artwork.py.
            if not item.get("title"):
                item["title"] = avid
            enrich.enrich_item(
                item,
                save_dir=WEEKLY_DIR,
                download_images=True,
                force_images=javbus.cover_needs_refresh(avid, WEEKLY_DIR),
            )
            item["magnet"] = sukebei.search(avid, "")
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

    # 3. DeepSeek: missing titleZh (retry + second pass for 503 leftovers)
    if not LIST_ONLY:
        batch_translate(merged)

    atomic_write_json(WEEKLY_JSON, merged)
    still = sum(
        1 for i in merged
        if not str(i.get("titleZh") or "").strip() and str(i.get("title") or "").strip()
    )
    log(f"=== Done: {len(merged)} items (+{len(new_items)} new) titleZh_missing={still} ===")


def main():
    with weekly_update_lock(WEEKLY_JSON):
        _main_locked()


if __name__ == "__main__":
    main()
