#!/usr/bin/env python3
"""Backfill weekly covers + fanarts (default: filtered 未看 only).

Scope matches frontend Weekly 未看 tab:
  /api/weekly (already blocked-genre/actress filtered) ∩ not watched ∩ not in queue ∩ not downloaded.
"""
import json
import os
import sys
import time
import traceback
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")
from src.weekly import artwork

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_DIR = os.path.join(SAVE_PATH, "__weekly__")
WEEKLY_JSON = os.path.join(WEEKLY_DIR, "weekly.json")
PROXY = os.environ.get("PROXY", "") or None
SAVE_EVERY = int(os.environ.get("BACKFILL_SAVE_EVERY", "15"))
FANART_LIMIT = int(os.environ.get("BACKFILL_FANART_LIMIT", "12"))
ONLY_MISSING_COVER = os.environ.get("BACKFILL_COVER_ONLY", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Default: only 未看 after tag filter (frontend unwatched count ~492)
UNWATCHED_ONLY = os.environ.get("BACKFILL_UNWATCHED_ONLY", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
SERVER_URL = os.environ.get("WEEKLY_BACKFILL_SERVER_URL", "http://127.0.0.1:31471")
LIMIT = int(os.environ.get("BACKFILL_LIMIT", "0"))
START = int(os.environ.get("BACKFILL_START", "0"))
_LOG_PATH = os.environ.get("BACKFILL_LOG", "/tmp/plwt_art_backfill.log")


def log(msg):
    line = f"[ArtBF] {msg}"
    print(line, flush=True)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as lf:
            lf.write(line + "\n")
            lf.flush()
    except OSError:
        pass


def normalize_id(raw):
    return str(raw or "").strip().upper()


def load_json_url(path, default):
    try:
        with urllib.request.urlopen(f"{SERVER_URL}{path}", timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log(f"Load {path} failed: {e}")
        return default


def queue_codes():
    queue = load_json_url("/api/queue/", [])
    if not isinstance(queue, list):
        return set()
    return {normalize_id(item.get("code")) for item in queue if normalize_id(item.get("code"))}


def visible_unwatched_ids():
    """Same scope as frontend 未看: API weekly − watched − queue − downloaded."""
    weekly = load_json_url("/api/weekly", [])
    watched = load_json_url("/api/weekly-watched", [])
    watched_set = {normalize_id(x) for x in watched if normalize_id(x)}
    queue_set = queue_codes()
    result = []
    seen = set()
    for item in weekly if isinstance(weekly, list) else []:
        avid = normalize_id(item.get("id"))
        if not avid or avid in seen:
            continue
        if item.get("downloaded") or avid in watched_set or avid in queue_set:
            continue
        seen.add(avid)
        result.append(avid)
    return result


def has_local_cover(item):
    c = str(item.get("cover") or "")
    if not c.startswith("/file/"):
        return False
    path = os.path.join(SAVE_PATH, c[len("/file/") :])
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 8000
    except OSError:
        return False


def local_fanart_count(item):
    code = (item.get("id") or "").upper()
    folder = os.path.join(WEEKLY_DIR, code)
    if not os.path.isdir(folder):
        return 0
    n = 0
    prefix = f"{code}-fanart-"
    for name in os.listdir(folder):
        if name.startswith(prefix) and name.lower().endswith(
            (".jpg", ".jpeg", ".webp", ".png")
        ):
            try:
                if os.path.getsize(os.path.join(folder, name)) > 3000:
                    n += 1
            except OSError:
                pass
    return n


def needs(item):
    if not (item.get("id") or "").strip():
        return False, False
    need_c = not has_local_cover(item)
    need_f = local_fanart_count(item) < 1
    if ONLY_MISSING_COVER:
        need_f = False
    return need_c, need_f


def main():
    open(_LOG_PATH, "w").close()
    artwork.set_proxy(PROXY)
    log(
        f"PROXY={PROXY} unwatched_only={UNWATCHED_ONLY} "
        f"save_every={SAVE_EVERY} fanart_limit={FANART_LIMIT}"
    )
    items = json.load(open(WEEKLY_JSON, encoding="utf-8"))
    by_id = {normalize_id(it.get("id")): it for it in items if isinstance(it, dict)}

    if UNWATCHED_ONLY:
        scope_ids = visible_unwatched_ids()
        log(f"visible 未看 scope={len(scope_ids)} (api weekly − watched − queue − downloaded)")
    else:
        scope_ids = [normalize_id(it.get("id")) for it in items if it.get("id")]
        log(f"full weekly scope={len(scope_ids)}")

    todo = []
    for avid in scope_ids:
        it = by_id.get(avid)
        if not it:
            continue
        nc, nf = needs(it)
        if nc or nf:
            todo.append((it, nc, nf))

    log(f"weekly.json={len(items)} need_art_in_scope={len(todo)} (start={START} limit={LIMIT})")
    if START:
        todo = todo[START:]
    if LIMIT > 0:
        todo = todo[:LIMIT]

    ok_c = ok_f = fail = 0
    t0 = time.time()
    for i, (item, nc, nf) in enumerate(todo, 1):
        avid = normalize_id(item.get("id"))
        try:
            artwork.download_for_item(
                item,
                WEEKLY_DIR,
                force_cover=nc,
                force_fanarts=nf,
                limit=FANART_LIMIT if nf else 0,
            )
            got_c = has_local_cover(item)
            n_f = local_fanart_count(item)
            if nc and got_c:
                ok_c += 1
            if nf and n_f:
                ok_f += 1
            if (nc and not got_c) and (nf and not n_f):
                fail += 1
            src = item.get("artworkSource") or "-"
            log(
                f"[{i}/{len(todo)}] {avid} cover={'Y' if got_c else 'N'} "
                f"fanarts={n_f} src={src} need_c={nc} need_f={nf}"
            )
        except Exception as e:
            fail += 1
            log(f"[{i}/{len(todo)}] {avid} ERR {e}")
            traceback.print_exc()

        if i % SAVE_EVERY == 0 or i == len(todo):
            tmp = WEEKLY_JSON + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            os.replace(tmp, WEEKLY_JSON)
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            log(
                f"--- saved i={i} ok_c={ok_c} ok_f={ok_f} fail={fail} {rate:.2f}/s ---"
            )

    log(
        f"=== DONE ok_c={ok_c} ok_f={ok_f} fail={fail} "
        f"elapsed={time.time() - t0:.0f}s ==="
    )


if __name__ == "__main__":
    main()
