#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from src.weekly import actresses as a


class TestActresses(unittest.TestCase):
    def test_clean_dash(self):
        self.assertEqual(a.clean_actresses(["----", "小島みこ", ""]), ["小島みこ"])
        self.assertEqual(a.clean_actresses(["---", "--", "-"]), [])

    def test_extract_huntc_499(self):
        title = (
            "HUNTC-499 無自覚に男を勃起させる罪な女の気まぐれ手コキ。"
            "その日の気分でボクの勃起したチ○ポを抜いたり、小島みこ 森あやみ"
        )
        body, names = a.extract_trailing_actresses(title)
        self.assertEqual(names, ["小島みこ", "森あやみ"])
        self.assertIn("手コキ", body)

    def test_extract_huntc_616(self):
        title = (
            "HUNTC-616 『えっウソ！クラスで勃起するのボクだけ？いやいや世界でボクだけ！？』"
            "もなみ鈴 宮西ひかる 綾瀬こころ"
        )
        body, names = a.extract_trailing_actresses(title)
        self.assertEqual(names, ["もなみ鈴", "宮西ひかる", "綾瀬こころ"])

    def test_extract_jyma(self):
        title = "JYMA-111 ワケありAV出演 世間知らずの豊満熟女を肉オナホにしてやりました。 藤沢麗央"
        body, names = a.extract_trailing_actresses(title)
        self.assertEqual(names, ["藤沢麗央"])

    def test_no_false_positive_4h(self):
        title = "ID-020 Aカップの微乳パイパン美少女映像 4時間"
        body, names = a.extract_trailing_actresses(title)
        self.assertEqual(names, [])

    def test_reject_title_tail_as_actress(self):
        # HJMO-732 / NHDTC-22701 style plot fragments
        self.assertFalse(a.is_valid_actress_name("快楽に屈さず連続フ"))
        self.assertFalse(a.is_valid_actress_name("嫌イキ巨尻ムスメ"))
        self.assertFalse(a.is_valid_actress_name("甘サドプレイ特化"))
        self.assertFalse(a.is_valid_actress_name("▼すべて表示する"))
        self.assertFalse(a.is_valid_actress_name("メガ潮吹きファン感謝祭"))
        self.assertEqual(a.clean_actresses(["快楽に屈さず連続フ", "小島みこ"]), ["小島みこ"])

        title = (
            "HJMO-732 清純人妻限定！固定吸引耐え抜きノーハンドフェラ選手権！"
            "快楽に屈さず連続フェラ"
        )
        _, names = a.extract_trailing_actresses(title)
        self.assertEqual(names, [])

        title2 = (
            "NHDTC-22701 中に出してもいいから止まってください！！！"
            "嫌イキ巨尻ムスメ"
        )
        _, names2 = a.extract_trailing_actresses(title2)
        self.assertEqual(names2, [])

    def test_ensure_and_finalize_title_zh(self):
        item = {
            "id": "HUNTC-499",
            "title": (
                "HUNTC-499 無自覚に男を勃起させる罪な女の気まぐれ手コキ。"
                "その日の気分でボクの勃起したチ○ポを抜いたり、小島みこ 森あやみ"
            ),
            "titleZh": "HUNTC-499：无意中让男人勃起的罪过女人随心所欲手交。——小岛美子、森彩美",
            "actresses": ["----"],
        }
        self.assertTrue(a.ensure_actresses(item))
        self.assertEqual(item["actresses"], ["小島みこ", "森あやみ"])
        self.assertTrue(a.finalize_title_zh(item))
        # titleZh must NOT carry actress names
        self.assertNotIn("小島みこ", item["titleZh"])
        self.assertNotIn("森あやみ", item["titleZh"])
        self.assertNotIn("小岛美子", item["titleZh"])
        self.assertIn("手交", item["titleZh"])

    def test_finalize_strips_actress_keeps_body(self):
        item = {
            "id": "JYMA-111",
            "title": "JYMA-111 ワケありAV出演 藤沢麗央",
            "titleZh": "JYMA-111 有缘AV出演 把不谙世事的丰满熟女当成肉自慰套 藤沢麗央",
            "actresses": ["藤沢麗央"],
        }
        a.finalize_title_zh(item)
        self.assertIn("丰满", item["titleZh"])
        self.assertNotIn("藤沢麗央", item["titleZh"])

    def test_finalize_keeps_short_body_after_code(self):
        item = {
            "id": "GVH-861",
            "title": "GVH-861 禁断介護 西元めいさ",
            "titleZh": "GVH-861: 禁忌护理",
            "actresses": ["西元めいさ"],
        }
        self.assertFalse(a.finalize_title_zh(item))
        self.assertEqual(item["titleZh"], "GVH-861: 禁忌护理")
        self.assertTrue(a.item_has_valid_title_zh(item))

    def test_title_for_translate_keeps_closing_punctuation(self):
        body, names = a.title_for_translate(
            "ID-061 愛しのデリヘル嬢 61 全身性感帯のドスケベむっちり関西娘編 俺の大好きな川口○奈と内○理央を足してなんかで割ったような超ナイスバディがヨガりながら言いよった！「あかん！あかん！お股の痙攣が止まらんやん！」 及川莉央",
            ["及川莉央"],
        )
        self.assertEqual(names, ["及川莉央"])
        self.assertTrue(body.endswith("！」"))

    def test_title_zh_validity_rejects_truncated_results(self):
        source = "SAN-478Z とても長い日本語の作品タイトルで翻訳結果に十分な本文が必要です"
        self.assertFalse(a.is_valid_title_zh("", source, "SAN-478Z"))
        self.assertFalse(a.is_valid_title_zh("SAN-478Z", source, "SAN-478Z"))
        self.assertFalse(a.is_valid_title_zh("让", source, "SAN-478Z"))
        self.assertFalse(
            a.is_valid_title_zh(
                "I cannot assist with this request, as it involves sexual content with a minor.",
                source,
                "SAN-478Z",
            )
        )
        self.assertFalse(
            a.is_valid_title_zh(
                "抱歉，我不能协助翻译这个标题。",
                source,
                "SAN-478Z",
            )
        )
        self.assertFalse(
            a.is_valid_title_zh(
                "GOJI-106: 「请把我当",
                "GOJI-106 「私を本当の恋人だと思ってください」長い日本語タイトル",
                "GOJI-106",
            )
        )

    def test_title_zh_validity_keeps_normal_short_titles(self):
        self.assertTrue(a.is_valid_title_zh("标题", "Title", "KEEP-001"))
        self.assertTrue(a.is_valid_title_zh("人妻交换", "夫婦交換", "KEEP-002"))
        self.assertTrue(
            a.is_valid_title_zh(
                "HUNTC-499：无意中让男人勃起的女人随心所欲手交",
                "HUNTC-499 無自覚に男を勃起させる女の気まぐれ手コキ",
                "HUNTC-499",
            )
        )

    def test_title_translation_requires_real_source_body(self):
        self.assertFalse(a.item_has_translatable_title({"id": "NLD-032", "title": "NLD-032"}))
        self.assertFalse(a.item_has_translatable_title({"id": "DEBZ-015", "title": "DEBZ-015 なお", "actresses": ["なお"]}))
        self.assertFalse(a.item_has_translatable_title({"id": "SIMM-907", "title": "SIMM-907 あや"}))
        self.assertTrue(
            a.item_has_translatable_title(
                {"id": "GVH-861", "title": "GVH-861 禁断介護 西元めいさ", "actresses": ["西元めいさ"]}
            )
        )

    def test_fold_and_snap_blocked(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("川上ゆう（\n森あやみ\n千葉優花\n")
            a._blocked_loaded = False
            old = a._default_blocked_actresses_path
            a._default_blocked_actresses_path = lambda: path
            try:
                self.assertTrue(a.is_blocked_actress("川上ゆう"))
                self.assertTrue(a.is_blocked_actress("川上ゆう（"))
                self.assertEqual(a.snap_to_blocked_actress("川上ゆう"), "川上ゆう（")
                self.assertTrue(a.is_blocked_actress("森あやみ"))
                # 繁简 fold
                self.assertTrue(a.is_blocked_actress("千葉优花") or a.is_blocked_actress("千葉優花"))
                self.assertEqual(a.fold_actress_key("千葉優花"), a.fold_actress_key("千葉优花"))
            finally:
                a._default_blocked_actresses_path = old
                a._blocked_loaded = False
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_rename_alias_uses_current_japanese_spelling(self):
        self.assertEqual(a.preferred_actress_spelling("河北彩花"), "河北彩伽")
        self.assertEqual(a.actress_alias_group("河北彩花"), ["河北彩伽", "河北彩花"])
        self.assertEqual(a.clean_actresses(["河北彩花", "河北彩伽"]), ["河北彩伽"])


if __name__ == "__main__":
    unittest.main()
