import unittest
from unittest import mock

from qb_task_guard import has_matching_qb_task

try:
    import worker
except (ImportError, OSError):
    worker = None


class WorkerQBGuardTest(unittest.TestCase):
    def test_finds_matching_task_across_all_categories(self):
        torrents = [{
            "state": "queuedDL",
            "category": "ARCHIVE",
            "tags": "",
            "name": "HUNTC-583",
            "content_path": "/data/HUNTC-583",
            "save_path": "/data",
        }]
        self.assertTrue(has_matching_qb_task(torrents, "HUNTC-583"))

    def test_completed_task_requires_valid_main_video(self):
        torrents = [{"state": "queuedUP", "tags": "MIKR-109", "name": "MIKR-109"}]
        self.assertFalse(has_matching_qb_task(torrents, "MIKR-109"))
        self.assertTrue(has_matching_qb_task(torrents, "MIKR-109", lambda *_: True))

    def test_matches_tag_but_not_longer_similar_code(self):
        tagged = [{"state": "downloading", "tags": "ABF-361", "name": "other"}]
        similar = [{"state": "downloading", "tags": "", "name": "ABF-3612"}]
        self.assertTrue(has_matching_qb_task(tagged, "ABF-361"))
        self.assertFalse(has_matching_qb_task(similar, "ABF-361"))

    def test_ignores_broken_qb_task(self):
        torrents = [{
            "state": "missingFiles",
            "tags": "ROE-505",
            "name": "ROE-505-C",
            "content_path": "/data/ROE-505-C",
        }]
        self.assertFalse(has_matching_qb_task(torrents, "ROE-505"))

    @unittest.skipUnless(worker is not None, "requires the Worker container runtime")
    def test_worker_queries_all_qb_categories(self):
        torrents = [{"state": "queuedDL", "name": "HUNTC-583"}]
        with mock.patch.object(worker, "qbittorrent_api", return_value=torrents) as qb_api:
            self.assertTrue(worker.has_active_qb_task("HUNTC-583"))
        qb_api.assert_called_once_with("GET", "/api/v2/torrents/info")

    @unittest.skipUnless(worker is not None, "requires the Worker container runtime")
    def test_existing_qb_task_prevents_online_fallback_without_magnet(self):
        with (
            mock.patch.object(worker.data, "initialize_db"),
            mock.patch.object(worker.data, "find_in_db", return_value=False),
            mock.patch.object(worker, "has_active_qb_task", return_value=True),
            mock.patch.object(worker, "log_write"),
            mock.patch.object(worker.downloaderMgr, "DownloaderMgr") as downloader_manager,
        ):
            self.assertFalse(worker.download_video("HUNTC-583"))
        downloader_manager.assert_not_called()


if __name__ == "__main__":
    unittest.main()
