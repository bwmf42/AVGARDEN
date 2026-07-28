#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot: rewrite weekly genres + memory + blocked_genres to simplified canonical."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")
from src.weekly import genre_zh

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_JSON = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")


def migrate_blocked() -> int:
    """Rewrite blocked_genres.txt lines via translate_genre (dedupe, preserve order)."""
    path = genre_zh._default_blocked_path()
    if not path or not os.path.isfile(path):
        print(f"[GenreNorm] blocked skip (no file): {path}", flush=True)
        return 0
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    out = []
    seen = set()
    changed = 0
    for ln in lines:
        raw = ln.strip()
        if not raw or raw.startswith("#"):
            out.append(ln)
            continue
        # translate without snap-to-self loop: temporarily empty block list
        zh = genre_zh._to_simplified(raw)
        # Prefer map/memory meaning for known tags
        mapped = genre_zh._lookup_static(genre_zh._norm_key(raw)) or genre_zh._lookup_static(
            genre_zh._norm_key(zh)
        )
        if mapped:
            zh = genre_zh._to_simplified(mapped)
        else:
            # full translate but avoid snap forcing old spelling — clear block cache
            old_list = genre_zh._blocked_list
            old_fold = genre_zh._blocked_fold
            old_loaded = genre_zh._blocked_loaded
            genre_zh._blocked_list = []
            genre_zh._blocked_fold = {}
            genre_zh._blocked_loaded = True
            try:
                zh = genre_zh.translate_genre(raw)
            finally:
                genre_zh._blocked_list = old_list
                genre_zh._blocked_fold = old_fold
                genre_zh._blocked_loaded = old_loaded
        if zh in seen:
            changed += 1
            continue
        seen.add(zh)
        if zh != raw:
            changed += 1
        out.append(zh)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
        if out and not out[-1].endswith("\n"):
            f.write("\n")
    os.replace(tmp, path)
    genre_zh._blocked_loaded = False
    genre_zh.load_blocked_genres(force=True)
    print(f"[GenreNorm] blocked path={path} lines_changed≈{changed}", flush=True)
    return changed


def migrate_memory() -> int:
    """Re-translate all memory values to simplified canonical."""
    mem = genre_zh.load_memory(force=True)
    if not mem:
        print("[GenreNorm] memory empty", flush=True)
        return 0
    # Avoid snap forcing old blocked spellings while rewriting values
    old_list = genre_zh._blocked_list
    old_fold = genre_zh._blocked_fold
    old_loaded = genre_zh._blocked_loaded
    genre_zh._blocked_list = []
    genre_zh._blocked_fold = {}
    genre_zh._blocked_loaded = True
    changed = 0
    try:
        for k, v in list(mem.items()):
            nv = genre_zh.translate_genre(k)
            if not nv:
                nv = genre_zh._to_simplified(v)
            if nv != v:
                mem[k] = nv
                changed += 1
                genre_zh._memory_dirty = True
    finally:
        genre_zh._blocked_list = old_list
        genre_zh._blocked_fold = old_fold
        genre_zh._blocked_loaded = old_loaded
    genre_zh.save_memory()
    print(
        f"[GenreNorm] memory path={genre_zh._MEMORY_PATH} keys={len(mem)} values_changed={changed}",
        flush=True,
    )
    return changed


def migrate_weekly() -> int:
    if not os.path.isfile(WEEKLY_JSON):
        print(f"[GenreNorm] weekly skip (no file): {WEEKLY_JSON}", flush=True)
        return 0
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
        f"[GenreNorm] weekly items_changed={changed_items}/{len(items)} path={WEEKLY_JSON}",
        flush=True,
    )
    return changed_items


def main():
    # Order: blocked first (so snap uses new spellings), then memory, then weekly
    migrate_blocked()
    migrate_memory()
    migrate_weekly()
    print("[GenreNorm] done", flush=True)


if __name__ == "__main__":
    main()
