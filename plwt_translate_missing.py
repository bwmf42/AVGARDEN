#!/usr/bin/env python3
"""Fill missing titleZh via DeepSeek; strip actress names from titleZh.

Safe to run on a schedule (uses weekly_update_lock).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")

from weekly_store import atomic_write_json, weekly_update_lock
from weekly_updater import WEEKLY_JSON, batch_translate, log, strip_actresses_from_title_zh


def main():
    with weekly_update_lock(WEEKLY_JSON):
        import json

        items = json.load(open(WEEKLY_JSON, encoding="utf-8"))
        missing_before = sum(
            1
            for i in items
            if not str(i.get("titleZh") or "").strip()
            and str(i.get("title") or "").strip()
        )
        log(f"Missing titleZh before: {missing_before}")
        stripped = strip_actresses_from_title_zh(items)
        if stripped:
            log(f"Stripped actress names from {stripped} titleZh")
        ok, fail = batch_translate(items, checkpoint_path=WEEKLY_JSON)
        atomic_write_json(WEEKLY_JSON, items)
        missing_after = sum(
            1
            for i in items
            if not str(i.get("titleZh") or "").strip()
            and str(i.get("title") or "").strip()
        )
        log(
            f"Done ok={ok} fail={fail} stripped={stripped} "
            f"missing_after={missing_after} path={WEEKLY_JSON}"
        )


if __name__ == "__main__":
    main()
