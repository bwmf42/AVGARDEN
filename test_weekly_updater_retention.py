import unittest
from unittest import mock

import weekly_updater
from src.weekly import merge


class WeeklyUpdaterRetentionTest(unittest.TestCase):
    def test_translation_provider_prefers_configured_relay(self):
        with mock.patch.object(weekly_updater, "TRANSLATE_API_BASE", "https://relay.example/v1"), \
             mock.patch.object(weekly_updater, "TRANSLATE_API_KEY", "relay-key"), \
             mock.patch.object(weekly_updater, "TRANSLATE_MODEL", "gpt-5.4"), \
             mock.patch.object(weekly_updater, "DS_API_KEY", "deepseek-key"):
            self.assertEqual(weekly_updater.translation_provider(), ("relay", "gpt-5.4"))

    def test_translation_provider_falls_back_to_deepseek_without_relay(self):
        with mock.patch.object(weekly_updater, "TRANSLATE_API_BASE", ""), \
             mock.patch.object(weekly_updater, "TRANSLATE_API_KEY", ""), \
             mock.patch.object(weekly_updater, "DS_API_KEY", "deepseek-key"), \
             mock.patch.object(weekly_updater, "DS_MODEL", "deepseek-v4-flash"):
            self.assertEqual(weekly_updater.translation_provider(), ("deepseek", "deepseek-v4-flash"))

    def test_clear_untranslatable_title_zh(self):
        items = [
            {"id": "NLD-032", "title": "NLD-032", "titleZh": "NLD-032: NLD-032"},
            {"id": "SIMP-021", "title": "SIMP-021 Ran", "titleZh": "诱人美腿"},
            {"id": "GVH-861", "title": "GVH-861 禁断介護 西元めいさ", "titleZh": "禁忌的看护", "actresses": ["西元めいさ"]},
        ]
        self.assertEqual(weekly_updater.clear_untranslatable_title_zh(items), 2)
        self.assertEqual(items[0]["titleZh"], "")
        self.assertEqual(items[1]["titleZh"], "")
        self.assertEqual(items[2]["titleZh"], "禁忌的看护")

    def test_batch_translate_retries_invalid_nonempty_result(self):
        item = {
            "id": "SAN-478Z",
            "title": "SAN-478Z とても長い日本語の作品タイトルで翻訳結果に十分な本文が必要です",
            "titleZh": "让",
            "actresses": [],
        }
        with mock.patch.object(weekly_updater, "DS_API_KEY", "test"), \
             mock.patch.object(weekly_updater.blocking, "load_rules", return_value={}), \
             mock.patch.object(weekly_updater.blocking, "match_reason", return_value=""), \
             mock.patch.object(
                 weekly_updater,
                 "translate_title_with_retry",
                 side_effect=["让", "SAN-478Z：这是一个完整的中文翻译标题"],
             ) as translate, \
             mock.patch.object(weekly_updater.time, "sleep"):
            ok, fail = weekly_updater.batch_translate([item], passes=2)

        self.assertEqual((ok, fail), (1, 1))
        self.assertEqual(translate.call_count, 2)
        self.assertEqual(item["titleZh"], "SAN-478Z：这是一个完整的中文翻译标题")

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
