"""Cross-process status for the Weekly scrape and its safe follow-up."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from queue_store import read_json, update_json

STATUS_DIR = os.environ.get("STATUS_DIR", "/db/status")
PIPELINE_PATH = os.environ.get(
    "SCRAPE_PIPELINE_PATH", os.path.join(STATUS_DIR, "scrape_pipeline.json")
)
STALE_SECONDS = int(os.environ.get("SCRAPE_PIPELINE_STALE_SECONDS", str(3 * 3600)))

PHASE_IDLE = "idle"
PHASE_WEEKLY = "weekly_scrape"
PHASE_UNWATCHED_CN = "unwatched_chinese"

PHASE_LABELS = {
    PHASE_IDLE: "空闲",
    PHASE_WEEKLY: "每日推荐刮削中",
    PHASE_UNWATCHED_CN: "未看中文补链中",
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default() -> Dict[str, Any]:
    return {
        "running": False,
        "phase": PHASE_IDLE,
        "phase_label": PHASE_LABELS[PHASE_IDLE],
        "trigger": "",
        "started_at": "",
        "updated_at": "",
        "finished_at": "",
        "progress": {"current": 0, "total": 0, "code": ""},
        "last_error": "",
        "last_summary": "",
        "stats": {},
    }


def _normalized(value: Any) -> Dict[str, Any]:
    status = _default()
    if isinstance(value, dict):
        status.update(value)
    phase = str(status.get("phase") or PHASE_IDLE)
    status["phase"] = phase
    status["phase_label"] = PHASE_LABELS.get(
        phase, str(status.get("phase_label") or phase)
    )
    if not isinstance(status.get("progress"), dict):
        status["progress"] = {"current": 0, "total": 0, "code": ""}
    if not isinstance(status.get("stats"), dict):
        status["stats"] = {}
    return status


def _is_stale(status: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    if not status.get("running"):
        return False
    raw = str(status.get("updated_at") or status.get("started_at") or "")
    if not raw:
        return True
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        current = now or datetime.now().astimezone()
        if stamp.tzinfo is None:
            stamp = stamp.astimezone()
        return (current - stamp).total_seconds() > STALE_SECONDS
    except (TypeError, ValueError):
        return True


def read_status(path: str = PIPELINE_PATH) -> Dict[str, Any]:
    return _normalized(read_json(path, {}))


def write_status(payload: Dict[str, Any], path: str = PIPELINE_PATH) -> Dict[str, Any]:
    def merge(value):
        status = _normalized(value)
        status.update(payload or {})
        status["updated_at"] = _now_iso()
        return _normalized(status)

    return update_json(path, {}, merge)


def begin_pipeline(
    phase: str = PHASE_WEEKLY,
    *,
    trigger: str = "",
    path: str = PIPELINE_PATH,
) -> bool:
    """Atomically claim the shared pipeline. Return False when it is active."""
    claimed = {"ok": False}

    def begin(value):
        status = _normalized(value)
        if status.get("running") and not _is_stale(status):
            return status
        now = _now_iso()
        claimed["ok"] = True
        return _normalized({
            **_default(),
            "running": True,
            "phase": phase,
            "trigger": str(trigger or ""),
            "started_at": now,
            "updated_at": now,
        })

    update_json(path, {}, begin)
    return claimed["ok"]


def set_phase(
    phase: str,
    *,
    current: int = 0,
    total: int = 0,
    code: str = "",
    path: str = PIPELINE_PATH,
) -> Dict[str, Any]:
    return write_status(
        {
            "running": phase != PHASE_IDLE,
            "phase": phase,
            "progress": {
                "current": int(current or 0),
                "total": int(total or 0),
                "code": str(code or ""),
            },
        },
        path=path,
    )


def set_progress(
    current: int,
    total: int,
    code: str = "",
    path: str = PIPELINE_PATH,
) -> Dict[str, Any]:
    return write_status(
        {
            "running": True,
            "progress": {
                "current": int(current or 0),
                "total": int(total or 0),
                "code": str(code or ""),
            },
        },
        path=path,
    )


def finish_pipeline(
    *,
    summary: str = "",
    error: str = "",
    stats: Optional[Dict[str, Any]] = None,
    path: str = PIPELINE_PATH,
) -> Dict[str, Any]:
    return write_status(
        {
            "running": False,
            "phase": PHASE_IDLE,
            "finished_at": _now_iso(),
            "last_summary": str(summary or "")[:500],
            "last_error": str(error or "")[:500],
            "stats": stats if isinstance(stats, dict) else {},
            "progress": {"current": 0, "total": 0, "code": ""},
        },
        path=path,
    )


def interrupt_running_pipeline(
    reason: str = "Worker 重启，上一轮刮削流程已中断",
    *,
    path: str = PIPELINE_PATH,
) -> bool:
    interrupted = {"ok": False}

    def interrupt(value):
        status = _normalized(value)
        if not status.get("running"):
            return status
        interrupted["ok"] = True
        now = _now_iso()
        return _normalized({
            **status,
            "running": False,
            "phase": PHASE_IDLE,
            "finished_at": now,
            "updated_at": now,
            "last_error": str(reason or "刮削流程已中断")[:500],
            "progress": {"current": 0, "total": 0, "code": ""},
        })

    update_json(path, {}, interrupt)
    return interrupted["ok"]


def is_pipeline_running(path: str = PIPELINE_PATH) -> bool:
    status = read_status(path)
    if not status.get("running"):
        return False
    if not _is_stale(status):
        return True

    running = {"value": False}

    def inspect(value):
        status = _normalized(value)
        if status.get("running") and _is_stale(status):
            now = _now_iso()
            return _normalized({
                **status,
                "running": False,
                "phase": PHASE_IDLE,
                "finished_at": now,
                "updated_at": now,
                "last_error": "刮削状态超过 3 小时未更新，已自动释放",
                "progress": {"current": 0, "total": 0, "code": ""},
            })
        running["value"] = bool(status.get("running"))
        return status

    update_json(path, {}, inspect)
    return running["value"]
