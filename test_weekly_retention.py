import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tools.maintenance import weekly_retention_maintenance as retention
from weekly_watched_store import load_records, mark_watched, write_records


class WatchedStoreTest(unittest.TestCase):
    def test_mark_watched_is_atomic_and_preserves_first_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "weekly_watched.json")
            self.assertTrue(mark_watched(path, "abf001", "2026-07-01T00:00:00+08:00", "blocked_genre"))
            self.assertFalse(mark_watched(path, "ABF-001", "2026-07-20T00:00:00+08:00", "manual"))
            records = load_records(path)
            self.assertEqual(records["ABF-001"]["watched_at"], "2026-07-01T00:00:00+08:00")
            self.assertEqual(records["ABF-001"]["reason"], "blocked_genre")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


class WeeklyRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.save = os.path.join(self.temp.name, "data")
        self.db = os.path.join(self.temp.name, "db")
        self.weekly = os.path.join(self.save, "__weekly__")
        os.makedirs(self.weekly)
        os.makedirs(self.db)
        for name in (
            "blocked_genres.txt",
            "blocked_keywords.txt",
            "favorite_actresses.txt",
        ):
            open(os.path.join(self.db, name), "w").close()
        with open(os.path.join(self.db, "blocked_actresses.txt"), "w") as handle:
            handle.write("Blocked Actress\n")
        with open(os.path.join(self.db, "actress_ages.json"), "w") as handle:
            json.dump({}, handle)
        self.now_dt = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        self.now = self.now_dt.timestamp()
        self.items = [
            {"id": "ABF-001", "title": "old unwatched", "releaseDate": "2025-01-01"},
            {"id": "ABF-002", "title": "old watched", "cover": "/file/ABF-002/cover.jpg"},
            {"id": "ABF-003", "title": "recent watched", "cover": "/file/ABF-003/cover.jpg"},
            {"id": "ABF-004", "title": "blocked recent", "postDate": "2026-07-20", "actresses": ["Blocked Actress"], "cover": "/file/ABF-004/cover.jpg", "fanarts": ["x"]},
            {"id": "ABF-005", "title": "blocked old", "postDate": "2026-05-01", "actresses": ["Blocked Actress"], "cover": "/file/ABF-005/cover.jpg"},
        ]
        with open(os.path.join(self.weekly, "weekly.json"), "w") as handle:
            json.dump(self.items, handle)
        records = {
            "ABF-002": {"id": "ABF-002", "watched_at": (self.now_dt - timedelta(days=31)).isoformat(), "reason": "manual"},
            "ABF-003": {"id": "ABF-003", "watched_at": (self.now_dt - timedelta(days=10)).isoformat(), "reason": "manual"},
        }
        write_records(os.path.join(self.db, "weekly_watched.json"), records)
        for item in self.items:
            path = os.path.join(self.weekly, item["id"])
            os.makedirs(path)
            with open(os.path.join(path, "cover.jpg"), "wb") as handle:
                handle.write(b"image")
        self.env = mock.patch.dict(os.environ, {
            "DB_PATH": os.path.join(self.db, "downloaded.db"),
            "BLOCKED_ACTRESSES_FILE": os.path.join(self.db, "blocked_actresses.txt"),
            "BLOCKED_GENRES_FILE": os.path.join(self.db, "blocked_genres.txt"),
            "FAV_ACTRESSES_FILE": os.path.join(self.db, "favorite_actresses.txt"),
            "BLOCKED_KEYWORDS_FILE": os.path.join(self.db, "blocked_keywords.txt"),
            "ACTRESS_AGES_FILE": os.path.join(self.db, "actress_ages.json"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_manifest_and_apply_keep_unwatched_and_strip_blocked_artwork(self):
        manifest = retention.build_manifest(self.save, self.db, now=self.now)
        self.assertEqual(manifest["actions"]["expire_ids"], ["ABF-002", "ABF-005"])
        removed_names = {os.path.basename(item["path"]) for item in manifest["actions"]["remove_artwork_dirs"]}
        self.assertEqual(removed_names, {"ABF-002", "ABF-004", "ABF-005"})

        result = retention.apply_manifest(manifest)
        with open(os.path.join(self.weekly, "weekly.json")) as handle:
            items = {item["id"]: item for item in json.load(handle)}
        self.assertEqual(set(items), {"ABF-001", "ABF-003", "ABF-004"})
        self.assertNotIn("cover", items["ABF-004"])
        self.assertEqual(items["ABF-004"]["fanarts"], [])
        self.assertTrue(os.path.isdir(os.path.join(self.weekly, "ABF-001")))
        self.assertTrue(os.path.isdir(os.path.join(self.weekly, "ABF-003")))
        self.assertFalse(os.path.exists(os.path.join(self.weekly, "ABF-004")))
        records = load_records(os.path.join(self.db, "weekly_watched.json"))
        self.assertEqual(set(records), {"ABF-003", "ABF-004"})
        self.assertEqual(records["ABF-004"]["reason"], "blocked_actress")
        self.assertEqual(result["weekly_after"], 3)
        self.assertEqual(len(result["backups"]), 2)

    def test_apply_stops_when_weekly_changes_after_manifest(self):
        manifest = retention.build_manifest(self.save, self.db, now=self.now)
        with open(os.path.join(self.weekly, "weekly.json"), "a") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(RuntimeError, "guard changed"):
            retention.apply_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
