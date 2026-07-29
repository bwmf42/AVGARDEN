#!/usr/bin/env python3
import os
import tempfile
import unittest

import weekly_backfill_details as backfill


class TestBackfillSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_save_path = backfill.SAVE_PATH
        backfill.SAVE_PATH = self.tmp.name

    def tearDown(self):
        backfill.SAVE_PATH = self.original_save_path
        self.tmp.cleanup()

    def _local_asset(self, relative, size):
        path = os.path.join(self.tmp.name, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        return "/file/" + relative

    def complete_item(self):
        return {
            "id": "TEST-001",
            "actresses": ["演员"],
            "genres": ["标签"],
            "duration": "90分钟",
            "releaseDate": "2026-07-23",
            "titleZh": "标题",
            "magnet": "magnet:?xt=urn:btih:test",
            "cover": self._local_asset("__weekly__/TEST-001/TEST-001-cover.jpg", 9000),
            "fanarts": [
                self._local_asset("__weekly__/TEST-001/TEST-001-fanart-1.jpg", 4000)
            ],
            "remoteFanarts": ["https://example.test/remote.jpg"],
        }

    def test_remote_fanart_does_not_requeue_complete_item(self):
        item = self.complete_item()
        self.assertEqual(backfill.missing_fields(item), [])
        self.assertFalse(backfill.needs_backfill(item))

    def test_missing_actress_is_a_real_target(self):
        item = self.complete_item()
        item["actresses"] = []
        self.assertIn("actresses", backfill.missing_fields(item))
        self.assertTrue(backfill.needs_backfill(item))

    def test_missing_local_fanart_is_a_real_target(self):
        item = self.complete_item()
        item["fanarts"] = ["https://example.test/remote.jpg"]
        self.assertIn("fanarts", backfill.missing_fields(item))
        self.assertTrue(backfill.needs_backfill(item))

    def test_truncated_title_is_a_real_target(self):
        item = self.complete_item()
        item["title"] = "TEST-001 とても長い日本語の作品タイトルで翻訳結果に十分な本文が必要です"
        item["titleZh"] = "让"
        self.assertIn("titleZh", backfill.missing_fields(item))
        self.assertTrue(backfill.needs_backfill(item))


if __name__ == "__main__":
    unittest.main()
