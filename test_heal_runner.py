#!/usr/bin/env python3
import os
import tempfile
import unittest
from unittest import mock

import heal_runner as h


class TestHealRunner(unittest.TestCase):
    def test_translation_probe_uses_relay_when_configured(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"pong"}}]}'

        with mock.patch.object(h, "TRANSLATE_API_BASE", "https://relay.example/v1"), \
             mock.patch.object(h, "TRANSLATE_API_KEY", "relay-key"), \
             mock.patch.object(h, "TRANSLATE_MODEL", "gpt-5.4"), \
             mock.patch.object(h.urllib.request, "urlopen", return_value=Response()) as urlopen:
            ok, msg = h.probe_translation()
        self.assertTrue(ok)
        self.assertEqual(msg, "GPT 中继 · model=gpt-5.4")
        self.assertIn("relay.example/v1/chat/completions", urlopen.call_args.args[0].full_url)

    def test_count_titlezh_gaps(self):
        items = [
            {"title": "source title", "titleZh": ""},
            {"title": "b", "titleZh": "中文"},
            {"title": "", "titleZh": ""},
            {"title": "another title"},
            {
                "id": "SAN-478Z",
                "title": "SAN-478Z とても長い日本語の作品タイトルで翻訳結果に十分な本文が必要です",
                "titleZh": "让",
            },
        ]
        self.assertEqual(h.count_titlezh_gaps(items), 3)

    def test_cooldown(self):
        state = {}
        self.assertTrue(h.cooldown_ok(state, "x"))
        h.mark_cooldown(state, "x")
        # just marked: not ok
        old = h.HEAL_COOLDOWN_M
        try:
            h.HEAL_COOLDOWN_M = 60
            self.assertFalse(h.cooldown_ok(state, "x"))
            state["cooldown"]["x"] = 0
            self.assertTrue(h.cooldown_ok(state, "x"))
        finally:
            h.HEAL_COOLDOWN_M = old

    def test_code_from_torrent_tags(self):
        t = {"tags": "ABF-367", "name": "foo", "state": "downloading"}
        self.assertEqual(h.code_from_torrent(t), "ABF-367")


if __name__ == "__main__":
    unittest.main()
