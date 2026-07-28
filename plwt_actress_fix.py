#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot: clean actress placeholders, extract names from JP title, fix titleZh tails."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")
from src.weekly import actresses as actress_util
from weekly_store import atomic_write_json, weekly_update_lock

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_JSON = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")


def migrate_blocked_spellings() -> int:
    """Rewrite blocked_actresses.txt: trim junk tails, keep one spelling per fold key."""
    path = actress_util._default_blocked_actresses_path()
    if not path or not os.path.isfile(path):
        print(f"[ActressFix] blocked skip (no file): {path}", flush=True)
        return 0
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    out = []
    seen_fold = set()
    changed = 0
    for ln in lines:
        raw = ln.strip()
        if not raw or raw.startswith("#"):
            out.append(ln)
            continue
        cleaned = raw.strip(" \t　（）()【】[]「」『』・·.,。．!！?？:：;；-_—–")
        if not cleaned:
            changed += 1
            continue
        key = actress_util.fold_actress_key(cleaned)
        if key in seen_fold:
            changed += 1
            continue
        seen_fold.add(key)
        if cleaned != raw:
            changed += 1
        out.append(cleaned)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
        if out:
            f.write("\n")
    os.replace(tmp, path)
    actress_util.load_blocked_actresses(force=True)
    print(f"[ActressFix] blocked path={path} lines_changed≈{changed}", flush=True)
    return changed


def _main_locked():
    migrate_blocked_spellings()
    items = json.load(open(WEEKLY_JSON, encoding="utf-8"))
    act_changed = 0
    zh_changed = 0
    cleared_dash = 0
    filled_from_title = 0
    snapped_blocked = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        before = list(it.get("actresses") or []) if isinstance(it.get("actresses"), list) else []
        had_dash = any(str(x).strip("-") == "" or str(x).strip() in ("----", "---", "--") for x in before)
        if actress_util.ensure_actresses(it):
            act_changed += 1
            after = it.get("actresses") or []
            if had_dash and not after:
                cleared_dash += 1
            if (not actress_util.clean_actresses(before)) and after:
                filled_from_title += 1
            # count snaps to blacklist spelling
            for a, b in zip(before, after):
                if a != b and actress_util.is_blocked_actress(b):
                    snapped_blocked += 1
        if actress_util.finalize_title_zh(it):
            zh_changed += 1

    atomic_write_json(WEEKLY_JSON, items)
    print(
        f"[ActressFix] items={len(items)} actress_changed={act_changed} "
        f"filled_from_title≈{filled_from_title} snapped_to_blocked≈{snapped_blocked} "
        f"titleZh_fixed={zh_changed}",
        flush=True,
    )


def main():
    with weekly_update_lock(WEEKLY_JSON):
        _main_locked()


if __name__ == "__main__":
    main()
