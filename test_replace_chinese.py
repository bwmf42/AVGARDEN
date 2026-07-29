import json
import os
import tempfile
import unittest
from unittest import mock

import replace_chinese


class ReplaceChineseSafetyTest(unittest.TestCase):
    def make_file(self, path, content=b"x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def candidate(self, path, size=200 * 1024 * 1024):
        return {"path": path, "size": size, "part_group": "", "part": 0}

    def test_selects_exact_largest_qb_video(self):
        selected = replace_chinese.select_qb_main_file([
            {"index": 0, "name": "MIKR-109/main.mp4", "size": 6_000_000_000, "progress": 1},
            {"index": 1, "name": "MIKR-109/ad.mp4", "size": 15_000_000, "progress": 1},
            {"index": 2, "name": "MIKR-109/larger.mp4", "size": 7_000_000_000, "progress": 0.8},
        ])
        self.assertEqual(selected["index"], 2)
        self.assertEqual(selected["name"], "MIKR-109/larger.mp4")

    def test_resolves_qb_file_list_path_under_save_root(self):
        with tempfile.TemporaryDirectory() as root:
            expected = self.make_file(os.path.join(root, "MIKR-109", "main.mp4"))
            actual = replace_chinese.resolve_qb_file_path(
                {"save_path": root, "content_path": os.path.dirname(expected)},
                {"name": "MIKR-109/main.mp4"},
            )
            self.assertEqual(actual, os.path.realpath(expected))
            escaped = replace_chinese.resolve_qb_file_path(
                {"save_path": root, "content_path": os.path.dirname(expected)},
                {"name": "../outside.mp4"},
            )
            self.assertIsNone(escaped)

    def test_qb_tasks_protect_only_healthy_media_directories(self):
        with tempfile.TemporaryDirectory() as root:
            protected = replace_chinese.qb_protected_media_dirs([
                {
                    "hash": "healthy",
                    "state": "uploading",
                    "content_path": os.path.join(root, "MIKR-109"),
                },
                {
                    "hash": "broken",
                    "state": "missingFiles",
                    "content_path": os.path.join(root, "SNOS-264"),
                },
                {
                    "hash": "elsewhere",
                    "state": "downloading",
                    "content_path": "/outside/PRED-886",
                },
            ], save_path=root)
            self.assertEqual(protected, {os.path.realpath(os.path.join(root, "MIKR-109"))})

    def test_stale_marker_without_main_video_does_not_trigger_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            dpath = os.path.join(root, "MIKR-109")
            marker = self.make_file(os.path.join(dpath, ".av_garden_chinese"))
            promo = self.make_file(os.path.join(dpath, "台湾uu美少女直播.mp4"))
            with mock.patch.object(replace_chinese, "SAVE_PATH", root), mock.patch.object(
                replace_chinese, "collect_main_video_candidates", return_value=[]
            ):
                self.assertEqual(replace_chinese.sweep_leftover_non_chinese(root, protected_dirs=set()), 0)
            self.assertTrue(os.path.exists(marker))
            self.assertTrue(os.path.exists(promo))

    def test_legacy_marker_keeps_unknown_main_and_only_removes_junk(self):
        with tempfile.TemporaryDirectory() as root:
            dpath = os.path.join(root, "MIKR-109")
            main = self.make_file(os.path.join(dpath, "489155.com@MIKR-109.mp4"))
            promo = self.make_file(os.path.join(dpath, "台湾uu美少女直播.mp4"))
            text = self.make_file(os.path.join(dpath, "site.txt"))
            self.make_file(os.path.join(dpath, ".av_garden_chinese"))
            candidates = [self.candidate(main)]
            with mock.patch.object(replace_chinese, "SAVE_PATH", root), mock.patch.object(
                replace_chinese, "collect_main_video_candidates", return_value=candidates
            ), mock.patch.object(replace_chinese, "recorded_chinese_main", return_value=None):
                replace_chinese.sweep_leftover_non_chinese(root, protected_dirs=set())
            self.assertTrue(os.path.exists(main))
            self.assertFalse(os.path.exists(promo))
            self.assertFalse(os.path.exists(text))

    def test_qb_owned_directory_is_never_cleaned(self):
        with tempfile.TemporaryDirectory() as root:
            dpath = os.path.join(root, "MIKR-109")
            main = self.make_file(os.path.join(dpath, "489155.com@MIKR-109.mp4"))
            promo = self.make_file(os.path.join(dpath, "台湾uu美少女直播.mp4"))
            self.make_file(os.path.join(dpath, ".av_garden_chinese"))
            candidates = [self.candidate(main)]
            with mock.patch.object(replace_chinese, "SAVE_PATH", root), mock.patch.object(
                replace_chinese, "collect_main_video_candidates", return_value=candidates
            ):
                replace_chinese.sweep_leftover_non_chinese(root, protected_dirs={dpath})
            self.assertTrue(os.path.exists(main))
            self.assertTrue(os.path.exists(promo))

    def test_provenance_identifies_the_only_replaceable_main(self):
        with tempfile.TemporaryDirectory() as root:
            dpath = os.path.join(root, "MIKR-109")
            chinese = self.make_file(os.path.join(dpath, "MIKR-109-C.mp4"))
            original = self.make_file(os.path.join(dpath, "MIKR-109.mp4"))
            candidates = [self.candidate(chinese), self.candidate(original)]
            with mock.patch.object(replace_chinese, "SAVE_PATH", root), mock.patch.object(
                replace_chinese, "collect_main_video_candidates", return_value=candidates
            ), mock.patch.object(replace_chinese, "recorded_chinese_main", return_value=chinese):
                replace_chinese.sweep_leftover_non_chinese(root, protected_dirs=set())
            self.assertTrue(os.path.exists(chinese))
            self.assertFalse(os.path.exists(original))

    def test_writes_persistent_qb_file_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            video = self.make_file(os.path.join(root, "MIKR-109-C.mp4"), b"video")
            selected = {"index": 4, "name": "torrent/MIKR-109.mp4", "size": 5}
            replace_chinese.write_media_provenance(root, "MIKR-109", "abc123", selected, video)
            with open(os.path.join(root, replace_chinese.MEDIA_PROVENANCE_FILE), encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["chineseMain"]["path"], "MIKR-109-C.mp4")
            self.assertEqual(payload["chineseMain"]["torrentFileIndex"], 4)
            self.assertEqual(payload["chineseMain"]["torrentFilePath"], "torrent/MIKR-109.mp4")


if __name__ == "__main__":
    unittest.main()
