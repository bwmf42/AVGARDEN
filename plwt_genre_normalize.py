#!/usr/bin/env python3
"""One-shot: rewrite weekly.json genres via genre_zh map+memory (no network AI)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")
from src.weekly import genre_zh

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_JSON = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")


def main():
    items = json.load(open(WEEKLY_JSON, encoding="utf-8"))
    changed_items = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        if genre_zh.normalize_item_genres(it):
            changed_items += 1
    genre_zh.save_memory()
    tmp = WEEKLY_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WEEKLY_JSON)
    print(
        f"[GenreNorm] items_changed={changed_items}/{len(items)} "
        f"memory={genre_zh._MEMORY_PATH} keys={len(genre_zh.load_memory())}",
        flush=True,
    )


if __name__ == "__main__":
    main()
