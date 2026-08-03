import os
import tempfile
import unittest
from contextlib import nullcontext
from unittest import mock

import download_source
from src.weekly import chinese_forum, sukebei


def nyaa_row(view_id, title, size, timestamp, magnet, row_class="default"):
    return f"""
    <tr class="{row_class}">
      <td><a href="/view/{view_id}" title="{title}">{title}</a></td>
      <td><a href="{magnet}">magnet</a></td>
      <td class="text-center">{size}</td>
      <td class="text-center" data-timestamp="{timestamp}">date</td>
      <td class="text-center">4</td><td class="text-center">1</td>
    </tr>
    """


class SukebeiSelectionTest(unittest.TestCase):
    def test_selects_largest_exact_chinese_candidate(self):
        html = "".join([
            nyaa_row(1, "SSIS-951 中文字幕 4K", "7.5 GiB", 1701000000, "magnet:?xt=urn:btih:cnlarge"),
            nyaa_row(2, "SSIS-951-C", "2.0 GiB", 1700000000, "magnet:?xt=urn:btih:cnsmall", "success"),
            nyaa_row(3, "SSIS-951 original", "9.0 GiB", 1699000000, "magnet:?xt=urn:btih:original"),
        ])
        selected = sukebei.select_preferred_candidate(sukebei._parse_nyaa_candidates("SSIS-951", html))
        self.assertEqual(selected["magnet"], "magnet:?xt=urn:btih:cnlarge")
        self.assertTrue(selected["is_cn"])

    def test_without_chinese_selects_earliest_upload(self):
        html = "".join([
            nyaa_row(1, "SSIS-951 newest huge", "12.0 GiB", 1701000000, "magnet:?xt=urn:btih:newest"),
            nyaa_row(2, "SSIS-951 oldest", "7.7 GiB", 1699000000, "magnet:?xt=urn:btih:oldest"),
            nyaa_row(3, "SSIS-951 middle", "9.0 GiB", 1700000000, "magnet:?xt=urn:btih:middle"),
        ])
        selected = sukebei.select_preferred_candidate(sukebei._parse_nyaa_candidates("SSIS-951", html))
        self.assertEqual(selected["magnet"], "magnet:?xt=urn:btih:oldest")
        self.assertFalse(selected["is_cn"])

    def test_similar_longer_code_is_not_exact(self):
        html = nyaa_row(1, "SSIS-9512 中文字幕", "20.0 GiB", 1699000000, "magnet:?xt=urn:btih:wrong")
        selected = sukebei.select_preferred_candidate(sukebei._parse_nyaa_candidates("SSIS-951", html))
        self.assertIsNone(selected)

    def test_compact_ch_suffix_is_exact_chinese(self):
        html = nyaa_row(1, "SSIS951CH", "3.0 GiB", 1699000000, "magnet:?xt=urn:btih:compactch")
        selected = sukebei.select_preferred_candidate(sukebei._parse_nyaa_candidates("SSIS-951", html))
        self.assertEqual(selected["magnet"], "magnet:?xt=urn:btih:compactch")
        self.assertTrue(selected["is_cn"])


class ChineseForumSearchTest(unittest.TestCase):
    def test_existing_thread_magnet_wrapper_still_fetches(self):
        with mock.patch.object(
            chinese_forum.ForumClient,
            "fetch_thread_magnet",
            return_value="magnet:?xt=urn:btih:existing",
        ) as fetch:
            magnet = chinese_forum.fetch_thread_magnet("https://forum.test/thread-1-1-1.html")
        self.assertEqual(magnet, "magnet:?xt=urn:btih:existing")
        fetch.assert_called_once_with("https://forum.test/thread-1-1-1.html")

    def test_parses_only_exact_forum_103_result(self):
        html = """
        <ul>
          <li class="pbw" id="1"><h3 class="xs3"><a href="forum.php?mod=viewthread&amp;tid=1">SSIS-951 中文字幕</a></h3>
          <p>magnet:?xt=urn:btih:1234567890123456789012345678901234567890</p>
          <p><span>2024-01-01 12:00</span><span><a href="forum-103-1.html">高清中文字幕</a></span></p></li>
          <li class="pbw" id="2"><h3 class="xs3"><a href="forum.php?mod=viewthread&amp;tid=2">SSIS-9512 中文字幕</a></h3>
          <p><span>2024-01-02</span><span><a href="forum-103-1.html">高清中文字幕</a></span></p></li>
          <li class="pbw" id="3"><h3 class="xs3"><a href="forum.php?mod=viewthread&amp;tid=3">SSIS-951 原版</a></h3>
          <p><span>2024-01-03</span><span><a href="forum-37-1.html">亚洲有码原创</a></span></p></li>
        </ul>
        """
        results = chinese_forum.parse_search_html(html, "SSIS-951", base="https://forum.test", fid="103")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["forumUrl"], "https://forum.test/forum.php?mod=viewthread&tid=1")
        self.assertTrue(results[0]["magnet"].startswith("magnet:?xt=urn:btih:"))


class DownloadSourceResolverTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_path = os.path.join(self.temp_dir.name, "sources.json")
        self.real_plwt_search_slot = download_source._plwt_search_slot
        self.slot_patch = mock.patch.object(download_source, "_plwt_search_slot", return_value=nullcontext())
        self.slot_patch.start()
        self.addCleanup(self.slot_patch.stop)

    def test_forum_hit_stops_before_sukebei(self):
        forum = {
            "magnet": "magnet:?xt=urn:btih:forum",
            "title": "SSIS-951 中文字幕",
            "forumUrl": "https://forum.test/thread-1-1-1.html",
            "postDate": "2024-01-01",
        }
        with mock.patch.object(chinese_forum, "search_exact_chinese", return_value=forum), mock.patch.object(
            sukebei, "search_preferred"
        ) as search_preferred:
            source = download_source.resolve_download_source("ssis951", cache_path=self.cache_path)
        self.assertEqual(source["source"], "plwt_chinese")
        search_preferred.assert_not_called()

    def test_plwt_rate_slot_uses_a_separate_lock_file(self):
        rate_path = os.path.join(self.temp_dir.name, "plwt-rate.json")
        with mock.patch.object(download_source, "PLWT_SEARCH_INTERVAL_SECONDS", 0):
            with self.real_plwt_search_slot(rate_path):
                pass
        self.assertTrue(os.path.exists(rate_path))
        self.assertTrue(os.path.exists(rate_path + ".slot.lock"))

    def test_plwt_search_slot_is_context_manager(self):
        """Regression: @contextmanager must decorate _plwt_search_slot (not only rate_limited).

        Missing decorator → TypeError: 'generator' object does not support the context manager protocol
        and every magnet resolve (qB/115) fails with feishu 所有源均失败.
        """
        rate_path = os.path.join(self.temp_dir.name, "plwt-cm.json")
        slot = download_source._plwt_search_slot(rate_path)
        self.assertTrue(hasattr(slot, "__enter__"), "must be context manager, not bare generator")
        self.assertTrue(hasattr(slot, "__exit__"))
        with mock.patch.object(download_source, "PLWT_SEARCH_INTERVAL_SECONDS", 0):
            with slot:
                pass

    def test_sukebei_result_is_cached_for_worker_reuse(self):
        candidate = {
            "magnet": "magnet:?xt=urn:btih:sukebei",
            "title": "SSIS-951 中文字幕",
            "view_id": "123",
            "size_gib": 7.5,
            "published_at": "2023-11-24 11:02",
            "is_cn": True,
        }
        with mock.patch.object(chinese_forum, "search_exact_chinese", return_value=None) as forum, mock.patch.object(
            sukebei, "search_preferred", return_value=candidate
        ) as search_preferred:
            first = download_source.resolve_download_source("SSIS-951", cache_path=self.cache_path)
            second = download_source.resolve_download_source("SSIS-951", cache_path=self.cache_path)
        self.assertEqual(first["source"], "sukebei_chinese")
        self.assertEqual(second["magnet"], candidate["magnet"])
        forum.assert_called_once()
        search_preferred.assert_called_once()

    def test_no_magnet_records_online_stream_fallback(self):
        with mock.patch.object(chinese_forum, "search_exact_chinese", return_value=None), mock.patch.object(
            sukebei, "search_preferred", return_value=None
        ):
            source = download_source.resolve_download_source("SSIS-951", cache_path=self.cache_path)
        self.assertEqual(source["kind"], "stream")
        self.assertEqual(source["source"], "online_stream")
        self.assertEqual(source["magnet"], "")

    def test_cleanup_removes_only_expired_sources(self):
        download_source.save_cached_source(
            "SSIS-951", {"source": "online_stream"}, path=self.cache_path, now=100
        )
        download_source.save_cached_source(
            "SSIS-952", {"source": "online_stream"}, path=self.cache_path, now=200
        )
        with mock.patch.object(download_source, "SOURCE_CACHE_TTL_SECONDS", 50):
            removed = download_source.cleanup_expired_sources(path=self.cache_path, now=240)
        self.assertEqual(removed, ["SSIS-951"])
        self.assertIsNone(download_source.get_cached_source("SSIS-951", path=self.cache_path, now=240))
        with mock.patch.object(download_source, "SOURCE_CACHE_TTL_SECONDS", 50):
            self.assertIsNotNone(download_source.get_cached_source("SSIS-952", path=self.cache_path, now=240))


if __name__ == "__main__":
    unittest.main()
