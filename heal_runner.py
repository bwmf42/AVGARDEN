#!/usr/bin/env python3
"""AVGARDEN 自愈：诊断 + 可逆修复（P0/P1）。

不重刮、不删种文件、不换节点（节点由 mihomo 98堂 url-test 负责）。
前台只写有动作/需人的摘要；明细 print 到 docker 日志。
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or "/app")

from src.log_writer import cleanup as log_cleanup
from src.log_writer import write as log_write

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_JSON = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
STATE_PATH = os.environ.get("STATE_PATH", "/db/queue_state.json")
QUEUE_PATH = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
HEAL_STATE_PATH = os.environ.get("HEAL_STATE_PATH", "/db/heal_state.json")
LAST_SCRAPE_PATH = os.environ.get("LAST_SCRAPE_PATH", "/db/last_scrape.json")

HEAL_ENABLE = os.environ.get("HEAL_ENABLE", "1").strip().lower() in ("1", "true", "yes", "on")
HEAL_TITLEZH = os.environ.get("HEAL_TITLEZH", "1").strip().lower() in ("1", "true", "yes", "on")
HEAL_LOCK = os.environ.get("HEAL_LOCK", "1").strip().lower() in ("1", "true", "yes", "on")
HEAL_QUEUE_SYNC = os.environ.get("HEAL_QUEUE_SYNC", "1").strip().lower() in ("1", "true", "yes", "on")
HEAL_PROBE = os.environ.get("HEAL_PROBE", "1").strip().lower() in ("1", "true", "yes", "on")
HEAL_COOLDOWN_M = max(5, int(os.environ.get("HEAL_COOLDOWN_M", "60") or "60"))
STUCK_SCRAPE_H = float(os.environ.get("HEAL_STUCK_SCRAPE_H", "8") or "8")

QB_URL = os.environ.get("QBITTORRENT_URL", "http://127.0.0.1:8080")
QB_USERNAME = os.environ.get("QBITTORRENT_USERNAME", "admin")
QB_PASSWORD = os.environ.get("QBITTORRENT_PASSWORD", "")
DS_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_DS_RAW = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash").strip()
DS_MODEL = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}.get(_DS_RAW, _DS_RAW)
TRANSLATE_API_BASE = os.environ.get("TRANSLATE_API_BASE", "").strip().rstrip("/")
TRANSLATE_API_KEY = os.environ.get("TRANSLATE_API_KEY", "").strip()
TRANSLATE_MODEL = (os.environ.get("TRANSLATE_MODEL") or "gpt-5.4").strip()

_QB_DONE = frozenset({"queuedUP", "uploading", "stalledUP", "pausedUP", "stoppedUP", "forcedUP"})
_QB_ACTIVE = frozenset({
    "downloading", "stalledDL", "metaDL", "forcedDL", "queuedDL",
    "pausedDL", "stoppedDL", "checkingDL", "allocating", "moving", "checkingResumeData",
})


def log(msg: str) -> None:
    print(f"[Heal] {msg}", flush=True)


def _env_true(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _state_file_lock(path: str):
    """File lock context manager for STATE_PATH specifically."""
    from contextlib import contextmanager
    lock_path = path + ".lock"

    @contextmanager
    def _lock():
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return _lock()


def load_json(path: str, default: Any) -> Any:
    """Load JSON with file lock for STATE_PATH."""
    try:
        if path == STATE_PATH:
            with _state_file_lock(path):
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
        else:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
    except Exception as e:
        log(f"load {path}: {e}")
    return default


def save_json(path: str, data: Any) -> None:
    """Save JSON with file lock for STATE_PATH."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"

        def _write():
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)

        if path == STATE_PATH:
            with _state_file_lock(path):
                _write()
        else:
            _write()
    except Exception as e:
        log(f"save {path}: {e}")


def cooldown_ok(state: dict, key: str, minutes: Optional[float] = None) -> bool:
    last = float((state.get("cooldown") or {}).get(key) or 0)
    wait_m = HEAL_COOLDOWN_M if minutes is None else float(minutes)
    return (time.time() - last) >= wait_m * 60


def mark_cooldown(state: dict, key: str) -> None:
    state.setdefault("cooldown", {})[key] = time.time()


def report(msg: str) -> None:
    """前台一行。"""
    log_write("Heal", msg)
    log(msg)


# ---------- diagnose helpers ----------

def count_titlezh_gaps(items: Optional[list] = None) -> int:
    if items is None:
        items = load_json(WEEKLY_JSON, [])
    try:
        from src.weekly import actresses as actress_util, blocking
        rules = blocking.load_rules()
    except Exception:
        actress_util = None
        blocking = None
        rules = None
    n = 0
    for i in items or []:
        if not isinstance(i, dict):
            continue
        if blocking is not None and blocking.match_reason(i, rules):
            continue
        valid = (
            not actress_util.item_needs_title_zh(i)
            if actress_util is not None
            else bool(str(i.get("titleZh") or "").strip())
        )
        if str(i.get("title") or "").strip() and not valid:
            n += 1
    return n


def list_related_pids() -> List[Tuple[int, str]]:
    """(pid, cmdline) for weekly/translate/heal."""
    out = []
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
            except Exception:
                continue
            if not cmd:
                continue
            low = cmd.lower()
            if any(
                k in low
                for k in (
                    "weekly_updater",
                    "plwt_translate_missing",
                    "heal_runner",
                )
            ):
                # skip self
                if str(os.getpid()) in cmd and "heal_runner" in low:
                    if pid == os.getpid():
                        continue
                out.append((pid, cmd[:200]))
    except Exception as e:
        log(f"list pids: {e}")
    return out


def lock_held_by_someone(lock_path: str) -> bool:
    """True if exclusive flock currently held by another process."""
    if not os.path.exists(lock_path):
        return False
    try:
        with open(lock_path, "a+", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except Exception:
        return False


def scrape_process_etime_hours() -> Optional[float]:
    for pid, cmd in list_related_pids():
        if "weekly_updater" not in cmd:
            continue
        try:
            # /proc/pid/stat field 22 starttime; simpler: use etime via status
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
                stat = f.read()
            # starttime is field 22 (1-based) after comm in parens
            rparen = stat.rfind(")")
            fields = stat[rparen + 2 :].split()
            starttime_ticks = int(fields[19])  # 22nd field overall, 20th after comm
            hz = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")) if hasattr(os, "sysconf") else 100
            try:
                hz = os.sysconf("SC_CLK_TCK")
            except Exception:
                hz = 100
            with open("/proc/uptime", "r", encoding="utf-8") as f:
                uptime = float(f.read().split()[0])
            start_sec = starttime_ticks / float(hz)
            age = max(0.0, uptime - start_sec)
            return age / 3600.0
        except Exception:
            return None
    return None


def qb_login_and_list() -> Tuple[bool, str, Optional[list]]:
    import http.cookiejar

    if not QB_PASSWORD:
        return False, "QBITTORRENT_PASSWORD is not configured", None
    try:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        login = f"{QB_URL}/api/v2/auth/login"
        data = f"username={urllib.parse.quote(QB_USERNAME)}&password={urllib.parse.quote(QB_PASSWORD)}".encode()
        resp = opener.open(urllib.request.Request(login, data=data), timeout=8)
        body = resp.read().decode().strip()
        if body not in ("Ok.", "Ok"):
            return False, f"login body={body[:40]!r}", None
        info = opener.open(
            urllib.request.Request(f"{QB_URL}/api/v2/torrents/info?category=AV_GARDEN"),
            timeout=15,
        )
        raw = info.read().decode()
        torrents = json.loads(raw) if raw else []
        if not isinstance(torrents, list):
            return False, "torrents not list", None
        return True, "ok", torrents
    except Exception as e:
        return False, str(e)[:160], None


def _chat_endpoint(base: str) -> str:
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def probe_translation() -> Tuple[bool, str]:
    """Probe the same translation provider that Weekly uses."""
    if TRANSLATE_API_BASE and TRANSLATE_API_KEY:
        provider = "GPT 中继"
        base = TRANSLATE_API_BASE
        key = TRANSLATE_API_KEY
        model = TRANSLATE_MODEL
    elif DS_API_KEY:
        provider = "DeepSeek"
        base = "https://api.deepseek.com"
        key = DS_API_KEY
        model = DS_MODEL
    else:
        return False, "未配置翻译 API"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 4,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        _chat_endpoint(base),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode())
        if provider == "DeepSeek":
            try:
                from src.status_report import record_deepseek_usage
                record_deepseek_usage(1)
            except Exception:
                pass
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if content is None:
            return False, "empty content"
        return True, f"{provider} · model={model}"
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)[:160]


def probe_deepseek() -> Tuple[bool, str]:
    """Compatibility alias for older callers and persisted health data."""
    return probe_translation()


def probe_plwt() -> Tuple[bool, str]:
    """Read-only: safe gate + at least one list item."""
    try:
        from src.weekly import chinese_forum, sources

        proxy = os.environ.get("PROXY") or None
        sources.set_proxy(proxy)
        chinese_forum.set_proxy(proxy)
        items = chinese_forum.get_weekly_list(max_pages=1, fid="37")
        if items:
            return True, f"list={len(items)}"
        return False, "empty list"
    except Exception as e:
        return False, str(e)[:160]


def code_from_torrent(t: dict) -> str:
    from video_id import normalize_video_id

    tags = str(t.get("tags") or "")
    for tag in tags.split(","):
        tag = tag.strip().upper()
        if not tag:
            continue
        n = normalize_video_id(tag) or tag
        if re.match(r"^[A-Z0-9]+-\d+", n):
            return n
    for field in (t.get("name", ""), t.get("content_path", "")):
        m = re.search(r"([A-Z0-9]{2,10}-\d{2,6})", str(field or "").upper())
        if m:
            n = normalize_video_id(m.group(1)) or m.group(1)
            if re.match(r"^[A-Z0-9]+-\d+", n):
                return n
    return ""


def diagnose() -> Dict[str, Any]:
    items = load_json(WEEKLY_JSON, [])
    gaps = count_titlezh_gaps(items)
    lock_path = WEEKLY_JSON + ".lock"
    held = lock_held_by_someone(lock_path)
    pids = list_related_pids()
    scrape_h = scrape_process_etime_hours()
    qb_ok, qb_msg, torrents = qb_login_and_list()
    missing_files = 0
    qb_codes_active: set = set()
    qb_codes_done: set = set()
    if torrents:
        for t in torrents:
            st = str(t.get("state") or "")
            code = code_from_torrent(t)
            if st == "missingFiles":
                missing_files += 1
            if code and st in _QB_ACTIVE:
                qb_codes_active.add(code)
            if code and (st in _QB_DONE or float(t.get("progress") or 0) >= 0.999):
                qb_codes_done.add(code)

    state_items = load_json(STATE_PATH, [])
    if not isinstance(state_items, list):
        state_items = []
    queue_codes = set()
    try:
        if os.path.exists(QUEUE_PATH):
            with open(QUEUE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    c = line.strip().upper()
                    if c:
                        queue_codes.add(c)
    except Exception:
        pass

    orphan_queued = []
    done_but_queued = []
    state_codes = set()
    for it in state_items:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code") or "").upper()
        if not code:
            continue
        state_codes.add(code)
        st = str(it.get("status") or "")
        if st != "queued":
            continue
        if code in qb_codes_done:
            done_but_queued.append(code)
        elif code not in queue_codes and code not in qb_codes_active and code not in qb_codes_done:
            # not in text queue and not active in qB
            orphan_queued.append(code)

    # 反向孤儿：qB 中活跃但 queue_state 没记录
    qb_orphan = []
    all_qb_codes = qb_codes_active | qb_codes_done
    for code in all_qb_codes:
        if code not in state_codes:
            qb_orphan.append(code)

    d = {
        "titlezh_gaps": gaps,
        "lock_path": lock_path,
        "lock_held": held,
        "related_pids": pids,
        "scrape_hours": scrape_h,
        "qb_ok": qb_ok,
        "qb_msg": qb_msg,
        "missing_files": missing_files,
        "orphan_queued": orphan_queued,
        "done_but_queued": done_but_queued,
        "qb_orphan": qb_orphan,
        "weekly_items": len(items) if isinstance(items, list) else 0,
    }
    if HEAL_PROBE:
        translation_ok, translation_msg = probe_translation()
        d["translation_ok"] = translation_ok
        d["translation_msg"] = translation_msg
        # Keep legacy fields so older status readers and heal state remain readable.
        d["deepseek_ok"] = translation_ok
        d["deepseek_msg"] = translation_msg
        plwt_ok, plwt_msg = probe_plwt()
        d["plwt_ok"] = plwt_ok
        d["plwt_msg"] = plwt_msg
    return d


# ---------- heal actions ----------

def heal_titlezh(state: dict, gaps: int) -> bool:
    if not HEAL_TITLEZH or gaps <= 0:
        return False
    if not cooldown_ok(state, "titlezh"):
        log("titlezh cooldown, skip")
        return False
    # if scrape/translate holding weekly lock, skip
    if lock_held_by_someone(WEEKLY_JSON + ".lock"):
        log("weekly lock held, skip titlezh")
        return False
    py = os.environ.get("WORKER_PYTHON", "/app/venv/bin/python3")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)) or "/app", "plwt_translate_missing.py")
    log(f"running plwt_translate_missing (gaps={gaps})")
    try:
        proc = subprocess.run(
            [py, script],
            timeout=3600,
            capture_output=True,
            text=True,
            check=False,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        ok = fail = 0
        m = re.search(r"ok=(\d+).*fail=(\d+)", out)
        if m:
            ok, fail = int(m.group(1)), int(m.group(2))
        mark_cooldown(state, "titlezh")
        if ok or fail or proc.returncode != 0:
            report(f"补译 ok={ok} fail={fail}" + (f" exit={proc.returncode}" if proc.returncode else ""))
            return True
        log("titlezh: nothing changed")
        return False
    except Exception as e:
        mark_cooldown(state, "titlezh")
        report(f"补译异常: {e}")
        return True


def heal_queue_sync(state: dict, diag: dict) -> bool:
    if not HEAL_QUEUE_SYNC:
        return False
    if not cooldown_ok(state, "queue_sync"):
        log("queue_sync cooldown, skip")
        return False
    orphan = list(diag.get("orphan_queued") or [])
    done = list(diag.get("done_but_queued") or [])
    qb_orphan = list(diag.get("qb_orphan") or [])
    if not orphan and not done and not qb_orphan:
        return False
    items = load_json(STATE_PATH, [])
    if not isinstance(items, list):
        return False
    orphan_set = set(orphan)
    done_set = set(done)
    new_items = []
    removed = 0
    marked = 0
    added = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code") or "").upper()
        if code in orphan_set and str(it.get("status") or "") == "queued":
            removed += 1
            continue
        if code in done_set and str(it.get("status") or "") == "queued":
            it = dict(it)
            it["status"] = "done"
            it["_post_done"] = True
            marked += 1
        new_items.append(it)
    # 补登记 qB 反向孤儿（qB 有但 queue_state 没有）
    for code in qb_orphan:
        new_items.append({
            "code": code,
            "status": "processing",
            "source": "unknown",
            "added_at": int(time.time()),
            "_heal_recovered": True
        })
        added += 1
    if removed or marked or added:
        save_json(STATE_PATH, new_items)
        mark_cooldown(state, "queue_sync")
        report(f"队列对齐: 清 orphan={removed} 同步完成={marked} 补登记={added}")
        return True
    return False


def heal_probes_alert(state: dict, diag: dict) -> bool:
    if not HEAL_PROBE:
        return False
    acted = False
    if not diag.get("qb_ok") and cooldown_ok(state, "probe_qb"):
        report(f"qB API 不可用: {diag.get('qb_msg')}")
        mark_cooldown(state, "probe_qb")
        acted = True
    translation_ok = diag.get("translation_ok", diag.get("deepseek_ok"))
    if translation_ok is False and cooldown_ok(state, "probe_translation"):
        report(f"翻译服务不可用: {diag.get('translation_msg') or diag.get('deepseek_msg')}")
        mark_cooldown(state, "probe_translation")
        acted = True
    if diag.get("plwt_ok") is False and cooldown_ok(state, "probe_plwt"):
        report(f"98堂不可达: {diag.get('plwt_msg')}（不自动重刮）")
        mark_cooldown(state, "probe_plwt")
        acted = True
    mf = int(diag.get("missing_files") or 0)
    if mf > 0 and cooldown_ok(state, "probe_missing"):
        report(f"qB missingFiles={mf}（需人工清理，不自动删种）")
        mark_cooldown(state, "probe_missing")
        acted = True
    scrape_h = diag.get("scrape_hours")
    if scrape_h is not None and scrape_h >= STUCK_SCRAPE_H and cooldown_ok(state, "probe_stuck"):
        report(f"weekly_updater 已运行 {scrape_h:.1f}h（可能卡住，需人工看日志）")
        mark_cooldown(state, "probe_stuck")
        acted = True
    return acted


def heal_lock_note(diag: dict) -> None:
    """flock 随进程释放；仅记录长时间占用。"""
    if not HEAL_LOCK:
        return
    if diag.get("lock_held") and diag.get("scrape_hours") is None:
        # lock held but no weekly_updater we found — unusual
        log(f"lock held but no weekly_updater pid seen: {diag.get('related_pids')}")


def heal_link115(state: dict) -> bool:
    """把 115生活备份/艾薇 下番号软链到 /data 根（不出现「艾薇」目录）。"""
    if not _env_true("HEAL_LINK115", "1"):
        return False
    # 短冷却，避免与 launcher 专用 watcher 重复刷日志
    if not cooldown_ok(state, "link115", minutes=max(5, int(os.environ.get("HEAL_LINK115_COOLDOWN_M", "15") or "15"))):
        return False
    try:
        from tools.maintenance.link_115_aiwei_into_data_root import sync_links

        stats = sync_links(data_root=SAVE_PATH)
        mark_cooldown(state, "link115")
        if stats.get("missing_source"):
            log(f"link115: source missing under {SAVE_PATH}")
            return False
        n = int(stats.get("linked") or 0) + int(stats.get("refreshed") or 0)
        if n or stats.get("removed_aiwei"):
            names = ",".join((stats.get("names") or [])[:8])
            report(
                f"115链接: 新增/更新={n}"
                + (f" ({names})" if names else "")
                + (f" 去艾薇入口={stats.get('removed_aiwei')}" if stats.get("removed_aiwei") else "")
            )
            return True
        log(f"link115: ok skipped={stats.get('skipped')}")
        return False
    except Exception as e:
        mark_cooldown(state, "link115")
        log(f"link115 error: {e}")
        return False


def heal_recover_transient(state: dict) -> bool:
    """捞回瞬时/系统类失败项（如 generator bug），清 retry 并重新入队。"""
    if not _env_true("HEAL_RECOVER_FAILED", "1"):
        return False
    if not cooldown_ok(
        state,
        "recover_failed",
        minutes=max(15, int(os.environ.get("HEAL_RECOVER_COOLDOWN_M", "30") or "30")),
    ):
        return False
    try:
        from src.failure_recovery import recover_transient_failures

        hours = float(os.environ.get("RECOVER_FAILED_MAX_AGE_H", "72") or "72")
        stats = recover_transient_failures(max_age_hours=hours, default_target="qb")
        mark_cooldown(state, "recover_failed")
        rec = stats.get("recovered") or []
        if rec:
            report(f"自动恢复失败项 {len(rec)} 个: {','.join(rec[:12])}")
            return True
        log("recover_failed: nothing")
        return False
    except Exception as e:
        mark_cooldown(state, "recover_failed")
        log(f"recover_failed error: {e}")
        return False


def run_once(do_heal: bool = True) -> dict:
    if not HEAL_ENABLE and do_heal:
        log("HEAL_ENABLE=0, diagnose only")
        do_heal = False

    state = load_json(HEAL_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}

    log("diagnose…")
    diag = diagnose()
    log(
        f"gaps={diag.get('titlezh_gaps')} lock_held={diag.get('lock_held')} "
        f"qb={diag.get('qb_ok')} missingFiles={diag.get('missing_files')} "
        f"orphan={len(diag.get('orphan_queued') or [])} "
        f"done_queued={len(diag.get('done_but_queued') or [])} "
        f"qb_orphan={len(diag.get('qb_orphan') or [])} "
        f"plwt={diag.get('plwt_ok')} translation={diag.get('translation_ok', diag.get('deepseek_ok'))} "
        f"scrape_h={diag.get('scrape_hours')}"
    )

    actions = []
    if do_heal:
        heal_lock_note(diag)
        if heal_titlezh(state, int(diag.get("titlezh_gaps") or 0)):
            actions.append("titlezh")
        if heal_queue_sync(state, diag):
            actions.append("queue_sync")
        if heal_probes_alert(state, diag):
            actions.append("probe_alert")
        if heal_link115(state):
            actions.append("link115")
        if heal_recover_transient(state):
            actions.append("recover_failed")

    try:
        log_cleanup()
    except Exception as e:
        log(f"log_cleanup: {e}")

    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    state["last_diag"] = {
        k: diag.get(k)
        for k in (
            "titlezh_gaps",
            "qb_ok",
            "missing_files",
            "plwt_ok",
            "translation_ok",
            "translation_msg",
            "deepseek_ok",
            "deepseek_msg",
            "scrape_hours",
        )
    }
    save_json(HEAL_STATE_PATH, state)

    # Persist probe snapshot for /api/status (atomic tmp+rename)
    health_payload = None
    try:
        from src.status_report import write_health_json

        health_payload = write_health_json(diag)
        log(f"health.json overall={health_payload.get('overall')}")
    except Exception as e:
        log(f"write health.json: {e}")

    return {"diag": diag, "actions": actions, "health": health_payload}


def main():
    import argparse

    p = argparse.ArgumentParser(description="AVGARDEN heal runner")
    p.add_argument("--diagnose-only", action="store_true")
    p.add_argument("--json", action="store_true", help="print result JSON")
    args = p.parse_args()
    result = run_once(do_heal=not args.diagnose_only)
    if args.json:
        # pids not serializable cleanly
        d = result.get("diag") or {}
        d = dict(d)
        d["related_pids"] = [list(x) for x in (d.get("related_pids") or [])]
        print(json.dumps({"actions": result.get("actions"), "diag": d}, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
