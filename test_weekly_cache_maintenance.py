import json
import os
import tempfile
import time
import unittest

from tools.maintenance import weekly_cache_maintenance


class WeeklyCacheMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.save = os.path.join(self.temp.name, "data")
        self.db = os.path.join(self.temp.name, "db")
        self.weekly = os.path.join(self.save, "__weekly__")
        os.makedirs(self.weekly)
        os.makedirs(self.db)
        with open(os.path.join(self.weekly, "weekly.json"), "w") as handle:
            json.dump([{"id": "KEEP-001"}], handle)

    def make_art(self, name, mtime):
        path = os.path.join(self.weekly, name)
        os.makedirs(path)
        with open(os.path.join(path, "cover.jpg"), "wb") as handle:
            handle.write(b"image")
        os.utime(path, (mtime, mtime))
        return path

    def test_default_retention_selects_only_old_unreferenced_directories(self):
        now = time.time()
        keep = self.make_art("KEEP-001", now - 60 * 24 * 60 * 60)
        old = self.make_art("OLD-001", now - 31 * 24 * 60 * 60)
        fresh = self.make_art("FRESH-001", now - 29 * 24 * 60 * 60)
        manifest = weekly_cache_maintenance.build_manifest(self.save, self.db, now=now)
        self.assertEqual([item["path"] for item in manifest["actions"]["remove_weekly_dirs"]], [os.path.realpath(old)])
        self.assertTrue(os.path.isdir(keep))
        self.assertTrue(os.path.isdir(fresh))

    def test_apply_backs_up_index_and_removes_only_manifest_paths(self):
        now = time.time()
        old = self.make_art("OLD-001", now - 31 * 24 * 60 * 60)
        fresh = self.make_art("FRESH-001", now - 29 * 24 * 60 * 60)
        manifest = weekly_cache_maintenance.build_manifest(self.save, self.db, now=now)
        result = weekly_cache_maintenance.apply_manifest(manifest)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(fresh))
        self.assertTrue(os.path.isfile(result["backup"]))


if __name__ == "__main__":
    unittest.main()
