"""瞬时/系统类下载失败的识别与自动恢复。

避免「代码 bug 导致 3 次失败」后 UI 一直挂着「所有源均失败」，
在 worker 启动、heal 周期里清 retry 并重新入队。
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from queue_store import append_unique, read_json, set_download_target, update_json

# 匹配这些文案的视为可自动恢复（非「真的没源」）
_TRANSIENT_RE = re.compile(
    r"generator|context manager|TypeError|ImportError|AttributeError|"
    r"异常:|queue_unavailable|连接中断|Connection|timed out|Timeout|"
    r"SSL|EOF|ECONN|Temporary|503|502|暂时|服务暂不可用|系统异常",
    re.I,
)

# 明确不可自动恢复
_PERMANENT_RE = re.compile(
    r"无可用源|在线流失败|98堂.*无可用|无可用磁链|已取消|用户取消",
    re.I,
)


def is_transient_reason(reason: str) -> bool:
    text = (reason or "").strip()
    if not text:
        return False
    if _PERMANENT_RE.search(text):
        return False
    return bool(_TRANSIENT_RE.search(text))


def _paths() -> Tuple[str, str, str, str]:
    queue_path = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
    queue_dir = os.path.dirname(queue_path) or "/db"
    failed_json = os.environ.get(
        "FAILED_QUEUE_JSON_PATH",
        os.path.join(queue_dir, "failed_queue.json"),
    )
    retry_path = os.environ.get(
        "RETRY_COUNTS_PATH",
        os.path.join(queue_dir, "retry_counts.json"),
    )
    targets = os.environ.get(
        "DOWNLOAD_TARGETS_PATH",
        os.path.join(queue_dir, "download_targets.json"),
    )
    return queue_path, failed_json, retry_path, targets


def recover_transient_failures(
    *,
    max_age_hours: float = 72.0,
    default_target: str = "qb",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """清瞬时失败记录并重新入队。

    条件（满足其一即可，且在 max_age_hours 内）：
    - record.recoverable is True
    - reason 匹配瞬时模式
    - 无 reason 但 failed_at 在 max_age_hours 内（兼容旧数据，如 generator 时代未写 reason）
    """
    queue_path, failed_json, retry_path, targets_path = _paths()
    now = time.time()
    max_age = max(1.0, float(max_age_hours)) * 3600.0

    records = read_json(failed_json, [])
    if not isinstance(records, list):
        records = []

    kept: List[dict] = []
    recovered: List[str] = []

    for item in records:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        if not code:
            continue
        reason = str(item.get("reason") or "")
        recoverable = bool(item.get("recoverable"))
        failed_at = str(item.get("failed_at") or "")

        age_ok = True
        if failed_at:
            try:
                t = time.mktime(time.strptime(failed_at[:19], "%Y-%m-%d %H:%M:%S"))
                age_ok = (now - t) <= max_age
            except Exception:
                age_ok = True  # 解析失败仍允许按 reason 恢复

        should = False
        if age_ok:
            if recoverable or is_transient_reason(reason):
                should = True
            elif not reason and age_ok:
                # 旧记录没写 reason：仅恢复近 max_age 内的（避免把很久前的永久失败捞回来）
                should = True

        if should and age_ok:
            recovered.append(code)
        else:
            kept.append(item)

    if dry_run:
        return {"recovered": recovered, "kept": len(kept), "dry_run": True}

    if recovered:
        # 写回失败队列
        def _save_failed(_):
            return kept

        update_json(failed_json, [], _save_failed)

        # 清 retry
        def _clear_retry(counts):
            counts = counts if isinstance(counts, dict) else {}
            for code in recovered:
                for k in list(counts.keys()):
                    if str(k).upper() == code:
                        counts.pop(k, None)
            return counts

        update_json(retry_path, {}, _clear_retry)

        # 入队
        for code in recovered:
            append_unique(queue_path, code)
            set_download_target(targets_path, code, default_target)

        # failed_queue.txt 兼容
        failed_txt = os.path.join(os.path.dirname(failed_json) or "/db", "failed_queue.txt")
        if os.path.isfile(failed_txt):
            try:
                rec_set = set(recovered)
                lines = []
                with open(failed_txt, "r", encoding="utf-8") as f:
                    for line in f:
                        c = line.strip().upper()
                        if c and c not in rec_set:
                            lines.append(line if line.endswith("\n") else line + "\n")
                with open(failed_txt, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            except OSError:
                pass

    return {"recovered": recovered, "kept": len(kept), "dry_run": False}
