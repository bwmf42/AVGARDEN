#!/usr/bin/env python3
"""One-shot: translate missing titleZh via DeepSeek (same hardened path as weekly_updater)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")

from weekly_store import atomic_write_json, weekly_update_lock
from weekly_updater import WEEKLY_JSON, batch_translate, log


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
        ok, fail = batch_translate(items)
        atomic_write_json(WEEKLY_JSON, items)
        missing_after = sum(
            1
            for i in items
            if not str(i.get("titleZh") or "").strip()
            and str(i.get("title") or "").strip()
        )
        log(
            f"Done ok={ok} fail={fail} missing_after={missing_after} "
            f"path={WEEKLY_JSON}"
        )


if __name__ == "__main__":
    main()
