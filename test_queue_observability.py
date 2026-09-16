"""Regression tests for queue request observability (diagnostics only)."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request

# Configure the observability knobs and an isolated state dir before importing
# the module under test, so the tests never touch the real /db state.
_STATE_DIR = tempfile.mkdtemp(prefix="queue-obs-test-")

os.environ["QUEUE_ACCESS_LOG"] = "all"
os.environ["QUEUE_ACCESS_LOG_MS"] = "0"
os.environ["QUEUE_PATH"] = os.path.join(_STATE_DIR, "download_queue.txt")
os.environ["STATE_PATH"] = os.path.join(_STATE_DIR, "queue_state.json")
os.environ["CURRENT_PATH"] = os.path.join(_STATE_DIR, "current_download.txt")
os.environ["LOCK_PATH"] = os.path.join(_STATE_DIR, "work")
os.environ["SAVE_PATH"] = os.path.join(_STATE_DIR, "data")
os.environ["DB_PATH"] = os.path.join(_STATE_DIR, "downloaded.db")
os.environ["HISTORY_PATH"] = os.path.join(_STATE_DIR, "download_history.json")
os.environ["DOWNLOAD_TARGETS_PATH"] = os.path.join(_STATE_DIR, "download_targets.json")
os.environ["LOG_DIR"] = os.path.join(_STATE_DIR, "logs")

import queue_api  # noqa: E402
import queue_store  # noqa: E402

# Belt and braces: if another test module already imported queue_api, point its
# module-level paths at the isolated dir anyway.
for _name in (
    "QUEUE_PATH",
    "STATE_PATH",
    "CURRENT_PATH",
    "LOCK_PATH",
    "SAVE_PATH",
    "DB_PATH",
    "HISTORY_PATH",
    "DOWNLOAD_TARGETS_PATH",
):
    setattr(queue_api, _name, os.environ[_name])
queue_api.WEEKLY_JSON = os.path.join(_STATE_DIR, "weekly.json")

unittest.addModuleCleanup(shutil.rmtree, _STATE_DIR, ignore_errors=True)


def _start_server(server_cls):
    server = server_cls(("127.0.0.1", 0), queue_api.QueueHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


def _request(server, method, path, request_id):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}", method=method, data=b"{}" if method == "POST" else None
    )
    req.add_header("X-Request-ID", request_id)
    if method == "POST":
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get("X-Request-ID"), resp.read()
    except urllib.error.HTTPError as exc:  # 404 for the side-effect-free POST probe
        return exc.code, exc.headers.get("X-Request-ID"), exc.read()


class QueueObservabilityTest(unittest.TestCase):
    def test_request_log_fields_and_request_id_echo(self):
        server, thread = _start_server(queue_api.QueueHTTPServer)
        self.addCleanup(_stop_server, server, thread)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status, echoed, _ = _request(server, "POST", "/api/queue/ping", "obs-test-1")
        self.assertEqual(status, 404)
        self.assertEqual(echoed, "obs-test-1")

        lines = [line for line in buf.getvalue().splitlines() if "[req] request=obs-test-1" in line]
        self.assertEqual(len(lines), 1, buf.getvalue())
        line = lines[0]
        for field in (
            "method=POST",
            "path=/api/queue/ping",
            "status=404",
            "accept_ms=",
            "lock_wait_ms=",
            "lock_hold_ms=",
            "handler_ms=",
            "response_write_ms=",
            "total_ms=",
            "error=-",
            "write_error=-",
        ):
            self.assertIn(field, line)

    def test_generated_request_id_is_logged(self):
        server, thread = _start_server(queue_api.QueueHTTPServer)
        self.addCleanup(_stop_server, server, thread)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status, echoed, _ = _request(server, "GET", "/api/queue/", "temporary")
        self.assertEqual(status, 200)
        self.assertEqual(echoed, "temporary")
        self.assertIn("[req] request=temporary method=GET path=/api/queue/", buf.getvalue())

    def test_lock_wait_is_separated_from_handler_time(self):
        """A request blocked behind another one must report lock_wait, not handler."""
        server, thread = _start_server(queue_api.QueueHTTPServer)
        self.addCleanup(_stop_server, server, thread)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            release = threading.Event()

            def holder():
                import queue_api as qa

                with qa.queue_state_lock:
                    release.wait(5)

            holder_thread = threading.Thread(target=holder, daemon=True)
            holder_thread.start()
            time.sleep(0.35)  # make sure the lock is held before the request arrives
            request_thread = threading.Thread(
                target=_request, args=(server, "GET", "/api/queue/", "obs-lock-1"), daemon=True
            )
            request_thread.start()
            time.sleep(0.35)
            release.set()
            holder_thread.join(5)
            request_thread.join(5)

        lines = [line for line in buf.getvalue().splitlines() if "[req] request=obs-lock-1" in line]
        self.assertEqual(len(lines), 1, buf.getvalue())
        fields = dict(part.split("=", 1) for part in lines[0].split() if "=" in part)
        self.assertGreater(float(fields["lock_wait_ms"]), 100.0, lines[0])
        self.assertLess(float(fields["lock_wait_ms"]), float(fields["total_ms"]), lines[0])

    def test_accept_to_handler_delay_is_measured(self):
        class SlowSpawnServer(queue_api.QueueHTTPServer):
            """Stamps the accept time, then delays the handler thread like a backlog would."""

            def finish_request(self, request, client_address):
                time.sleep(0.2)
                super().finish_request(request, client_address)

        server, thread = _start_server(SlowSpawnServer)
        self.addCleanup(_stop_server, server, thread)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _request(server, "POST", "/api/queue/ping", "obs-accept-1")

        lines = [line for line in buf.getvalue().splitlines() if "[req] request=obs-accept-1" in line]
        self.assertEqual(len(lines), 1, buf.getvalue())
        fields = dict(part.split("=", 1) for part in lines[0].split() if "=" in part)
        self.assertGreaterEqual(float(fields["accept_ms"]), 150.0, lines[0])

    def test_flock_hook_reports_wait_and_is_opt_in(self):
        calls = []
        queue_store.set_trace_hook(lambda path, wait, hold: calls.append((path, wait, hold)))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                queue_store.write_json(os.path.join(tmp, "state.json"), {"a": 1})
        finally:
            queue_store.set_trace_hook(queue_api._lock_trace_hook)

        self.assertEqual(len(calls), 1, calls)
        self.assertTrue(calls[0][0].endswith("state.json"))
        self.assertGreaterEqual(calls[0][1], 0.0)
        self.assertGreaterEqual(calls[0][2], 0.0)

        calls.clear()
        queue_store.set_trace_hook(None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                queue_store.write_json(os.path.join(tmp, "state.json"), {"a": 1})
        finally:
            queue_store.set_trace_hook(queue_api._lock_trace_hook)
        self.assertEqual(calls, [])

    def test_slow_threshold_is_respected(self):
        original_ms = queue_api.QUEUE_ACCESS_LOG_MS
        original_all = queue_api.QUEUE_ACCESS_LOG_ALL
        queue_api.QUEUE_ACCESS_LOG_MS = 10_000.0
        queue_api.QUEUE_ACCESS_LOG_ALL = False
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                queue_api._slow_op("unit-op", 1.0, "extra=1")
                queue_api._slow_op("unit-op", 20_000.0, "extra=1")
        finally:
            queue_api.QUEUE_ACCESS_LOG_MS = original_ms
            queue_api.QUEUE_ACCESS_LOG_ALL = original_all
        logged = buf.getvalue()
        self.assertEqual(logged.count("[slow]"), 1, logged)
        self.assertIn("duration_ms=20000.0", logged)

    def test_fast_queue_request_is_not_logged_by_default(self):
        """Default mode must stay quiet for fast queue requests (no log spam)."""
        original_ms = queue_api.QUEUE_ACCESS_LOG_MS
        original_all = queue_api.QUEUE_ACCESS_LOG_ALL
        queue_api.QUEUE_ACCESS_LOG_MS = 500.0
        queue_api.QUEUE_ACCESS_LOG_ALL = False

        def scope(path, age_ms):
            return {
                "id": "spam-check",
                "resolved": True,
                "method": "GET",
                "path": path,
                "t_received": time.monotonic() - age_ms / 1000.0,
                "accept_ms": 0.4,
                "lock_wait_ms": 0.3,
                "lock_hold_ms": age_ms,
                "handler_ms": age_ms,
                "handler_done_ts": 0.0,
                "response_write_ms": 0.1,
                "lock_events": [],
                "slow_ops": [],
                "qb_calls": [],
                "status": 200,
                "error": "",
                "write_error": "",
            }

        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                queue_api._emit_request_log(scope("/api/queue/", 5.0))
            self.assertEqual(buf.getvalue(), "", "fast queue request must not be logged")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                queue_api._emit_request_log(scope("/api/queue/", 600.0))
            self.assertIn("[req] request=spam-check", buf.getvalue())
        finally:
            queue_api.QUEUE_ACCESS_LOG_MS = original_ms
            queue_api.QUEUE_ACCESS_LOG_ALL = original_all


if __name__ == "__main__":
    unittest.main()
