import os
import signal
import subprocess
import threading
import time

from video_id import normalize_video_id


_active_lock = threading.Lock()
_active_process = None


def _state_dir():
    queue_path = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
    return os.path.dirname(queue_path) or "/db"


def _cancel_dir():
    return os.path.join(_state_dir(), "cancel_requests")


def _cancel_path(raw):
    code = normalize_video_id(raw)
    if not code:
        raise ValueError("invalid video ID")
    return os.path.join(_cancel_dir(), code)


def request_cancel(raw):
    path = _cancel_path(raw)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as file:
        file.write("1")


def clear_cancel_request(raw):
    try:
        os.remove(_cancel_path(raw))
    except FileNotFoundError:
        pass


def is_cancel_requested(raw):
    try:
        return os.path.exists(_cancel_path(raw))
    except ValueError:
        return True


def cancel_request_age(raw):
    try:
        return max(0.0, time.time() - os.path.getmtime(_cancel_path(raw)))
    except (FileNotFoundError, ValueError):
        return None


def cleanup_stale_cancel_requests(max_age=24 * 60 * 60):
    directory = _cancel_dir()
    if not os.path.isdir(directory):
        return 0
    removed = 0
    now = time.time()
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path) and now - os.path.getmtime(path) >= max_age:
                os.remove(path)
                removed += 1
        except FileNotFoundError:
            pass
    return removed


def _terminate(process):
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def terminate_active_process():
    with _active_lock:
        process = _active_process
    _terminate(process)


def run_tracked(args, code):
    global _active_process

    if is_cancel_requested(code):
        return 130
    process = subprocess.Popen(args, start_new_session=os.name != "nt")
    with _active_lock:
        _active_process = process
    try:
        while process.poll() is None:
            if is_cancel_requested(code):
                _terminate(process)
                return 130
            time.sleep(0.25)
        return process.returncode
    finally:
        with _active_lock:
            if _active_process is process:
                _active_process = None
