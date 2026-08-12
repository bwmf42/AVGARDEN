import json
import os
import tempfile
import threading
import unittest
import urllib.request
import time
import sqlite3
from contextlib import ExitStack
from unittest.mock import patch

import queue_api
import download_source
from queue_store import append_unique, read_queue, write_json


class QueueAPITest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = self.temp_dir.name
        self.queue_path = os.path.join(root, "download_queue.txt")
        self.state_path = os.path.join(root, "queue_state.json")
        self.history_path = os.path.join(root, "download_history.json")
        self.current_path = os.path.join(root, "current_download.txt")
        self.lock_path = os.path.join(root, "work")
        self.save_path = os.path.join(root, "media")
        os.makedirs(self.save_path)
        with open(self.lock_path, "w", encoding="ascii") as file:
            file.write("0")

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"QUEUE_PATH": self.queue_path}))
        for name, value in {
            "QUEUE_PATH": self.queue_path,
            "STATE_PATH": self.state_path,
            "HISTORY_PATH": self.history_path,
            "CURRENT_PATH": self.current_path,
            "LOCK_PATH": self.lock_path,
            "SAVE_PATH": self.save_path,
            "FAILED_QUEUE_JSON_PATH": os.path.join(root, "failed_queue.json"),
            "FAILED_QUEUE_PATH": os.path.join(root, "failed_queue.txt"),
            "RETRY_PATH": os.path.join(root, "retry_counts.json"),
            "DOWNLOAD_TARGETS_PATH": os.path.join(root, "download_targets.json"),
        }.items():
            self.stack.enter_context(patch.object(queue_api, name, value))

        self.server = queue_api.ThreadingHTTPServer(("127.0.0.1", 0), queue_api.QueueHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}{path}",
            method=method,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())

    def test_queue_status_fetches_qb_once(self):
        for code in ("OMG-032", "300MIUM-1395", "T28-557"):
            append_unique(self.queue_path, code)
        with patch.object(queue_api, "qb_api", return_value=[]) as qb_api:
            status, payload = self.request("/api/queue/")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload), 3)
        self.assertEqual(qb_api.call_count, 1)

    def test_scrape_status_is_read_only(self):
        with patch.object(queue_api, "is_pipeline_running", return_value=True), patch.object(
            queue_api, "read_scrape_status", return_value={
                "running": True,
                "phase": "unwatched_chinese",
                "phase_label": "未看中文补链中",
            },
        ):
            status, payload = self.request("/api/scrape-status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["running"])
        self.assertEqual(payload["phase_label"], "未看中文补链中")

    def test_current_download_helpers_use_atomic_queue_store(self):
        self.assertIsNone(queue_api.read_current_download())
        queue_api.write_current_download("SSIS-951")
        self.assertEqual(queue_api.read_current_download(), "SSIS-951")
        queue_api.clear_current_download()
        self.assertIsNone(queue_api.read_current_download())

    def test_database_connection_closes_after_write_error(self):
        connection = unittest.mock.Mock()
        connection.execute.side_effect = [None, None, sqlite3.OperationalError("locked")]
        with patch("sqlite3.connect", return_value=connection):
            self.assertFalse(queue_api.write_to_missav_db("SSIS-951"))
        connection.close.assert_called_once_with()

    def test_post_normalizes_compact_numeric_leading_code(self):
        with patch.object(queue_api, "qb_api", return_value=[]):
            status, payload = self.request("/api/queue/", method="POST", payload={"code": "300mium1395"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["code"], "300MIUM-1395")
        self.assertEqual(read_queue(self.queue_path), ["300MIUM-1395"])

    def test_qb_done_without_main_video_is_not_reported(self):
        torrents = [{"state": "queuedUP", "tags": "MIKR-109", "name": "MIKR-109"}]
        with patch.object(queue_api, "qb_api", return_value=torrents):
            status, payload = self.request("/api/queue/")
        self.assertEqual(status, 200)
        self.assertEqual(payload, [])

    def test_qb_v5_stopped_download_is_reported_as_queued(self):
        torrents = [{
            "state": "stoppedDL",
            "tags": "MNGS-071",
            "name": "MNGS-071",
            "completed": 10,
            "dlspeed": 0,
            "progress": 0.5,
        }]
        with patch.object(queue_api, "qb_api", return_value=torrents):
            status, payload = self.request("/api/queue/")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["code"], "MNGS-071")
        self.assertEqual(payload[0]["status"], "queued")

    def test_recent_registration_stays_visible_after_worker_pops_queue(self):
        write_json(self.state_path, [{
            "code": "SSIS-951",
            "status": "queued",
            "added_at": time.time(),
        }])
        with patch.object(queue_api, "qb_api", return_value=[]):
            status, payload = self.request("/api/queue/")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["code"], "SSIS-951")
        self.assertEqual(payload[0]["status"], "queued")

    def test_main_video_index_resolves_numeric_prefix_alias_without_overriding_primary(self):
        real_save_path = os.path.realpath(self.save_path)
        for name in ("259LUXU-1881", "LUXU-1881"):
            os.makedirs(os.path.join(self.save_path, name))
        queue_api.main_video_cache_time = 0
        with patch.object(
            queue_api,
            "find_main_video",
            side_effect=lambda path: os.path.join(path, "main.mp4"),
        ):
            index = queue_api.get_main_video_index()
        self.assertEqual(index["259LUXU-1881"], os.path.join(real_save_path, "259LUXU-1881", "main.mp4"))
        self.assertEqual(index["LUXU-1881"], os.path.join(real_save_path, "LUXU-1881", "main.mp4"))

    def test_delete_requests_cancel_and_removes_queue_record(self):
        append_unique(self.queue_path, "OMG-032")
        write_json(self.state_path, [{"code": "OMG-032", "status": "queued"}])
        with patch.object(queue_api, "qb_remove_code", return_value=True):
            status, payload = self.request("/api/queue/OMG032", method="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(payload["cancel_requested"])
        self.assertTrue(payload["qb_removed"])
        self.assertEqual(read_queue(self.queue_path), [])
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, "cancel_requests", "OMG-032")))

    def test_qb_removal_uses_exact_code_match(self):
        torrents = [
            {"hash": "short", "name": "ABC-12-C.mp4", "tags": ""},
            {"hash": "long", "name": "ABC-123.mp4", "tags": ""},
            {"hash": "numeric", "name": "unrelated.bin", "tags": "300MIUM-1395"},
        ]
        with patch.object(queue_api, "qb_api", return_value=torrents), patch.object(
            queue_api, "qb_request", return_value=True
        ) as qb_request:
            self.assertTrue(queue_api.qb_remove_code("ABC-12"))
            self.assertEqual(qb_request.call_args.args[1]["hashes"], "short")
            self.assertTrue(queue_api.qb_remove_code("300MIUM-1395"))
            self.assertEqual(qb_request.call_args.args[1]["hashes"], "numeric")

    def test_resolve_actresses_prefers_mgs_and_normalizes_rename(self):
        with patch("src.weekly.mgs.fetch_detail", return_value={"actresses": ["河北彩花"]}), patch(
            "src.weekly.dmm.fetch_metadata"
        ) as dmm_fetch:
            payload, error = queue_api.resolve_actresses_remote("snos233")
        self.assertEqual(error, "")
        self.assertEqual(payload["code"], "SNOS-233")
        self.assertEqual(payload["source"], "mgs")
        self.assertEqual(payload["actresses"], ["河北彩伽"])
        dmm_fetch.assert_not_called()

    def test_resolve_actresses_falls_back_to_dmm(self):
        with patch("src.weekly.mgs.fetch_detail", return_value={"actresses": []}), patch(
            "src.weekly.dmm.fetch_metadata", return_value={"actresses": ["小島みこ"]}
        ):
            payload, error = queue_api.resolve_actresses_remote("OMG032")
        self.assertEqual(error, "")
        self.assertEqual(payload["source"], "dmm")
        self.assertEqual(payload["actresses"], ["小島みこ"])

    def test_online_cache_ttl_removes_only_expired_directory(self):
        online_dir = os.path.join(self.temp_dir.name, "online")
        old_dir = os.path.join(online_dir, "OLD-001")
        fresh_dir = os.path.join(online_dir, "NEW-001")
        os.makedirs(old_dir)
        os.makedirs(fresh_dir)
        now = time.time()
        os.utime(old_dir, (now - 100, now - 100))
        with patch.object(queue_api, "ONLINE_DIR", online_dir), patch.object(
            queue_api, "ONLINE_TTL_SECONDS", 50
        ):
            removed = queue_api.cleanup_expired_online_details(now=now)
        self.assertEqual(removed, ["OLD-001"])
        self.assertFalse(os.path.exists(old_dir))
        self.assertTrue(os.path.isdir(fresh_dir))

    def test_leaving_unqueued_online_detail_clears_source_cache(self):
        online_dir = os.path.join(self.temp_dir.name, "online")
        source_path = os.path.join(self.temp_dir.name, "download_sources.json")
        os.makedirs(os.path.join(online_dir, "SSIS-951"))
        download_source.save_cached_source(
            "SSIS-951", {"source": "sukebei_chinese"}, path=source_path
        )
        with patch.object(queue_api, "ONLINE_DIR", online_dir), patch.object(
            download_source, "SOURCE_CACHE_PATH", source_path
        ):
            self.assertTrue(queue_api.cleanup_online_detail("SSIS-951"))
        self.assertIsNone(download_source.get_cached_source("SSIS-951", path=source_path))

    def test_queued_online_detail_keeps_source_for_worker(self):
        online_dir = os.path.join(self.temp_dir.name, "online")
        source_path = os.path.join(self.temp_dir.name, "download_sources.json")
        os.makedirs(os.path.join(online_dir, "SSIS-951"))
        append_unique(self.queue_path, "SSIS-951")
        download_source.save_cached_source(
            "SSIS-951", {"source": "sukebei_chinese"}, path=source_path
        )
        with patch.object(queue_api, "ONLINE_DIR", online_dir), patch.object(
            download_source, "SOURCE_CACHE_PATH", source_path
        ):
            self.assertTrue(queue_api.cleanup_online_detail("SSIS-951"))
        self.assertIsNotNone(download_source.get_cached_source("SSIS-951", path=source_path))


if __name__ == "__main__":
    unittest.main()
