#!/usr/bin/env python3
"""Tests for the safe unwatched Chinese magnet follow-up."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from unittest import mock

import unwatched_chinese_refill as refill
from src import scrape_pipeline


class TestUnwatchedChineseRefill(unittest.TestCase):
    def test_list_skips_watched_downloaded_and_chinese(self):
        weekly = [
            {"id": "AAA-001", "hasChinese": False, "downloaded": False},
            {"id": "AAA-002", "hasChinese": True, "downloaded": False},
            {"id": "AAA-003", "hasChinese": False, "downloaded": True},
            {"id": "AAA-004", "hasChinese": False, "downloaded": False},
            {"id": "AAA-005", "title": "某某 中文字幕", "downloaded": False},
        ]
        need = refill.list_unwatched_needing_cn(
            weekly,
            {"AAA-004"},
            {"AAA-003"},
            set(),
            {},
        )
        self.assertEqual([item["id"] for item in need], ["AAA-001"])

    def test_loads_active_queue_ids_from_shared_registration_files(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = os.path.join(directory, "download_queue.txt")
            state = os.path.join(directory, "queue_state.json")
            current = os.path.join(directory, "current_download.txt")
            with open(queue, "w", encoding="utf-8") as handle:
                handle.write("AAA-001\n")
            with open(state, "w", encoding="utf-8") as handle:
                json.dump([
                    {"code": "AAA-002", "status": "queued"},
                    {"code": "AAA-003", "status": "done"},
                ], handle)
            with open(current, "w", encoding="utf-8") as handle:
                handle.write("AAA-004\n")
            with mock.patch.object(refill, "QUEUE_PATH", queue), \
                 mock.patch.object(refill, "STATE_PATH", state), \
                 mock.patch.object(refill, "CURRENT_PATH", current), \
                 mock.patch("queue_api.qb_api", side_effect=OSError("offline")):
                self.assertEqual(
                    refill.load_active_queue_ids(),
                    {"AAA-001", "AAA-002", "AAA-004"},
                )

    def test_loads_qb_discovered_active_ids_from_queue_api(self):
        torrents = [
            {"tags": "AAA-005", "name": "AAA-005", "state": "downloading"},
            {"tags": "AAA-006", "name": "AAA-006", "state": "queuedUP"},
        ]
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("queue_api.qb_api", return_value=torrents), \
             mock.patch.object(refill, "QUEUE_PATH", os.path.join(directory, "queue.txt")), \
             mock.patch.object(refill, "STATE_PATH", os.path.join(directory, "state.json")), \
             mock.patch.object(refill, "CURRENT_PATH", os.path.join(directory, "current.txt")):
            self.assertEqual(refill.load_active_queue_ids(), {"AAA-005"})

    def test_loads_watched_ids_from_shared_record_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "weekly_watched.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"items": [{"id": "BBB-002", "watched_at": "2026-08-13T00:00:00+08:00"}]}, handle)
            with mock.patch.object(refill, "WATCHED_JSON", path):
                self.assertEqual(refill.load_watched_ids(), {"BBB-002"})

    def test_apply_updates_only_approved_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "weekly.json")
            original = {
                "id": "BBB-001",
                "title": "Original title",
                "titleZh": "已有译名",
                "magnet": "magnet:?xt=urn:btih:OLD",
                "hasChinese": False,
                "custom": "keep",
            }
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([original], handle)

            with mock.patch.object(refill, "WEEKLY_JSON", path):
                with mock.patch.object(refill, "load_watched_ids", return_value=set()), \
                     mock.patch.object(refill, "load_active_queue_ids", return_value=set()), \
                     mock.patch.object(refill, "load_downloaded_ids", return_value=set()), \
                     mock.patch("src.weekly.blocking.load_rules", return_value={}), \
                     mock.patch("src.weekly.blocking.match_reason", return_value=""):
                    changed = refill.apply_chinese_magnet(
                        "BBB-001", "magnet:?xt=urn:btih:NEW", "plwt_chinese"
                    )

            self.assertTrue(changed)
            with open(path, encoding="utf-8") as handle:
                item = json.load(handle)[0]
            self.assertEqual(item["title"], "Original title")
            self.assertEqual(item["titleZh"], "已有译名")
            self.assertEqual(item["custom"], "keep")
            self.assertEqual(item["magnet"], "magnet:?xt=urn:btih:NEW")
            self.assertTrue(item["hasChinese"])
            self.assertTrue(item["isChinese"])
            self.assertEqual(item["chineseSource"], "plwt_chinese")
            self.assertTrue(item["chineseUpdatedAt"])

    def test_apply_rejects_non_forum_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "weekly.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([{"id": "BBB-001"}], handle)
            with mock.patch.object(refill, "WEEKLY_JSON", path):
                changed = refill.apply_chinese_magnet(
                    "BBB-001", "magnet:?xt=urn:btih:NEW", "sukebei_chinese"
                )
            self.assertFalse(changed)

    def test_apply_rechecks_visibility_before_writing(self):
        with mock.patch.object(refill, "load_watched_ids", return_value={"BBB-001"}), \
             mock.patch.object(refill, "load_active_queue_ids") as queue_ids, \
             mock.patch.object(refill, "load_downloaded_ids") as downloaded_ids:
            changed = refill.apply_chinese_magnet(
                "BBB-001", "magnet:?xt=urn:btih:NEW", "plwt_chinese"
            )
        self.assertFalse(changed)
        queue_ids.assert_not_called()
        downloaded_ids.assert_not_called()

    def test_search_uses_shared_slot_and_marks_rate_limit(self):
        client = mock.Mock()
        slot = mock.Mock(return_value=nullcontext())
        with mock.patch.object(refill, "_plwt_search_slot", slot), \
             mock.patch.object(refill, "_mark_plwt_rate_limited") as mark, \
             mock.patch(
                 "src.weekly.chinese_forum.search_exact_chinese",
                 return_value={"_rate_limited": True},
             ):
            magnet, source = refill.search_chinese_magnet("BBB-001", client)
        self.assertIsNone(magnet)
        self.assertEqual(source, "rate_limited")
        slot.assert_called_once_with()
        mark.assert_called_once_with()


class TestScrapePipeline(unittest.TestCase):
    def test_begin_pipeline_is_an_atomic_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "scrape_pipeline.json")
            self.assertTrue(scrape_pipeline.begin_pipeline(trigger="manual", path=path))
            self.assertFalse(scrape_pipeline.begin_pipeline(trigger="daily", path=path))
            status = scrape_pipeline.read_status(path)
            self.assertTrue(status["running"])
            self.assertEqual(status["trigger"], "manual")

            scrape_pipeline.finish_pipeline(summary="done", path=path)
            self.assertTrue(scrape_pipeline.begin_pipeline(trigger="daily", path=path))

    def test_interrupt_clears_a_running_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "scrape_pipeline.json")
            scrape_pipeline.begin_pipeline(trigger="manual", path=path)
            self.assertTrue(scrape_pipeline.interrupt_running_pipeline(path=path))
            status = scrape_pipeline.read_status(path)
            self.assertFalse(status["running"])
            self.assertEqual(status["phase"], "idle")
            self.assertIn("重启", status["last_error"])
            self.assertFalse(scrape_pipeline.interrupt_running_pipeline(path=path))


if __name__ == "__main__":
    unittest.main()
