#!/usr/bin/env python3
"""Run the read-only-to-media follow-up after weekly_updater succeeds."""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scrape_pipeline import (
    PHASE_UNWATCHED_CN,
    finish_pipeline,
    read_status,
    set_phase,
)

APP = os.environ.get("AVGARDEN_APP", "/app")
PYTHON = os.environ.get("AVGARDEN_PYTHON", "/app/venv/bin/python3")
if not os.path.isfile(PYTHON):
    PYTHON = sys.executable


def log(msg: str) -> None:
    print(f"[ScrapeFollowups] {msg}", flush=True)


def _script_path(name: str) -> str:
    deployed = os.path.join(APP, name)
    if os.path.isfile(deployed):
        return deployed
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def main() -> int:
    path = _script_path("unwatched_chinese_refill.py")
    set_phase(PHASE_UNWATCHED_CN)
    log(f"start {path}")
    try:
        proc = subprocess.run([PYTHON, path], timeout=3600, check=False)
        rc = int(proc.returncode or 0)
    except subprocess.TimeoutExpired:
        rc = 124
    except Exception as exc:
        rc = 1
        log(f"error: {exc}")

    current = read_status()
    stats = current.get("stats") if isinstance(current.get("stats"), dict) else {}
    if rc == 0:
        summary = str(current.get("last_summary") or "刮削与未看中文补链完成")
        finish_pipeline(summary=summary, stats=stats)
        log(summary)
        return 0

    error = str(current.get("last_error") or f"未看中文补链失败 (exit={rc})")
    finish_pipeline(summary="每日推荐已更新，但未看中文补链未完成", error=error, stats=stats)
    log(error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
