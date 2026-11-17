import json
import os
import sys
import tempfile
import types
import unittest
from dataclasses import asdict
from unittest import mock

logger = mock.Mock()
loguru_module = types.ModuleType("loguru")
loguru_module.logger = logger
requests_stub = mock.Mock()
requests_stub.exceptions.RequestException = Exception
curl_module = types.ModuleType("curl_cffi")
curl_module.requests = requests_stub
pil_module = types.ModuleType("PIL")
pil_module.Image = mock.Mock()
comm_module = types.ModuleType("src.comm")
comm_module.scraperDomain = "www.javbus.com"

sys.modules.setdefault("loguru", loguru_module)
sys.modules.setdefault("curl_cffi", curl_module)
sys.modules.setdefault("PIL", pil_module)
sys.modules.setdefault("src.comm", comm_module)

from src.scraper import AVMetadata, Sracper, headers

for module_name in ("src.comm", "loguru", "curl_cffi", "PIL"):
    if sys.modules.get(module_name) in (comm_module, loguru_module, curl_module, pil_module):
        del sys.modules[module_name]


class ScraperMetadataTest(unittest.TestCase):
    def test_title_translation_only_calls_deepseek_with_legacy_relay_env(self):
        import weekly_updater

        response = mock.Mock()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": "这是完整的中文故事标题"}}]}).encode()
        with mock.patch.dict(os.environ, {"TRANSLATE_API_BASE": "https://relay.example/v1",
                                          "TRANSLATE_API_KEY": "fake-relay-key"}), \
             mock.patch.object(weekly_updater, "DS_API_KEY", "fake-deepseek-key"), \
             mock.patch("src.status_report.record_deepseek_usage"), \
             mock.patch("translate_settings.open_translation_request", return_value=response) as request:
            metadata = AVMetadata(avid="ABF-123", title="日本語の物語タイトル")
            Sracper("/tmp").translate_title(metadata)
        self.assertEqual(metadata.title_zh, "这是完整的中文故事标题")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0].full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer fake-deepseek-key")

    def test_optional_fields_may_be_missing(self):
        html = """
        <html><head><title>ABF-123 Sample title - JavBus</title></head>
        <body><a class="bigImage" href="/cover.jpg"><img src="/thumb.jpg"></a></body></html>
        """
        metadata = Sracper("/tmp")._extract(html)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.avid, "ABF-123")
        self.assertEqual(metadata.title, "ABF-123 Sample title")
        self.assertEqual(metadata.cover, "https://www.javbus.com/cover.jpg")
        self.assertEqual(metadata.description, "")
        self.assertEqual(metadata.keywords, [])
        self.assertEqual(metadata.release_date, "")
        self.assertEqual(metadata.duration, "")

    def test_required_fields_still_reject_invalid_page(self):
        self.assertIsNone(Sracper("/tmp")._extract("<title>ABF-123 - JavBus</title>"))

    def test_list_fields_are_per_instance_and_serialized(self):
        first = AVMetadata(keywords=["A"], fanarts=["one.jpg"])
        second = AVMetadata()
        first.keywords.append("B")
        self.assertEqual(second.keywords, [])
        self.assertEqual(asdict(first)["fanarts"], ["one.jpg"])
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "metadata.json")
            self.assertTrue(first.to_json(path))
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["keywords"], ["A", "B"])

    def test_referer_does_not_mutate_global_headers(self):
        before = dict(headers)
        response = mock.Mock()
        response.text = "ok"
        response.raise_for_status.return_value = None
        with mock.patch("src.scraper.requests.get", return_value=response) as get:
            self.assertEqual(Sracper("/tmp")._fetch_html("https://example.test", "https://ref.test"), "ok")
        self.assertEqual(headers, before)
        self.assertEqual(get.call_args.kwargs["headers"]["Referer"], "https://ref.test")

    def test_nfo_without_artwork_does_not_raise(self):
        with tempfile.TemporaryDirectory() as root:
            metadata = AVMetadata(avid="ABF-123", title="Title")
            scraper = Sracper(root)
            os.makedirs(os.path.join(root, "ABF-123"))
            self.assertTrue(scraper.genNFO(metadata))
            self.assertTrue(os.path.exists(os.path.join(root, "ABF-123", "ABF-123.nfo")))

    def test_nfo_with_fanart_but_no_cover_does_not_raise(self):
        with tempfile.TemporaryDirectory() as root:
            metadata = AVMetadata(avid="ABF-123", title="Title", fanarts=["sample.jpg"])
            scraper = Sracper(root)
            os.makedirs(os.path.join(root, "ABF-123"))
            self.assertTrue(scraper.genNFO(metadata))


if __name__ == "__main__":
    unittest.main()
