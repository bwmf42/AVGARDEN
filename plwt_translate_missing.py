#!/usr/bin/env python3
"""Fill missing titleZh via DeepSeek; strip actress names from titleZh.

Safe to run on a schedule (uses weekly_update_lock).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")

from weekly_store import atomic_write_json, weekly_update_lock
from weekly_updater import (
    WEEKLY_JSON,
    batch_translate,
    clear_untranslatable_title_zh,
    log,
    strip_actresses_from_title_zh,
)
from src.weekly import actresses as actress_util, blocking


def main():
    with weekly_update_lock(WEEKLY_JSON):
        import json

        with open(WEEKLY_JSON, encoding="utf-8") as handle:
            items = json.load(handle)
        rules = blocking.load_rules()
        eligible = [item for item in items if not blocking.match_reason(item, rules)]
        titles_before = [str(item.get("titleZh") or "") for item in items]
        cleared = clear_untranslatable_title_zh(eligible)
        if cleared:
            log(f"Cleared {cleared} untranslatable titleZh fields")
        missing_before = sum(
            1
            for i in eligible
            if actress_util.item_needs_title_zh(i)
        )
        log(f"Missing titleZh before: {missing_before}")
        stripped = strip_actresses_from_title_zh(eligible)
        if stripped:
            log(f"Stripped actress names from {stripped} titleZh")
        ok, fail = batch_translate(items, checkpoint_path=WEEKLY_JSON)
        titles_changed = titles_before != [str(item.get("titleZh") or "") for item in items]
        if stripped or titles_changed:
            atomic_write_json(WEEKLY_JSON, items)
        else:
            log("No title changes; weekly.json left untouched")
        missing_after = sum(
            1
            for i in eligible
            if actress_util.item_needs_title_zh(i)
        )
        log(
            f"Done ok={ok} fail={fail} stripped={stripped} "
            f"cleared={cleared} missing_after={missing_after} path={WEEKLY_JSON}"
        )


if __name__ == "__main__":
    main()
