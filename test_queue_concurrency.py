"""Queue POST idempotency, in-flight de-duplication and lock-scope tests."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import queue_api
import queue_store


def _json_get(url, timeout=30):
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body}
        return exc.code, payload


def _json_post(url, payload, timeout=30):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return exc.code, parsed


class QueueConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="queue-concurrency-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.queue_path = os.path.join(self.tmp, "download_queue.txt")
        self.state_path = os.path.join(self.tmp, "queue_state.json")
        self.current_path = os.path.join(self.tmp, "current_download.txt")
        self.targets_path = os.path.join(self.tmp, "download_targets.json")
        self.idem_path = os.path.join(self.tmp, "queue_idempotency.json")
        self.history_path = os.path.join(self.tmp, "download_history.json")

        os.environ["QUEUE_PATH"] = self.queue_path
        queue_api.QUEUE_PATH = self.queue_path
        queue_api.STATE_PATH = self.state_path
        queue_api.CURRENT_PATH = self.current_path
        queue_api.DOWNLOAD_TARGETS_PATH = self.targets_path
        queue_api.IDEMPOTENCY_PATH = self.idem_path
        queue_api.HISTORY_PATH = self.history_path
        queue_api.SAVE_PATH = os.path.join(self.tmp, "data")
        queue_api.WEEKLY_JSON = os.path.join(self.tmp, "weekly.json")
        queue_api.LOCK_PATH = os.path.join(self.tmp, "work")
        queue_api.FAILED_QUEUE_JSON_PATH = os.path.join(self.tmp, "failed_queue.json")
        queue_api.FAILED_QUEUE_PATH = os.path.join(self.tmp, "failed_queue.txt")
        queue_api.RETRY_PATH = os.path.join(self.tmp, "retry_counts.json")
        queue_api.DB_PATH = os.path.join(self.tmp, "downloaded.db")
        os.makedirs(queue_api.SAVE_PATH, exist_ok=True)

        self._original_qb_api = queue_api.qb_api
        self.addCleanup(self._restore_qb)
        self.qb_calls = []
        queue_api.qb_api = self._stub_qb([])

        self.server = queue_api.QueueHTTPServer(("127.0.0.1", 0), queue_api.QueueHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def _restore_qb(self):
        queue_api.qb_api = self._original_qb_api

    def _stub_qb(self, torrents, delay=0.0, once_delay=None, calls=None):
        """Return a qb_api replacement; records calls and can delay."""
        state = {"first": True}

        def stub(endpoint, *args, **kwargs):
            self.qb_calls.append((endpoint, time.monotonic()))
            if calls is not None:
                calls.append(endpoint)
            if once_delay and state["first"]:
                state["first"] = False
                time.sleep(once_delay)
            elif delay:
                time.sleep(delay)
            return list(torrents)

        return stub

    # -- helpers ---------------------------------------------------------
    def post(self, code, target="qb", request_id=""):
        payload = {"code": code, "target": target}
        if request_id:
            payload["request_id"] = request_id
        return _json_post(f"{self.base}/api/queue/", payload)

    def queue_codes(self):
        if not os.path.exists(self.queue_path):
            return []
        with open(self.queue_path) as handle:
            return [line.strip() for line in handle if line.strip()]

    def read_state(self):
        if not os.path.exists(self.state_path):
            return []
        with open(self.state_path) as handle:
            return json.load(handle)

    def write_state(self, items):
        with open(self.state_path, "w") as handle:
            json.dump(items, handle)

    def read_targets(self):
        if not os.path.exists(self.targets_path):
            return {}
        with open(self.targets_path) as handle:
            return json.load(handle)

    def queue_payload(self):
        _, payload = _json_get(f"{self.base}/api/queue/")
        return payload

    def simulate_worker_pop(self, code):
        """worker_loop: pop_first(queue) then set_current_download(code)."""
        queue_store.pop_first(self.queue_path)
        queue_api.write_current_download(code)

    def seed_completed_sources(self, code, size=123456789):
        """Make GET see `code` as completed without creating a real 100MB file."""
        with open(queue_api.WEEKLY_JSON, "w") as handle:
            json.dump([{"id": code, "title": code, "downloaded": False}], handle)
        # Minimal MissAV schema (same columns as src/data.initialize_db) so the
        # test stays hermetic and does not import the app's loguru config.
        import sqlite3

        conn = sqlite3.connect(queue_api.DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS MissAV (
                    bvid TEXT PRIMARY KEY, title TEXT, title_jp TEXT, actresses TEXT,
                    genres TEXT, release_date TEXT, duration TEXT, source TEXT,
                    found_date TEXT, add_date TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
        original_find = queue_api.find_mp4_path
        original_size = queue_api.get_file_size
        video_path = os.path.join(queue_api.SAVE_PATH, code, "main.mp4")
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        with open(video_path, "wb") as handle:
            handle.write(b"test")
        queue_api.find_mp4_path = lambda c: video_path if str(c).upper() == code.upper() else None
        queue_api.get_file_size = lambda path: size
        self.addCleanup(setattr, queue_api, "find_mp4_path", original_find)
        self.addCleanup(setattr, queue_api, "get_file_size", original_size)

    def weekly_downloaded(self, code):
        with open(queue_api.WEEKLY_JSON) as handle:
            return json.load(handle)[0].get("downloaded")

    def history(self):
        if not os.path.exists(self.history_path):
            return []
        with open(self.history_path) as handle:
            return json.load(handle)

    def db_rows(self, code):
        import sqlite3

        conn = sqlite3.connect(queue_api.DB_PATH)
        try:
            return conn.execute("SELECT COUNT(*) FROM MissAV WHERE bvid = ?", (code,)).fetchone()[0]
        finally:
            conn.close()

    def state_item(self, code):
        return next((item for item in self.read_state() if item.get("code") == code), None)

    # -- A: same request_id, concurrent -------------------------------
    def test_a_same_request_id_concurrent_posts_create_one_task(self):
        results = []
        lock = threading.Lock()

        def worker():
            status, payload = self.post("SYN-001", "qb", "req-A-1")
            with lock:
                results.append((status, payload))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)

        self.assertEqual(len(results), 4)
        self.assertTrue(all(status == 200 for status, _ in results), results)
        self.assertEqual(self.queue_codes(), ["SYN-001"])
        self.assertEqual(len(self.read_state()), 1)
        accepted = [p for _, p in results if not p.get("already_accepted")]
        replayed = [p for _, p in results if p.get("already_accepted")]
        self.assertEqual(len(accepted), 1, results)
        self.assertEqual(len(replayed), 3, results)
        self.assertTrue(all(p.get("replayed") for p in replayed))

    # -- B: different request_id, same code ---------------------------
    def test_b_different_request_ids_same_code_only_one_inflight(self):
        results = []
        lock = threading.Lock()

        def worker(index):
            status, payload = self.post("SYN-002", "qb", f"req-B-{index}")
            with lock:
                results.append((status, payload))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)

        self.assertEqual(self.queue_codes(), ["SYN-002"])
        added = [p for _, p in results if p.get("status") == "added"]
        inflight = [p for _, p in results if p.get("status") == "already_in_flight"]
        self.assertEqual(len(added), 1, results)
        self.assertEqual(len(inflight), 3, results)

    # -- C: worker already popped the code -----------------------------
    def test_c_post_after_worker_pop_does_not_requeue(self):
        status, _ = self.post("SYN-003", "qb", "req-C-1")
        self.assertEqual(status, 200)
        self.simulate_worker_pop("SYN-003")

        status, payload = self.post("SYN-003", "qb", "req-C-2")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload.get("status"), "already_in_flight")
        self.assertEqual(payload.get("source"), "current_download")
        self.assertEqual(self.queue_codes(), [], "must not re-append while worker holds it")

    # -- D: cross-channel target conflict -----------------------------
    def test_d_target_conflict_is_not_overwritten(self):
        status, _ = self.post("SYN-004", "115", "req-D-1")
        self.assertEqual(status, 200)
        self.assertEqual(self.read_targets().get("SYN-004"), "115")
        self.simulate_worker_pop("SYN-004")

        status, payload = self.post("SYN-004", "qb", "req-D-2")
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload.get("status"), "already_in_flight")
        self.assertEqual(payload.get("existing_target"), "115")
        self.assertEqual(payload.get("requested_target"), "qb")
        self.assertIn("115", payload.get("message", ""))
        self.assertEqual(self.read_targets().get("SYN-004"), "115", "target must stay 115")
        self.assertEqual(self.queue_codes(), [], "no re-append on conflict")

    # -- E: slow qB must not block other requests ---------------------
    def test_e_slow_qb_get_does_not_block_post_or_second_get(self):
        queue_api.qb_api = self._stub_qb([], once_delay=20.0)
        timings = {}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slow = threading.Thread(target=lambda: timings.__setitem__("slow", self._timed_get()))
            slow.start()
            time.sleep(0.5)  # slow GET is now inside its qB call
            timings["post"] = self._timed_post()
            timings["get2"] = self._timed_get()
            slow.join(30)

        self.assertLess(timings["post"], 2.0, timings)
        self.assertLess(timings["get2"], 3.0, timings)
        self.assertLess(timings["slow"], 30.0, timings)
        locked = [line for line in buf.getvalue().splitlines() if "[req]" in line]
        for line in locked:
            fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
            if fields.get("path", "").startswith("/api/queue"):
                self.assertLess(float(fields.get("lock_hold_ms", 0)), 1000.0, line)

    def _timed_get(self):
        started = time.monotonic()
        _json_get(f"{self.base}/api/queue/", timeout=60)
        return time.monotonic() - started

    def _timed_post(self):
        started = time.monotonic()
        self.post("SYN-005", "qb", "req-E-1")
        return time.monotonic() - started

    # -- F: 5s qB call must not be held under the lock ----------------
    def test_f_qb_5s_does_not_hold_queue_state_lock(self):
        queue_api.qb_api = self._stub_qb([], delay=5.0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            total = self._timed_get()
        self.assertGreaterEqual(total, 4.5)
        lines = [line for line in buf.getvalue().splitlines() if "[req]" in line]
        self.assertTrue(lines, buf.getvalue())
        fields = dict(part.split("=", 1) for part in lines[0].split() if "=" in part)
        self.assertLess(float(fields["lock_hold_ms"]), 500.0, lines[0])
        self.assertGreater(float(fields["total_ms"]), 4000.0, lines[0])

    # -- G: GET revalidation must not clobber newer state ------------
    def test_g_get_snapshot_revalidation_keeps_worker_changes(self):
        self.write_state([{"code": "SYN-006", "status": "downloading", "added_at": 1000.0}])
        original_find_ts = queue_api.find_ts_path
        calls = {"n": 0}

        def racing_find_ts(code):
            calls["n"] += 1
            if calls["n"] == 1:
                # Simulate the worker restarting the task while phase B runs.
                self.write_state([{"code": "SYN-006", "status": "queued", "added_at": 2000.0}])
            return None

        queue_api.find_ts_path = racing_find_ts
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                _json_get(f"{self.base}/api/queue/")
        finally:
            queue_api.find_ts_path = original_find_ts

        remaining = {item["code"]: item for item in self.read_state()}
        self.assertIn("SYN-006", remaining, "stale snapshot must not delete newer state")
        self.assertEqual(remaining["SYN-006"]["status"], "queued")
        self.assertEqual(remaining["SYN-006"]["added_at"], 2000.0)
        self.assertIn("Skip stale state removal", buf.getvalue())

    # -- H: 115 unavailable -> POST still fast and accepted ----------
    def test_h_115_unavailable_post_is_fast_and_accepted(self):
        from src import p115_offline as p115

        called = []
        original_probe = p115.probe_cached
        original_test = p115.test_connection

        def slow_probe(*args, **kwargs):
            called.append("probe")
            time.sleep(30)
            return True, "unexpected"

        p115.probe_cached = slow_probe
        p115.test_connection = slow_probe
        try:
            started = time.monotonic()
            status, payload = self.post("SYN-007", "115", "req-H-1")
            elapsed = time.monotonic() - started
        finally:
            p115.probe_cached = original_probe
            p115.test_connection = original_test

        self.assertEqual(status, 200, payload)
        self.assertEqual(payload.get("status"), "added")
        self.assertLess(elapsed, 1.0, elapsed)
        self.assertEqual(called, [], "POST must not probe 115")

    # -- I: qB unavailable -> POST target=qb is not blocked ----------
    def test_i_qb_unavailable_post_is_fast(self):
        def broken_qb(*args, **kwargs):
            time.sleep(30)
            return None

        queue_api.qb_api = broken_qb
        started = time.monotonic()
        status, payload = self.post("SYN-008", "qb", "req-I-1")
        elapsed = time.monotonic() - started
        self.assertEqual(status, 200, payload)
        self.assertLess(elapsed, 1.0, elapsed)

    # -- J: POST performs no slow local work either ------------------
    def test_j_post_does_no_library_walk_or_du(self):
        def boom(*args, **kwargs):
            raise AssertionError("POST must not call slow local helpers")

        original_index = queue_api.get_main_video_index
        original_du = queue_api.get_dir_size
        queue_api.get_main_video_index = boom
        queue_api.get_dir_size = boom
        try:
            status, payload = self.post("SYN-009", "qb", "req-J-1")
        finally:
            queue_api.get_main_video_index = original_index
            queue_api.get_dir_size = original_du
        self.assertEqual(status, 200, payload)

    # -- K: one qB snapshot per GET ----------------------------------
    def test_k_single_qb_snapshot_per_get(self):
        queue_api.qb_api = self._stub_qb([])
        _json_get(f"{self.base}/api/queue/")
        self.assertEqual(len(self.qb_calls), 1, self.qb_calls)

    # -- L: lock hold baseline ---------------------------------------
    # -- M: post_done crash consistency ------------------------------
    def test_m1_post_done_crash_before_side_effects_is_retried(self):
        code = "SYN-800"
        self.seed_completed_sources(code)
        self.write_state([{"code": code, "status": "queued", "added_at": 5000.0}])

        calls = {"n": 0}

        def crashing(code_arg, size_arg):
            calls["n"] += 1
            raise RuntimeError("simulated crash before post-download side effects")

        original = queue_api.run_post_download_actions
        queue_api.run_post_download_actions = crashing
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(Exception):
                    _json_get(f"{self.base}/api/queue/")
        finally:
            queue_api.run_post_download_actions = original

        self.assertEqual(calls["n"], 1)
        self.assertFalse(self.state_item(code).get("_post_done"), "crash must not set a permanent mark")
        self.assertEqual(self.history(), [])
        self.assertFalse(self.weekly_downloaded(code))

        with contextlib.redirect_stdout(io.StringIO()):
            _json_get(f"{self.base}/api/queue/")
        self.assertTrue(self.weekly_downloaded(code))
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.db_rows(code), 1)
        self.assertTrue(self.state_item(code).get("_post_done"))

    def test_m2_post_done_crash_after_side_effects_before_mark_is_safe(self):
        code = "SYN-801"
        self.seed_completed_sources(code)
        self.write_state([{"code": code, "status": "queued", "added_at": 5100.0}])

        original_mark = queue_api.QueueHandler._mark_post_done
        queue_api.QueueHandler._mark_post_done = lambda self, actions, snapshot: None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                _json_get(f"{self.base}/api/queue/")
        finally:
            queue_api.QueueHandler._mark_post_done = original_mark

        # side effects landed, completion mark is missing (crash window)
        self.assertTrue(self.weekly_downloaded(code))
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.db_rows(code), 1)
        self.assertFalse(self.state_item(code).get("_post_done"))

        with contextlib.redirect_stdout(io.StringIO()):
            _json_get(f"{self.base}/api/queue/")
        self.assertEqual(len(self.history()), 1, "history must not be duplicated")
        self.assertEqual(self.db_rows(code), 1, "MissAV row must not be duplicated")
        self.assertTrue(self.weekly_downloaded(code))
        self.assertTrue(self.state_item(code).get("_post_done"))

    def test_m3_post_done_normal_flow_runs_once(self):
        code = "SYN-802"
        self.seed_completed_sources(code)
        self.write_state([{"code": code, "status": "queued", "added_at": 5200.0}])

        with contextlib.redirect_stdout(io.StringIO()):
            _json_get(f"{self.base}/api/queue/")
        self.assertTrue(self.state_item(code).get("_post_done"))
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.db_rows(code), 1)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _json_get(f"{self.base}/api/queue/")
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.db_rows(code), 1)
        self.assertNotIn("Post-download actions for", buf.getvalue())

    def test_post_done_waits_for_database_success_then_retries(self):
        code = "SYN-803"
        self.seed_completed_sources(code)
        self.write_state([{"code": code, "status": "queued", "added_at": time.time()}])
        original = queue_api.write_to_missav_db
        calls = {"count": 0}
        def fail_once(value):
            calls["count"] += 1
            return False if calls["count"] == 1 else original(value)
        queue_api.write_to_missav_db = fail_once
        try:
            self.queue_payload()
            self.assertFalse(self.state_item(code).get("_post_done"))
            self.queue_payload()
            self.assertTrue(self.state_item(code).get("_post_done"))
            self.assertEqual(calls["count"], 2)
            self.assertEqual(self.db_rows(code), 1)
        finally:
            queue_api.write_to_missav_db = original

    # -- N: terminal state vs recent_accept --------------------------
    def test_n1_terminal_state_allows_requeue_within_accept_window(self):
        code = "SYN-810"
        status, _ = self.post(code, "qb", "req-N1-1")
        self.assertEqual(status, 200)
        # worker finished the task while the recent-accept window is still open
        queue_store.pop_first(self.queue_path)
        queue_api.write_current_download("")
        self.write_state([{"code": code, "status": "done", "added_at": 8000.0}])

        status, payload = self.post(code, "qb", "req-N1-2")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload.get("status"), "added")
        self.assertIn(code, self.queue_codes())

    def test_n2_recent_accept_still_protects_race_window(self):
        code = "SYN-811"
        status, _ = self.post(code, "qb", "req-N2-1")
        self.assertEqual(status, 200)
        # pop -> current_download -> cleared, and no terminal row at all
        queue_store.pop_first(self.queue_path)
        queue_api.write_current_download("")
        self.write_state([])

        status, payload = self.post(code, "qb", "req-N2-2")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload.get("status"), "already_in_flight")
        self.assertEqual(payload.get("source"), "recent_accept")
        self.assertEqual(self.queue_codes(), [], "race window must stay protected")

    def test_n3_request_id_replay_ignores_terminal_state(self):
        code = "SYN-812"
        status, first = self.post(code, "qb", "req-N3-1")
        self.assertEqual(status, 200)
        queue_store.pop_first(self.queue_path)
        self.write_state([{"code": code, "status": "done", "added_at": 8100.0}])

        status, replay = self.post(code, "qb", "req-N3-1")
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay.get("already_accepted"))
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(replay.get("status"), first.get("status"))
        self.assertEqual(self.queue_codes(), [], "replay must not enqueue again")

    def test_l_lock_hold_baseline(self):
        original_all = queue_api.QUEUE_ACCESS_LOG_ALL
        queue_api.QUEUE_ACCESS_LOG_ALL = True  # measure fast requests too
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                for _ in range(20):
                    _json_get(f"{self.base}/api/queue/")
                for index in range(20):
                    self.post(f"SYN-1{index:02d}", "qb", f"req-L-{index}")
        finally:
            queue_api.QUEUE_ACCESS_LOG_ALL = original_all
        holds_get, holds_post = [], []
        for line in buf.getvalue().splitlines():
            if "[req]" not in line:
                continue
            fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
            path = fields.get("path", "")
            value = float(fields.get("lock_hold_ms", 0) or 0)
            if path.startswith("/api/queue"):
                if fields.get("method") == "POST":
                    holds_post.append(value)
                else:
                    holds_get.append(value)
        self.assertTrue(holds_get, "expected GET lock measurements")
        self.assertTrue(holds_post, "expected POST lock measurements")
        self.assertLess(max(holds_get), 200.0, holds_get)
        self.assertLess(max(holds_post), 200.0, holds_post)
        print(
            f"\nlock_hold_ms GET max={max(holds_get):.1f} avg={sum(holds_get)/len(holds_get):.1f} "
            f"POST max={max(holds_post):.1f} avg={sum(holds_post)/len(holds_post):.1f}"
        )


if __name__ == "__main__":
    unittest.main()
