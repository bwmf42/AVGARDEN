import unittest
from unittest import mock

import weekly_updater
from src.weekly import merge


class WeeklyUpdaterRetentionTest(unittest.TestCase):
    def test_blocked_item_never_fetches_artwork_or_magnet(self):
        item = {"id": "ABF-001", "title": "title"}
        with mock.patch.object(weekly_updater.enrich, "enrich_item", side_effect=lambda value, **_: value.update({"actresses": ["Blocked"]})), \
             mock.patch.object(weekly_updater.blocking, "match_reason", return_value="blocked_actress"), \
             mock.patch.object(weekly_updater.blocking, "strip_expensive_fields", wraps=weekly_updater.blocking.strip_expensive_fields), \
             mock.patch.object(weekly_updater.artwork, "download_for_item") as artwork, \
             mock.patch.object(weekly_updater.chinese_forum, "fetch_thread_magnet") as forum, \
             mock.patch.object(weekly_updater.sukebei, "search") as sukebei, \
             mock.patch.object(weekly_updater, "mark_watched") as watched:
            reason = weekly_updater.enrich_new_item(item, rules={})
        self.assertEqual(reason, "blocked_actress")
        artwork.assert_not_called()
        forum.assert_not_called()
        sukebei.assert_not_called()
        watched.assert_called_once()

    def test_unblocked_item_fetches_artwork_then_magnet(self):
        item = {"id": "ABF-002", "title": "title", "forumUrl": "https://example.test/thread"}
        with mock.patch.object(weekly_updater.enrich, "enrich_item"), \
             mock.patch.object(weekly_updater.blocking, "match_reason", return_value=""), \
             mock.patch.object(weekly_updater.javbus, "cover_needs_refresh", return_value=False), \
             mock.patch.object(weekly_updater.artwork, "download_for_item", side_effect=lambda value, *_args, **_kwargs: value.update({"cover": "/file/cover.jpg"})) as artwork, \
             mock.patch.object(weekly_updater.chinese_forum, "fetch_thread_magnet", return_value="magnet:test") as forum, \
             mock.patch.object(weekly_updater.sukebei, "search") as sukebei:
            reason = weekly_updater.enrich_new_item(item, rules={})
        self.assertEqual(reason, "")
        artwork.assert_called_once()
        forum.assert_called_once()
        sukebei.assert_not_called()
        self.assertEqual(item["magnet"], "magnet:test")

    def test_merge_keeps_old_downloaded_item_until_watched_retention_removes_it(self):
        existing = [{"id": "ABF-003", "releaseDate": "2020-01-01", "downloaded": True}]
        self.assertEqual(merge.merge(existing, [], 30), existing)


if __name__ == "__main__":
    unittest.main()
