#!/usr/bin/env python3
import os
import tempfile
import unittest
from unittest import mock

import heal_runner as h


class TestHealRunner(unittest.TestCase):
    def test_count_titlezh_gaps(self):
        items = [
            {"title": "a", "titleZh": ""},
            {"title": "b", "titleZh": "中文"},
            {"title": "", "titleZh": ""},
            {"title": "c"},
        ]
        self.assertEqual(h.count_titlezh_gaps(items), 2)

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
