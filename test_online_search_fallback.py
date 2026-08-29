#!/usr/bin/env python3
"""Unit tests for online-search metadata and artwork fallback."""
import unittest
from unittest.mock import patch

import queue_api


def source_result(**overrides):
    result = {
        "kind": "stream",
        "source": "online_stream",
        "magnet": "",
    }
    result.update(overrides)
    return result


class OnlineSearchFallbackTest(unittest.TestCase):
    def setUp(self):
        self.proxy_patch = patch.object(queue_api, "ONLINE_PROXY", None)
        self.proxy_patch.start()
        self.addCleanup(self.proxy_patch.stop)
        self.translate_patch = patch.object(queue_api, "translate_online_title_zh", return_value=False)
        self.translate_patch.start()
        self.addCleanup(self.translate_patch.stop)
        self.javbus_page = patch("src.weekly.javbus.fetch_page", return_value=None)
        self.javbus_page.start()
        self.addCleanup(self.javbus_page.stop)

    def test_uses_current_mgs_metadata_chain_without_javbus(self):
        mgs_meta = {
            "title": "MGS product title",
            "actresses": ["Actor A"],
            "genres": ["巨乳"],
            "duration": "100分钟",
            "releaseDate": "2024-02-02",
        }
        with patch("src.weekly.mgs.set_proxy"), \
                patch("src.weekly.dmm.set_proxy"), \
                patch("src.weekly.javbus.set_proxy"), \
                patch("src.weekly.artwork.set_proxy"), \
                patch("src.weekly.mgs.fetch_detail", return_value=mgs_meta), \
                patch("src.weekly.dmm.fetch_metadata") as dmm_fetch, \
                patch("src.weekly.artwork.download_for_item"), \
                patch("download_source.resolve_download_source", return_value=source_result()):
            item, error = queue_api.build_online_detail("ABC-123")

        self.assertEqual(error, "")
        self.assertEqual(item["title"], "MGS product title")
        self.assertEqual(item["metaSource"], "mgs")
        self.assertEqual(item["actresses"], ["Actor A"])
        dmm_fetch.assert_not_called()

    def test_falls_back_to_dmm_metadata_when_mgs_has_no_product(self):
        dmm_meta = {
            "actresses": ["Actor B"],
            "genres": ["ドラマ"],
            "duration": "90分钟",
            "releaseDate": "2023-03-03",
        }
        with patch("src.weekly.mgs.set_proxy"), \
                patch("src.weekly.dmm.set_proxy"), \
                patch("src.weekly.javbus.set_proxy"), \
                patch("src.weekly.artwork.set_proxy"), \
                patch("src.weekly.mgs.fetch_detail", return_value=None), \
                patch("src.weekly.dmm.fetch_metadata", return_value=dmm_meta), \
                patch("src.weekly.javdatabase.fetch_detail") as jdb_fetch, \
                patch("src.weekly.artwork.download_for_item"), \
                patch("download_source.resolve_download_source", return_value=source_result()):
            item, error = queue_api.build_online_detail("XYZ-001")

        self.assertEqual(error, "")
        self.assertEqual(item["metaSource"], "dmm")
        self.assertEqual(item["actresses"], ["Actor B"])
        self.assertTrue(item["genres"])
        jdb_fetch.assert_not_called()

    def test_falls_back_to_javdatabase_after_mgs_and_dmm(self):
        jdb_meta = {
            "actresses": ["Actor C"],
            "genres": ["Drama"],
            "duration": "80分钟",
            "releaseDate": "2022-04-04",
            "cid": "",
        }
        with patch("src.weekly.mgs.set_proxy"), \
                patch("src.weekly.dmm.set_proxy"), \
                patch("src.weekly.javbus.set_proxy"), \
                patch("src.weekly.artwork.set_proxy"), \
                patch("src.weekly.mgs.fetch_detail", return_value=None), \
                patch("src.weekly.dmm.fetch_metadata", return_value=None), \
                patch("src.weekly.javdatabase.fetch_detail", return_value=jdb_meta), \
                patch("src.weekly.artwork.download_for_item"), \
                patch("download_source.resolve_download_source", return_value=source_result()):
            item, error = queue_api.build_online_detail("JDB-001")

        self.assertEqual(error, "")
        self.assertEqual(item["metaSource"], "javdatabase")
        self.assertEqual(item["actresses"], ["Actor C"])

    def test_artwork_or_magnet_can_supply_a_result_without_metadata(self):
        def add_artwork(item, *_args, **_kwargs):
            item["cover"] = "/file/__online__/ART-001/ART-001-cover.jpg"
            item["poster"] = item["cover"]
            item["artworkSource"] = "dmm"

        with patch("src.weekly.mgs.set_proxy"), \
                patch("src.weekly.dmm.set_proxy"), \
                patch("src.weekly.javbus.set_proxy"), \
                patch("src.weekly.artwork.set_proxy"), \
                patch("src.weekly.mgs.fetch_detail", return_value=None), \
                patch("src.weekly.dmm.fetch_metadata", return_value=None), \
                patch("src.weekly.javdatabase.fetch_detail", return_value=None), \
                patch("src.weekly.artwork.download_for_item", side_effect=add_artwork), \
                patch("download_source.resolve_download_source", return_value=source_result()):
            artwork_item, artwork_error = queue_api.build_online_detail("ART-001")

        self.assertEqual(artwork_error, "")
        self.assertEqual(artwork_item["artworkSource"], "dmm")

        with patch("src.weekly.enrich.enrich_item"), \
                patch(
                    "download_source.resolve_download_source",
                    return_value=source_result(
                        kind="magnet",
                        source="sukebei_chinese",
                        magnet="magnet:?xt=urn:btih:test",
                    ),
                ):
            magnet_item, magnet_error = queue_api.build_online_detail("MAG-001")

        self.assertEqual(magnet_error, "")
        self.assertTrue(magnet_item["hasChinese"])
        self.assertEqual(magnet_item["magnetSource"], "sukebei_chinese")

    def test_metadata_survives_download_source_error(self):
        def add_metadata(item, *_args, **_kwargs):
            item["title"] = "Recovered metadata title"
            item["metaSource"] = "mgs"

        with patch("src.weekly.enrich.enrich_item", side_effect=add_metadata), \
                patch("download_source.resolve_download_source", side_effect=RuntimeError("offline")):
            item, error = queue_api.build_online_detail("ERR-001")

        self.assertEqual(error, "")
        self.assertEqual(item["title"], "Recovered metadata title")
        self.assertEqual(item["magnet"], "")

    def test_no_metadata_artwork_or_magnet_is_not_a_detail(self):
        with patch("src.weekly.enrich.enrich_item"), \
                patch("download_source.resolve_download_source", return_value=source_result()):
            item, error = queue_api.build_online_detail("NONE-000")

        self.assertIsNone(item)
        self.assertEqual(error, "detail not found")

    def test_fills_title_from_magnet_listing_when_enrich_left_the_code(self):
        with patch("src.weekly.enrich.enrich_item"), \
                patch("src.weekly.javbus.fetch_page", return_value=None), \
                patch(
                    "download_source.resolve_download_source",
                    return_value=source_result(
                        kind="magnet",
                        source="plwt_chinese",
                        magnet="magnet:?xt=urn:btih:test",
                        title="SNOS-334 最強ビジュOLさん、出張先で相部屋",
                    ),
                ):
            item, error = queue_api.build_online_detail("SNOS-334")
        self.assertEqual(error, "")
        self.assertEqual(item["title"], "SNOS-334 最強ビジュOLさん、出張先で相部屋")
        self.assertTrue(item["hasChinese"])

    def test_fills_title_from_javbus_when_listing_title_is_the_code(self):
        with patch("src.weekly.enrich.enrich_item"), \
                patch("src.weekly.javbus.set_proxy"), \
                patch("src.weekly.javbus.fetch_page", return_value="<html>"), \
                patch(
                    "src.weekly.javbus.parse_page",
                    return_value={"title": "最強ビジュOLさん、出張先で死ぬほど嫌いな中年上司と相部屋"},
                ), \
                patch(
                    "download_source.resolve_download_source",
                    return_value=source_result(
                        kind="magnet",
                        source="plwt_chinese",
                        magnet="magnet:?xt=urn:btih:test",
                        title="SNOS-334",
                    ),
                ):
            item, error = queue_api.build_online_detail("SNOS-334")
        self.assertEqual(error, "")
        self.assertEqual(item["title"], "最強ビジュOLさん、出張先で死ぬほど嫌いな中年上司と相部屋")


if __name__ == "__main__":
    unittest.main()
