#!/usr/bin/env python3
"""Unit tests for genre ZH + MGS metadata parse (no network)."""
import unittest

from src.weekly import genre_zh, mgs


class TestGenreZh(unittest.TestCase):
    def test_basic_align_javbus(self):
        self.assertEqual(genre_zh.translate_genre("中出し"), "中出")
        self.assertEqual(genre_zh.translate_genre("独占配信"), "DMM獨家")
        self.assertEqual(genre_zh.translate_genre("フルハイビジョン(FHD)"), "高畫質")
        self.assertEqual(genre_zh.translate_genre("人妻"), "已婚婦女")
        self.assertEqual(genre_zh.translate_genre("単体作品"), "單體作品")
        self.assertEqual(genre_zh.translate_genre("素人"), "業餘")
        self.assertEqual(genre_zh.translate_genre("ハメ撮り"), "第一人稱攝影")
        self.assertEqual(genre_zh.translate_genre("NTR"), "NTR")
        self.assertEqual(genre_zh.translate_genre("寝取り・寝取られ"), "NTR")

    def test_javbus_passthrough(self):
        # already-library tags stay the same
        for g in ("高畫質", "單體作品", "DMM獨家", "業餘", "已婚婦女", "顏射", "苗條"):
            self.assertEqual(genre_zh.translate_genre(g), g)

    def test_list_dedupe(self):
        out = genre_zh.translate_genres(["巨乳", "巨乳", "中出し", "高畫質"])
        self.assertEqual(out, ["巨乳", "中出", "高畫質"])

    def test_merge(self):
        out = genre_zh.merge_genres(["已婚婦女"], ["中出し", "人妻"])
        self.assertEqual(out, ["已婚婦女", "中出"])


class TestMgsParse(unittest.TestCase):
    def test_parse_siro_like_table(self):
        html = """
        <html><body>
        <h1>テストタイトル SIRO-5711</h1>
        <div id="detail_data">
        <table>
        <tr><th>出演：</th><td>しおり 21歳 ファミレスでバイト</td></tr>
        <tr><th>メーカー：</th><td><a href="/x">シロウトTV</a></td></tr>
        <tr><th>収録時間：</th><td>66min</td></tr>
        <tr><th>品番：</th><td>SIRO-5711</td></tr>
        <tr><th>配信開始日：</th><td>2026/07/22</td></tr>
        <tr><th>ジャンル：</th><td>
          <a href="/g1">独占配信</a>
          <a href="/g2">配信専用</a>
          <a href="/g3">素人</a>
          <a href="/g4">フルハイビジョン(FHD)</a>
          <a href="/g5">巨乳</a>
        </td></tr>
        </table>
        <img src="https://image.mgstage.com/images/shirouto/siro/5711/pb_e_siro-5711.jpg">
        <img src="https://image.mgstage.com/images/shirouto/siro/5711/cap_e_0_siro-5711.jpg">
        </div>
        </body></html>
        """
        meta = mgs.parse_metadata(html, "SIRO-5711")
        self.assertEqual(meta["duration"], "66分钟")
        self.assertEqual(meta["releaseDate"], "2026-07-22")
        self.assertIn("独占配信", meta["genres"])
        self.assertIn("素人", meta["genres"])
        self.assertTrue(meta["actresses"])
        self.assertIn("pb_e_siro-5711", meta["cover"])
        self.assertEqual(len(meta["samples"]), 1)
        zh = genre_zh.translate_genres(meta["genres"])
        self.assertIn("DMM獨家", zh)
        self.assertIn("業餘", zh)
        self.assertIn("高畫質", zh)
        self.assertIn("巨乳", zh)


if __name__ == "__main__":
    unittest.main()
