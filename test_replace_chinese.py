import json
import os
import tempfile
import unittest
import urllib.parse
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

    def test_qb_task_removal_never_deletes_media_files(self):
        class Response:
            def read(self):
                return b"Ok."

        class Opener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout):
                self.request = request
                return Response()

        opener = Opener()
        replace_chinese.remove_qb_torrent_record(opener, "abc123")
        values = urllib.parse.parse_qs(opener.request.data.decode())
        self.assertEqual(values["hashes"], ["abc123"])
        self.assertEqual(values["deleteFiles"], ["false"])

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

    def test_strict_selection_disables_every_file_except_largest_mp4(self):
        files = [
            {"index": 0, "name": "MNGS-071-U/main.mp4", "size": 4_900_000_000, "progress": 0.2},
            {"index": 1, "name": "MNGS-071-U/ad.mp4", "size": 15_000_000, "progress": 0.1},
            {"index": 2, "name": "MNGS-071-U/site.html", "size": 100, "progress": 1},
        ]

        class Response:
            def __init__(self, body):
                self.body = body

            def read(self):
                return self.body

        class Opener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout):
                self.requests.append(request)
                if "/torrents/files" in request.full_url:
                    return Response(json.dumps(files).encode())
                return Response(b"Ok.")

        opener = Opener()
        selected = replace_chinese.apply_strict_file_selection(opener, "MNGS-071", "hash")
        self.assertEqual(selected["index"], 0)
        posts = [
            (request.full_url, urllib.parse.parse_qs(request.data.decode()))
            for request in opener.requests if request.data
        ]
        disabled = next(values for url, values in posts if url.endswith("/filePrio") and values["priority"] == ["0"])
        kept = next(values for url, values in posts if url.endswith("/filePrio") and values["priority"] == ["1"])
        self.assertEqual(disabled["id"], ["1|2"])
        self.assertEqual(kept["id"], ["0"])
        self.assertTrue(posts[0][0].endswith("/stop"))
        self.assertTrue(posts[-1][0].endswith("/start"))

    def test_exact_torrent_cleanup_does_not_delete_unlisted_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            main = self.make_file(os.path.join(root, "MNGS-071", "main.mp4"))
            ad = self.make_file(os.path.join(root, "MNGS-071", "ad.mp4"))
            nfo = self.make_file(os.path.join(root, "MNGS-071", "MNGS-071.nfo"))
            outside = self.make_file(os.path.join(root, "outside.mp4"))
            torrent = {
                "save_path": root,
                "content_path": os.path.join(root, "MNGS-071"),
            }
            files = [
                {"name": "MNGS-071/main.mp4"},
                {"name": "MNGS-071/ad.mp4"},
                {"name": "../outside.mp4"},
            ]
            deleted, failed = replace_chinese.delete_exact_torrent_files(
                torrent,
                files,
                save_path=root,
            )
            self.assertEqual(failed, [])
            self.assertEqual(set(deleted), {"MNGS-071/main.mp4", "MNGS-071/ad.mp4"})
            self.assertFalse(os.path.exists(main))
            self.assertFalse(os.path.exists(ad))
            self.assertTrue(os.path.exists(nfo))
            self.assertTrue(os.path.exists(outside))

    def test_superseded_task_removes_exact_original_and_keeps_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            original = self.make_file(os.path.join(root, "MNGS-071", "original.mp4"))
            nfo = self.make_file(os.path.join(root, "MNGS-071", "MNGS-071.nfo"))
            files = [{"index": 0, "name": "MNGS-071/original.mp4", "size": 6_000_000_000}]

            class Response:
                def __init__(self, body=b"Ok."):
                    self.body = body

                def read(self):
                    return self.body

            class Opener:
                def __init__(self):
                    self.requests = []

                def open(self, request, timeout):
                    self.requests.append(request)
                    if "/torrents/files" in request.full_url:
                        return Response(json.dumps(files).encode())
                    return Response()

            torrents = [{
                "hash": "original",
                "state": "stoppedDL",
                "tags": "MNGS-071",
                "name": "MNGS-071",
                "save_path": root,
                "content_path": os.path.join(root, "MNGS-071"),
            }]
            pending = {"original": {"avid": "MNGS-071"}, "chinese": {"avid": "MNGS-071"}}
            opener = Opener()
            with mock.patch.object(replace_chinese, "SAVE_PATH", root):
                removed, failures = replace_chinese.remove_superseded_tasks(
                    opener,
                    torrents,
                    "MNGS-071",
                    "chinese",
                    pending,
                )
            self.assertEqual(removed, ["original"])
            self.assertEqual(failures, [])
            self.assertFalse(os.path.exists(original))
            self.assertTrue(os.path.exists(nfo))
            self.assertNotIn("original", pending)
            delete_request = next(
                request for request in opener.requests if request.full_url.endswith("/torrents/delete")
            )
            values = urllib.parse.parse_qs(delete_request.data.decode())
            self.assertEqual(values["deleteFiles"], ["false"])

    def test_forum_source_tag_identifies_chinese_torrent_without_filename_marker(self):
        torrent = {"hash": "cn", "tags": "MNGS-071,plwt_chinese", "name": "MNGS-071-U"}
        self.assertTrue(replace_chinese.torrent_is_known_chinese(torrent, {}, "MNGS-071"))

    def test_recovery_pending_does_not_turn_an_original_torrent_into_chinese(self):
        torrent = {"hash": "original", "tags": "MNGS-071", "name": "+++ [FHD] MNGS-071"}
        pending = {"original": {"avid": "MNGS-071", "recovery_manifest": "/logs/recovery.json"}}
        self.assertFalse(replace_chinese.torrent_is_known_chinese(torrent, pending, "MNGS-071"))

    def test_extracts_exact_info_hash_from_magnet(self):
        value = "31a83434f26bccdb67a1411d8d506b652d194215"
        magnet = f"magnet:?xt=urn:btih:{value.upper()}&dn=MNGS-071-U"
        self.assertEqual(replace_chinese.magnet_info_hash(magnet), value)


if __name__ == "__main__":
    unittest.main()
