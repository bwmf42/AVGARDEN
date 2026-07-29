#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-translate titleZh that were over-stripped (code + names only)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")
from src.weekly import actresses as actress_util
from weekly_store import atomic_write_json, weekly_update_lock
from weekly_updater import WEEKLY_JSON, log, translate_title_with_retry

def is_broken_title_zh(item: dict) -> bool:
    zh = str(item.get("titleZh") or "").strip()
    title = str(item.get("title") or "").strip()
    if not zh or not title:
        return False
    return not actress_util.item_has_valid_title_zh(item)


def main():
    with weekly_update_lock(WEEKLY_JSON):
        items = json.load(open(WEEKLY_JSON, encoding="utf-8"))
        broken = [it for it in items if isinstance(it, dict) and is_broken_title_zh(it)]
        log(f"Broken titleZh candidates: {len(broken)}")
        ok = fail = 0
        for idx, it in enumerate(broken):
            avid = (it.get("id") or "").upper()
            try:
                actress_util.ensure_actresses(it)
                # force re-translate
                it["titleZh"] = ""
                zh = translate_title_with_retry(
                    avid, it.get("title") or "", actresses=it.get("actresses")
                )
                it["titleZh"] = zh
                actress_util.finalize_title_zh(it)
                if not actress_util.item_has_valid_title_zh(it):
                    it["titleZh"] = ""
                    raise RuntimeError("invalid or truncated translation")
                ok += 1
            except Exception as e:
                it["titleZh"] = ""
                fail += 1
                log(f"Repair {avid} failed: {e}")
            if (idx + 1) % 10 == 0 or (idx + 1) == len(broken):
                log(f"Repaired {idx + 1}/{len(broken)} ok={ok} fail={fail}")
        atomic_write_json(WEEKLY_JSON, items)
        log(f"Done ok={ok} fail={fail} path={WEEKLY_JSON}")


if __name__ == "__main__":
    main()
