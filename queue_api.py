#!/usr/bin/env python3
"""
AV/GARDEN Queue API v7 — 
下载管理（完整声明周期：排队→下载中→已完成，保留展示）
完成后自动更新 weekly.json + 写入 AV/GARDEN SQLite（让主页也可见）
"""
import contextlib, os, sys, json, signal, time, subprocess, re, shutil, threading, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse

from process_control import cancel_request_age, cleanup_stale_cancel_requests, clear_cancel_request, request_cancel
from main_video import find_main_video
from queue_store import (
    append_many_unique,
    append_unique,
    clear_if_matches,
    clear_download_target,
    get_download_target,
    normalize_download_target,
    read_json,
    read_queue,
    remove_code,
    set_download_target,
    update_json,
    write_json,
    write_queue,
)
import queue_store
from video_id import (
    local_video_id_aliases,
    normalize_local_video_id,
    normalize_video_id,
    safe_local_dir,
    safe_video_dir,
)
from weekly_store import atomic_write_json, update_json as update_weekly_json, weekly_update_lock
from src.scrape_pipeline import (
    PHASE_WEEKLY,
    begin_pipeline,
    finish_pipeline,
    is_pipeline_running,
    read_status as read_scrape_status,
)

QUEUE_PATH = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
STATE_PATH = os.environ.get("STATE_PATH", "/db/queue_state.json")
CURRENT_PATH = os.environ.get("CURRENT_PATH", "/db/current_download.txt")
LOCK_PATH = os.environ.get("LOCK_PATH", "/app/work")
SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
DB_PATH = os.environ.get("DB_PATH", "/db/downloaded.db")
HISTORY_PATH = os.environ.get("HISTORY_PATH", "/db/download_history.json")
HISTORY_RETENTION_DAYS = int(os.environ.get("HISTORY_RETENTION_DAYS", "7"))
FAILED_QUEUE_JSON_PATH = os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "failed_queue.json")
FAILED_QUEUE_PATH = os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "failed_queue.txt")
RETRY_PATH = os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "retry_counts.json")
DOWNLOAD_TARGETS_PATH = os.environ.get(
    "DOWNLOAD_TARGETS_PATH",
    os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "download_targets.json"),
)
WEEKLY_JSON = os.path.join(SAVE_PATH, "__weekly__", "weekly.json")
ONLINE_DIR = os.path.join(SAVE_PATH, "__online__")
ONLINE_TTL_SECONDS = int(os.environ.get("ONLINE_TTL_SECONDS", str(30 * 24 * 60 * 60)))
ONLINE_CLEANUP_INTERVAL_SECONDS = int(os.environ.get("ONLINE_CLEANUP_INTERVAL_SECONDS", "3600"))
ONLINE_PROXY = os.environ.get("PROXY", "") or None
BLOCKED_ACTRESSES = set(
    name.strip() for name in os.environ.get("BLOCKED_ACTRESSES", "").split(",") if name.strip()
)
weekly_scrape_proc = None
weekly_scrape_lock = threading.Lock()
weekly_json_lock = threading.Lock()
queue_state_lock = threading.RLock()
main_video_cache_lock = threading.Lock()
main_video_cache_root = ""
main_video_cache_time = 0.0
main_video_cache = {}
MAIN_VIDEO_CACHE_TTL_SECONDS = int(os.environ.get("MAIN_VIDEO_CACHE_TTL_SECONDS", "30"))
DEBUG = os.environ.get("DEBUG", "0") == "1"
QUEUE_REGISTRATION_GRACE_SECONDS = int(os.environ.get("QUEUE_REGISTRATION_GRACE_SECONDS", "120"))

# --- POST idempotency / in-flight de-duplication (local state only) ---------
# Empty means "derive from QUEUE_PATH at call time" so path overrides work.
IDEMPOTENCY_PATH = os.environ.get("QUEUE_IDEMPOTENCY_PATH", "")
IDEMPOTENCY_TTL_SECONDS = int(os.environ.get("QUEUE_IDEMPOTENCY_TTL", str(7 * 24 * 3600)))
IDEMPOTENCY_MAX_ENTRIES = int(os.environ.get("QUEUE_IDEMPOTENCY_MAX", "5000"))
# Window in which an accepted code still counts as in-flight even though it has
# already left download_queue.txt (worker pop -> current_download, 115 submit).
INFLIGHT_ACCEPT_TTL_SECONDS = int(os.environ.get("QUEUE_INFLIGHT_TTL", "300"))
ACTIVE_STATE_STATUSES = frozenset({"queued", "downloading", "processing"})
# Terminal rows explicitly end a lifecycle: they win over the short
# "recently accepted" race-window protection.
TERMINAL_STATE_STATUSES = frozenset(
    {"done", "failed", "error", "cancelled", "canceled", "completed", "complete", "skipped"}
)


# ---------------------------------------------------------------------------
# Request observability (diagnostics only — no behaviour change)
#
# Every reference to a queue request is stamped with a request id taken from the
# X-Request-ID header (or generated) so a Go "[QueueProxy]" line and the Python
# "[req]"/"[lock]"/"[flock]"/"[qb]"/"[slow]" lines can be correlated.
# Only timings, paths, statuses and request ids are logged: cookies, SID,
# passwords, magnets and request bodies are never printed.
# ---------------------------------------------------------------------------
def _env_float(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return float(default)


QUEUE_ACCESS_LOG_MS = _env_float("QUEUE_ACCESS_LOG_MS", 500)
QUEUE_ACCESS_LOG_ALL = (
    os.environ.get("QUEUE_ACCESS_LOG", "").strip().lower() in ("1", "all", "true", "yes")
    or DEBUG
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_request_ctx = threading.local()
_accept_ctx = threading.local()


def _request_scope():
    return getattr(_request_ctx, "scope", None)


def _ms(value):
    return round(float(value or 0.0), 1)


def _sanitize_request_id(raw):
    value = str(raw or "").strip()
    if value and _REQUEST_ID_RE.match(value):
        return value
    return ""


def _ensure_request_id(handler):
    """Resolve the request id / method / path once the request line is parsed."""
    scope = _request_scope()
    if scope is None:
        return ""
    if scope.get("resolved"):
        return scope.get("id") or ""
    raw = ""
    try:
        raw = handler.headers.get("X-Request-ID") or ""
    except Exception:
        raw = ""
    scope["id"] = _sanitize_request_id(raw) or ("q-" + uuid.uuid4().hex[:16])
    scope["method"] = str(getattr(handler, "command", "") or scope.get("method") or "")
    try:
        scope["path"] = urlparse(getattr(handler, "path", "") or "").path
    except Exception:
        scope["path"] = ""
    scope["resolved"] = True
    return scope["id"]


def _begin_request_scope(handler):
    scope = {
        "id": "",
        "resolved": False,
        "method": str(getattr(handler, "command", "") or ""),
        "path": "",
        "t_received": getattr(handler, "_qd_t_received", time.monotonic()),
        "accept_ms": float(getattr(handler, "_qd_accept_ms", 0.0) or 0.0),
        "lock_wait_ms": 0.0,
        "lock_hold_ms": 0.0,
        "lock_wait_total_ms": 0.0,
        "lock_hold_max_ms": 0.0,
        "lock_count": 0,
        "lock_sections": [],
        "handler_ms": 0.0,
        "handler_done_ts": 0.0,
        "response_write_ms": 0.0,
        "lock_events": [],
        "slow_ops": [],
        "qb_calls": [],
        "status": 0,
        "error": "",
        "write_error": "",
    }
    _request_ctx.scope = scope
    return scope


def _slow_op(op, duration_ms, extra=""):
    """Report a local operation that exceeded the slow threshold."""
    if duration_ms < QUEUE_ACCESS_LOG_MS and not QUEUE_ACCESS_LOG_ALL:
        return
    scope = _request_scope()
    suffix = f" {extra}" if extra else ""
    if duration_ms >= QUEUE_ACCESS_LOG_MS and scope is not None:
        scope["slow_ops"].append(f"{op}:{_ms(duration_ms)}ms")
    rid = (scope or {}).get("id") or "-"
    log(f"[slow] request={rid} op={op} duration_ms={_ms(duration_ms)}{suffix}")


def _lock_trace_hook(path, wait_ms, hold_ms):
    """queue_store hook: attribute flock wait/hold time to the current request."""
    scope = _request_scope()
    if scope is None:
        return
    scope["lock_wait_ms"] = max(scope["lock_wait_ms"], wait_ms)
    scope["lock_hold_ms"] = max(scope["lock_hold_ms"], hold_ms)
    if wait_ms < QUEUE_ACCESS_LOG_MS and hold_ms < QUEUE_ACCESS_LOG_MS:
        return
    name = os.path.basename(path) or path
    scope["lock_events"].append(f"{name}:wait={_ms(wait_ms)},hold={_ms(hold_ms)}")
    log(
        f"[flock] request={scope.get('id') or '-'} file={name} "
        f"wait_ms={_ms(wait_ms)} hold_ms={_ms(hold_ms)}"
    )


# Inert for every other process (the worker never installs a hook).
queue_store.set_trace_hook(_lock_trace_hook)


def _qb_caller():
    """Which queue route issued the qB call (worker uses its own adapter)."""
    scope = _request_scope()
    method = str((scope or {}).get("method") or "").upper()
    if method in ("GET", "POST", "DELETE"):
        return f"queue.{method}"
    return "other"


def _record_lock_event(section, phase, wait_ms=None, hold_ms=None):
    """Accumulate + report one queue_state_lock critical section."""
    scope = _request_scope()
    if scope is not None:
        if wait_ms is not None:
            scope["lock_wait_ms"] = max(scope["lock_wait_ms"], wait_ms)
            scope["lock_wait_total_ms"] += wait_ms
        if hold_ms is not None:
            scope["lock_hold_ms"] += hold_ms
            scope["lock_hold_max_ms"] = max(scope["lock_hold_max_ms"], hold_ms)
            scope["lock_count"] += 1
        if phase == "released":
            scope["lock_sections"].append(
                f"{section}:wait={_ms(wait_ms or 0)},hold={_ms(hold_ms or 0)}"
            )
    log_line = wait_ms is not None and wait_ms >= QUEUE_ACCESS_LOG_MS
    hold_line = hold_ms is not None and (
        hold_ms >= QUEUE_ACCESS_LOG_MS or (wait_ms or 0) >= QUEUE_ACCESS_LOG_MS
    )
    if not (log_line or hold_line):
        return
    rid = (scope or {}).get("id") or "-"
    method = (scope or {}).get("method") or "-"
    path = (scope or {}).get("path") or "-"
    if phase == "acquired":
        log(
            f"[lock] request={rid} method={method} path={path} section={section} "
            f"phase=acquired lock_wait_ms={_ms(wait_ms)}"
        )
    else:
        log(
            f"[lock] request={rid} method={method} path={path} section={section} "
            f"phase=released lock_wait_ms={_ms(wait_ms or 0)} lock_hold_ms={_ms(hold_ms or 0)}"
        )


@contextlib.contextmanager
def queue_state_critical(section="queue_state"):
    """Short critical section around shared queue state.

    Only local read-modify-write work belongs inside; qB/HTTP/du/os.walk must
    stay outside so a slow request cannot block every other queue request.
    """
    started = time.monotonic()
    with queue_state_lock:
        acquired = time.monotonic()
        wait_ms = (acquired - started) * 1000.0
        _record_lock_event(section, "acquired", wait_ms=wait_ms)
        try:
            yield
        finally:
            hold_ms = (time.monotonic() - acquired) * 1000.0
            _record_lock_event(section, "released", wait_ms=wait_ms, hold_ms=hold_ms)


def _idempotency_path():
    configured = os.environ.get("QUEUE_IDEMPOTENCY_PATH") or ""
    path = configured or globals().get("IDEMPOTENCY_PATH") or ""
    if path:
        return path
    return os.path.join(os.path.dirname(QUEUE_PATH) or "/db", "queue_idempotency.json")


def _idem_store():
    """Load the idempotency store; never fail a request over the store."""
    try:
        data = read_json(_idempotency_path(), {})
    except Exception as exc:
        log(f"Idempotency store unavailable ({exc}); continuing without replay data")
        data = {}
    if not isinstance(data, dict):
        data = {}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    return {"version": 1, "entries": entries}


def _idem_prune(store, now=None):
    now = now or time.time()
    entries = store["entries"]
    for key in [
        k
        for k, value in entries.items()
        if now - float((value or {}).get("created_at") or 0) > IDEMPOTENCY_TTL_SECONDS
    ]:
        entries.pop(key, None)
    if IDEMPOTENCY_MAX_ENTRIES > 0 and len(entries) > IDEMPOTENCY_MAX_ENTRIES:
        ordered = sorted(entries.items(), key=lambda kv: float((kv[1] or {}).get("created_at") or 0))
        for key, _ in ordered[: len(entries) - IDEMPOTENCY_MAX_ENTRIES]:
            entries.pop(key, None)
    return store


def _idem_record(request_id, code, target, status, response):
    """Persist the first result for request_id (atomic, survives restart)."""
    if not request_id:
        return
    now = time.time()

    def updater(store):
        store = _idem_prune(store if isinstance(store, dict) else {"version": 1, "entries": {}}, now)
        if not isinstance(store.get("entries"), dict):
            store["entries"] = {}
        store["version"] = 1
        store["entries"][request_id] = {
            "request_id": request_id,
            "code": code,
            "target": target,
            "status": status,
            "result": response,
            "created_at": now,
            "updated_at": now,
        }
        return store

    try:
        update_json(_idempotency_path(), {"version": 1, "entries": {}}, updater)
    except Exception as exc:
        # The task itself is already accepted; losing the replay record only
        # means a retry is treated as a fresh (but still in-flight-deduped) add.
        log(f"Idempotency record failed for {request_id}: {exc}")


def _recent_accept(code, ttl=None):
    """Most recent accepted entry for code within ttl (covers pop->processing gap)."""
    ttl = INFLIGHT_ACCEPT_TTL_SECONDS if ttl is None else ttl
    upper = str(code or "").upper()
    if not upper:
        return None
    now = time.time()
    entries = _idem_store()["entries"]
    best = None
    for value in entries.values():
        if not isinstance(value, dict):
            continue
        if str(value.get("code") or "").upper() != upper:
            continue
        created = float(value.get("created_at") or 0)
        if now - created > ttl:
            continue
        if best is None or created > float(best.get("created_at") or 0):
            best = value
    return best


def _channel_label(target):
    """User-facing channel label."""
    return "115 离线" if str(target or "").lower() == "115" else "qB"


def _channel_log_label(target):
    """Log label kept identical to the pre-existing av-garden.log wording."""
    return "115" if str(target or "").lower() == "115" else "qB"


def _inflight_for_code(code, state_items, queue_codes, current_code, failed_codes=None):
    """Local-only in-flight probe: (in_flight, existing_target, source).

    Terminal local state (done/failed/cancelled in queue_state, or a recorded
    failure) always wins over the `recent_accept` race-window heuristic, so an
    accepted-then-finished task can be queued again with a new request_id.
    """
    upper = str(code or "").upper()
    if not upper:
        return False, None, ""
    if any(str(c or "").upper() == upper for c in queue_codes):
        return True, get_download_target(DOWNLOAD_TARGETS_PATH, code), "queued"
    if str(current_code or "").upper() == upper:
        return True, get_download_target(DOWNLOAD_TARGETS_PATH, code), "current_download"
    if {str(c or "").upper() for c in (failed_codes or ())} & {upper}:
        return False, None, "terminal:failed"
    terminal_seen = False
    for item in state_items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("code") or "").upper() != upper:
            continue
        status = str(item.get("status") or "").lower()
        if status in ACTIVE_STATE_STATUSES:
            stored = str(item.get("target") or "").strip() or None
            return True, stored or get_download_target(DOWNLOAD_TARGETS_PATH, code), f"state:{status}"
        if status in TERMINAL_STATE_STATUSES:
            terminal_seen = True
    if terminal_seen:
        return False, None, "terminal:state"
    recent = _recent_accept(code)
    if recent is not None:
        return True, str(recent.get("target") or "") or get_download_target(DOWNLOAD_TARGETS_PATH, code), "recent_accept"
    return False, None, ""


def _emit_request_log(scope):
    finished = time.monotonic()
    total_ms = (finished - scope["t_received"]) * 1000.0
    after_handler_ms = 0.0
    if scope["handler_done_ts"]:
        after_handler_ms = max(0.0, (finished - scope["handler_done_ts"]) * 1000.0)
    is_queue_path = scope["path"] == "/api/queue" or scope["path"].startswith("/api/queue/")
    slow = (
        total_ms >= QUEUE_ACCESS_LOG_MS
        or scope["lock_wait_ms"] >= QUEUE_ACCESS_LOG_MS
        or scope["handler_ms"] >= QUEUE_ACCESS_LOG_MS
        or bool(scope["lock_events"])
        or bool(scope["slow_ops"])
    )
    # Default: only slow queue requests, failures/disconnects, or full tracing.
    # Fast queue requests stay silent so the log volume does not grow.
    if not (
        (is_queue_path and slow)
        or scope["error"]
        or scope["write_error"]
        or QUEUE_ACCESS_LOG_ALL
    ):
        return
    log(
        f"[req] request={scope.get('id') or '-'} method={scope['method'] or '-'} "
        f"path={scope['path'] or '-'} status={scope['status'] or 0} "
        f"accept_ms={_ms(scope['accept_ms'])} "
        f"lock_wait_ms={_ms(scope['lock_wait_ms'])} lock_hold_ms={_ms(scope['lock_hold_ms'])} "
        f"lock_hold_max_ms={_ms(scope['lock_hold_max_ms'])} lock_count={scope['lock_count']} "
        f"handler_ms={_ms(scope['handler_ms'])} response_write_ms={_ms(scope['response_write_ms'])} "
        f"after_handler_ms={_ms(after_handler_ms)} "
        f"total_ms={_ms(total_ms)} "
        f"locks={'|'.join(scope['lock_events']) or '-'} "
        f"sections={'|'.join(scope['lock_sections']) or '-'} "
        f"slow_ops={'|'.join(scope['slow_ops']) or '-'} "
        f"qb={'|'.join(scope['qb_calls']) or '-'} "
        f"error={scope['error'] or '-'} write_error={scope['write_error'] or '-'}"
    )


def _end_request_scope(handler):
    scope = _request_scope()
    if scope is None:
        return
    try:
        _emit_request_log(scope)
    finally:
        _request_ctx.scope = None


def _p115_probe(p115, force=False):
    """Use probe_cached when present; old images only have test_connection."""
    probe = getattr(p115, "probe_cached", None)
    if callable(probe):
        return probe(force=True) if force else probe()
    return p115.test_connection()


def _p115_public_config(p115, refresh=False):
    try:
        return p115.public_config(refresh=refresh)
    except TypeError:
        return p115.public_config()


def _actress_is_blocked(name: str) -> bool:
    """Match blocked actresses with fold (空白/尾标点/常见繁简), same as Go."""
    raw = (name or "").strip()
    if not raw:
        return False
    if raw in BLOCKED_ACTRESSES:
        return True
    try:
        from src.weekly import actresses as actress_util

        # file + env via actress_util; also honor in-process env set
        if actress_util.is_blocked_actress(raw):
            return True
        # env-only names may not be in file
        fold = actress_util.fold_actress_key(raw)
        for b in BLOCKED_ACTRESSES:
            if actress_util.fold_actress_key(b) == fold:
                return True
    except Exception:
        pass
    return False


def queue_route_locked(method):
    """Legacy handler-wide lock — kept only for DELETE.

    GET/POST no longer use it: they take queue_state_critical() around their
    local read-modify-write sections and keep slow/external work unlocked.
    """
    def wrapped(self, *args, **kwargs):
        path = urlparse(self.path).path.rstrip("/")
        scope = _request_scope()
        if path != "/api/queue" and not path.startswith("/api/queue/"):
            if scope is None:
                return method(self, *args, **kwargs)
            started = time.monotonic()
            try:
                return method(self, *args, **kwargs)
            finally:
                scope["handler_ms"] = (time.monotonic() - started) * 1000.0
                scope["handler_done_ts"] = time.monotonic()

        _ensure_request_id(self)
        started = time.monotonic()
        with queue_state_critical("handler"):
            try:
                return method(self, *args, **kwargs)
            finally:
                if scope is not None:
                    scope["handler_ms"] = (time.monotonic() - started) * 1000.0
                    scope["handler_done_ts"] = time.monotonic()
    return wrapped

def clean_avid(name):
    """从文件夹/种子名中提取标准车牌号（去掉 -C, ch, 中文字幕 等后缀）"""
    return normalize_local_video_id(name) or str(name or "").strip().upper()


# qB states that mean "still our job" (must include queuedDL — waiting for a slot)
_QB_ACTIVE_DL = frozenset({
    "downloading", "stalledDL", "metaDL", "forcedDL", "queuedDL",
    "pausedDL", "stoppedDL", "checkingDL", "allocating", "moving", "checkingResumeData",
})
_QB_DONE_UP = frozenset({
    "queuedUP", "uploading", "stalledUP", "pausedUP", "stoppedUP", "forcedUP",
})


def code_from_qb_torrent(torrent):
    """Resolve DVD code from qB torrent: tags (worker sets tags=番号) then name/path."""
    tags = str(torrent.get("tags") or "")
    for tag in tags.split(","):
        tag = tag.strip().upper()
        if not tag:
            continue
        normalized = normalize_video_id(tag) or clean_avid(tag)
        if normalized and re.match(r"^[A-Z0-9]+-\d+", normalized):
            return normalized
    for field in (
        torrent.get("name", ""),
        torrent.get("content_path", ""),
        os.path.basename(str(torrent.get("save_path", "")).rstrip("/")),
    ):
        code = clean_avid(str(field or ""))
        if code and re.match(r"^[A-Z0-9]+-\d+", code):
            return code
    return ""


def qb_status_from_state(torrent_state):
    """Map qB state → queue API status string."""
    if torrent_state in _QB_DONE_UP:
        return "done"
    if torrent_state in _QB_ACTIVE_DL:
        if torrent_state in ("queuedDL", "pausedDL", "stoppedDL"):
            return "queued"
        return "downloading"
    return ""


def codes_in_qb(torrents):
    """Set of active/recent DVD codes present in AV_GARDEN category."""
    out = set()
    if not isinstance(torrents, list):
        return out
    for t in torrents:
        st = str(t.get("state") or "")
        if st not in _QB_ACTIVE_DL and st not in _QB_DONE_UP:
            continue
        code = code_from_qb_torrent(t)
        if code and (st in _QB_ACTIVE_DL or find_mp4_path(code)):
            out.add(code)
    return out

_speed_cache = {}
_speed_cache_lock = threading.Lock()
_SPEED_CACHE_MAX_SIZE = 10000  # 最多缓存 10000 个番号的速度记录

# qBittorrent 配置
QB_URL = os.environ.get("QBITTORRENT_URL", "http://127.0.0.1:8080")
QB_USERNAME = os.environ.get("QBITTORRENT_USERNAME", "admin")
QB_PASSWORD = os.environ.get("QBITTORRENT_PASSWORD", "")

def log(msg):
    print(f"[QueueAPI] {msg}", flush=True)


def log_write(source, message):
    """写入 av-garden.log，与 launcher 的 log_write 保持一致"""
    from datetime import datetime
    log_dir = os.environ.get("LOG_DIR", "/app/logs")
    log_file = os.path.join(log_dir, "av-garden.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a") as f:
            f.write(f"{ts} [{source}] {message}\n")
    except Exception:
        pass


def qb_request(endpoint, data=None, caller=None):
    """Call qBittorrent Web API with a fresh authenticated session.

    Timings are diagnostics only; credentials/SID are never logged.
    """
    import http.cookiejar
    import urllib.parse
    import urllib.request

    scope = _request_scope()
    caller = caller or _qb_caller()
    started = time.monotonic()
    login_ms = 0.0
    api_ms = 0.0
    login_status = 0
    api_status = 0

    def _finish(result):
        total_ms = (time.monotonic() - started) * 1000.0
        if total_ms >= QUEUE_ACCESS_LOG_MS or QUEUE_ACCESS_LOG_ALL:
            detail = (
                f"{caller}:{endpoint}:login={_ms(login_ms)},api={_ms(api_ms)},"
                f"total={_ms(total_ms)},login_status={login_status},status={api_status}"
            )
            if scope is not None:
                scope["qb_calls"].append(detail)
            log(
                f"[qb] request={(scope or {}).get('id') or '-'} caller={caller} endpoint={endpoint} "
                f"login_ms={_ms(login_ms)} api_ms={_ms(api_ms)} total_ms={_ms(total_ms)} "
                f"login_status={login_status} status={api_status}"
            )
        return result

    if not QB_PASSWORD:
        log("QBITTORRENT_PASSWORD is not configured")
        return _finish(None)
    try:
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        login_url = f"{QB_URL}/api/v2/auth/login"
        login_data = f"username={urllib.parse.quote(QB_USERNAME)}&password={urllib.parse.quote(QB_PASSWORD)}".encode()
        login_started = time.monotonic()
        try:
            resp = opener.open(urllib.request.Request(login_url, data=login_data), timeout=5)
        finally:
            login_ms = (time.monotonic() - login_started) * 1000.0
        try:
            try:
                login_status = int(getattr(resp, "status", 0) or 0)
            except (TypeError, ValueError):
                login_status = 0
            if resp.status != 200:
                return _finish(None)
            request_data = urllib.parse.urlencode(data).encode() if data is not None else None
            request = urllib.request.Request(f"{QB_URL}{endpoint}", data=request_data)
            api_started = time.monotonic()
            try:
                resp2 = opener.open(request, timeout=10)
            finally:
                api_ms = (time.monotonic() - api_started) * 1000.0
            try:
                try:
                    api_status = int(getattr(resp2, "status", 0) or 0)
                except (TypeError, ValueError):
                    api_status = 0
                body = resp2.read().decode().strip()
                if not body or body == "Ok.":
                    return _finish(True)
                if body == "Fails.":
                    return _finish(None)
                return _finish(json.loads(body))
            finally:
                resp2.close()
        finally:
            resp.close()
    except Exception as e:
        log(f"qB API error: {e}")
        return _finish(None)


def qb_api(endpoint):
    return qb_request(endpoint)


def qb_remove_code(code, delete_files=False):
    """Remove qBittorrent tasks for a code with safety checks."""
    torrents = qb_api("/api/v2/torrents/info")
    if not isinstance(torrents, list):
        return False
    hashes = []
    for torrent in torrents:
        tags = {tag.strip().upper() for tag in str(torrent.get("tags", "")).split(",") if tag.strip()}
        candidates = set()
        for value in (torrent.get("name", ""), torrent.get("save_path", ""), torrent.get("content_path", "")):
            value = str(value)
            for token in re.findall(r"[A-Z0-9]+(?:[-_][A-Z0-9]+){0,2}", value.upper()):
                variants = {token, re.sub(r"(?:[-_](?:C|CH)|CH)$", "", token)}
                for variant in variants:
                    normalized = normalize_video_id(variant)
                    if normalized:
                        candidates.add(normalized)
        if code in tags or code in candidates:
            torrent_hash = str(torrent.get("hash", "")).strip()
            if torrent_hash:
                # Safety check before allowing file deletion
                if delete_files:
                    state = str(torrent.get("state", ""))
                    content_path = str(torrent.get("content_path", ""))
                    save_path_env = os.environ.get("SAVE_PATH", "/data")

                    # Refuse deletion if torrent is active or seeding
                    if state in ("downloading", "stalledDL", "metaDL", "checkingDL", "checkingResumeData", "uploading", "stalledUP", "queuedUP", "checkingUP", "forcedUP"):
                        log(f"Refuse to delete files for active/seeding torrent {code} (state={state})")
                        continue

                    # Verify content_path is within SAVE_PATH
                    if content_path:
                        try:
                            real_save = os.path.realpath(save_path_env)
                            real_content = os.path.realpath(content_path)
                            if os.path.commonpath([real_save, real_content]) != real_save:
                                log(f"Refuse to delete files outside SAVE_PATH: {content_path}")
                                delete_files = False
                        except (ValueError, OSError) as e:
                            log(f"Path validation failed for {content_path}: {e}")
                            delete_files = False

                    # Check if content_path is used by other torrents
                    if content_path and delete_files:
                        for other in torrents:
                            if other.get("hash") == torrent_hash:
                                continue
                            other_path = str(other.get("content_path", ""))
                            if other_path and os.path.realpath(other_path) == os.path.realpath(content_path):
                                log(f"Refuse to delete {content_path}: shared by torrent {other.get('hash', 'unknown')[:12]}")
                                delete_files = False
                                break

                hashes.append(torrent_hash)
    if not hashes:
        return False

    # Audit log before deletion
    if delete_files:
        log(f"AUDIT: Deleting files for {code}, hashes={','.join(h[:12] for h in hashes)}")

    result = qb_request(
        "/api/v2/torrents/delete",
        {"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"},
    )
    if delete_files and result is True:
        log(f"Deleted qB task(s) for {code} with files (hashes={len(hashes)})")
        log_write("Cleanup", f"{code} qB任务及文件已删除 (hashes={len(hashes)})")
    return result is True


def get_qb_progress(save_dir, torrents=None):
    """从 qBittorrent 获取指定下载目录的进度 {size, speed, progress_pct}"""
    if torrents is None:
        torrents = qb_api("/api/v2/torrents/info")
    if not torrents:
        return None
    code = os.path.basename(save_dir.rstrip("/")).upper()
    for t in torrents:
        state = str(t.get("state") or "")
        if state not in _QB_ACTIVE_DL and state not in _QB_DONE_UP:
            continue
        t_code = code_from_qb_torrent(t)
        if t_code and (t_code == code or clean_avid(t_code) == clean_avid(code)):
            if state in _QB_DONE_UP and not find_mp4_path(t_code):
                continue
            return {
                "size": t.get("completed", 0),
                "speed": t.get("dlspeed", 0),
                "progress_pct": int(t.get("progress", 0) * 100),
            }
        cp = (t.get("content_path", "") or t.get("name", "")).upper()
        if code in cp:
            if state in _QB_DONE_UP and not find_mp4_path(code):
                continue
            return {
                "size": t.get("completed", 0),
                "speed": t.get("dlspeed", 0),
                "progress_pct": int(t.get("progress", 0) * 100),
            }
    return None

def load_state():
    """Load queue state with file lock protection."""
    value = read_json(STATE_PATH, [])
    return value if isinstance(value, list) else []

def save_state(items):
    """Save queue state with file lock protection."""
    write_json(STATE_PATH, items)


def is_stale_heal_ghost(item, *, qb_codes, is_locked, current_code) -> bool:
    """Heal-recovered processing rows with no lock/files/qB should not stay visible."""
    if not isinstance(item, dict):
        return False
    code = item.get("code")
    if not code:
        return False
    if is_locked and code == current_code:
        return False
    if code in qb_codes:
        return False
    status = str(item.get("status") or "")
    recovered = bool(item.get("_heal_recovered"))
    post_done = bool(item.get("_post_done"))
    if status != "processing" and not (
        recovered and post_done and status not in ("queued", "downloading", "done")
    ):
        return False
    if find_mp4_path(code) is not None or find_ts_path(code) is not None:
        return False
    code_dir = get_code_dir(code)
    if os.path.isdir(code_dir) and get_dir_size(code_dir) > 0:
        return False
    return True


def update_state(updater):
    """Update queue state atomically with file lock protection."""
    return update_json(STATE_PATH, [], updater)

def load_history():
    history = read_json(HISTORY_PATH, [])
    return prune_history(history) if isinstance(history, list) else []

def save_history(items):
    write_json(HISTORY_PATH, items)

def parse_history_time(value):
    if not value:
        return None
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return time.mktime(time.strptime(value[:size], fmt))
        except:
            pass
    return None

def is_recent_timestamp(value):
    if not value:
        return True
    try:
        ts = float(value)
    except:
        return True
    if ts <= 0:
        return True
    return ts >= time.time() - HISTORY_RETENTION_DAYS * 86400

def prune_history(items):
    if not isinstance(items, list):
        return []
    cutoff = time.time() - HISTORY_RETENTION_DAYS * 86400
    kept = []
    changed = False
    for item in items:
        completed_at = parse_history_time(item.get("completed_at", ""))
        if completed_at is None or completed_at >= cutoff:
            kept.append(item)
        else:
            changed = True
    if changed:
        save_history(kept)
    return kept

def append_history(code, size):
    """追加一条完成记录（去重）"""
    history = load_history()
    if code in [h["code"] for h in history]:
        return
    history.append({
        "code": code,
        "size": size,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_history(history)

def run_post_download_actions(code, size):
    """Idempotent post-download side effects (safe to repeat after a crash).

    weekly.json only flips `downloaded`, the MissAV row is existence-checked +
    INSERT OR REPLACE, append_history de-duplicates by code and
    clear_failure_record is idempotent. The completion mark is written only
    after these return, so a crash in between re-runs them instead of losing
    them permanently.
    """
    results = {}
    actions = (
        ("weekly", lambda: update_weekly_json_downloaded(code)),
        ("db", lambda: write_to_missav_db(code)),
        ("history", lambda: append_history(code, size)),
        ("clear_failure", lambda: clear_failure_record(code)),
    )
    for name, action in actions:
        try:
            results[name] = action()
        except Exception as exc:
            log(f"Post-download {name} failed for {code}: {exc}")
            results[name] = False
    return results


def is_weekly_scrape_running():
    global weekly_scrape_proc
    if weekly_scrape_proc and weekly_scrape_proc.poll() is None:
        return True
    weekly_scrape_proc = None
    return is_pipeline_running()

def _watch_weekly_scrape(proc):
    """Wait for weekly_updater, then run the safe unwatched-CN follow-up."""
    try:
        proc.wait(timeout=7200)
        rc = proc.returncode
        if rc == 0:
            log("Manual weekly scrape finished successfully")
            log_write("ManualScrape", "刮削完成 (weekly_updater)")
            followup = subprocess.run(
                ["/app/venv/bin/python3", "/app/run_scrape_followups.py"],
                timeout=3900,
                check=False,
            )
            if followup.returncode == 0:
                log("Manual scrape follow-up finished successfully")
                log_write("ManualScrape", "未看中文补链完成")
            else:
                log(f"Manual scrape follow-up failed (exit {followup.returncode})")
                log_write("ManualScrape", f"未看中文补链失败 (exit {followup.returncode})")
                status = read_scrape_status()
                if status.get("running"):
                    finish_pipeline(
                        summary="每日推荐已更新，但未看中文补链未完成",
                        error=str(status.get("last_error") or f"follow-up exit={followup.returncode}"),
                        stats=status.get("stats") if isinstance(status.get("stats"), dict) else {},
                    )
        else:
            log(f"Manual weekly scrape failed (exit {rc})")
            log_write("ManualScrape", f"刮削失败 (exit {rc})")
            finish_pipeline(
                summary="每日推荐刮削未完成",
                error=f"weekly_updater exit={rc}",
            )
    except subprocess.TimeoutExpired:
        if proc.poll() is None:
            proc.kill()
            message = "每日推荐刮削超时，已终止"
        else:
            message = "未看中文补链超时，已终止"
        finish_pipeline(summary="刮削流程未完成", error=message)
        log(message)
        log_write("ManualScrape", message)
    except Exception as e:
        log(f"Manual weekly scrape watcher error: {e}")
        log_write("ManualScrape", f"刮削异常: {e}")
        finish_pipeline(summary="刮削流程未完成", error=str(e))


def start_weekly_scrape():
    global weekly_scrape_proc
    with weekly_scrape_lock:
        if is_weekly_scrape_running():
            return False
        if not begin_pipeline(PHASE_WEEKLY, trigger="manual"):
            return False
        log_write("ManualScrape", "刮削开始 (weekly_updater)")
        try:
            weekly_scrape_proc = subprocess.Popen(
                ["/app/venv/bin/python3", "/app/weekly_updater.py"],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except Exception as e:
            finish_pipeline(summary="每日推荐刮削未启动", error=str(e))
            log_write("ManualScrape", f"刮削启动失败: {e}")
            return False
        # 后台监控子进程，结束后写日志
        t = threading.Thread(target=_watch_weekly_scrape, args=(weekly_scrape_proc,), daemon=True)
        t.start()
        return True

def clear_failure_record(code):
    """重新入队时清理旧失败/重试记录，避免刚添加就显示失败。"""
    code = code.upper().strip()
    try:
        update_json(
            FAILED_QUEUE_JSON_PATH,
            [],
            lambda records: [r for r in records if str(r.get("code", "")).upper() != code]
            if isinstance(records, list) else [],
        )
    except Exception as e:
        log(f"Failed to clear failed_queue.json for {code}: {e}")

    try:
        remove_code(FAILED_QUEUE_PATH, code)
    except Exception as e:
        log(f"Failed to clear failed_queue.txt for {code}: {e}")

    try:
        def clear_retry_value(retries):
            retries = retries if isinstance(retries, dict) else {}
            retries.pop(code, None)
            return retries
        update_json(RETRY_PATH, {}, clear_retry_value)
    except Exception as e:
        log(f"Failed to clear retry count for {code}: {e}")


def load_failure_codes():
    codes = set()
    try:
        records = read_json(FAILED_QUEUE_JSON_PATH, [])
        if isinstance(records, list):
            for item in records:
                code = str(item.get("code", "")).upper().strip()
                if code:
                    codes.add(code)
    except Exception as e:
        log(f"Failed to read failed_queue.json: {e}")

    try:
        if os.path.exists(FAILED_QUEUE_PATH):
            with open(FAILED_QUEUE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    code = line.strip().upper()
                    if code:
                        codes.add(code)
    except Exception as e:
        log(f"Failed to read failed_queue.txt: {e}")

    return codes

def get_lock():
    try:
        with open(LOCK_PATH, "r") as f:
            return f.read().strip() == "1"
    except:
        return False

def read_current_download():
    items = read_queue(CURRENT_PATH)
    return items[0] if items else None

def write_current_download(code):
    write_queue(CURRENT_PATH, [code])

def clear_current_download(expected=None):
    if expected:
        return clear_if_matches(CURRENT_PATH, expected)
    write_queue(CURRENT_PATH, [])
    return True

def get_code_dir(code):
    try:
        return safe_video_dir(SAVE_PATH, code)
    except ValueError:
        return safe_local_dir(SAVE_PATH, code)

def find_ts_path(code):
    dir_path = get_code_dir(code)
    if not os.path.isdir(dir_path):
        return None
    for f in sorted(os.listdir(dir_path), reverse=True):
        path = os.path.join(dir_path, f)
        if f.endswith('.ts') and os.path.getsize(path) > 1024:
            return path
    return None

def find_mp4_path(code):
    """Return the same recursively validated main MP4 used by the Go server."""
    normalized = normalize_local_video_id(code) or normalize_video_id(code)
    if not normalized:
        return None
    return get_main_video_index().get(normalized)


def get_main_video_index():
    global main_video_cache, main_video_cache_root, main_video_cache_time
    root = os.path.realpath(SAVE_PATH)
    now = time.time()
    with main_video_cache_lock:
        if (
            main_video_cache_root == root
            and now - main_video_cache_time < MAIN_VIDEO_CACHE_TTL_SECONDS
        ):
            return main_video_cache
        build_started = time.monotonic()
        primary = {}
        alias_candidates = {}
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                path = os.path.join(root, name)
                if not os.path.isdir(path) or name.startswith("__") or name == "thumb":
                    continue
                main_video = find_main_video(path)
                if not main_video:
                    continue
                aliases = local_video_id_aliases(name)
                if aliases:
                    primary[aliases[0]] = main_video
                    for alias in aliases[1:]:
                        alias_candidates.setdefault(alias, set()).add(main_video)
        index = dict(primary)
        for alias, candidates in alias_candidates.items():
            if alias not in index and len(candidates) == 1:
                index[alias] = next(iter(candidates))
        _slow_op(
            "get_main_video_index",
            (time.monotonic() - build_started) * 1000.0,
            f"items={len(index)}",
        )
        main_video_cache = index
        main_video_cache_root = root
        main_video_cache_time = now
        return main_video_cache

def get_dir_size(path):
    started = time.monotonic()
    try:
        r = subprocess.run(["du", "-sb", path], capture_output=True, text=True, timeout=5)
        size = int(r.stdout.split()[0])
    except:
        size = 0
    _slow_op(
        "du",
        (time.monotonic() - started) * 1000.0,
        f"path={os.path.basename(str(path).rstrip('/')) or path}",
    )
    return size

def get_file_size(path):
    try:
        return os.path.getsize(path)
    except:
        return 0

def parse_duration_minutes(text):
    if not text:
        return None
    m = re.search(r'(\d+)\s*分鐘', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*min', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+):(\d+)', text)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    return None

def get_duration_from_weekly(code):
    if not os.path.exists(WEEKLY_JSON):
        return None
    try:
        with open(WEEKLY_JSON, "r") as f:
            items = json.load(f)
        for item in items:
            if item.get("id", "").upper() == code.upper():
                dur = item.get("duration", "")
                if dur:
                    mins = parse_duration_minutes(dur)
                    if mins:
                        return mins * 60
                return None
    except:
        pass
    return None

def get_ts_duration_seconds(ts_path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", ts_path],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and r.stdout.strip():
            val = float(r.stdout.strip())
            if val > 0:
                return val
    except:
        pass
    return None

def update_weekly_json_downloaded(code):
    """Update weekly.json: set downloaded=true for this code"""
    if not os.path.exists(WEEKLY_JSON):
        return False
    changed = False
    try:
        def mark_downloaded(items):
            nonlocal changed
            for item in items if isinstance(items, list) else []:
                if item.get("id", "").upper() == code.upper():
                    if item.get("downloaded") is not True:
                        item["downloaded"] = True
                        changed = True
                    break
            return items

        update_weekly_json(WEEKLY_JSON, [], mark_downloaded)
        if changed:
            log(f"Updated weekly.json: {code} downloaded=true")
            return True
    except Exception as e:
        log(f"Failed to update weekly.json: {e}")
    return False

def write_to_missav_db(code):
    """Write to AV/GARDEN SQLite MissAV table so it shows on homepage"""
    conn = None
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            pass
        
        # Check if already exists
        cur = conn.execute("SELECT bvid FROM MissAV WHERE bvid = ?", (code,))
        if cur.fetchone():
            log(f"{code} already in MissAV table")
            return True
        
        # Get metadata from weekly.json
        title = code
        title_jp = ""
        actresses = "[]"
        genres = "[]"
        release_date = ""
        duration = ""
        
        if os.path.exists(WEEKLY_JSON):
            with open(WEEKLY_JSON, "r") as f:
                items = json.load(f)
            for item in items:
                if item.get("id", "").upper() == code.upper():
                    title = item.get("title", code)
                    title_jp = item.get("titleJp", "")
                    actresses = json.dumps(item.get("actresses", []), ensure_ascii=False)
                    genres = json.dumps(item.get("genres", []), ensure_ascii=False)
                    release_date = item.get("releaseDate", "")
                    duration = item.get("duration", "")
                    break

        # 屏蔽演员检查（精确 + fold，与 Go weekly 过滤一致）
        act_list = json.loads(actresses) if isinstance(actresses, str) else actresses
        if any(_actress_is_blocked(a) for a in (act_list or [])):
            log(f"Blocked: {code} (actress in blocklist)")
            return False

        # Insert into MissAV table
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT OR REPLACE INTO MissAV 
            (bvid, title, title_jp, actresses, genres, release_date, duration, source, found_date, add_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, title, title_jp, actresses, genres, release_date, duration, "weekly_queue", now, now))
        conn.commit()
        log(f"Wrote {code} to MissAV DB → homepage visible!")
        return True
    except Exception as e:
        log(f"Failed to write to MissAV DB: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()

def get_download_info(code, torrents=None):
    """Returns {size, speed, progress_pct}.

    `torrents` lets a caller reuse one request-scoped /torrents/info snapshot
    instead of triggering another qB login + query inside the same request.
    """
    # qB 优先取实时速度
    save_dir = get_code_dir(code)
    qb_progress = get_qb_progress(save_dir, torrents=torrents)
    if qb_progress:
        return qb_progress

    mp4_path = find_mp4_path(code)
    if mp4_path:
        total = get_file_size(mp4_path)
        return {"size": total, "speed": 0, "progress_pct": 100}

    ts_path = find_ts_path(code)
    if ts_path:
        current = get_file_size(ts_path)
        current_sec = get_ts_duration_seconds(ts_path)
    else:
        # 没有 .ts 文件，qB 已经在函数开头查过了，直接看磁盘
        if os.path.isdir(save_dir):
            current = get_dir_size(save_dir)
            current_sec = None
        else:
            current = 0
            current_sec = None

    now = time.time()
    speed = 0
    with _speed_cache_lock:
        if code in _speed_cache:
            prev_bytes, prev_time = _speed_cache[code]
            elapsed = now - prev_time
            if elapsed > 0 and current >= prev_bytes:
                speed = (current - prev_bytes) / elapsed
        _speed_cache[code] = (current, now)
        # LRU 淘汰：超过上限时删除最旧的 20%
        if len(_speed_cache) > _SPEED_CACHE_MAX_SIZE:
            sorted_items = sorted(_speed_cache.items(), key=lambda x: x[1][1])
            to_remove = int(_SPEED_CACHE_MAX_SIZE * 0.2)
            for old_code, _ in sorted_items[:to_remove]:
                del _speed_cache[old_code]

    progress_pct = 0
    if current_sec and current_sec > 0:
        total_sec = get_duration_from_weekly(code)
        if total_sec and total_sec > 0:
            progress_pct = min(99, int(current_sec / total_sec * 100))
        else:
            est_total = 1.5 * 1024**3
            progress_pct = min(99, int(current / est_total * 100))
    elif current > 0:
        est_total = 1.5 * 1024**3
        progress_pct = min(99, int(current / est_total * 100))

    return {"size": current, "speed": speed, "progress_pct": progress_pct}

def read_queue_file():
    try:
        return read_queue(QUEUE_PATH)
    except Exception:
        return []


def normalize_online_code(raw):
    return normalize_video_id(unquote(str(raw or "")))


def online_code_dir(code):
    """Return safe path for online code directory with realpath resolution."""
    normalized = code.upper()
    if not normalized or normalized in (".", "..") or "/" in normalized or "\\" in normalized:
        raise ValueError("invalid online code")
    root = os.path.realpath(ONLINE_DIR)
    target = os.path.realpath(os.path.join(ONLINE_DIR, normalized))
    if os.path.commonpath([root, target]) != root:
        raise ValueError("online path escapes base directory")
    return target


def cleanup_online_detail(code):
    code = normalize_online_code(code)
    if not code:
        return False
    try:
        target = online_code_dir(code)
    except ValueError as e:
        log(f"Invalid online code path {code}: {e}")
        return False
    removed = False
    if os.path.isdir(target):
        shutil.rmtree(target)
        log(f"Cleaned online temp detail: {code}")
        removed = True
    if not _has_registered_job(code):
        try:
            from download_source import delete_cached_source
            delete_cached_source(code)
        except Exception as e:
            log(f"Online source cache cleanup failed for {code}: {e}")
    return removed


def _has_registered_job(code):
    target = normalize_online_code(code)
    if not target:
        return False
    if target == read_current_download():
        return True
    if target in {normalize_online_code(item) for item in read_queue(QUEUE_PATH)}:
        return True
    return any(
        normalize_online_code(item.get("code")) == target
        and item.get("status") in ("queued", "downloading")
        for item in load_state()
        if isinstance(item, dict)
    )


def cleanup_expired_online_details(now=None):
    if not os.path.isdir(ONLINE_DIR):
        return []
    cutoff = (time.time() if now is None else now) - ONLINE_TTL_SECONDS
    root = os.path.realpath(ONLINE_DIR)
    removed = []
    for name in os.listdir(ONLINE_DIR):
        target = os.path.join(ONLINE_DIR, name)
        try:
            if not os.path.isdir(target) or os.path.islink(target) or os.path.getmtime(target) > cutoff:
                continue
            real_target = os.path.realpath(target)
            if os.path.commonpath([root, real_target]) != root:
                continue
            shutil.rmtree(real_target)
            removed.append(name)
        except (OSError, ValueError) as error:
            log(f"Online TTL cleanup skipped {name}: {error}")
    if removed:
        log(f"Cleaned {len(removed)} expired online detail cache(s): {', '.join(sorted(removed))}")
    return removed


def online_cleanup_loop(stop_event=None):
    stop_event = stop_event or threading.Event()
    while not stop_event.wait(ONLINE_CLEANUP_INTERVAL_SECONDS):
        cleanup_expired_online_details()
        try:
            from download_source import cleanup_expired_sources
            cleanup_expired_sources()
        except Exception as e:
            log(f"Download source TTL cleanup failed: {e}")


def _usable_online_title(text, code):
    title = str(text or "").strip()
    if not title:
        return False
    if title.upper() == str(code or "").upper():
        return False
    studio = str(code or "").split("-", 1)[0]
    if studio and title.upper() == studio.upper():
        return False
    return True


def fill_online_missing_title(item, code, source=None):
    """When enrich left title as the code, use magnet listing or JavBus."""
    if _usable_online_title(item.get("title"), code):
        return False
    src_title = str((source or {}).get("title") or "").strip()
    if _usable_online_title(src_title, code):
        item["title"] = src_title
        return True
    try:
        from src.weekly import javbus

        javbus.set_proxy(ONLINE_PROXY)
        html = javbus.fetch_page(code)
        detail = javbus.parse_page(html) if html else {}
        official = str(detail.get("title") or "").strip()
        if _usable_online_title(official, code):
            item["title"] = official
            return True
    except Exception as e:
        log(f"Online JavBus title fallback failed for {code}: {e}")
    return False


def translate_online_title_zh(item, code):
    """One-shot Chinese title for online search details."""
    try:
        from src.weekly import actresses as actress_util

        if not actress_util.item_needs_title_zh(item):
            return False
        from weekly_updater import translate_title_once

        zh = translate_title_once(code, item.get("title"), item.get("actresses"))
        if not zh:
            return False
        item["titleZh"] = zh
        actress_util.finalize_title_zh(item)
        return bool(str(item.get("titleZh") or "").strip())
    except Exception as e:
        log(f"Online title translate failed for {code}: {e}")
        return False


def build_online_detail(raw_code):
    code = normalize_online_code(raw_code)
    if not code:
        return None, "invalid code"
    try:
        from download_source import resolve_download_source
        from src.weekly import enrich

        item = {
            "id": code,
            "title": code,
            "titleZh": "",
            "titleJp": "",
            "cover": "",
            "poster": "",
            "releaseDate": "",
            "duration": "",
            "actresses": [],
            "genres": [],
            "fanarts": [],
            "hasChinese": False,
            "size": "",
            "source": "online",
            "downloaded": False,
        }
        enrich.enrich_item(
            item,
            save_dir=ONLINE_DIR,
            proxy=ONLINE_PROXY,
            download_images=True,
        )

        source = {}
        try:
            source = resolve_download_source(code, proxy=ONLINE_PROXY) or {}
        except Exception as source_error:
            log(f"Online download source lookup failed for {code}: {source_error}")
        item["magnet"] = source.get("magnet") or ""
        item["magnetSource"] = source.get("source") or ""
        item["hasChinese"] = item["magnetSource"] in (
            "plwt_chinese",
            "sukebei_chinese",
        )
        fill_online_missing_title(item, code, source)
        # Do not translate here: Grok/relay timeouts made /search sit on 加载中 for minutes.

        metadata_found = any((
            item.get("title") and item.get("title") != code,
            item.get("actresses"),
            item.get("genres"),
            item.get("releaseDate"),
            item.get("duration"),
            item.get("maker"),
            item.get("series"),
            item.get("label"),
        ))
        artwork_found = bool(item.get("cover") or item.get("poster") or item.get("fanarts"))
        download_found = bool(item.get("magnet"))
        if not (metadata_found or artwork_found or download_found):
            return None, "detail not found"
        return item, ""
    except Exception as e:
        log(f"Online detail lookup failed for {code}: {e}")
        return None, "lookup failed"


def resolve_actresses_remote(raw_code):
    """Resolve JP actress names via MGS then DMM (no artwork/magnet)."""
    code = normalize_online_code(raw_code)
    if not code:
        return None, "invalid code"
    proxy = ONLINE_PROXY
    try:
        from src.weekly import actresses as actress_util
        from src.weekly import dmm, mgs

        mgs.set_proxy(proxy)
        dmm.set_proxy(proxy)

        # MGS first
        try:
            meta = mgs.fetch_detail(code)
        except Exception as e:
            log(f"resolve-actresses MGS {code}: {e}")
            meta = None
        if meta and meta.get("actresses"):
            names = actress_util.clean_actresses(meta.get("actresses"))
            if names:
                return {"code": code, "source": "mgs", "actresses": names}, ""

        # DMM
        try:
            meta = dmm.fetch_metadata(code)
        except Exception as e:
            log(f"resolve-actresses DMM {code}: {e}")
            meta = None
        if meta and meta.get("actresses"):
            names = actress_util.clean_actresses(meta.get("actresses"))
            if names:
                return {"code": code, "source": "dmm", "actresses": names}, ""

        return {"code": code, "source": "none", "actresses": []}, "no actresses found"
    except Exception as e:
        log(f"resolve-actresses failed {code}: {e}")
        return None, "lookup failed"


def localize_weekly_fanarts(raw_code):
    code = normalize_online_code(raw_code)
    if not code:
        return None, "invalid code"
    if not os.path.exists(WEEKLY_JSON):
        return None, "weekly not found"
    try:
        from src.weekly import javbus
        javbus.set_proxy(ONLINE_PROXY)
        with weekly_json_lock, weekly_update_lock(WEEKLY_JSON):
            with open(WEEKLY_JSON, "r", encoding="utf-8") as f:
                items = json.load(f)
            if not isinstance(items, list):
                return None, "weekly not found"

            target = None
            for item in items:
                item_id = normalize_online_code(item.get("id", ""))
                if item_id == code:
                    target = item
                    break
            if target is None:
                return None, "detail not found"

            remote_fanarts = target.get("remoteFanarts") if isinstance(target.get("remoteFanarts"), list) else []
            fanarts = target.get("fanarts") if isinstance(target.get("fanarts"), list) else []
            source_fanarts = remote_fanarts or fanarts
            if not fanarts:
                html = javbus.fetch_page(code)
                detail = javbus.parse_page(html) if html else {}
                source_fanarts = detail.get("fanarts") if isinstance(detail.get("fanarts"), list) else []

            if any(str(url or "").startswith("http") for url in source_fanarts):
                target["remoteFanarts"] = source_fanarts
            local_fanarts = javbus.download_fanarts(code, source_fanarts, os.path.join(SAVE_PATH, "__weekly__"))
            next_fanarts = local_fanarts if local_fanarts else ([] if source_fanarts else fanarts)
            if target.get("remoteFanarts") != remote_fanarts or next_fanarts != target.get("fanarts"):
                target["fanarts"] = next_fanarts
                atomic_write_json(WEEKLY_JSON, items)
            return {"id": target.get("id") or code, "fanarts": local_fanarts}, ""
    except Exception as e:
        log(f"Weekly fanart localization failed for {code}: {e}")
        return None, "lookup failed"


class QueueHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that records how long a connection waited for its handler.

    The accept timestamp is handed to the handler thread through a thread-local
    (socket objects have __slots__, so they cannot carry attributes).
    """

    _accept_stamps = {}
    _accept_stamps_lock = threading.Lock()

    def process_request(self, request, client_address):
        now = time.monotonic()
        with self._accept_stamps_lock:
            if len(self._accept_stamps) > 256:
                cutoff = now - 60.0
                for key in [k for k, v in self._accept_stamps.items() if v < cutoff]:
                    self._accept_stamps.pop(key, None)
            self._accept_stamps[id(request)] = now
        super().process_request(request, client_address)

    def finish_request(self, request, client_address):
        with self._accept_stamps_lock:
            stamp = self._accept_stamps.pop(id(request), None)
        _accept_ctx.stamp = stamp
        try:
            super().finish_request(request, client_address)
        finally:
            _accept_ctx.stamp = None


class QueueHandler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        scope = _request_scope()
        _ensure_request_id(self)
        body = json.dumps(data, ensure_ascii=False).encode()
        write_started = time.monotonic()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-ID")
            if scope is not None and scope.get("id"):
                self.send_header("X-Request-ID", scope["id"])
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except Exception as exc:
            if scope is not None and not scope.get("write_error"):
                scope["write_error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if scope is not None:
                scope["response_write_ms"] += (time.monotonic() - write_started) * 1000.0

    def send_response(self, code, message=None):
        scope = _request_scope()
        if scope is not None:
            try:
                scope["status"] = int(code)
            except (TypeError, ValueError):
                pass
        super().send_response(code, message)

    def parse_request(self):
        ok = super().parse_request()
        if ok:
            _ensure_request_id(self)
        return ok

    def handle_one_request(self):
        self._qd_t_received = time.monotonic()
        # Gap between "connection accepted" and "this handler thread started":
        # distinguishes server accept/thread scheduling delay from handler work.
        self._qd_accept_ms = 0.0
        accept_ts = getattr(_accept_ctx, "stamp", None)
        if accept_ts:
            self._qd_accept_ms = max(0.0, (self._qd_t_received - accept_ts) * 1000.0)
        _begin_request_scope(self)
        try:
            super().handle_one_request()
        except Exception as exc:
            scope = _request_scope()
            if scope is not None and not scope.get("error"):
                scope["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _end_request_scope(self)

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/weekly-fanarts/"):
            raw_code = path.replace("/api/weekly-fanarts/", "", 1)
            item, error = localize_weekly_fanarts(raw_code)
            if not item:
                status = 400 if error == "invalid code" else 404
                self._json({"error": error}, status)
                return
            self._json(item)
            return

        if path.startswith("/api/online-search/"):
            raw_code = path.replace("/api/online-search/", "", 1)
            item, error = build_online_detail(raw_code)
            if not item:
                status = 400 if error == "invalid code" else 404
                self._json({"error": error}, status)
                return
            self._json(item)
            return

        if path.startswith("/api/resolve-actresses/"):
            raw_code = path.replace("/api/resolve-actresses/", "", 1)
            item, error = resolve_actresses_remote(raw_code)
            if not item:
                status = 400 if error == "invalid code" else 502
                self._json({"error": error, "actresses": []}, status)
                return
            if error and not item.get("actresses"):
                self._json({**item, "error": error}, 404)
                return
            self._json(item)
            return

        if path in ("/api/p115/config", "/api/p115/config/"):
            try:
                from src import p115_offline as p115

                self._json(_p115_public_config(p115, refresh=True))
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        if path in ("/api/p115/test", "/api/p115/test/"):
            try:
                from src import p115_offline as p115

                ok, msg = p115.test_connection()
                pub = p115.public_config()
                self._json({"ok": ok, "message": msg, **pub}, 200 if ok else 400)
            except Exception as e:
                self._json({"ok": False, "message": str(e)}, 500)
            return

        if path == "/api/scrape-status":
            is_pipeline_running()
            self._json(read_scrape_status())
            return

        if path != "/api/queue":
            self._json({"error": "not found"}, 404)
            return

        # Phase A — consistent local snapshot under a short lock. Nothing slow
        # (qB, du, os.walk) may happen while queue_state_lock is held.
        with queue_state_critical("get.snapshot"):
            state = load_state()
            snapshot = {
                "state": state,
                # Pristine copy used for phase-C revalidation: phase B mutates
                # `state` in place while building the response.
                "expected": {
                    str(item.get("code") or "").upper(): {
                        "status": item.get("status"),
                        "added_at": item.get("added_at"),
                    }
                    for item in state
                    if isinstance(item, dict) and item.get("code")
                },
                "queue_codes": read_queue_file(),
                "current_code": read_current_download(),
                "is_locked": get_lock(),
                "failed_codes": load_failure_codes(),
            }
        state = snapshot["state"]
        is_locked = snapshot["is_locked"]
        queue_codes = snapshot["queue_codes"]
        current_code = snapshot["current_code"]
        failed_codes = snapshot["failed_codes"]

        # Phase B — slow/external work runs unlocked; one qB snapshot per request.
        qb_torrents = qb_api("/api/v2/torrents/info")
        if not isinstance(qb_torrents, list):
            qb_torrents = []
        mutations = []
        
        result = {}
        
        # Items in queue.txt → queued（先用 qB 数据覆盖）
        for c in queue_codes:
            result[c] = {"code": c, "status": "queued", "size": 0, "speed": 0, "progress_pct": 0}
            qb_info = get_qb_progress(get_code_dir(c), qb_torrents)
            if qb_info:
                result[c] = {"code": c, "status": "downloading", **qb_info}
        
        # Current download
        if is_locked and current_code:
            mp4 = find_mp4_path(current_code)
            if mp4:
                # Already done but current_download.txt not cleaned
                total = get_file_size(mp4)
                result[current_code] = {"code": current_code, "status": "done", "size": total, "speed": 0, "progress_pct": 100}
                if current_code.upper() in failed_codes:
                    failed_codes.discard(current_code.upper())
                    mutations.append(("clear_failure", current_code))
                mutations.append(("clear_current", current_code))
                log(f"Cleaned stale current_download {current_code} (already done)")
            else:
                info = get_download_info(current_code, torrents=qb_torrents)
                result[current_code] = {"code": current_code, "status": "downloading", **info}
        elif is_locked and not current_code:
            # Scan state for downloading items
            for item in state:
                c = item["code"]
                if c not in queue_codes:
                    mp4 = find_mp4_path(c)
                    if mp4:
                        continue
                    has_ts = find_ts_path(c) is not None
                    if has_ts or get_dir_size(get_code_dir(c)) > 0:
                        info = get_download_info(c, torrents=qb_torrents)
                        result[c] = {"code": c, "status": "downloading", **info}
                        mutations.append(("set_current", c, False))
                        log(f"Discovered download from state: {c}")
                        break
            
            # If still no current download, scan disk for .ts files
            if not current_code and not any(r.get("status") == "downloading" for r in result.values()):
                if os.path.isdir(SAVE_PATH):
                    for d in sorted(os.listdir(SAVE_PATH), reverse=True):
                        dir_path = os.path.join(SAVE_PATH, d)
                        if not os.path.isdir(dir_path) or d.startswith("__"):
                            continue
                        has_ts = find_ts_path(d) is not None
                        if has_ts and not find_mp4_path(d):
                            # This directory has a .ts file but no .mp4 = active download
                            info = get_download_info(d, torrents=qb_torrents)
                            if info["size"] > 1024 * 1024:  # > 1MB = actively downloading
                                result[d] = {"code": d, "status": "downloading", **info}
                                mutations.append(("set_current", d, True))
                                if d not in [s["code"] for s in state]:
                                    state.append({"code": d, "status": "downloading", "added_at": time.time()})
                                log(f"Discovered download from disk: {d}")
                                break

        # Scan qBittorrent (incl. queuedDL — waiting for download slot)
        qb_codes = codes_in_qb(qb_torrents)
        if qb_torrents:
            for t in qb_torrents:
                torrent_state = str(t.get("state") or "")
                status = qb_status_from_state(torrent_state)
                if not status:
                    continue
                code = code_from_qb_torrent(t)
                if not code:
                    continue
                if status == "done" and not find_mp4_path(code):
                    log(f"Ignoring false qB completion without main video: {code}")
                    continue
                if status == "done" and not is_recent_timestamp(
                    t.get("completion_on") or t.get("seen_complete") or t.get("added_on")
                ):
                    continue

                # Prefer longer/cleaner code if already present under a variant
                already_key = None
                for k in list(result.keys()):
                    if clean_avid(k) == code or clean_avid(code) == clean_avid(k):
                        already_key = k
                        break
                if already_key:
                    # Upgrade queued → downloading if qB is actively transferring
                    if status == "downloading" and result[already_key].get("status") == "queued":
                        result[already_key] = {
                            "code": already_key,
                            "status": "downloading",
                            "size": t.get("completed", 0),
                            "speed": t.get("dlspeed", 0),
                            "progress_pct": min(99, int(t.get("progress", 0) * 100)),
                        }
                    continue

                progress_pct = int(t.get("progress", 0) * 100)
                if status == "queued":
                    progress_pct = 0
                elif status == "downloading" and progress_pct >= 100:
                    progress_pct = 99
                result[code] = {
                    "code": code,
                    "status": status,
                    "size": t.get("completed", 0),
                    "speed": t.get("dlspeed", 0) if status == "downloading" else 0,
                    "progress_pct": progress_pct if status != "done" else 100,
                }
                log(f"Discovered from qBittorrent: {t.get('name', '')[:60]} -> {code} ({status} {progress_pct}%)")

        # Items from state (registration file is primary for "已加入队列")
        for item in state:
            c = item["code"]
            if c in result:
                continue  # Already in result from queue.txt or qB

            if is_stale_heal_ghost(
                item, qb_codes=qb_codes, is_locked=is_locked, current_code=current_code
            ):
                log(f"Removing stale heal ghost: {c} (status={item.get('status')})")
                mutations.append(("remove_state", c, item.get("status"), item.get("added_at")))
                state = [s for s in state if s["code"] != c]
                continue

            mp4 = find_mp4_path(c)
            if mp4:
                total = get_file_size(mp4)
                result[c] = {"code": c, "status": "done", "size": total, "speed": 0, "progress_pct": 100}
                if c.upper() in failed_codes:
                    failed_codes.discard(c.upper())
                    mutations.append(("clear_failure", c))
                if item.get("status") != "done":
                    mutations.append(("mark_done", c, item.get("status")))
                    item["status"] = "done"
            elif item.get("status") == "downloading" and not is_locked:
                # Stale download: no mp4, no active lock, not in qB → clean
                has_ts = find_ts_path(c) is not None
                dir_size = get_dir_size(get_code_dir(c)) if os.path.isdir(get_code_dir(c)) else 0
                if not has_ts and dir_size == 0 and c not in qb_codes:
                    log(f"Removing stale download state: {c} (no files, no lock, not in qB)")
                    mutations.append(("remove_state", c, item.get("status"), item.get("added_at")))
                    state = [s for s in state if s["code"] != c]
                    continue
                else:
                    info = get_download_info(c, torrents=qb_torrents)
                    result[c] = {"code": c, "status": item.get("status", "queued"), **info}
            elif item.get("status") == "queued" and c not in queue_codes:
                # Keep registration if still in qB (e.g. queuedDL) or worker current
                if c in qb_codes or c == current_code:
                    result[c] = {
                        "code": c,
                        "status": "queued",
                        "size": 0,
                        "speed": 0,
                        "progress_pct": 0,
                    }
                    continue
                added_at = float(item.get("added_at") or 0)
                if added_at and time.time() - added_at < QUEUE_REGISTRATION_GRACE_SECONDS:
                    result[c] = {
                        "code": c,
                        "status": "queued",
                        "size": 0,
                        "speed": 0,
                        "progress_pct": 0,
                    }
                    continue
                # Orphan: only scraped sidecar under __weekly__ etc., no real job
                if find_ts_path(c) is None:
                    log(f"Removing stale queued state: {c} (not in queue/qB/current)")
                    mutations.append(("remove_state", c, item.get("status"), item.get("added_at")))
                    state = [s for s in state if s["code"] != c]
                    continue
                info = get_download_info(c, torrents=qb_torrents)
                result[c] = {"code": c, "status": "queued", **info}
            else:
                visible_status = item.get("status", "queued")
                if visible_status == "processing":
                    visible_status = "queued"
                if visible_status not in ("queued", "downloading", "done"):
                    continue
                info = get_download_info(c, torrents=qb_torrents)
                result[c] = {"code": c, "status": visible_status, **info}
        
        # Check for newly completed items → trigger post-download actions
        for c in list(result.keys()):
            if result[c]["status"] == "done":
                # Decide only — the completion mark is written *after* the
                # (idempotent) side effects so a crash can never skip them.
                state_item = next((s for s in state if s["code"] == c), None)
                if state_item and not state_item.get("_post_done"):
                    mutations.append(("post_done", c, result[c].get("size", 0)))
                    state_item["_post_done_pending"] = True
                    if c.upper() in failed_codes:
                        failed_codes.discard(c.upper())
                elif state_item and state_item.get("status") != "done":
                    mutations.append(("mark_done", c, state_item.get("status")))
                    state_item["status"] = "done"
        
        # Merge history into result (persistent done items)
        history = load_history()
        if DEBUG:
            log(f"History: {len(history)} items: {[h['code'] for h in history]}")
        else:
            log(f"History: {len(history)} items")
        for h in history:
            if h["code"] not in result:
                result[h["code"]] = {
                    "code": h["code"],
                    "status": "done",
                    "size": h.get("size", 0),
                    "speed": 0,
                    "progress_pct": 100,
                }
        
        # Sort: downloading, queued, done
        order = {"downloading": 0, "queued": 1, "done": 2}
        sorted_result = sorted(result.values(), key=lambda x: order.get(x["status"], 9))

        # Phase C — commit only revalidated local mutations under a short lock;
        # the heavier post-download writes then run unlocked.
        post_actions = []
        if mutations:
            with queue_state_critical("get.commit"):
                post_actions = self._apply_queue_mutations(mutations, snapshot)

        # Phase B2 — post-download side effects, unlocked and idempotent.
        # The completion mark is *not* written yet: if the process dies here the
        # next GET simply repeats these (safe to repeat) operations.
        for code, size in post_actions:
            log(f"Post-download actions for {code}")
            run_post_download_actions(code, size)
        if post_actions:
            # Phase C2 — revalidate and finalise the completion mark.
            with queue_state_critical("get.post_done"):
                self._mark_post_done(post_actions, snapshot)

        self._json(sorted_result)

    def _apply_queue_mutations(self, mutations, snapshot):
        """Phase C: revalidate every intent against current state, then commit.

        A worker/mutation that landed while phase B was running wins: stale
        snapshot intents are dropped instead of overwriting newer state.
        """
        expected = snapshot.get("expected") or {
            str(item.get("code") or "").upper(): {
                "status": item.get("status"),
                "added_at": item.get("added_at"),
            }
            for item in (snapshot.get("state") or [])
            if isinstance(item, dict) and item.get("code")
        }
        state = None
        dirty = False
        post_actions = []

        def load_current():
            nonlocal state
            if state is None:
                state = load_state()
            return state

        def find(items, code):
            upper = str(code or "").upper()
            return next((s for s in items if str(s.get("code") or "").upper() == upper), None)

        def matches_snapshot(item, want):
            if item is None or want is None:
                return False
            return (
                str(item.get("status") or "") == str(want.get("status") or "")
                and float(item.get("added_at") or 0) == float(want.get("added_at") or 0)
            )

        def same_lifecycle(item, want):
            """Same job lifecycle = same added_at (status may have been updated
            by an earlier mutation in this very phase)."""
            if item is None:
                return False
            if want is None:
                return True
            return float(item.get("added_at") or 0) == float(want.get("added_at") or 0)

        for mutation in mutations:
            kind = mutation[0]
            if kind == "clear_current":
                clear_current_download(mutation[1])
            elif kind == "clear_failure":
                clear_failure_record(mutation[1])
            elif kind == "set_current":
                code, register = mutation[1], mutation[2]
                write_current_download(code)
                if register:
                    items = load_current()
                    if find(items, code) is None:
                        items.append({"code": code, "status": "downloading", "added_at": time.time()})
                        dirty = True
            elif kind == "remove_state":
                code, want = mutation[1], expected.get(str(mutation[1]).upper())
                items = load_current()
                item = find(items, code)
                if matches_snapshot(item, want):
                    state = [
                        s for s in items if str(s.get("code") or "").upper() != str(code).upper()
                    ]
                    dirty = True
                else:
                    log(f"Skip stale state removal for {code} (state changed during scan)")
            elif kind == "mark_done":
                items = load_current()
                item = find(items, mutation[1])
                if item is not None and str(item.get("status") or "") != "done":
                    item["status"] = "done"
                    dirty = True
            elif kind == "post_done":
                code, size = mutation[1], mutation[2]
                items = load_current()
                item = find(items, code)
                want = expected.get(str(code).upper())
                if item is not None and not item.get("_post_done") and same_lifecycle(item, want):
                    # Decide only; side effects + final mark happen outside.
                    post_actions.append((code, size))
                else:
                    log(f"Skip post-download actions for {code} (state changed or already done)")
        if dirty and state is not None:
            save_state(state)
        return post_actions

    def _mark_post_done(self, post_actions, snapshot):
        """Phase C2: finalise the completion mark *after* the side effects ran.

        Revalidates against the pristine snapshot (same lifecycle = same
        `added_at`), so a stale GET cannot mark a different completion. Crash
        safe: if this never runs, the next GET repeats the idempotent side
        effects and marks afterwards.
        """
        expected = snapshot.get("expected") or {}
        state = load_state()
        dirty = False
        for code, size in post_actions:
            upper = str(code or "").upper()
            item = next(
                (s for s in state if str(s.get("code") or "").upper() == upper), None
            )
            if item is None:
                log(f"Skip post-done mark for {code} (state gone)")
                continue
            if item.get("_post_done"):
                continue
            want = expected.get(upper)
            if want is not None and float(item.get("added_at") or 0) != float(
                want.get("added_at") or 0
            ):
                log(f"Skip post-done mark for {code} (new lifecycle started)")
                continue
            item["_post_done"] = True
            item["status"] = "done"
            item["_post_done_size"] = size
            item["_post_done_at"] = time.time()
            item.pop("_post_done_pending", None)
            dirty = True
        if dirty:
            save_state(state)

    def do_POST(self):
        path = self.path.rstrip("/")
        if path in ("/api/p115/config", "/api/p115/config/"):
            try:
                from src import p115_offline as p115
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode() or "{}")
                if not isinstance(body, dict):
                    self._json({"error": "invalid body"}, 400)
                    return
                cfg = p115.save_config(body)
                self._json({"ok": True, **cfg})
            except ValueError as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if path in ("/api/p115/test", "/api/p115/test/"):
            try:
                from src import p115_offline as p115

                ok, msg = p115.test_connection()
                pub = p115.public_config()
                self._json(
                    {"ok": ok, "message": msg, **pub},
                    200 if ok else 400,
                )
            except Exception as e:
                self._json({"ok": False, "message": str(e)}, 500)
            return
        if path == "/api/weekly-scrape":
            if is_weekly_scrape_running():
                self._json({"ok": False, "running": True, "message": "周推荐刮削正在运行"}, 409)
                return
            if start_weekly_scrape():
                log("Manual weekly scrape started")
                self._json({"ok": True, "running": True, "message": "周推荐刮削已开始，请稍后刷新每日推荐"})
                return
            self._json({"ok": False, "message": "周推荐刮削启动失败"}, 500)
            return

        if path != "/api/queue":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else "{}"
        try:
            data = json.loads(body)
        except:
            data = {}
        code = normalize_video_id(data.get("code", ""))
        if not code:
            self._json({"error": "invalid code"}, 400)
            return
        target = normalize_download_target(data.get("target", "qb"))
        if target is None:
            self._json({"error": "invalid target (use qb or 115)"}, 400)
            return
        request_id = _sanitize_request_id(data.get("request_id", ""))

        # POST performs local state changes only: no 115 probe, no qB login or
        # torrents/info, no du/os.walk. Downstream availability is discovered by
        # the worker when it actually runs the task.
        with queue_state_critical("post"):
            self._queue_add_locked(code, target, request_id)

    def _queue_add_locked(self, code, target, request_id):
        """Idempotent enqueue. Caller holds the queue_state_lock."""
        entry = _idem_store()["entries"].get(request_id) if request_id else None
        if entry:
            if (
                str(entry.get("code") or "").upper() != code.upper()
                or str(entry.get("target") or "") != target
            ):
                self._json(
                    {
                        "error": "request_id_conflict",
                        "message": "该请求编号已用于其它番号或通道，请重新发起",
                        "request_id": request_id,
                        "code": code,
                        "target": target,
                    },
                    409,
                )
                return
            payload = dict(entry.get("result") or {})
            payload["already_accepted"] = True
            payload["replayed"] = True
            payload["request_id"] = request_id
            log(f"Idempotent replay: {code} target={target} request={request_id}")
            self._json(payload)
            return

        cancel_age = cancel_request_age(code)
        if cancel_age is not None and cancel_age < 300:
            self._json(
                {
                    "error": "cancellation in progress",
                    "code": code,
                    "message": "取消进行中，请稍后再试",
                },
                409,
            )
            return
        if cancel_age is not None:
            clear_cancel_request(code)

        in_flight, existing_target, source = _inflight_for_code(
            code,
            load_state(),
            read_queue_file(),
            read_current_download(),
            load_failure_codes(),
        )
        if in_flight:
            existing_target = existing_target or target
            if existing_target != target:
                self._json(
                    {
                        "status": "already_in_flight",
                        "error": "already_in_flight",
                        "message": f"该任务当前正在通过 {_channel_label(existing_target)} 处理",
                        "code": code,
                        "existing_target": existing_target,
                        "requested_target": target,
                        "source": source,
                    },
                    409,
                )
                return
            payload = {
                "status": "already_in_flight",
                "already_in_flight": True,
                "already_accepted": True,
                "code": code,
                "target": target,
                "source": source,
            }
            if request_id:
                payload["request_id"] = request_id
                _idem_record(request_id, code, target, "already_in_flight", payload)
            self._json(payload)
            return

        clear_failure_record(code)
        append_unique(QUEUE_PATH, code)
        set_download_target(DOWNLOAD_TARGETS_PATH, code, target)

        # Registration file is UI source of truth (write-through on add)
        def add_or_update_code(state):
            existing = next((s for s in state if s.get("code") == code), None)
            if existing is None:
                state.append({
                    "code": code,
                    "status": "queued",
                    "added_at": time.time(),
                    "target": target,
                })
                log_write("Queue", f"{code} 已加入下载列表（{_channel_log_label(target)}）")
            else:
                existing["status"] = "queued"
                existing["target"] = target
                if not existing.get("added_at"):
                    existing["added_at"] = time.time()
                # New lifecycle: let the next completion run post-download
                # actions again (they are idempotent).
                existing.pop("_post_done", None)
                existing.pop("_post_done_pending", None)
            return state

        update_state(add_or_update_code)
        payload = {
            "status": "added",
            "code": code,
            "target": target,
            "already_accepted": False,
        }
        if request_id:
            payload["request_id"] = request_id
            _idem_record(request_id, code, target, "accepted", payload)
        self._json(payload)

    @queue_route_locked
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/online-search/"):
            raw_code = path.replace("/api/online-search/", "", 1)
            code = normalize_online_code(raw_code)
            if not code:
                self._json({"error": "code required"}, 400)
                return
            removed = cleanup_online_detail(code)
            self._json({"status": "cleaned", "code": code, "removed": removed})
            return

        if not path.startswith("/api/queue/"):
            self._json({"error": "not found"}, 404)
            return
        code = normalize_video_id(unquote(path.replace("/api/queue/", "")))
        if not code:
            self._json({"error": "invalid code"}, 400)
            return
        delete_files = "delete_files=1" in (parsed.query or "")
        request_cancel(code)
        qb_removed = qb_remove_code(code, delete_files=delete_files)

        def remove_code_from_state(state):
            return [s for s in state if s["code"] != code]
        update_state(remove_code_from_state)

        remove_code(QUEUE_PATH, code)
        clear_download_target(DOWNLOAD_TARGETS_PATH, code)

        clear_current_download(code)
        
        # 默认只移出队列/状态；显式 delete_files=1 才删除磁盘文件。
        files_deleted = False
        delete_error = ""
        if delete_files and os.path.exists(get_code_dir(code)):
            try:
                # 忽略系统目录
                code_dir = get_code_dir(code)
                dirname = os.path.basename(code_dir.rstrip("/"))
                if dirname in ("__weekly__", "thumb"):
                    log(f"Cannot delete system directory: {dirname}")
                else:
                    shutil.rmtree(code_dir)
                    log(f"Deleted files: {code_dir}")
                    files_deleted = True
            except Exception as e:
                log(f"Delete failed: {e}")
                delete_error = str(e)
        
        self._json({
            "status": "removed",
            "code": code,
            "cancel_requested": True,
            "qb_removed": qb_removed,
            "files_deleted": files_deleted,
            "delete_error": delete_error,
        })

    def log_message(self, format, *args):
        pass


def main():
    port = int(os.environ.get("QUEUE_PORT", 31473))
    log(f"v7 starting: port={port}, lock={get_lock()}")
    
    # 启动自检：恢复残留锁、扫描未完成下载
    startup_recovery()
    cleanup_expired_online_details()
    try:
        from download_source import cleanup_expired_sources
        cleanup_expired_sources()
    except Exception as e:
        log(f"Download source startup cleanup failed: {e}")
    threading.Thread(target=online_cleanup_loop, daemon=True).start()
    
    server = QueueHTTPServer(("0.0.0.0", port), QueueHandler)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

def startup_recovery():
    """
    启动自检：释放残留锁、恢复下载状态、重建 state
    在容器重启后自动执行，确保下载任务不丢失
    """
    log("=== Startup Recovery ===")
    stale_cancel_count = cleanup_stale_cancel_requests()
    if stale_cancel_count:
        log(f"  Removed {stale_cancel_count} stale cancellation markers")
    
    # 1. 检查当前下载记录
    current = read_current_download()
    is_locked = get_lock()
    
    log(f"  current_download={current}, lock={is_locked}")
    
    # 2. 如果 lock=1 但没 worker（已重启），释放锁
    if is_locked:
        # 检查是否有真正的 downloader 进程在跑
        has_m3u8 = False
        try:
            r = subprocess.run(["pgrep", "-f", "m3u8-Downloader"], capture_output=True, timeout=3)
            has_m3u8 = r.returncode == 0
        except:
            pass
        
        if not has_m3u8:
            log("  No active downloader found, releasing stale lock")
            with open(LOCK_PATH, "w") as f:
                f.write("0")
            is_locked = False
            log("  Lock released")
    
    # 3. 扫描磁盘，找 .ts 文件（未完成下载）
    state = load_state()
    state_codes = {s["code"] for s in state}
    recovered = []
    
    if os.path.isdir(SAVE_PATH):
        for d in sorted(os.listdir(SAVE_PATH), reverse=True):
            dir_path = os.path.join(SAVE_PATH, d)
            if not os.path.isdir(dir_path) or d.startswith("__"):
                continue
            has_ts = False
            for f in os.listdir(dir_path):
                if f.endswith('.ts') and os.path.getsize(os.path.join(dir_path, f)) > 1024:
                    has_ts = True
                    break
            has_mp4 = False
            for f in os.listdir(dir_path):
                if f.endswith('.mp4'):
                    has_mp4 = True
                    break
            
            if has_ts and not has_mp4 and d not in state_codes:
                # Unfinished download - add to queue for re-download
                if not current or current != d:
                    recovered.append(d)
                    log(f"  Found unfinished: {d}")
    
    if recovered:
        for code in append_many_unique(QUEUE_PATH, [item.upper() for item in recovered]):
            log(f"  Re-queued: {code}")

        # Add to state atomically
        def add_recovered_codes(state):
            state_codes = {s["code"] for s in state}
            for code in recovered:
                if code not in state_codes:
                    state.append({"code": code.upper(), "status": "queued", "added_at": time.time()})
                    state_codes.add(code)
            return state
        update_state(add_recovered_codes)
    
    # 4. 清理 current_download.txt（等 worker 重新拾取）
    if current and not is_locked:
        clear_current_download(current)
        log("  Cleared stale current_download")
    
    log(f"=== Recovery complete: {len(recovered)} re-queued ===")

if __name__ == "__main__":
    main()
