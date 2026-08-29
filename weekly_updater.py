#!/usr/bin/env python3
"""周推荐自动更新 — 98堂 forum-37 列表 + 个体页/图源补充细节"""
import json, os, re, sys, time, random, urllib.error, urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.weekly import actresses as actress_util, sources, javbus, sukebei, merge, artwork, enrich, chinese_forum, blocking
from weekly_store import atomic_write_json, weekly_update_lock
from weekly_watched_store import mark_many, mark_watched

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_DIR = os.path.join(SAVE_PATH, "__weekly__")
WEEKLY_JSON = os.path.join(WEEKLY_DIR, "weekly.json")
WEEKLY_WATCHED_FILE = os.environ.get("WEEKLY_WATCHED_FILE", "/db/weekly_watched.json")
PROXY = os.environ.get("PROXY", "") or None
MAX_NEW = int(os.environ.get("WEEKLY_MAX_NEW", "20"))
MAX_AGE = int(os.environ.get("WEEKLY_MAX_AGE", "30"))
MAX_PAGES = int(os.environ.get("WEEKLY_MAX_PAGES", "3"))
BACKFILL_DAYS = int(os.environ.get("WEEKLY_BACKFILL_DAYS", "0") or "0")
LIST_ONLY = os.environ.get("WEEKLY_LIST_ONLY", "").strip().lower() in ("1", "true", "yes", "on")
DS_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
# DeepSeek retired deepseek-chat; map legacy name so old compose env still works.
_DS_MODEL_RAW = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash").strip()
DS_MODEL = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}.get(_DS_MODEL_RAW, _DS_MODEL_RAW)
# Prefer the configured OpenAI-compatible relay (for example Hermes/code77).
# DeepSeek remains a compatibility fallback for installations without relay settings.
TRANSLATE_API_BASE = os.environ.get("TRANSLATE_API_BASE", "").strip().rstrip("/")
TRANSLATE_API_KEY = os.environ.get("TRANSLATE_API_KEY", "").strip()
TRANSLATE_MODEL = (os.environ.get("TRANSLATE_MODEL") or "gpt-5.4").strip()
# Per-title retries + exponential backoff on 429/5xx
DS_TRANSLATE_RETRIES = int(os.environ.get("DS_TRANSLATE_RETRIES", "4"))
DS_TRANSLATE_TIMEOUT = float(os.environ.get("DS_TRANSLATE_TIMEOUT", "45"))
DS_TRANSLATE_SLEEP = float(os.environ.get("DS_TRANSLATE_SLEEP", "0.6"))
DS_TRANSLATE_PASSES = int(os.environ.get("DS_TRANSLATE_PASSES", "3"))
DS_TRANSLATE_CHECKPOINT = int(os.environ.get("DS_TRANSLATE_CHECKPOINT", "10"))

def log(msg):
    print(f"[WeeklyUpdater] {msg}", flush=True)


def _http_status(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return None


def translation_provider():
    """Return the provider name and model used by Weekly translation."""
    if TRANSLATE_API_BASE and TRANSLATE_API_KEY:
        return "relay", TRANSLATE_MODEL
    if DS_API_KEY:
        return "deepseek", DS_MODEL
    return "", ""


def _chat_endpoint(base):
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _chat_completion(base, api_key, model, messages, temperature=0.3):
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": 256,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        _chat_endpoint(base),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=DS_TRANSLATE_TIMEOUT) as resp:
        result = json.loads(resp.read().decode())
    return ((result.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "") or ""


def _deepseek_chat(messages, temperature=0.3):
    return _chat_completion(
        "https://api.deepseek.com",
        DS_API_KEY,
        DS_MODEL,
        messages,
        temperature=temperature,
    )


def translate_title_once(avid, title, actresses=None):
    """Translate one title. Returns Chinese titleZh without actress names."""
    provider, model = translation_provider()
    if not provider:
        raise RuntimeError("translation API is not configured")
    from src.weekly import actresses as actress_util

    body, _names = actress_util.title_for_translate(title, actresses)
    text = f"{avid}: {body}" if body else f"{avid}: {title}"
    # Primary prompt, then milder fallback if content filter returns empty
    prompts = [
        actress_util.translate_system_prompt(),
        "将日文影片标题译为简洁简体中文。只输出中文标题，不要女优姓名，不要解释。",
    ]
    last_empty = False
    for i, sys_p in enumerate(prompts):
        messages = [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": text},
        ]
        if provider == "relay":
            zh = _chat_completion(
                TRANSLATE_API_BASE,
                TRANSLATE_API_KEY,
                model,
                messages,
                temperature=0.3 if i == 0 else 0.2,
            ).strip()
        else:
            zh = _deepseek_chat(messages, temperature=0.3 if i == 0 else 0.2).strip()
        if zh:
            # Never append actress names into titleZh — they live in actresses[]
            return zh
        last_empty = True
    if last_empty:
        raise RuntimeError("empty translation")
    raise RuntimeError("empty translation")


def translate_title_with_retry(avid, title, actresses=None):
    """Retry with exponential backoff on 429/5xx and transient errors."""
    last_err = None
    for attempt in range(1, DS_TRANSLATE_RETRIES + 1):
        try:
            return translate_title_once(avid, title, actresses=actresses)
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


def strip_actresses_from_title_zh(items):
    """Strip actress names from existing titleZh (title vs name separation)."""
    from src.weekly import actresses as actress_util

    n = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        actress_util.ensure_actresses(item)
        if actress_util.finalize_title_zh(item):
            n += 1
    return n


def clear_untranslatable_title_zh(items):
    """Clear invented translations when the source is only a code or name."""
    n = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("titleZh") or "").strip() and not actress_util.item_has_translatable_title(item):
            item["titleZh"] = ""
            n += 1
    return n


def _legacy_first_seen(item):
    """Best available timestamp for items created before retention tracking."""
    for key in ("postDate", "releaseDate"):
        raw = str(item.get(key) or "").strip()
        if not raw:
            continue
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(raw[:10], fmt).astimezone().isoformat(timespec="seconds")
            except ValueError:
                continue
    return None


def mark_existing_blocked(items, rules=None):
    """Mark existing filtered items and prevent later artwork/translation refreshes."""
    rules = rules or blocking.load_rules()
    count = changed = 0
    blocked_ids = set()
    watched_entries = []
    for item in items or []:
        reason = blocking.match_reason(item, rules)
        if not reason:
            continue
        code = str(item.get("id") or "").upper()
        if not code:
            continue
        blocked_ids.add(code)
        count += 1
        before = dict(item)
        blocking.strip_expensive_fields(item)
        changed += item != before
        watched_entries.append({
            "id": code,
            "watched_at": _legacy_first_seen(item),
            "reason": reason,
        })
    mark_many(WEEKLY_WATCHED_FILE, watched_entries)
    return blocked_ids, count, changed


def enrich_new_item(item, rules=None):
    """Enrich metadata first; only unblocked items receive artwork and magnets."""
    rules = rules or blocking.load_rules()
    avid = str(item.get("id") or "").upper()
    if not item.get("title"):
        item["title"] = avid

    enrich.enrich_item(item, save_dir=WEEKLY_DIR, download_images=False)
    reason = blocking.match_reason(item, rules)
    if reason:
        blocking.strip_expensive_fields(item)
        mark_watched(WEEKLY_WATCHED_FILE, avid, reason=reason)
        log(f"  blocked {avid}: {reason}; skipped artwork/magnet/translation")
        return reason

    artwork.download_for_item(
        item,
        WEEKLY_DIR,
        force_cover=javbus.cover_needs_refresh(avid, WEEKLY_DIR),
        force_fanarts=javbus.cover_needs_refresh(avid, WEEKLY_DIR),
    )
    if item.get("cover"):
        item["poster"] = item["cover"]

    magnet = ""
    forum_url = (item.get("forumUrl") or "").strip()
    if forum_url:
        try:
            chinese_forum.set_proxy(PROXY)
            magnet = chinese_forum.fetch_thread_magnet(forum_url) or ""
            if magnet:
                log(f"  magnet from forum for {avid}")
        except Exception as e:
            log(f"  forum magnet fail {avid}: {e}")
    if not magnet:
        magnet = sukebei.search(avid, "") or ""
        if magnet:
            log(f"  magnet from sukebei for {avid}")
    item["magnet"] = magnet
    return ""


def batch_translate(items, passes=None, checkpoint_path=None):
    """Translate missing titleZh with multi-pass retry and optional checkpoint writes.

    Returns (ok_count, fail_count).
    """
    if passes is None:
        passes = max(1, DS_TRANSLATE_PASSES)

    rules = blocking.load_rules()
    eligible = [item for item in items if not blocking.match_reason(item, rules)]

    cleared = clear_untranslatable_title_zh(eligible)
    if cleared:
        log(f"Cleared {cleared} untranslatable titleZh fields")
        if checkpoint_path:
            atomic_write_json(checkpoint_path, items)

    provider, model = translation_provider()
    if not provider:
        log("Skip translate: no translation API configured")
        return 0, 0
    log(f"Translate provider={provider} model={model}")

    # Always peel names off existing titleZh first
    stripped = strip_actresses_from_title_zh(eligible)
    if stripped:
        log(f"Stripped actress names from {stripped} titleZh fields")
        if checkpoint_path:
            atomic_write_json(checkpoint_path, items)

    total_ok = total_fail = 0
    for pass_i in range(1, passes + 1):
        to_translate = [
            i for i in eligible
            if actress_util.item_needs_title_zh(i)
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
            item["titleZh"] = ""
            try:
                actress_util.ensure_actresses(item)
                item["titleZh"] = translate_title_with_retry(
                    avid, title, actresses=item.get("actresses")
                )
                actress_util.finalize_title_zh(item)
                if not actress_util.item_has_valid_title_zh(item):
                    item["titleZh"] = ""
                    raise RuntimeError("invalid or truncated translation")
                ok += 1
            except Exception as e:
                item["titleZh"] = ""
                fail += 1
                log(f"Translate {avid} failed after retries: {e}")
            if (idx + 1) % 10 == 0 or (idx + 1) == n:
                log(f"Translated {idx + 1}/{n} (ok={ok} fail={fail})")
            # Checkpoint so SIGTERM does not lose whole pass
            if checkpoint_path and DS_TRANSLATE_CHECKPOINT > 0:
                if (idx + 1) % DS_TRANSLATE_CHECKPOINT == 0 or (idx + 1) == n:
                    try:
                        atomic_write_json(checkpoint_path, items)
                    except Exception as e:
                        log(f"Translate checkpoint write failed: {e}")
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

    if os.path.exists(WEEKLY_JSON):
        with open(WEEKLY_JSON, encoding="utf-8") as handle:
            existing = json.load(handle)
    else:
        existing = []
    if not existing:
        existing = []
    existing_ids = {i["id"].upper() for i in existing if i.get("id")}
    log(f"Existing: {len(existing)}")

    rules = blocking.load_rules()
    blocked_ids, blocked_count, blocked_changed = mark_existing_blocked(existing, rules)
    if blocked_count:
        log(f"Existing blocked: {blocked_count} (metadata-only, watched retention)")

    # 1. 补封面（列表挂了也先落盘）
    if not LIST_ONLY:
        n = merge.fill_covers(
            [item for item in existing if str(item.get("id") or "").upper() not in blocked_ids],
            WEEKLY_DIR,
        )
        if n:
            log(f"Filled {n} covers")
        if n or blocked_changed:
            try:
                atomic_write_json(WEEKLY_JSON, existing)
            except Exception as e:
                log(f"Cover checkpoint write failed: {e}")

    # 2. 列表：默认 98堂 forum-37，失败重试 + 回退 JavBus（见 sources.get_recent）
    recent = []
    try:
        if BACKFILL_DAYS > 0:
            stop = (datetime.now() - timedelta(days=BACKFILL_DAYS)).strftime("%Y-%m-%d")
            backfill_pages = max(1, int(os.environ.get("WEEKLY_BACKFILL_MAX_PAGES", "40") or "40"))
            log(f"List backfill: forum-37 until {stop} (days={BACKFILL_DAYS}, max_pages={backfill_pages})")
            recent = sources.get_recent_plwt_until(stop, max_pages=backfill_pages) or []
        else:
            recent = sources.get_recent(MAX_PAGES) or []
    except Exception as e:
        log(f"List source crashed (continuing without new items): {e}")
        recent = []

    freshness_counts = {}
    for item in recent:
        marker = item.get("freshness") or item.get("source") or "unknown"
        freshness_counts[marker] = freshness_counts.get(marker, 0) + 1
    extra_codes = [
        c.strip().upper()
        for c in (os.environ.get("WEEKLY_BACKFILL_CODES") or "").split(",")
        if c.strip()
    ]
    if extra_codes:
        extra_set = set(extra_codes)
        stubs = []
        for code in extra_codes:
            stubs.append({
                "id": code,
                "title": code,
                "cover": "",
                "releaseDate": "",
                "freshness": "backfill-code",
                "source": "plwt-37",
                "forumUrl": "",
                "postDate": "",
            })
            log(f"Backfill extra code: {code}")
        recent = stubs + [r for r in recent if str(r.get("id") or "").upper() not in extra_set]

    if recent:
        log(f"Weekly list items: {len(recent)} ({freshness_counts})")
    else:
        log(
            "WARNING: weekly list empty after plwt retries + fallback; "
            "no new titles this run (covers/titleZh still updated)"
        )

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
            enrich_new_item(item, rules)
            # 补齐缺失字段
            for k in ["titleZh", "titleJp", "poster", "duration", "actresses", "genres", "fanarts", "size"]:
                item.setdefault(k, "")
            for k in ["actresses", "genres", "fanarts"]:
                item.setdefault(k, [])
        item.setdefault("hasChinese", False)
        item.setdefault("downloaded", False)

        if BACKFILL_DAYS > 0 and not merge.is_recent(item, MAX_AGE):
            log(f"  skip {avid}: release {item.get('releaseDate') or 'unknown'} older than {MAX_AGE}d")
            continue

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

    # 3. DeepSeek: missing titleZh (multi-pass + checkpoint; leftovers → launcher retry)
    if not LIST_ONLY:
        batch_translate(merged, checkpoint_path=WEEKLY_JSON)

    atomic_write_json(WEEKLY_JSON, merged)
    still = sum(
        1 for i in merged
        if actress_util.item_needs_title_zh(i)
    )
    log(f"=== Done: {len(merged)} items (+{len(new_items)} new) titleZh_missing={still} ===")
    # 供 heal 探针展示上次刮削结果（不触发自动重刮）
    try:
        from datetime import datetime as _dt
        last_path = os.environ.get("LAST_SCRAPE_PATH", "/db/last_scrape.json")
        payload = {
            "ok": True,
            "ts": _dt.now().isoformat(timespec="seconds"),
            "total": len(merged),
            "new": len(new_items),
            "titlezh_missing": still,
            "source": os.environ.get("WEEKLY_LIST_SOURCE", "plwt"),
        }
        os.makedirs(os.path.dirname(last_path) or ".", exist_ok=True)
        with open(last_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"last_scrape write failed: {e}")


def main():
    try:
        with weekly_update_lock(WEEKLY_JSON):
            _main_locked()
    except Exception as e:
        log(f"FATAL: {e}")
        try:
            from datetime import datetime as _dt
            last_path = os.environ.get("LAST_SCRAPE_PATH", "/db/last_scrape.json")
            os.makedirs(os.path.dirname(last_path) or ".", exist_ok=True)
            with open(last_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "ok": False,
                        "ts": _dt.now().isoformat(timespec="seconds"),
                        "error": str(e)[:300],
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
