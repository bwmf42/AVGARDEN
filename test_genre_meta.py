#!/usr/bin/env python3
"""Unit tests for genre ZH + MGS metadata parse (no network)."""
import unittest

from src.weekly import dmm, enrich, genre_zh, javdatabase, mgs


class TestGenreZh(unittest.TestCase):
    def test_basic_align_javbus(self):
        self.assertEqual(genre_zh.translate_genre("中出し"), "中出")
        self.assertEqual(genre_zh.translate_genre("独占配信"), "DMM獨家")
        self.assertEqual(genre_zh.translate_genre("フルハイビジョン(FHD)"), "高畫質")
        self.assertEqual(genre_zh.translate_genre("人妻"), "已婚婦女")
        self.assertEqual(genre_zh.translate_genre("人妻・主婦"), "已婚婦女")
        self.assertEqual(genre_zh.translate_genre("単体作品"), "單體作品")
        self.assertEqual(genre_zh.translate_genre("素人"), "業餘")
        self.assertEqual(genre_zh.translate_genre("ハメ撮り"), "第一人稱攝影")
        self.assertEqual(genre_zh.translate_genre("寝取り・寝取られ・NTR"), "NTR")
        self.assertEqual(genre_zh.translate_genre("NTR"), "NTR")
        self.assertEqual(genre_zh.translate_genre("寝取り・寝取られ"), "NTR")
        self.assertEqual(genre_zh.translate_genre("サンプル動画"), "樣片")
        self.assertEqual(genre_zh.translate_genre("アクメ・オーガズム"), "高潮")
        self.assertEqual(genre_zh.translate_genre("バイブ"), "按摩棒")
        self.assertEqual(genre_zh.translate_genre("ゲロ"), "呕吐")
        self.assertEqual(genre_zh.translate_genre("シックスナイン"), "69")
        self.assertEqual(genre_zh.translate_genre("即ハメ"), "即插")

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

    def test_memory_persist(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            old = genre_zh._MEMORY_PATH
            genre_zh._MEMORY_PATH = path
            genre_zh._memory = {}
            genre_zh._memory_loaded = False
            genre_zh._memory_dirty = False
            genre_zh.remember("テストタグXYZ", "測試標籤")
            self.assertTrue(genre_zh.save_memory())
            genre_zh._memory = {}
            genre_zh._memory_loaded = False
            genre_zh.load_memory(force=True)
            self.assertEqual(genre_zh.translate_genre("テストタグXYZ"), "測試標籤")
        finally:
            genre_zh._MEMORY_PATH = old
            genre_zh._memory_loaded = False
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_snap_to_blocked_spelling(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("觸手\n紧缚\n變性者\n超乳\n")
            # force path via env-like override
            genre_zh._blocked_loaded = False
            old_fn = genre_zh._default_blocked_path
            genre_zh._default_blocked_path = lambda: path
            try:
                self.assertEqual(genre_zh.snap_to_blocked("触手"), "觸手")
                self.assertEqual(genre_zh.snap_to_blocked("緊縛"), "紧缚")
                self.assertEqual(genre_zh.translate_genre("触手"), "觸手")
                self.assertEqual(genre_zh.translate_genre("変性者"), "變性者")
                self.assertEqual(genre_zh.translate_genre("爆乳"), "超乳")
            finally:
                genre_zh._default_blocked_path = old_fn
                genre_zh._blocked_loaded = False
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class TestMgsParse(unittest.TestCase):
    def test_normalize_known_amateur_profile_labels(self):
        cases = {
            "きれい 24歳 パチンコ店副店長": "きれい",
            "あむ 21歳 美容クリニック受付": "あむ",
            "かほ 22歳 アパレル販売員": "かほ",
            "みこと 23歳 会社員": "みこと",
            "まな 25歳 エステティシャン": "まな",
            "なぎさ 18歳 大学生": "なぎさ",
            "すい 38歳 空港ラウンジ嬢": "すい",
            "みな 22歳 居酒屋店員": "みな",
            "つむぎ 20歳 ダンスの専門学生": "つむぎ",
            "ゆの 25歳 旅館の仲居": "ゆの",
            "のどかさん 31歳 ヨガインストラクター": "のどかさん",
            "はる 23歳 出版社コミック編集部": "はる",
            "ひなちゃん 21歳 女子大生": "ひなちゃん",
            "サラちゃん 27歳 美容液マルチ": "サラちゃん",
            "サラ 28歳 英会話教室の先生": "サラ",
            "かほ 34歳 料理教室の先生": "かほ",
            "ミズホちゃん 新規 120分コース": "ミズホちゃん",
            "にいな 29歳 丸の内勤務": "にいな",
            "経験人数少なめな敏感キレかわギャル アイちゃん (23歳) 夜のバイト ※就活中": "アイちゃん",
            "小林さん 27歳 バツ2の新婚": "小林さん",
            "あむ 20歳 カラオケ店員": "あむ",
            "なぎさ 20歳 学生": "なぎさ",
            "みな 20歳 大学生兼カードショップ店員": "みな",
            "みより 23歳 カフェ店員": "みより",
            "れあさん 31歳 総務部": "れあさん",
            "あまね 24歳 アパレル店員": "あまね",
            "あかね 26歳 スーパーの惣菜屋さん": "あかね",
            "えみり 22歳 大学生": "えみり",
            "しおり 21歳 ファミレスでバイト": "しおり",
            "舞菜 20歳 理系の大学生": "舞菜",
            "妃莉奈 腋もアナルも綺麗": "妃莉奈",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(mgs.normalize_actress_label(raw), expected)

    def test_normalize_preserves_unrecognized_names(self):
        for name in ("工藤香澄", "MINAMO", "Aika Yumeno"):
            self.assertEqual(mgs.normalize_actress_label(name), name)

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
        self.assertEqual(meta["actresses"], ["しおり"])
        self.assertIn("pb_e_siro-5711", meta["cover"])
        self.assertEqual(len(meta["samples"]), 1)
        zh = genre_zh.translate_genres(meta["genres"])
        self.assertIn("DMM獨家", zh)
        self.assertIn("業餘", zh)
        self.assertIn("高畫質", zh)
        self.assertIn("巨乳", zh)

    def test_generic_mgs_page_is_not_metadata(self):
        html = "<html><body><a href='/product/product_detail/'>nav</a></body></html>"
        self.assertEqual(mgs.parse_metadata(html, "NONE-999"), {})


class TestDmmMetadata(unittest.TestCase):
    def test_parse_classic_product_table(self):
        html = """
        <table>
          <tr><td class="nw">発売日：</td><td>2026/07/23</td></tr>
          <tr><td class="nw">収録時間：</td><td>95分</td></tr>
          <tr><td class="nw">出演者：</td><td><span id="performer"><a>工藤香澄</a></span></td></tr>
          <tr><td class="nw">ジャンル：</td><td><a>熟女</a>&nbsp;<a>人妻・主婦</a>&nbsp;<a>SOD30周年40％オフセール</a></td></tr>
        </table>
        """
        meta = dmm.parse_metadata(html, "FERA-212", "https://example.test", "h_086fera212")
        self.assertEqual(meta["actresses"], ["工藤香澄"])
        self.assertEqual(meta["genres"], ["熟女", "人妻・主婦"])
        self.assertEqual(meta["duration"], "95分钟")
        self.assertEqual(meta["releaseDate"], "2026-07-23")

    def test_parse_digital_amateur_graphql(self):
        payload = {
            "data": {
                "ppvContent": {
                    "id": "peep180",
                    "makerContentId": "PEEP-180",
                    "deliveryStartDate": "2026-04-16T15:00:00Z",
                    "duration": 3267,
                    "amateurActress": {"name": "彩月"},
                    "genres": [
                        {"name": "盗撮・のぞき"},
                        {"name": "巨乳"},
                    ],
                    "packageImage": {
                        "largeUrl": None,
                        "mediumUrl": "https://example.test/peep180jp.jpg",
                    },
                    "sampleImages": [
                        {"number": 2, "largeImageUrl": "https://example.test/jp-002.jpg"},
                        {"number": 1, "largeImageUrl": "https://example.test/jp-001.jpg"},
                    ],
                }
            }
        }
        meta = dmm.parse_digital_metadata(
            payload,
            "PEEP-180",
            "https://video.dmm.co.jp/amateur/content/?id=peep180",
            "peep180",
        )
        self.assertEqual(meta["actresses"], ["彩月"])
        self.assertEqual(meta["duration"], "54分钟")
        self.assertEqual(meta["releaseDate"], "2026-04-17")
        self.assertEqual(meta["genres"], ["盗撮・のぞき", "巨乳"])
        self.assertEqual(meta["samples"], [
            "https://example.test/jp-001.jpg",
            "https://example.test/jp-002.jpg",
        ])

    def test_parse_digital_av_graphql_actresses(self):
        payload = {
            "data": {
                "ppvContent": {
                    "id": "pred00880",
                    "makerContentId": "PRED-880",
                    "duration": 6997,
                    "actresses": [{"name": "音無鈴"}],
                    "amateurActress": None,
                    "genres": [{"name": "中出し"}],
                }
            }
        }
        meta = dmm.parse_digital_metadata(payload, "PRED-880", cid="pred00880")
        self.assertEqual(meta["actresses"], ["音無鈴"])
        self.assertEqual(meta["duration"], "116分钟")

    def test_digital_graphql_rejects_wrong_maker_code(self):
        payload = {
            "data": {
                "ppvContent": {
                    "id": "peep180",
                    "makerContentId": "PEEP-181",
                }
            }
        }
        self.assertIsNone(dmm.parse_digital_metadata(payload, "PEEP-180", cid="peep180"))

    def test_mgs_genres_prevent_dmm_fallback(self):
        original_mgs = mgs.fetch_detail
        original_dmm = dmm.fetch_metadata
        try:
            mgs.fetch_detail = lambda code: {
                "genres": ["巨乳"],
                "actresses": ["工藤香澄"],
                "duration": "95分钟",
            }
            dmm.fetch_metadata = lambda code: self.fail("DMM must not run after MGS genres")
            item = {"id": "FERA-212", "actresses": [], "genres": [], "duration": ""}
            enrich.enrich_item(item, download_images=False)
            self.assertEqual(item["metaSource"], "mgs")
        finally:
            mgs.fetch_detail = original_mgs
            dmm.fetch_metadata = original_dmm

    def test_dmm_fills_only_empty_fields_when_mgs_has_no_genres(self):
        original_mgs = mgs.fetch_detail
        original_dmm = dmm.fetch_metadata
        try:
            mgs.fetch_detail = lambda code: {"genres": [], "actresses": []}
            dmm.fetch_metadata = lambda code: {
                "genres": ["中出し"],
                "actresses": ["工藤香澄"],
                "duration": "95分钟",
            }
            item = {"id": "FERA-212", "actresses": [], "genres": [], "duration": ""}
            enrich.enrich_item(item, download_images=False)
            self.assertEqual(item["actresses"], ["工藤香澄"])
            self.assertEqual(item["genres"], ["中出"])
            self.assertEqual(item["duration"], "95分钟")
            self.assertEqual(item["metaSource"], "dmm")
        finally:
            mgs.fetch_detail = original_mgs
            dmm.fetch_metadata = original_dmm

    def test_javdatabase_is_final_fallback_after_dmm_miss(self):
        original_mgs = mgs.fetch_detail
        original_dmm = dmm.fetch_metadata
        original_candidates = dmm.fetch_digital_metadata_candidates
        original_jdb = javdatabase.fetch_detail
        try:
            mgs.fetch_detail = lambda code: None
            dmm.fetch_metadata = lambda code: None
            dmm.fetch_digital_metadata_candidates = lambda code, cids, page="": None
            javdatabase.fetch_detail = lambda code: {
                "cid": "ebwh00359",
                "page": "https://www.javdatabase.com/movies/ebwh-359/",
                "actresses": ["Marika Sonoda"],
                "genres": ["Athlete", "Big Tits", "Hi-Def"],
                "duration": "150分钟",
                "releaseDate": "2026-07-17",
            }
            item = {"id": "EBWH-359", "actresses": [], "genres": [], "duration": ""}
            enrich.enrich_item(item, download_images=False)
            self.assertEqual(item["actresses"], ["Marika Sonoda"])
            self.assertEqual(item["genres"], ["運動員", "巨乳", "高畫質"])
            self.assertEqual(item["duration"], "150分钟")
            self.assertEqual(item["metaSource"], "javdatabase")
        finally:
            mgs.fetch_detail = original_mgs
            dmm.fetch_metadata = original_dmm
            dmm.fetch_digital_metadata_candidates = original_candidates
            javdatabase.fetch_detail = original_jdb


if __name__ == "__main__":
    unittest.main()
