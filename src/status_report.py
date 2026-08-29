"""Status artifacts for AVGARDEN: DB backup, health.json, daily-report, translation usage."""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from queue_store import read_json as locked_read_json
from queue_store import update_json as locked_update_json
from queue_store import write_json as locked_write_json

STATUS_DIR = os.environ.get("STATUS_DIR", "/db/status")
HEALTH_PATH = os.environ.get("HEALTH_PATH", os.path.join(STATUS_DIR, "health.json"))
DAILY_REPORT_PATH = os.environ.get(
    "DAILY_REPORT_PATH", os.path.join(STATUS_DIR, "daily-report.json")
)
DS_USAGE_PATH = os.environ.get("DS_USAGE_PATH", os.path.join(STATUS_DIR, "ds_usage.json"))
BACKUPS_DIR = os.environ.get("DB_BACKUPS_DIR", "/db/backups")
DB_PATH = os.environ.get("DB_PATH", "/db/downloaded.db")
LOG_FILE = os.environ.get(
    "LOG_FILE",
    os.path.join(os.environ.get("LOG_DIR", "/logs"), "av-garden.log"),
)
SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
QUEUE_API_URL = os.environ.get("QUEUE_API_URL", "http://127.0.0.1:31473")
BACKUP_KEEP = max(1, int(os.environ.get("DB_BACKUP_KEEP", "7") or "7"))
REPORT_KEEP = max(1, int(os.environ.get("DAILY_REPORT_KEEP", "7") or "7"))
DEEPSEEK_DAILY_ALERT_LIMIT = max(
    1, int(os.environ.get("DEEPSEEK_DAILY_ALERT_LIMIT", "500") or "500")
)


def _log(msg: str) -> None:
    print(f"[StatusReport] {msg}", flush=True)


def atomic_write_json(path: str, data: Any) -> None:
    locked_write_json(path, data)


def read_json(path: str, default: Any = None) -> Any:
    fallback = default if default is not None else {}
    return locked_read_json(path, fallback)


def du_bytes(path: str) -> int:
    if not path or not os.path.exists(path):
        return 0
    try:
        total = 0
        if os.path.isfile(path):
            return int(os.path.getsize(path))
        for root, _dirs, files in os.walk(path):
            for name in files:
                fp = os.path.join(root, name)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total
    except Exception:
        return 0


def du_human(n: int) -> str:
    x = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(x)}{unit}"
            return f"{x:.1f}{unit}"
        x /= 1024.0
    return f"{n}B"


def prune_glob(dir_path: str, prefix: str, suffix: str, keep: int) -> None:
    if not os.path.isdir(dir_path):
        return
    files = []
    for name in os.listdir(dir_path):
        if name.startswith(prefix) and name.endswith(suffix):
            files.append(os.path.join(dir_path, name))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for old in files[keep:]:
        try:
            os.unlink(old)
            _log(f"pruned {old}")
        except OSError as e:
            _log(f"prune fail {old}: {e}")


def backup_sqlite(
    db_path: str = DB_PATH,
    backups_dir: str = BACKUPS_DIR,
    keep: int = BACKUP_KEEP,
) -> Dict[str, Any]:
    """Concurrent-safe snapshot via sqlite3.Connection.backup + gzip.

    Returns dict with ok, path, msg, check_ok.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "path": "",
        "msg": "",
        "check_ok": False,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    if not os.path.exists(db_path):
        result["msg"] = f"db missing: {db_path}"
        _log(result["msg"])
        return result

    os.makedirs(backups_dir, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    raw_path = os.path.join(backups_dir, f"downloaded-{day}.db")
    gz_path = raw_path + ".gz"
    raw_fd, tmp_raw = tempfile.mkstemp(prefix=f"downloaded-{day}.", suffix=".db.tmp", dir=backups_dir)
    os.close(raw_fd)
    gz_fd, tmp_gz = tempfile.mkstemp(prefix=f"downloaded-{day}.", suffix=".db.gz.tmp", dir=backups_dir)
    os.close(gz_fd)

    try:
        src = sqlite3.connect(db_path, timeout=30)
        try:
            dst = sqlite3.connect(tmp_raw)
            try:
                src.backup(dst)
                dst.commit()
            finally:
                dst.close()
        finally:
            src.close()

        # integrity on snapshot
        check = sqlite3.connect(tmp_raw)
        try:
            row = check.execute("PRAGMA quick_check").fetchone()
            check_ok = bool(row and str(row[0]).lower() == "ok")
        finally:
            check.close()
        result["check_ok"] = check_ok
        if not check_ok:
            result["msg"] = f"quick_check failed: {row!r}"
            try:
                os.unlink(tmp_raw)
            except OSError:
                pass
            _log(result["msg"])
            return result

        with open(tmp_raw, "rb") as fin, gzip.open(tmp_gz, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        os.replace(tmp_gz, gz_path)
        try:
            os.unlink(tmp_raw)
        except OSError:
            pass
        # remove uncompressed same-day if any
        if os.path.exists(raw_path):
            try:
                os.unlink(raw_path)
            except OSError:
                pass

        prune_glob(backups_dir, "downloaded-", ".db.gz", keep)
        result["ok"] = True
        result["path"] = gz_path
        result["msg"] = f"backup ok size={du_human(os.path.getsize(gz_path))}"
        _log(result["msg"] + f" -> {gz_path}")
        return result
    except Exception as e:
        result["msg"] = f"backup failed: {e}"
        _log(result["msg"])
        return result
    finally:
        for p in (tmp_raw, tmp_gz):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except OSError:
                pass


def apply_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    """WAL + busy_timeout (call after connect). Used when P0-2 is enabled."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error as e:
        _log(f"pragma: {e}")


def version_status() -> Dict[str, Any]:
    """Lightweight version lag check (in-container BUILD_INFO / VERSION)."""
    info: Dict[str, Any] = {"ok": True, "behind": False, "msg": "ok", "ts": _now_ts()}
    version = "dev"
    tree = ""
    git_dirty = False
    for path in ("/app/VERSION", "VERSION"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    version = v
                    break
        except OSError:
            pass
    for path in ("/app/BUILD_INFO.json", "BUILD_INFO.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                version = str(data.get("version") or version)
                tree = str(data.get("tree_hash") or data.get("tree_hash_server") or "")
                git_dirty = bool(data.get("git_dirty"))
            break
        except Exception:
            continue
    info["version"] = version
    info["tree_hash"] = tree
    info["git_dirty"] = git_dirty
    expected = (os.environ.get("AVGARDEN_EXPECTED_TREE_HASH") or "").strip()
    behind = False
    msgs = []
    if expected and tree and expected != tree:
        behind = True
        msgs.append(f"expected {expected[:12]} got {tree[:12]}")
    elif expected and (not tree or tree in ("unknown", "dev")):
        behind = True
        msgs.append("tree_hash missing/unknown")
    elif git_dirty:
        msgs.append("运行中（含未提交改动）")
    elif not tree or tree in ("unknown", "dev"):
        msgs.append("运行中")
    info["behind"] = behind
    info["ok"] = not behind
    info["msg"] = "; ".join(msgs) if msgs else "ok"
    return info


def _now_ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_health_from_diag(diag: Dict[str, Any]) -> Dict[str, Any]:
    """Build health.json payload from heal_runner diagnose() result."""
    ts = _now_ts()
    checks: Dict[str, Dict[str, Any]] = {}

    def add(name: str, ok: Optional[bool], msg: str) -> None:
        if ok is None:
            return
        checks[name] = {"ok": bool(ok), "msg": msg or "", "ts": ts}

    add("qb", diag.get("qb_ok"), str(diag.get("qb_msg") or ""))
    if "translation_ok" in diag or "translation_msg" in diag:
        add("translation", diag.get("translation_ok"), str(diag.get("translation_msg") or ""))
    elif "deepseek_ok" in diag:
        # Read old heal snapshots while workers roll forward to the new key.
        add("translation", diag.get("deepseek_ok"), str(diag.get("deepseek_msg") or ""))
    if "plwt_ok" in diag:
        add("plwt", diag.get("plwt_ok"), str(diag.get("plwt_msg") or ""))
    # 未配置时 p115_ok 不在 diag 里；失效只黄不红
    if diag.get("p115_ok") is not None:
        add("p115", diag.get("p115_ok"), str(diag.get("p115_msg") or ""))
    mf = int(diag.get("missing_files") or 0)
    add("missing_files", mf == 0, f"count={mf}" if mf else "ok")
    scrape_h = diag.get("scrape_hours")
    stuck_h = float(os.environ.get("HEAL_STUCK_SCRAPE_H", "8") or "8")
    if scrape_h is not None:
        add("scrape", float(scrape_h) < stuck_h, f"running {float(scrape_h):.1f}h")
    else:
        add("scrape", True, "idle")

    ver = version_status()
    checks["version"] = {
        "ok": not ver.get("behind"),
        "msg": ver.get("msg") or "",
        "ts": ts,
        "version": ver.get("version"),
        "tree_hash": ver.get("tree_hash"),
        "behind": bool(ver.get("behind")),
    }

    fails = [k for k, v in checks.items() if not v.get("ok")]
    # yellow: non-critical (version behind, missing_files, p115 cookie)
    # red: qB/plwt/translation down or scrape stuck
    critical = {"qb", "plwt", "translation", "deepseek", "scrape"}
    crit_fails = [k for k in fails if k in critical]
    if crit_fails:
        overall = "red"
    elif fails:
        overall = "yellow"
    else:
        overall = "green"

    return {
        "overall": overall,
        "ts": ts,
        "checks": checks,
        "diag_summary": {
            "titlezh_gaps": diag.get("titlezh_gaps"),
            "weekly_items": diag.get("weekly_items"),
            "orphan_queued": len(diag.get("orphan_queued") or []),
            "qb_orphan": len(diag.get("qb_orphan") or []),
        },
        "version_behind": bool(ver.get("behind")),
    }


def write_health_json(diag: Dict[str, Any], path: str = HEALTH_PATH) -> Dict[str, Any]:
    payload = build_health_from_diag(diag)
    atomic_write_json(path, payload)
    return payload


def parse_log_events(log_path: str = LOG_FILE, hours: float = 24) -> List[Dict[str, str]]:
    """Parse av-garden.log lines for enqueue/start/done/fail style events."""
    if not os.path.exists(log_path):
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    events: List[Dict[str, str]] = []
    # Common patterns: [YYYY-MM-DD HH:MM:SS] [Tag] message
    line_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}).*?\[([^\]]+)\]\s*(.*)$"
    )
    keywords = (
        "入队",
        "加入",
        "开始",
        "完成",
        "失败",
        "queued",
        "download",
        "fail",
        "error",
        "刮削",
        "补译",
        "备份",
        "Heal",
    )
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # read last ~2MB to stay bounded
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 2_000_000), os.SEEK_SET)
                if f.tell() > 0:
                    f.readline()
            except OSError:
                f.seek(0)
            for line in f:
                m = line_re.match(line.strip())
                if not m:
                    continue
                ts_s, tag, msg = m.group(1), m.group(2), m.group(3)
                try:
                    ts = datetime.strptime(ts_s.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                low = msg.lower()
                if not any(k.lower() in low or k in msg or k in tag for k in keywords):
                    continue
                kind = "info"
                if any(x in msg for x in ("失败", "fail", "error", "Error")):
                    kind = "fail"
                elif any(x in msg for x in ("完成", "done", "succ")):
                    kind = "done"
                elif any(x in msg for x in ("开始", "start", "Running")):
                    kind = "start"
                elif any(x in msg for x in ("入队", "加入", "queue")):
                    kind = "enqueue"
                events.append(
                    {
                        "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "tag": tag,
                        "kind": kind,
                        "msg": msg[:240],
                    }
                )
    except Exception as e:
        _log(f"parse log: {e}")
    return events[-500:]


def fetch_queue_status() -> Dict[str, Any]:
    url = os.environ.get("STATUS_QUEUE_URL") or f"{QUEUE_API_URL.rstrip('/')}/api/queue"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("items") or data.get("queue") or []
        else:
            items = []
        counts: Dict[str, int] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            st = str(it.get("status") or "unknown").lower()
            counts[st] = counts.get(st, 0) + 1
        return {"ok": True, "counts": counts, "total": len(items)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160], "counts": {}, "total": 0}


def build_daily_report(
    health: Optional[Dict[str, Any]] = None,
    hours: float = 24,
) -> Dict[str, Any]:
    if health is None:
        health = read_json(HEALTH_PATH, {})
    events = parse_log_events(LOG_FILE, hours=hours)
    fails = [e for e in events if e.get("kind") == "fail"]
    queue = fetch_queue_status()
    disk = {
        "data": {"path": SAVE_PATH, "bytes": du_bytes(SAVE_PATH), "human": du_human(du_bytes(SAVE_PATH))},
        "db": {"path": "/db", "bytes": du_bytes("/db"), "human": du_human(du_bytes("/db"))},
        "backups": {
            "path": BACKUPS_DIR,
            "bytes": du_bytes(BACKUPS_DIR),
            "human": du_human(du_bytes(BACKUPS_DIR)),
        },
    }
    return {
        "ts": _now_ts(),
        "window_hours": hours,
        "health": {
            "overall": (health or {}).get("overall"),
            "ts": (health or {}).get("ts"),
            "version_behind": (health or {}).get("version_behind"),
            "checks": (health or {}).get("checks") or {},
        },
        "events": events[-200:],
        "fail_events": fails[-50:],
        "fail_count": len(fails),
        "queue": queue,
        "disk": disk,
        "ds_usage": read_json(DS_USAGE_PATH, {}),
    }


def write_daily_report(path: str = DAILY_REPORT_PATH) -> Dict[str, Any]:
    report = build_daily_report()
    atomic_write_json(path, report)
    # also archive dated copy
    day = datetime.now().strftime("%Y%m%d")
    archive = os.path.join(STATUS_DIR, f"daily-report-{day}.json")
    try:
        atomic_write_json(archive, report)
        prune_glob(STATUS_DIR, "daily-report-", ".json", REPORT_KEEP + 1)
        # keep live daily-report.json always
    except Exception as e:
        _log(f"archive daily report: {e}")
    _log(f"daily-report written fails={report.get('fail_count')} overall={report.get('health', {}).get('overall')}")
    return report


def record_deepseek_usage(n: int = 1) -> Dict[str, Any]:
    """Increment daily DeepSeek call counter; alert via log_write if over limit."""
    today = datetime.now().strftime("%Y-%m-%d")
    should_alert = False

    def increment(data):
        nonlocal should_alert
        if not isinstance(data, dict) or data.get("date") != today:
            data = {"date": today, "count": 0, "limit": DEEPSEEK_DAILY_ALERT_LIMIT, "alerted": False}
        data["count"] = int(data.get("count") or 0) + max(0, int(n))
        data["limit"] = DEEPSEEK_DAILY_ALERT_LIMIT
        data["updated_at"] = _now_ts()
        if data["count"] >= data["limit"] and not data.get("alerted"):
            data["alerted"] = True
            should_alert = True
        return data

    data = locked_update_json(DS_USAGE_PATH, {}, increment)
    if should_alert:
        msg = f"DeepSeek 日用量超限: {data['count']}/{data['limit']}"
        _log(msg)
        try:
            from src.log_writer import write as log_write

            log_write("DeepSeek", msg)
        except Exception:
            pass
    return data


def run_morning_jobs() -> Dict[str, Any]:
    """04:30 jobs: sqlite backup + daily report."""
    out: Dict[str, Any] = {}
    bak = backup_sqlite()
    out["backup"] = bak
    if not bak.get("ok"):
        try:
            from src.log_writer import write as log_write

            log_write("Backup", f"数据库备份失败: {bak.get('msg')}")
        except Exception:
            pass
    else:
        try:
            from src.log_writer import write as log_write

            log_write("Backup", f"数据库备份完成: {bak.get('path')}")
        except Exception:
            pass
    # refresh health lightly if heal state exists
    try:
        heal_state = read_json(os.environ.get("HEAL_STATE_PATH", "/db/heal_state.json"), {})
        last = heal_state.get("last_diag") if isinstance(heal_state, dict) else {}
        if isinstance(last, dict) and last:
            # synthesize minimal diag for health write
            diag = {
                "qb_ok": last.get("qb_ok"),
                "qb_msg": "from heal_state",
                "translation_ok": last.get("translation_ok", last.get("deepseek_ok")),
                "translation_msg": last.get("translation_msg", last.get("deepseek_msg")) or "from heal_state",
                "plwt_ok": last.get("plwt_ok"),
                "plwt_msg": "from heal_state",
                "missing_files": last.get("missing_files") or 0,
                "scrape_hours": last.get("scrape_hours"),
                "titlezh_gaps": last.get("titlezh_gaps"),
                "orphan_queued": [],
                "qb_orphan": [],
            }
            out["health"] = write_health_json(diag)
    except Exception as e:
        _log(f"health refresh: {e}")
    out["daily"] = write_daily_report()
    return out
