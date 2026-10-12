#!/usr/bin/env python3
"""Run the read-only-to-media follow-up after weekly_updater succeeds."""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scrape_pipeline import (
    PHASE_UNWATCHED_CN,
    finish_pipeline,
    read_status,
    set_phase,
    write_status,
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


def followup_budget(total: int) -> int:
    # Allow the shared 31/60s search slot plus network overhead. Loading the
    # candidates gets the one-hour floor; large batches must not hit that floor.
    return max(3600, max(0, int(total)) * 90 + 1800)


def run_with_budget(path: str) -> int:
    started = time.monotonic()
    budget = followup_budget(0)
    timeout_error = ""
    with subprocess.Popen([PYTHON, path]) as proc:
        try:
            while True:
                progress = read_status().get("progress") or {}
                new_budget = followup_budget(progress.get("total") or 0)
                if new_budget > budget:
                    budget = new_budget
                    log(f"candidate budget: total={progress.get('total')} timeout={budget}s")
                remaining = budget - (time.monotonic() - started)
                if remaining <= 0:
                    # set_progress announces the current attempt before searching.
                    completed = max(0, int(progress.get("current") or 0) - 1)
                    total = int(progress.get("total") or 0)
                    timeout_error = f"未看中文补链超时（{budget // 60} 分钟，已检查 {completed}/{total}）"
                    return 124
                try:
                    return proc.wait(timeout=min(5, remaining))
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if timeout_error:
                write_status({"last_error": timeout_error})


def main() -> int:
    path = _script_path("unwatched_chinese_refill.py")
    set_phase(PHASE_UNWATCHED_CN)
    log(f"start {path}")
    try:
        rc = run_with_budget(path)
    except Exception as exc:
        rc = 1
        log(f"error: {exc}")
        write_status({"last_error": f"未看中文补链运行失败：{exc}"[:300]})

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
