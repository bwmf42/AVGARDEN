#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from src.weekly import actresses as a


class TestActresses(unittest.TestCase):
    def test_profiles_are_not_actor_identities(self):
        for value in ['京香 大学生モデル', '真央 19さい', '美優 19才', '専業主婦', '結城りえ(24)', '個人撮影', 'カップル']:
            with self.subTest(value=value):
                item = {'actresses': [value], 'title': '作品タイトル 京香'}
                self.assertTrue(a.ensure_actresses(item))
                self.assertEqual(item['actresses'], [])
                self.assertEqual(item['performerNotes'], [value])
                self.assertFalse(a.ensure_actresses(item))

    def test_new_metadata_repairs_old_nicknames_without_losing_formal_credit(self):
        item = {'actresses': ['しおり', '鈴村あいり']}
        meta = {'actresses': ['鈴村あいり'], 'performerNotes': ['しおり 21歳 ファミレスでバイト']}
        self.assertTrue(a.normalize_performer_fields(item, meta))
        self.assertEqual(item['actresses'], ['鈴村あいり'])
        self.assertEqual(item['performerNotes'], meta['performerNotes'])
        self.assertFalse(a.normalize_performer_fields(item, meta))
        confirmed = {'actresses': ['彩月'], 'performerNotes': ['彩月']}
        a.normalize_performer_fields(confirmed, {'actresses': ['彩月']})
        self.assertEqual(confirmed, {'actresses': ['彩月'], 'performerNotes': []})

    def test_title_only_given_name_needs_explicit_credit(self):
        item = {'title': 'CHUC-193 テストタイトル まり', 'actresses': ['----']}
        self.assertTrue(a.ensure_actresses(item))
        self.assertEqual(item['actresses'], [])
        self.assertEqual(item['performerNotes'], ['まり'])
        official = {'title': '作品タイトル', 'actresses': ['めぐり']}
        a.ensure_actresses(official)
        self.assertEqual(official['actresses'], ['めぐり'])

    def test_explicit_uncredited_source_and_paired_profiles(self):
        uncredited = {'actresses': ['まり'], 'metaSource': 'dmm'}
        a.normalize_performer_fields(uncredited, {'actresses': ['----']})
        self.assertEqual(uncredited['actresses'], [])
        self.assertEqual(uncredited['performerNotes'], ['まり'])
        pair = {'actresses': ['Nちゃん＆Yちゃん'], 'metaSource': 'mgs'}
        a.normalize_performer_fields(pair, {'performerNotes': ['Nちゃん(20)＆Yちゃん(20)']})
        self.assertEqual(pair['actresses'], [])
        self.assertEqual(pair['performerNotes'], ['Nちゃん(20)＆Yちゃん(20)'])
        formal = {'actresses': ['めぐり'], 'metaSource': 'javdatabase'}
        a.normalize_performer_fields(formal, {'actresses': ['----']})
        self.assertEqual(formal['actresses'], ['めぐり'])

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

    def test_title_zh_keeps_japanese_series_and_actress_names(self):
        titles = [
            "259LUXU-1881 与爆乳超淫荡保姆的油性爱 草食系无法满足的色情爆乳 ラグジュTV 1874",
            "DSOD-046: “下跪是犯规啊…” 因怕被讨厌而无法拒绝的美少女J系",
            "ABF-387：毒舌女服务员",
            "HSODA-069 魔镜NTR美容院 隔壁纤美美乳女友被人睡走，我却抵不住巨乳姐姐的高超技巧",
            "MIDA-696 全裸羞耻调教打工 被变态店长要求在深夜班次中不穿胸罩 葵いぶき",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(a.is_valid_title_zh(title))

    def test_title_zh_rejects_refusals_and_non_chinese_results(self):
        source = "【爆乳どスケベ保母さんとオイルSEX】…"
        for title in [
            "申し訳ありませんが、成人向け動画のタイトル翻訳はお手伝いできません。",
            "I can't help with this request.",
            "I appreciate you testing this, but…",
            "抱歉，我无法协助翻译此类内容。",
            "すみません、このリクエストにはお応えできません。",
            "これはテストです、ありがとうございます",
            "259LUXU-1881",
        ]:
            with self.subTest(title=title):
                self.assertFalse(a.is_valid_title_zh(title, source, "259LUXU-1881"))

    def test_title_refusal_prefixes_ignore_case_and_punctuation_width(self):
        prefixes = [
            "申し訳", "すみません", "恐れ入り", "お手伝いできません",
            "対応できません", "翻訳できません", "お断り", "ご要望にはお応え",
            "I appreciate", "I apologize", "Sorry", "I'm sorry", "I'm not able",
            "I won't", "As an AI", "很抱歉", "抱歉", "无法为您", "我无法", "我不能",
        ]
        # Enough Han text keeps the ratio check from masking missing keywords.
        tail = "这是模型返回的解释内容而非所需的中文作品译名" * 4
        for prefix in prefixes + ["Ｉ＇Ｍ ＳＯＲＲＹ", "i’m not able", "i WoN’t"]:
            for punctuation in [",", "，", ":", "：", ".", "。"]:
                with self.subTest(prefix=prefix, punctuation=punctuation):
                    self.assertFalse(a.is_valid_title_zh(f"ABF-387：{prefix}{punctuation}{tail}"))

    def test_title_refusal_matching_stays_at_start(self):
        for phrase in ["我无法", "抱歉", "Sorry", "作为AI无法帮助"]:
            with self.subTest(phrase=phrase):
                self.assertTrue(a.is_valid_title_zh(f"女服务员说{phrase}，却仍无法拒绝的故事"))

    def test_title_zh_kana_ratio_boundary(self):
        han = "中文作品标题保留日本系列名"  # 13 Han characters.
        cases = [
            ("あいうえおか", True),   # 6/19 < 0.35
            ("あいうえおかき", True),  # 7/20 == 0.35
            ("あいうえおかきく", False),  # 8/21 > 0.35
            ("アイウエオカキク", False),
            ("ｱｲｳｴｵｶｷｸ", False),
        ]
        for kana, expected in cases:
            for prefix in ["", "259LUXU-1881："]:
                with self.subTest(kana=kana, prefix=prefix):
                    # Latin text, numbers and punctuation cannot dilute the ratio.
                    title = f"{prefix}{han}{kana} TV 1874 NTR・，。"
                    self.assertEqual(a.is_valid_title_zh(title), expected)

    def test_translate_title_once_uses_fallback_after_japanese_refusal(self):
        from unittest import mock
        import weekly_updater

        refusal = "申し訳ありませんが、成人向け動画のタイトル翻訳はお手伝いできません。"
        translated = "与爆乳超淫荡保姆的油性爱 草食系无法满足的色情爆乳"
        providers = [
            ("relay", "https://relay.example/v1", "fake-relay", "relay-model"),
            ("deepseek", "https://deepseek.example/v1", "fake-deepseek", "fallback-model"),
        ]

        def complete(base, api_key, model, messages, temperature=0.3):
            return refusal if base == providers[0][1] else translated

        with mock.patch.object(weekly_updater, "translation_provider_candidates", return_value=providers), \
             mock.patch.object(weekly_updater, "_chat_completion", side_effect=complete) as chat, \
             mock.patch("src.status_report.record_deepseek_usage") as usage:
            result = weekly_updater.translate_title_once(
                "259LUXU-1881", "【爆乳どスケベ保母さんとオイルSEX】…", actresses=[],
            )
        self.assertEqual(result, translated)
        self.assertEqual(chat.call_args_list[0].args[0], providers[0][1])
        self.assertEqual(chat.call_args_list[-1].args[:3], providers[1][1:])
        self.assertEqual(sum(call.args[0] == providers[1][1] for call in chat.call_args_list), 1)
        usage.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
