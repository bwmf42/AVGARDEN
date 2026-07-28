import json
import os
import tempfile
import unittest
from unittest import mock

from tools.maintenance import storage_cleanup


class StorageCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.save = os.path.join(self.temp.name, "data")
        self.db = os.path.join(self.temp.name, "db")
        self.logs = os.path.join(self.temp.name, "logs")
        self.cfg = os.path.join(self.temp.name, "cfg", "configs.json")
        for path in (self.save, self.db, self.logs, os.path.dirname(self.cfg)):
            os.makedirs(path)
        os.makedirs(os.path.join(self.save, "__weekly__"))
        with open(os.path.join(self.save, "__weekly__", "weekly.json"), "w") as handle:
            json.dump([{"id": "KEEP-001"}], handle)
        with open(os.path.join(self.db, "weekly_watched.json"), "w") as handle:
            json.dump({"items": [{"id": "OLD-001"}]}, handle)
        with open(self.cfg, "w") as handle:
            handle.write("{}")

    def sparse(self, path, size=200 * 1024 * 1024):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.truncate(size)

    def test_manifest_separates_sparse_metadata_and_active_directories(self):
        self.sparse(os.path.join(self.save, "SPARSE-001", "SPARSE-001.mp4"))
        os.makedirs(os.path.join(self.save, "META-001"))
        with open(os.path.join(self.save, "META-001", "META-001.nfo"), "w") as handle:
            handle.write("metadata")
        self.sparse(os.path.join(self.save, "ACTIVE-001", "ACTIVE-001.mp4"))
        torrents = [{"hash": "active", "state": "stalledDL", "tags": "ACTIVE-001", "category": ""}]
        with mock.patch.object(storage_cleanup, "EXPECTED_BASELINE", {}):
            manifest = storage_cleanup.build_manifest(self.save, self.db, self.cfg, self.logs, torrents)
        removed = {os.path.basename(item["path"]) for item in manifest["actions"]["remove_media_dirs"]}
        self.assertEqual(removed, {"SPARSE-001", "META-001"})
        self.assertNotIn("ACTIVE-001", removed)
        self.assertEqual(manifest["actions"]["qb_set_category"][0]["hash"], "active")

    def test_tree_signature_detects_changes(self):
        path = os.path.join(self.save, "META-001")
        os.makedirs(path)
        file_path = os.path.join(path, "metadata.json")
        with open(file_path, "w") as handle:
            handle.write("{}")
        record = storage_cleanup.tree_record(path, "test")
        self.assertTrue(storage_cleanup.is_current_record(record))
        with open(file_path, "a") as handle:
            handle.write("x")
        self.assertFalse(storage_cleanup.is_current_record(record))

    def test_numeric_prefix_media_satisfies_short_qb_label(self):
        media_dir = os.path.join(self.save, "259LUXU-1881")
        os.makedirs(media_dir)
        real_media_dir = os.path.realpath(media_dir)
        torrent = {
            "hash": "luxu",
            "state": "queuedUP",
            "tags": "LUXU-1881",
            "category": "",
        }
        with mock.patch.object(storage_cleanup, "EXPECTED_BASELINE", {}), mock.patch.object(
            storage_cleanup,
            "find_main_video",
            side_effect=lambda path: os.path.join(path, "main.mp4") if path == real_media_dir else None,
        ):
            manifest = storage_cleanup.build_manifest(self.save, self.db, self.cfg, self.logs, [torrent])
        self.assertEqual(manifest["actions"]["qb_set_category"][0]["hash"], "luxu")

    def test_active_download_is_not_counted_as_completed_missing_poster(self):
        media_dir = os.path.realpath(os.path.join(self.save, "PAI-267"))
        os.makedirs(media_dir)
        torrent = {
            "hash": "active",
            "state": "downloading",
            "tags": "PAI-267",
            "category": "AV_GARDEN",
        }
        with mock.patch.object(storage_cleanup, "EXPECTED_BASELINE", {}), mock.patch.object(
            storage_cleanup,
            "find_main_video",
            side_effect=lambda path: os.path.join(path, "partial.mp4") if path == media_dir else None,
        ):
            manifest = storage_cleanup.build_manifest(self.save, self.db, self.cfg, self.logs, [torrent])
        self.assertEqual(manifest["counts"]["media_missing_posters"], 0)
        self.assertEqual(manifest["actions"]["copy_posters"], [])


if __name__ == "__main__":
    unittest.main()
