import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


# Allow offline tests on hosts without curl_cffi, without leaking a global stub.
optional_stubs = {}
try:
    import curl_cffi
except ModuleNotFoundError:
    curl_stub = types.ModuleType("curl_cffi")
    curl_stub.requests = mock.Mock()
    curl_stub.requests.exceptions.RequestException = Exception
    optional_stubs["curl_cffi"] = curl_stub

# src.comm normally reads runtime config and initializes disk logging.
comm_stub = types.ModuleType("src.comm")
comm_stub.scraperDomain = "www.javbus.com"
comm_stub.myproxy = None
import_stubs = {**optional_stubs, "src.comm": comm_stub}
previous_modules = {name: sys.modules.get(name) for name in import_stubs}
sys.modules.update(import_stubs)
try:
    from tools.maintenance import translate_media_titles as titles
    from src.scraper import AVMetadata, Sracper
finally:
    for name, previous in previous_modules.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


MIHD = "MIHD-004 ハメドリ 配信限定 MOODYZ専属のナチュラルSEXを解禁 石原希望"
MIDA = "MIDA-696 全裸羞耻调教打工 被变态店长要求…… 葵いぶき"


class TitleDetectionTest(unittest.TestCase):
    def test_title_shapes(self):
        cases = [
            (MIHD, "MIHD-004", True),
            (MIDA, "MIDA-696", False),
            ("ABF-123 はじめてのデート", "", True),
            ("ABF-123 初次约会的故事", "", False),
            ("ABF-123 中文译名里有の字也已完成翻译 葵いぶき", "", False),
            ("ABF-123 MOODYZ はじめてのデート 石原希望", "", True),
            ("ABF-123 MOODYZ 中文译名 葵いぶき", "", False),
            ("ABF-123", "", False),
            ("", "", False),
            ("ABF-123 ドキドキする初体験 葵いぶき", "", True),
            ("ABF-123 中文标题 ジュリア・アン", "", False),
            ("ABF-123 中文标题 尾崎エリカ", "", False),
            ("ABF-123 中文のの", "", False),  # exactly 50% Han
        ]
        for title, avid, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(titles.title_needs_translation(title, avid), expected)

    def test_chinese_title_with_japanese_actor_is_not_retranslated(self):
        self.assertFalse(titles.title_needs_translation(MIDA, "MIDA-696"))


class MissingNfoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.dict(sys.modules, {"src.comm": comm_stub}))
        self.fetch = self.patches.enter_context(mock.patch.object(Sracper, "fetch_metadata"))
        self.metadata = AVMetadata(
            avid="ABF-123", title="ABF-123 はじめてのデート 葵いぶき",
            release_date="2026-10-01", duration="120分鐘", actress={"葵いぶき": "https://invalid/avatar.jpg"},
            cover="https://invalid/poster.jpg", fanarts=["https://invalid/fanart.jpg"],
            keywords=["ABF-123"], description="must not be written",
        )
        self.fetch.return_value = self.metadata
        self.translate = self.patches.enter_context(mock.patch.object(titles, "translate_title_once", return_value="初次约会的故事"))

    def folder(self, name="ABF-123"):
        folder = self.root / name
        folder.mkdir()
        (folder / "movie.MP4").write_bytes(b"original video")
        return folder

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def main(self, *args):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["translate_media_titles", "--path", str(self.root), *args]), contextlib.redirect_stdout(output):
            titles.main()
        return output.getvalue()

    def test_dry_run_is_offline_read_only_and_lists_candidates(self):
        self.folder()
        self.folder("ABF-124")
        for name in ("thumb", "__weekly__", "_private"):
            self.folder(name)
        (self.root / "ABF-125").mkdir()  # no video
        before = self.snapshot()
        with mock.patch.object(titles, "write_xml") as write, mock.patch.object(titles.time, "sleep") as sleep:
            output = self.main("--create-missing")
        self.fetch.assert_not_called()
        self.translate.assert_not_called()
        write.assert_not_called()
        sleep.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertIn("would_create ABF-123", output)
        self.assertIn("would_create ABF-124", output)
        self.assertIn("folders=2", output)
        self.assertIn("would_create=2", output)

    def test_apply_creates_only_allowed_nfo_fields_and_no_images(self):
        folder = self.folder()
        with mock.patch.object(titles.time, "sleep") as sleep, mock.patch.object(titles.random, "uniform", return_value=3) as delay:
            output = self.main("--create-missing", "--apply", "--limit", "1")
        tree = ET.parse(folder / "ABF-123.nfo").getroot()
        self.assertEqual(tree.tag, "movie")
        self.assertEqual({node.tag for node in tree}, {"title", "originaltitle", "generator", "premiered", "releasedate", "runtime", "actor"})
        self.assertEqual(tree.findtext("title"), "ABF-123 初次约会的故事")
        self.assertEqual(tree.findtext("originaltitle"), self.metadata.title)
        self.assertEqual(tree.findtext("runtime"), "120")
        self.assertEqual(tree.findtext("premiered"), "2026-10-01")
        self.assertEqual(tree.findtext("releasedate"), "2026-10-01")
        self.assertEqual(tree.findtext("actor/name"), "葵いぶき")
        self.assertEqual([node.tag for node in tree.find("actor")], ["name"])
        for tag in ("art", "poster", "fanart", "thumb", "genre", "plot"):
            self.assertIsNone(tree.find(".//" + tag))
        self.assertEqual({p.name for p in folder.iterdir()}, {"movie.MP4", "ABF-123.nfo"})
        self.assertEqual((folder / "movie.MP4").read_bytes(), b"original video")
        self.fetch.assert_called_once_with("ABF-123")
        self.translate.assert_called_once_with("ABF-123", self.metadata.title, actresses=[])
        delay.assert_called_once_with(3.0, 6.0)
        sleep.assert_called_once_with(3)
        self.assertIn("created=1", output)

    def test_page_fetch_creation_marks_generator_after_originaltitle(self):
        folder = self.folder()
        self.assertEqual(titles.process_missing_folder(folder, apply=True)[0], "created")
        root = ET.parse(folder / "ABF-123.nfo").getroot()
        self.assertEqual([node.tag for node in root],
                         ["title", "originaltitle", "generator", "premiered", "releasedate", "runtime", "actor"])
        self.assertEqual(root.findtext("generator"), "avgarden-title-only/1")

    def test_existing_nfo_rewrite_does_not_add_generator(self):
        folder = self.folder()
        nfo = folder / "MIHD-004.nfo"
        root = ET.Element("movie")
        ET.SubElement(root, "title").text = MIHD
        ET.ElementTree(root).write(nfo, encoding="utf-8")
        self.assertEqual(titles.process_file(nfo, apply=True)[0], "updated")
        saved = ET.parse(nfo).getroot()
        self.assertEqual(saved.findtext("title"), "MIHD-004 初次约会的故事")
        self.assertIsNone(saved.find("generator"))

    def test_any_existing_nfo_is_skipped_including_nested_hidden_and_uppercase(self):
        for index, name in enumerate(("old.nfo", "nested/old.nfo", "._ABF-123.nfo", "nested/._old.NFO", "ABF-123.nfo")):
            folder = self.folder(f"ABF-{123 + index}")
            nfo = folder / name
            nfo.parent.mkdir(exist_ok=True)
            nfo.write_bytes(b"existing nfo")
            before = self.snapshot()
            self.assertEqual(titles.process_missing_folder(folder, apply=True)[0], "skip")
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(titles.iter_missing_folders(self.root)), [])
        self.fetch.assert_not_called()
        self.translate.assert_not_called()

    def test_failed_inputs_leave_no_partial_files(self):
        folder = self.folder()
        for metadata, translation, status in (
            (None, "中文标题", "no_metadata"),
            (AVMetadata(avid="ABF-123"), "中文标题", "no_metadata"),
            (AVMetadata(avid="WRONG-123", title="日文"), "中文标题", "no_metadata"),
            (self.metadata, "", "unchanged"),
            (self.metadata, "English only", "unchanged"),
        ):
            with self.subTest(metadata=metadata, translation=translation):
                self.fetch.return_value = metadata
                self.translate.return_value = translation
                before = self.snapshot()
                self.assertEqual(titles.process_missing_folder(folder, apply=True)[0], status)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(list(folder.iterdir()), [folder / "movie.MP4"])
        invalid = self.folder("unrecognized")
        self.fetch.reset_mock()
        self.assertEqual(titles.process_missing_folder(invalid, apply=True)[0], "invalid_avid")
        self.fetch.assert_not_called()

    def test_failures_are_counted_and_delay_applies_after_failure(self):
        self.folder()
        self.folder("ABF-124")
        self.folder("unrecognized")
        self.fetch.side_effect = [None, AVMetadata(avid="ABF-124", title="日文原题")]
        self.translate.side_effect = RuntimeError("translation failed")
        with mock.patch.object(titles.time, "sleep") as sleep, mock.patch.object(titles.random, "uniform", return_value=4) as delay:
            output = self.main("--create-missing", "--apply", "--min-delay", "4", "--max-delay", "5")
        self.assertEqual(delay.call_args_list, [mock.call(4, 5), mock.call(4, 5)])
        self.assertEqual(sleep.call_args_list, [mock.call(4), mock.call(4)])
        for count in ("failed=1", "no_metadata=1", "invalid_avid=1", "created=0"):
            self.assertIn(count, output)
        self.assertFalse(list(self.root.rglob("*.nfo")))
        self.assertFalse(list(self.root.rglob("*.tmp")))

    def test_limit_and_normalization(self):
        self.folder("ABF-123-C")
        self.folder("ABF-124")
        self.translate.return_value = "  中文\n 标题 - JavBus "
        with mock.patch.object(titles.time, "sleep"):
            output = self.main("--create-missing", "--apply", "--limit", "1")
        self.assertEqual(ET.parse(self.root / "ABF-123-C/ABF-123.nfo").findtext("title"), "ABF-123 中文 标题")
        self.assertIn("folders=1", output)
        self.fetch.assert_called_once_with("ABF-123")

    def test_nfo_appearing_during_fetch_is_preserved(self):
        folder = self.folder()
        def fetch(_avid):
            (folder / "._external.nfo").write_bytes(b"external")
            return self.metadata
        self.fetch.side_effect = fetch
        self.assertEqual(titles.process_missing_folder(folder, apply=True)[0], "skip")
        self.assertEqual((folder / "._external.nfo").read_bytes(), b"external")
        self.assertEqual({p.name for p in folder.iterdir()}, {"movie.MP4", "._external.nfo"})

    def test_atomic_write_failure_cleans_temporary_file(self):
        folder = self.folder()
        with mock.patch.object(titles.os, "replace", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                titles.process_missing_folder(folder, apply=True)
        self.assertEqual(list(folder.iterdir()), [folder / "movie.MP4"])

    def test_existing_title_mode_preserves_original_and_other_fields(self):
        folder = self.folder()
        nfo = folder / "MIHD-004.nfo"
        tree = ET.Element("movie")
        ET.SubElement(tree, "title").text = MIHD
        ET.SubElement(tree, "genre").text = "existing genre"
        ET.ElementTree(tree).write(nfo, encoding="utf-8")
        before = nfo.read_bytes()
        self.assertEqual(titles.process_file(nfo)[0], "would_update")
        self.assertEqual(nfo.read_bytes(), before)
        self.translate.assert_not_called()
        self.assertEqual(titles.process_file(nfo, apply=True)[0], "updated")
        saved = ET.parse(nfo)
        self.assertEqual(saved.findtext("originaltitle"), MIHD)
        self.assertEqual(saved.findtext("genre"), "existing genre")
        self.assertEqual(saved.findtext("title"), "MIHD-004 初次约会的故事")


class MetadataOnlyTest(unittest.TestCase):
    def test_fetch_only_gets_page_and_extracts_without_writing(self):
        with tempfile.TemporaryDirectory() as root:
            scraper = Sracper(root)
            html = '<title>ABF-123 はじめてのデート - JavBus</title><a class="bigImage" href="/cover.jpg"><img src="/thumb.jpg"></a>'
            with mock.patch.object(scraper, "_fetch_html", return_value=html) as fetch, \
                 mock.patch.object(scraper, "downloadIMG") as images, \
                 mock.patch.object(scraper, "genNFO") as nfo, \
                 mock.patch.object(scraper, "translate_title") as translate, \
                 mock.patch("builtins.open", side_effect=AssertionError("unexpected file write")), \
                 mock.patch.object(Path, "open", side_effect=AssertionError("unexpected file write")), \
                 mock.patch.object(os, "replace", side_effect=AssertionError("unexpected file write")):
                metadata = scraper.fetch_metadata("abf-123")
            self.assertEqual(metadata.avid, "ABF-123")
            self.assertEqual(metadata.title_zh, "")
            fetch.assert_called_once_with("https://www.javbus.com/ABF-123", referer="self.domain")
            images.assert_not_called()
            nfo.assert_not_called()
            translate.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_missing_or_invalid_page_returns_none(self):
        scraper = Sracper("/unused")
        for html in (None, "invalid page"):
            with self.subTest(html=html), mock.patch.object(scraper, "_fetch_html", return_value=html):
                self.assertIsNone(scraper.fetch_metadata("ABF-123"))

    def test_existing_scrape_pipeline_still_translates_downloads_and_generates_nfo(self):
        scraper = Sracper("/unused")
        metadata = AVMetadata(avid="ABF-123", title="original")
        with mock.patch.object(scraper, "_fetch_html", return_value="html"), \
             mock.patch.object(scraper, "_extract", return_value=metadata), \
             mock.patch.object(scraper, "translate_title") as translate, \
             mock.patch.object(scraper, "downloadIMG", return_value=True) as images, \
             mock.patch.object(scraper, "genNFO") as nfo:
            self.assertIs(scraper._scrape("ABF-123"), metadata)
        translate.assert_called_once_with(metadata)
        images.assert_called_once_with(metadata)
        nfo.assert_called_once_with(metadata)


class TitlesJsonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.fetch = self.patches.enter_context(mock.patch.object(Sracper, "fetch_metadata"))
        self.scraper = self.patches.enter_context(mock.patch("src.scraper.Sracper"))
        self.translate = self.patches.enter_context(
            mock.patch.object(titles, "translate_title_once", return_value="初次约会的故事"))
        self.sleep = self.patches.enter_context(mock.patch.object(titles.time, "sleep"))
        self.delay = self.patches.enter_context(mock.patch.object(titles.random, "uniform", return_value=3))
        self.addCleanup(self.fetch.assert_not_called)
        self.addCleanup(self.scraper.assert_not_called)
        self.jp_title = "はじめてのデート 葵いぶき"
        self.json_path = self.root / "titles.json"

    def folder(self, name="ABF-123"):
        folder = self.root / name
        folder.mkdir()
        (folder / "movie.MP4").write_bytes(b"original video")
        return folder

    def write_titles(self, data):
        import json
        self.json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def main(self, *args):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        argv = ["translate_media_titles", "--path", str(self.root), "--titles-json", str(self.json_path), *args]
        with mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            result = titles.main()
        return result, self.stdout.getvalue()

    def test_japanese_title_creates_exactly_two_fields_without_page_fetch(self):
        folder = self.folder()
        self.write_titles({"abf-123": self.jp_title})
        _, output = self.main("--create-missing", "--apply")
        root = ET.parse(folder / "ABF-123.nfo").getroot()
        self.assertEqual(root.tag, "movie")
        self.assertEqual([node.tag for node in root.iter()], ["movie", "title", "originaltitle", "generator"])
        self.assertEqual(root.findtext("title"), "ABF-123 初次约会的故事")
        self.assertEqual(root.findtext("originaltitle"), self.jp_title)
        self.assertEqual({p.name for p in folder.iterdir()}, {"movie.MP4", "ABF-123.nfo"})
        self.assertEqual((folder / "movie.MP4").read_bytes(), b"original video")
        self.translate.assert_called_once_with("ABF-123", self.jp_title, actresses=[])
        self.sleep.assert_not_called()  # first and only network call
        self.assertIn("created=1", output)

    def test_chinese_title_is_used_verbatim_without_translation_or_originaltitle(self):
        folder = self.folder()
        chinese_title = MIDA.replace("MIDA-696", "ABF-123")
        self.write_titles({"ABF-123": chinese_title})
        _, output = self.main("--create-missing", "--apply")
        root = ET.parse(folder / "ABF-123.nfo").getroot()
        self.assertEqual([node.tag for node in root], ["title", "generator"])
        self.assertEqual(root.findtext("title"), chinese_title)
        self.translate.assert_not_called()
        self.sleep.assert_not_called()
        self.delay.assert_not_called()
        self.assertIn("created=1", output)

    def test_json_creation_marks_generator_with_and_without_translation(self):
        for code, title, tags in (
            ("ABF-123", self.jp_title, ["title", "originaltitle", "generator"]),
            ("ABF-124", "中文标题", ["title", "generator"]),
        ):
            with self.subTest(code=code):
                folder = self.folder(code)
                self.assertEqual(titles.process_missing_folder(
                    folder, apply=True, titles_by_avid={code: title})[0], "created")
                root = ET.parse(folder / f"{code}.nfo").getroot()
                self.assertEqual([node.tag for node in root], tags)
                self.assertEqual(root.findtext("generator"), "avgarden-title-only/1")

    def test_missing_or_empty_title_is_counted_without_network_or_writes(self):
        self.folder()
        for data in ({}, {"ABF-124": self.jp_title}, {"ABF-123": "  "}):
            with self.subTest(data=data):
                self.write_titles(data)
                before = self.snapshot()
                _, output = self.main("--create-missing", "--apply")
                self.assertIn("no_title ABF-123: ABF-123", output)
                self.assertIn("no_title=1", output)
                self.assertEqual(self.snapshot(), before)
        self.translate.assert_not_called()
        self.sleep.assert_not_called()

    def test_dry_run_reports_all_three_statuses_and_is_offline_read_only(self):
        for code in ("ABF-123", "ABF-124", "ABF-125"):
            self.folder(code)
        self.write_titles({"ABF-123": self.jp_title, "abf-124": "ABF-124 中文标题"})
        before = self.snapshot()
        with mock.patch.object(titles, "write_xml") as write:
            _, output = self.main("--create-missing")
        for status in ("would_create ABF-123", "would_create_no_translate ABF-124", "no_title ABF-125",
                       "would_create=1", "would_create_no_translate=1", "no_title=1"):
            self.assertIn(status, output)
        write.assert_not_called()
        self.translate.assert_not_called()
        self.sleep.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_folder_suffixes_and_key_case_use_existing_code_cleaning(self):
        self.write_titles({"abf-123": self.jp_title})
        for name in ("abf-123-c", "ABF-123-UC", "ABF-123-U", "ABF-123-中文字幕"):
            with self.subTest(name=name):
                folder = self.folder(name)
                self.main("--create-missing", "--apply")
                self.assertEqual(ET.parse(folder / "ABF-123.nfo").findtext("title"), "ABF-123 初次约会的故事")
        self.assertEqual(self.translate.call_count, 4)

    def test_any_existing_nfo_is_preserved_and_not_a_candidate(self):
        self.write_titles({"ABF-123": self.jp_title})
        for index, name in enumerate(("old.nfo", "nested/old.nfo", "._old.nfo", "nested/._old.NFO", "OLD.NFO")):
            folder = self.folder(f"ABF-{123 + index}")
            nfo = folder / name
            nfo.parent.mkdir(exist_ok=True)
            nfo.write_bytes(b"existing nfo")
            before = self.snapshot()
            self.assertEqual(titles.process_missing_folder(
                folder, apply=True, titles_by_avid={"ABF-123": self.jp_title})[0], "skip")
            self.assertEqual(self.snapshot(), before)
        _, output = self.main("--create-missing", "--apply")
        self.assertIn("folders=0", output)
        self.translate.assert_not_called()

    def test_invalid_translation_leaves_no_nfo_or_temp_files(self):
        folder = self.folder()
        self.write_titles({"ABF-123": self.jp_title})
        for translated in ("", "English only", "カタカナ"):
            with self.subTest(translated=translated):
                self.translate.return_value = translated
                before = self.snapshot()
                _, output = self.main("--create-missing", "--apply")
                self.assertIn("unchanged=1", output)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(list(folder.iterdir()), [folder / "movie.MP4"])

    def test_translation_exception_is_unchanged_and_next_call_is_throttled(self):
        self.folder()
        self.folder("ABF-124")
        self.write_titles({"ABF-123": self.jp_title, "ABF-124": self.jp_title})
        self.translate.side_effect = [RuntimeError("translation failed"), "中文标题"]
        _, output = self.main("--create-missing", "--apply")
        self.assertIn("unchanged=1", output)
        self.assertIn("created=1", output)
        self.assertFalse((self.root / "ABF-123/ABF-123.nfo").exists())
        self.assertFalse(list(self.root.rglob("*.tmp")))
        self.delay.assert_called_once_with(3.0, 6.0)
        self.sleep.assert_called_once_with(3)

    def test_only_translation_calls_are_throttled_and_limit_is_respected(self):
        for code in ("ABF-123", "ABF-124", "ABF-125", "ABF-126", "ABF-127"):
            self.folder(code)
        self.write_titles({"ABF-123": self.jp_title, "ABF-124": "中文标题",
                           "ABF-126": self.jp_title, "ABF-127": self.jp_title})
        _, output = self.main("--create-missing", "--apply", "--limit", "4", "--min-delay", "4", "--max-delay", "5")
        self.assertIn("folders=4", output)
        self.assertIn("created=3", output)
        self.assertIn("no_title=1", output)
        self.assertEqual(self.translate.call_count, 2)
        self.delay.assert_called_once_with(4, 5)
        self.sleep.assert_called_once_with(3)
        self.assertFalse((self.root / "ABF-127/ABF-127.nfo").exists())

    def test_invalid_json_is_rejected_before_any_write(self):
        self.folder()
        for raw, error in (("{invalid", "cannot read --titles-json"), ("[]", "JSON object"),
                           ('"title"', "JSON object"),
                           ('{"ABF-123": "はじめて", "ABF-999": 3}', "values must all be strings"),
                           ('{"ABF-123": null}', "values must all be strings"),
                           ('{"ABF-123": {}}', "values must all be strings")):
            with self.subTest(raw=raw):
                self.json_path.write_text(raw, encoding="utf-8")
                before = self.snapshot()
                with self.assertRaises(SystemExit) as raised:
                    self.main("--create-missing", "--apply")
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(error, self.stderr.getvalue())
                self.assertEqual(self.snapshot(), before)
        self.translate.assert_not_called()

    def test_unreadable_or_invalid_encoding_json_is_rejected(self):
        self.folder()
        for data in (None, b"\xff"):
            with self.subTest(data=data):
                if data is not None:
                    self.json_path.write_bytes(data)
                before = self.snapshot()
                with self.assertRaises(SystemExit) as raised:
                    self.main("--create-missing", "--apply")
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("cannot read --titles-json", self.stderr.getvalue())
                self.assertEqual(self.snapshot(), before)
        self.translate.assert_not_called()

    def test_titles_json_requires_create_missing(self):
        self.folder()
        self.write_titles({"ABF-123": self.jp_title})
        before = self.snapshot()
        with self.assertRaises(SystemExit) as raised:
            self.main("--apply")
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--titles-json requires --create-missing", self.stderr.getvalue())
        self.assertEqual(self.snapshot(), before)
        self.translate.assert_not_called()

    def test_nfo_appearing_during_translation_is_preserved(self):
        folder = self.folder()
        self.write_titles({"ABF-123": self.jp_title})
        def translate(*_args, **_kwargs):
            (folder / "._external.NFO").write_bytes(b"external")
            return "中文标题"
        self.translate.side_effect = translate
        _, output = self.main("--create-missing", "--apply")
        self.assertIn("skip=1", output)
        self.assertEqual((folder / "._external.NFO").read_bytes(), b"external")
        self.assertEqual({p.name for p in folder.iterdir()}, {"movie.MP4", "._external.NFO"})

    def test_atomic_write_failure_cleans_temporary_file(self):
        folder = self.folder()
        self.write_titles({"ABF-123": self.jp_title})
        with mock.patch.object(titles.os, "replace", side_effect=OSError("write failed")):
            _, output = self.main("--create-missing", "--apply")
        self.assertIn("failed=1", output)
        self.assertEqual(list(folder.iterdir()), [folder / "movie.MP4"])


    def test_title_key_candidates_preserve_prefix_and_cleaner_fallback(self):
        cases = [
            ("  259luxu-1881  ", ["259LUXU-1881", "LUXU-1881"]),
            ("390JAC-244", ["390JAC-244", "JAC-244"]),
            ("300MIUM-1363", ["300MIUM-1363", "MIUM-1363"]),
            ("MIHD-004", ["MIHD-004"]),
            ("MIHD-004-U", ["MIHD-004"]),
            ("MIHD-004-C", ["MIHD-004"]),
            ("MIHD-004-UC", ["MIHD-004"]),
            ("MIHD-004-UCC", ["MIHD-004"]),
            ("MIHD-004-CH", ["MIHD-004"]),
            ("259LUXU-1881-UC", ["259LUXU-1881", "LUXU-1881"]),
            ("ABF-123-中文字幕", ["ABF-123"]),
            ("source ABF-123", ["ABF-123"]),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(titles.title_key_candidates(name), expected)

    def test_numeric_prefix_json_keys_create_matching_nfo_and_single_title_prefix(self):
        codes = ["259LUXU-1881", "259LUXU-1889", "259LUXU-1894",
                 "300MIUM-1363", "300MIUM-1389", "300MIUM-1395",
                 "300MIUM-1416", "300MIUM-1423", "390JAC-244"]
        for code in codes:
            with self.subTest(code=code):
                folder = self.folder(code)
                self.write_titles({code.lower(): f"{code} {self.jp_title}"})
                before = self.snapshot()
                self.translate.reset_mock()
                _, output = self.main("--create-missing")
                self.assertIn(f"would_create {code}: {code}", output)
                self.assertEqual(self.snapshot(), before)
                self.translate.assert_not_called()
                _, output = self.main("--create-missing", "--apply")
                self.assertIn("created=1", output)
                root = ET.parse(folder / f"{code}.nfo").getroot()
                title = root.findtext("title")
                self.assertEqual(title, f"{code} 初次约会的故事")
                self.assertEqual(title.count(code), 1)
                self.assertEqual(root.findtext("originaltitle"), f"{code} {self.jp_title}")
                self.assertEqual([node.tag for node in root], ["title", "originaltitle", "generator"])
                self.assertEqual({p.name for p in folder.iterdir()}, {"movie.MP4", f"{code}.nfo"})
                self.translate.assert_called_once_with(code, f"{code} {self.jp_title}", actresses=[])

    def test_json_version_suffixes_use_base_code_for_title_and_filename(self):
        for suffix in ("U", "C", "UC", "UCC", "CH"):
            for code in ("MIHD-004", "259LUXU-1881"):
                with self.subTest(suffix=suffix, code=code):
                    folder = self.folder(f"{code}-{suffix}")
                    status, _ = titles.process_missing_folder(
                        folder, apply=True, titles_by_avid={code: self.jp_title})
                    self.assertEqual(status, "created")
                    self.assertEqual(ET.parse(folder / f"{code}.nfo").findtext("title"),
                                     f"{code} 初次约会的故事")
                    self.assertEqual({p.name for p in folder.iterdir()}, {"movie.MP4", f"{code}.nfo"})

    def test_missing_json_keys_and_invalid_folders_remain_read_only(self):
        self.write_titles({"259LUXU-1881": self.jp_title,
                           "艾薇": self.jp_title, "你在录视频": self.jp_title})
        cases = [("PEEP-180-U", "no_title"), ("YUJ-069", "no_title"),
                 ("艾薇", "invalid_avid"), ("你在录视频", "invalid_avid")]
        for name, expected_status in cases:
            with self.subTest(name=name):
                folder = self.folder(name)
                before = self.snapshot()
                for args in (("--create-missing",), ("--create-missing", "--apply")):
                    _, output = self.main(*args)
                    self.assertIn(f"{expected_status} {name}: {name}", output)
                    self.assertEqual(self.snapshot(), before)
                self.assertFalse(list(folder.rglob("*.nfo")))
        self.assertFalse(list((self.root / "艾薇").rglob("*.nfo")))
        self.translate.assert_not_called()
        self.sleep.assert_not_called()

    def test_numeric_prefix_key_takes_priority_and_cleaned_key_remains_fallback(self):
        cases = [
            ("259LUXU-1881", {"LUXU-1881": "中文回退标题", "259LUXU-1881": self.jp_title},
             "259LUXU-1881", "259LUXU-1881 初次约会的故事"),
            ("259LUXU-1881-U", {"LUXU-1881": self.jp_title},
             "LUXU-1881", "LUXU-1881 初次约会的故事"),
            ("259LUXU-1881-C", {"259LUXU-1881": "259LUXU-1881 中文标题"},
             "259LUXU-1881", "259LUXU-1881 中文标题"),
        ]
        for name, data, expected_code, expected_title in cases:
            with self.subTest(name=name):
                folder = self.folder(name)
                status, _ = titles.process_missing_folder(folder, apply=True, titles_by_avid=data)
                self.assertEqual(status, "created")
                self.assertEqual(ET.parse(folder / f"{expected_code}.nfo").findtext("title"), expected_title)
                self.assertEqual({p.name for p in folder.iterdir()}, {"movie.MP4", f"{expected_code}.nfo"})

    def test_blank_preferred_key_does_not_select_different_fallback_title(self):
        folder = self.folder("259LUXU-1881")
        before = self.snapshot()
        result = titles.process_missing_folder(
            folder, apply=True, titles_by_avid={"259LUXU-1881": " ", "LUXU-1881": self.jp_title})
        self.assertEqual(result, ("no_title", "259LUXU-1881"))
        self.assertEqual(self.snapshot(), before)
        self.translate.assert_not_called()


class TranslatedTitlePrefixTest(unittest.TestCase):
    def test_prefixed_translations(self):
        cases = [
            ("ABF-387", "ABF-387: 毒舌女服务员", "毒舌女服务员"),
            ("HSODA-069", "HSODA-069 魔镜NTR按摩院 …", "魔镜NTR按摩院 …"),
            ("ABF-387", "ABF-387：毒舌女服务员", "毒舌女服务员"),
            ("ABF-387", "ABF-387-毒舌女服务员", "毒舌女服务员"),
            ("ABF-387", "ABF-387 - 毒舌女服务员", "毒舌女服务员"),
            ("ABF-387", "  abf-387:  毒舌女服务员  ", "毒舌女服务员"),
            ("259LUXU-1881", "LUXU-1881: 中文标题", "中文标题"),
            ("259LUXU-1881", "259LUXU-1881: 中文标题", "中文标题"),
            ("259LUXU-1881", "luxu-1881：中文标题", "中文标题"),
            ("ABF-387", "ABF-387: 中文标题提及 HSODA-069 和 ABF-387",
             "中文标题提及 HSODA-069 和 ABF-387"),
            ("ABF-387", "ABF-387: ABF-387: 中文标题", "ABF-387: 中文标题"),
            ("ABF-387", "ABF-387:", ""),
            ("ABF-387", "ABF-387：  ", ""),
            ("ABF-387", "ABF-387 - ", ""),
            ("ABF-387", "ABF-387", ""),
            ("ABF-387", "ABF-387: English only", ""),
            ("ABF-387", "ABF-387: カタカナ", ""),
        ]
        for avid, translated, body in cases:
            for preserve in (False, True):
                with self.subTest(avid=avid, translated=translated, preserve=preserve):
                    with mock.patch.object(titles, "translate_title_once", return_value=translated) as translate:
                        expected_code = avid if preserve else titles.clean_avid(avid)
                        expected = f"{expected_code} {body}" if body else ""
                        self.assertEqual(titles.translate_title(avid, "日文原题", preserve), expected)
                    translate.assert_called_once_with(avid, "日文原题", actresses=[])

    def test_unmatched_prefix_and_unprefixed_translations_are_unchanged(self):
        for translated in ("中文标题", "  中文\n 标题 - JavBus ",
                           "ABF-3870: 中文标题", "HSODA-069 中文标题"):
            with self.subTest(translated=translated):
                with mock.patch.object(titles, "translate_title_once", return_value=translated):
                    self.assertEqual(titles.translate_title("ABF-387", "日文原题"),
                                     f"ABF-387 {titles.normalize_title(translated)}")

    def test_nfo_writes_use_deduplicated_title_and_reject_invalid_body(self):
        for create in (False, True):
            for translated, expected_body in (("ABF-387: 毒舌女服务员", "毒舌女服务员"),
                                              ("ABF-387：", ""), ("ABF-387: English only", "")):
                with self.subTest(create=create, translated=translated), tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp) / "ABF-387"
                    folder.mkdir()
                    path = folder / "ABF-387.nfo"
                    original_title = "ABF-387 はじめてのデート"
                    if not create:
                        path.write_text(f"<movie><title>{original_title}</title></movie>", encoding="utf-8")
                    before = path.read_bytes() if path.exists() else None
                    with mock.patch.object(titles, "translate_title_once", return_value=translated):
                        if create:
                            status, _ = titles.process_missing_folder(
                                folder, apply=True, titles_by_avid={"ABF-387": original_title})
                        else:
                            status, _ = titles.process_file(path, apply=True)
                    if expected_body:
                        self.assertEqual(status, "created" if create else "updated")
                        self.assertEqual(ET.parse(path).findtext("title"), f"ABF-387 {expected_body}")
                        self.assertEqual(ET.parse(path).findtext("originaltitle"), original_title)
                    else:
                        self.assertEqual(status, "unchanged")
                        self.assertEqual(path.read_bytes() if path.exists() else None, before)
                    self.assertEqual({p.name for p in folder.iterdir()}, {path.name} if path.exists() else set())


class WriteXmlPermissionsTest(unittest.TestCase):
    def test_new_and_existing_nfo_permissions(self):
        for create, existing_mode, expected_mode in (
            (True, None, 0o644),
            (False, None, 0o644),
            (False, 0o600, 0o600),
            (False, 0o664, 0o664),
        ):
            with self.subTest(create=create, existing_mode=existing_mode), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "ABF-123.nfo"
                if existing_mode is not None:
                    path.write_text("<movie><title>old</title></movie>", encoding="utf-8")
                    os.chmod(path, existing_mode)
                root = ET.Element("movie")
                ET.SubElement(root, "title").text = "中文标题"
                self.assertTrue(titles.write_xml(path, root, create=create))
                self.assertEqual(os.stat(path).st_mode & 0o777, expected_mode)
                self.assertEqual(ET.parse(path).findtext("title"), "中文标题")
                self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_create_recheck_preserves_appearing_nfo_and_cleans_temporary_file(self):
        for name in ("ABF-123.nfo", "nested/old.NFO"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                path = folder / "ABF-123.nfo"
                existing = folder / name
                original_has_nfo = titles.has_nfo_file

                def nfo_appears(directory):
                    self.assertEqual(len(list(folder.glob("*.tmp"))), 1)
                    existing.parent.mkdir(exist_ok=True)
                    existing.write_bytes(b"existing nfo")
                    os.chmod(existing, 0o600)
                    return original_has_nfo(directory)

                with mock.patch.object(titles, "has_nfo_file", side_effect=nfo_appears) as recheck:
                    self.assertFalse(titles.write_xml(path, ET.Element("movie"), create=True))
                recheck.assert_called_once_with(folder)
                self.assertEqual(existing.read_bytes(), b"existing nfo")
                self.assertEqual(os.stat(existing).st_mode & 0o777, 0o600)
                self.assertEqual([p for p in folder.rglob("*") if p.is_file()], [existing])


if __name__ == "__main__":
    unittest.main()
