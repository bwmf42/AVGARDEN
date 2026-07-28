#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-translate titleZh that were over-stripped (code + names only)."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")
from src.weekly import actresses as actress_util
from weekly_store import atomic_write_json, weekly_update_lock
from weekly_updater import WEEKLY_JSON, log, translate_title_with_retry

_CODE = re.compile(
    r"^(?:[A-Z0-9]{2,15}-?\d+[A-Z]?)[:：\s\-]*",
    re.I,
)


def is_broken_title_zh(item: dict) -> bool:
    zh = str(item.get("titleZh") or "").strip()
    title = str(item.get("title") or "").strip()
    if not zh or not title:
        return False
    acts = actress_util.clean_actresses(item.get("actresses") or [])
    body = zh
    for n in acts:
        body = body.replace(n, " ")
    body = _CODE.sub("", body)
    body = re.sub(r"[\s　、,·・：:\-—–]+", "", body)
    # broken if almost no content left but JP title is long
    if len(body) < 6 and len(actress_util.strip_code_prefix(title)) > 20:
        return True
    # also if zh is shorter than half of title and mostly names
    if acts and len(zh) < 22 and len(title) > 35:
        return True
    return False


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
                ok += 1
            except Exception as e:
                fail += 1
                log(f"Repair {avid} failed: {e}")
            if (idx + 1) % 10 == 0 or (idx + 1) == len(broken):
                log(f"Repaired {idx + 1}/{len(broken)} ok={ok} fail={fail}")
        atomic_write_json(WEEKLY_JSON, items)
        log(f"Done ok={ok} fail={fail} path={WEEKLY_JSON}")


if __name__ == "__main__":
    main()
