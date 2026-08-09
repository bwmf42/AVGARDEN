#!/usr/bin/env python3
"""Unit tests for forum-title truncation restore (no network)."""
import unittest
from unittest import mock

from src.weekly import enrich

FORUM = "IPZZ-940 最近元気がないパート先の人妻「仲村さん」を気分転換がてらドライブデートに誘。仲村みう"
OFFICIAL = "IPZZ-940 最近元気がないパート先の人妻「仲村さん」を気分転換がてらドライブデートに誘ったらセックスレスと夫の浮気を打ち明けられホテルで一晩中、愛し続けてあげたら「オンナとしての悦び」を改めて知り僕なしでは生きられないカラダになってしまった。 仲村みう"


def _item(title=FORUM, source="plwt-37", acts=("仲村みう",), vid="IPZZ-940"):
    return {"id": vid, "title": title, "titleZh": "IPZZ-940: 最近无精",
            "actresses": list(acts), "source": source}


class TestForumTitleTruncation(unittest.TestCase):
    def test_truncated_prefix_detected(self):
        self.assertTrue(enrich._forum_title_is_truncated_prefix(_item(), OFFICIAL))

    def test_identical_title_not_truncated(self):
        self.assertFalse(enrich._forum_title_is_truncated_prefix(_item(title=OFFICIAL), OFFICIAL))

    def test_unrelated_title_not_truncated(self):
        self.assertFalse(enrich._forum_title_is_truncated_prefix(
            _item(title="IPZZ-940 完全に別のタイトルです。仲村みう"), OFFICIAL))

    def test_small_gap_not_truncated(self):
        short_official = "IPZZ-940 最近元気がないパート先の人妻「仲村さん」を気分転換がてらドライブデートに誘ったら。 仲村みう"
        self.assertFalse(enrich._forum_title_is_truncated_prefix(_item(), short_official))

    def test_non_plwt_source_skipped(self):
        self.assertFalse(enrich._forum_title_is_truncated_prefix(_item(source="dmm"), OFFICIAL))

    def test_restore_replaces_title_and_clears_zh(self):
        with mock.patch.object(enrich.javbus, "fetch_page", return_value="<html>page</html>"), \
             mock.patch.object(enrich.javbus, "parse_page", return_value={"title": OFFICIAL}):
            item = _item()
            self.assertTrue(enrich.restore_truncated_forum_title(item))
        self.assertEqual(item["title"], OFFICIAL)
        self.assertEqual(item["titleZh"], "")

    def test_restore_unchanged_on_fetch_error(self):
        with mock.patch.object(enrich.javbus, "fetch_page", side_effect=RuntimeError("boom")):
            item = _item()
            self.assertFalse(enrich.restore_truncated_forum_title(item))
        self.assertEqual(item["title"], FORUM)
        self.assertNotEqual(item["titleZh"], "")


if __name__ == "__main__":
    unittest.main()
