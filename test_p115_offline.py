#!/usr/bin/env python3
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from src import p115_offline as p115


class TestP115ProbeCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg_path = os.path.join(self.tmp.name, "p115_config.json")
        self.cookie_path = os.path.join(self.tmp.name, "115-cookies.txt")
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            f.write("UID=abc; CID=def; SEID=ghi\n")
        self.stack = mock.patch.multiple(
            p115,
            CONFIG_PATH=self.cfg_path,
            COOKIES_PATH=self.cookie_path,
        )
        self.stack.start()
        self.addCleanup(self.stack.stop)

    def _write_store(self, **kwargs):
        store = {
            "enabled": True,
            "save_path": "/艾薇",
            "verified": True,
            "verified_at": time.time(),
            "last_error": "",
            "last_msg": "cached ok",
            "has_cookies": True,
        }
        store.update(kwargs)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(store, f)

    def test_probe_cached_reuses_ttl_without_network(self):
        self._write_store()
        with mock.patch.object(p115, "test_connection") as probe:
            ok, msg = p115.probe_cached(ttl=120)
        self.assertTrue(ok)
        self.assertEqual(msg, "cached ok")
        probe.assert_not_called()

    def test_probe_cached_force_hits_network(self):
        self._write_store()
        with mock.patch.object(p115, "test_connection", return_value=(False, "登录失效")) as probe:
            ok, msg = p115.probe_cached(force=True)
        self.assertFalse(ok)
        self.assertEqual(msg, "登录失效")
        probe.assert_called_once()

    def test_public_config_refresh_marks_expired_unavailable(self):
        self._write_store(verified=True, verified_at=1)

        def expire():
            p115.set_verified(False, "登录失效")
            return False, "登录失效"

        with mock.patch.object(p115, "test_connection", side_effect=expire):
            pub = p115.public_config(refresh=True)
        self.assertFalse(pub["available"])
        self.assertFalse(pub["verified"])
        self.assertIn("登录失效", pub["message"])

    def test_auth_failure_invalidates_verified(self):
        self._write_store()
        p115._note_auth_failure({"state": False, "errno": 99, "error": "请先登录"})
        cfg = p115.load_config()
        self.assertFalse(cfg["verified"])
        self.assertIn("登录", cfg["last_error"])


if __name__ == "__main__":
    unittest.main()
