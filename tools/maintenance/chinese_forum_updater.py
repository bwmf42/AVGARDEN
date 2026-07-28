#!/usr/bin/env python3
"""中文字幕论坛列表更新（list-only，不进帖、不刮磁链/封面）。

默认写本机 SAVE_PATH/__weekly__/weekly.json，用于验证。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from src.weekly import chinese_forum

SAVE_PATH = os.environ.get("SAVE_PATH", str(PROJECT_ROOT / "work" / "chinese_scrape"))
WEEKLY_DIR = os.path.join(SAVE_PATH, "__weekly__")
WEEKLY_JSON = os.path.join(WEEKLY_DIR, "weekly.json")
PROXY = os.environ.get("PROXY", "") or None
MAX_PAGES = int(os.environ.get("CHINESE_FORUM_MAX_PAGES", "20"))


def log(msg: str):
    print(f"[ChineseForumUpdater] {msg}", flush=True)


def _load_existing():
    if not os.path.exists(WEEKLY_JSON):
        return []
    with open(WEEKLY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def merge_chinese_list(existing: list, scraped: list):
    """合并：不覆盖已有 cover/magnet；标记 hasChinese；新号插入。"""
    by_id = {}
    for item in existing:
        avid = (item.get("id") or "").upper()
        if not avid:
            continue
        by_id[avid] = item

    new_count = 0
    updated_count = 0
    for item in scraped:
        avid = (item.get("id") or "").upper()
        if not avid:
            continue
        if avid in by_id:
            cur = by_id[avid]
            changed = False
            if cur.get("hasChinese") is not True:
                cur["hasChinese"] = True
                changed = True
            if not cur.get("titleZh") and item.get("titleZh"):
                cur["titleZh"] = item["titleZh"]
                changed = True
            if not cur.get("title") and item.get("title"):
                cur["title"] = item["title"]
                changed = True
            if item.get("forumUrl") and not cur.get("forumUrl"):
                cur["forumUrl"] = item["forumUrl"]
                changed = True
            if item.get("category") and not cur.get("category"):
                cur["category"] = item["category"]
                changed = True
            if item.get("source") and not cur.get("source"):
                cur["source"] = item["source"]
                changed = True
            # genres 补中文字幕标签
            genres = cur.get("genres") if isinstance(cur.get("genres"), list) else []
            if "中文字幕" not in genres:
                genres = list(genres) + ["中文字幕"]
                cur["genres"] = genres
                changed = True
            if changed:
                updated_count += 1
            by_id[avid] = cur
        else:
            by_id[avid] = item
            new_count += 1

    merged = list(by_id.values())
    for item in merged:
        if item.get("hasChinese") is not True:
            item["hasChinese"] = False
        if item.get("downloaded") is not True:
            item["downloaded"] = False
        for k in ("actresses", "genres", "fanarts"):
            if not isinstance(item.get(k), list):
                item[k] = []
    merged.sort(key=lambda x: x.get("releaseDate", ""), reverse=True)
    return merged, new_count, updated_count


def main():
    t0 = time.time()
    log("=== Start (list-only, no thread visits) ===")
    log(f"SAVE_PATH={SAVE_PATH}")
    log(f"WEEKLY_JSON={WEEKLY_JSON}")
    log(f"MAX_PAGES={MAX_PAGES}")
    log(f"BASE={chinese_forum.BASE} FID={chinese_forum.FID}")
    log(
        f"PAGE_DELAY={chinese_forum.PAGE_DELAY_MIN}-{chinese_forum.PAGE_DELAY_MAX}s "
        f"PROXY={'set' if PROXY else 'none'}"
    )

    chinese_forum.set_proxy(PROXY)
    existing = _load_existing()
    log(f"Existing items: {len(existing)}")

    scraped = chinese_forum.get_list(MAX_PAGES)
    log(f"Scraped unique with id: {len(scraped)}")

    merged, new_count, updated_count = merge_chinese_list(existing, scraped)

    os.makedirs(WEEKLY_DIR, exist_ok=True)
    # 同时落一份纯本次刮取结果，方便核对
    scrape_out = os.path.join(WEEKLY_DIR, "chinese_forum_scrape.json")
    tmp_scrape = scrape_out + ".tmp"
    with open(tmp_scrape, "w", encoding="utf-8") as f:
        json.dump(scraped, f, ensure_ascii=False, indent=2)
    os.replace(tmp_scrape, scrape_out)

    tmp = WEEKLY_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WEEKLY_JSON)

    elapsed = time.time() - t0
    log(
        f"=== Done: total={len(merged)} new={new_count} updated={updated_count} "
        f"scraped={len(scraped)} elapsed={elapsed:.1f}s ==="
    )
    log(f"Wrote {WEEKLY_JSON}")
    log(f"Wrote {scrape_out}")

    # 抽样
    for item in scraped[:10]:
        log(f"  sample {item.get('id')}: {str(item.get('titleZh') or item.get('title') or '')[:60]}")


if __name__ == "__main__":
    main()
