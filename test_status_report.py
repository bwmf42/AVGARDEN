#!/usr/bin/env python3
"""Tests for status_report: backup_sqlite, health payload, DS usage."""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from src import status_report as sr


class TestBackupSqlite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "downloaded.db")
        self.bak = os.path.join(self.tmp.name, "backups")
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE MissAV (bvid TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO MissAV (bvid) VALUES ('ABF-1')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_backup_ok_and_quick_check(self):
        r = sr.backup_sqlite(self.db, self.bak, keep=7)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["check_ok"])
        self.assertTrue(r["path"].endswith(".db.gz"))
        self.assertTrue(os.path.exists(r["path"]))
        # gunzip and query
        raw = r["path"][:-3]
        with gzip.open(r["path"], "rb") as f:
            with open(raw, "wb") as out:
                out.write(f.read())
        c = sqlite3.connect(raw)
        row = c.execute("SELECT bvid FROM MissAV").fetchone()
        c.close()
        self.assertEqual(row[0], "ABF-1")

    def test_backup_missing_db(self):
        r = sr.backup_sqlite(os.path.join(self.tmp.name, "nope.db"), self.bak)
        self.assertFalse(r["ok"])
        self.assertIn("missing", r["msg"])

    def test_backup_corrupt_quick_check_fails(self):
        # write non-sqlite file as "db"
        bad = os.path.join(self.tmp.name, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"not a sqlite database!!!!!")
        r = sr.backup_sqlite(bad, self.bak)
        # sqlite may refuse connect or backup may fail
        self.assertFalse(r["ok"])


class TestHealthPayload(unittest.TestCase):
    def test_green_yellow_red(self):
        green = sr.build_health_from_diag(
            {
                "qb_ok": True,
                "qb_msg": "ok",
                "deepseek_ok": True,
                "deepseek_msg": "ok",
                "plwt_ok": True,
                "plwt_msg": "ok",
                "missing_files": 0,
                "scrape_hours": None,
            }
        )
        self.assertEqual(green["overall"], "green")
        self.assertFalse(green["checks"]["version"]["behind"])

        red = sr.build_health_from_diag(
            {
                "qb_ok": False,
                "qb_msg": "down",
                "deepseek_ok": True,
                "deepseek_msg": "ok",
                "plwt_ok": True,
                "plwt_msg": "ok",
                "missing_files": 0,
            }
        )
        self.assertEqual(red["overall"], "red")

        yellow = sr.build_health_from_diag(
            {
                "qb_ok": True,
                "qb_msg": "ok",
                "deepseek_ok": True,
                "deepseek_msg": "ok",
                "plwt_ok": True,
                "plwt_msg": "ok",
                "missing_files": 3,
            }
        )
        self.assertEqual(yellow["overall"], "yellow")

        p115_yellow = sr.build_health_from_diag(
            {
                "qb_ok": True,
                "qb_msg": "ok",
                "deepseek_ok": True,
                "deepseek_msg": "ok",
                "plwt_ok": True,
                "plwt_msg": "ok",
                "p115_ok": False,
                "p115_msg": "登录失效，请重新复制 Cookie",
                "missing_files": 0,
            }
        )
        self.assertEqual(p115_yellow["overall"], "yellow")
        self.assertFalse(p115_yellow["checks"]["p115"]["ok"])
        self.assertIn("登录失效", p115_yellow["checks"]["p115"]["msg"])

        unused = sr.build_health_from_diag(
            {
                "qb_ok": True,
                "qb_msg": "ok",
                "deepseek_ok": True,
                "deepseek_msg": "ok",
                "plwt_ok": True,
                "plwt_msg": "ok",
                "p115_ok": None,
                "p115_msg": "未配置",
                "missing_files": 0,
            }
        )
        self.assertNotIn("p115", unused["checks"])

    def test_missing_tree_hash_is_not_behind(self):
        with mock.patch.object(sr.os, "environ", {"AVGARDEN_EXPECTED_TREE_HASH": ""}):
            info = sr.version_status()
        self.assertFalse(info["behind"])
        self.assertTrue(info["ok"])


class TestDeepseekUsage(unittest.TestCase):
    def test_limit_alert(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, "ds_usage.json")
            with mock.patch.object(sr, "DS_USAGE_PATH", path), mock.patch.object(
                sr, "DEEPSEEK_DAILY_ALERT_LIMIT", 2
            ):
                d1 = sr.record_deepseek_usage(1)
                self.assertEqual(d1["count"], 1)
                self.assertFalse(d1.get("alerted"))
                d2 = sr.record_deepseek_usage(1)
                self.assertEqual(d2["count"], 2)
                self.assertTrue(d2.get("alerted"))
                with open(path, encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["count"], 2)
        finally:
            tmp.cleanup()

    def test_concurrent_increments_are_not_lost(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "ds_usage.json")
            with mock.patch.object(sr, "DS_USAGE_PATH", path), mock.patch.object(
                sr, "DEEPSEEK_DAILY_ALERT_LIMIT", 1000
            ):
                threads = [threading.Thread(target=sr.record_deepseek_usage) for _ in range(20)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["count"], 20)


class TestAtomicWrite(unittest.TestCase):
    def test_atomic(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, "h.json")
            sr.atomic_write_json(path, {"a": 1})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["a"], 1)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
