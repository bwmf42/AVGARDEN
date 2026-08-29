#!/usr/bin/env python3
import json
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

    def test_probe_115_skips_when_unused(self):
        fake = mock.Mock()
        fake.load_config.return_value = {"cookies": "", "enabled": False}
        with mock.patch.dict("sys.modules", {"src.p115_offline": fake}):
            ok, msg = h.probe_115()
        self.assertIsNone(ok)
        self.assertEqual(msg, "未配置")

    def test_code_from_torrent_tags(self):
        t = {"tags": "ABF-367", "name": "foo", "state": "downloading"}
        self.assertEqual(h.code_from_torrent(t), "ABF-367")

    def test_classify_queue_drift_ignores_done_qb_and_drops_processing_ghost(self):
        state = [
            {
                "code": "DLDSS-488",
                "status": "processing",
                "_heal_recovered": True,
                "_post_done": True,
            },
            {"code": "ABF-376", "status": "queued"},
        ]
        drift = h.classify_queue_drift(
            state,
            queue_codes={"ABF-376"},
            qb_codes_active=set(),
            qb_codes_done={"DLDSS-488", "ROYD-331"},
        )
        self.assertEqual(drift["qb_orphan"], [])
        self.assertIn("DLDSS-488", drift["stale_processing"])
        self.assertEqual(drift["orphan_queued"], [])

    def test_classify_queue_drift_recovers_only_active_qb(self):
        drift = h.classify_queue_drift(
            [],
            queue_codes=set(),
            qb_codes_active={"START-587"},
            qb_codes_done={"DLDSS-488"},
        )
        self.assertEqual(drift["qb_orphan"], ["START-587"])
        self.assertEqual(drift["stale_processing"], [])

    def test_heal_queue_sync_removes_processing_ghost(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state_path = os.path.join(tmp.name, "queue_state.json")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(
                [{
                    "code": "DLDSS-488",
                    "status": "processing",
                    "_heal_recovered": True,
                    "_post_done": True,
                }],
                f,
            )
        heal_state = {}
        with mock.patch.object(h, "STATE_PATH", state_path), mock.patch.object(
            h, "report", lambda *_args, **_kwargs: None
        ):
            acted = h.heal_queue_sync(
                heal_state,
                {"stale_processing": ["DLDSS-488"], "qb_active": []},
            )
        self.assertTrue(acted)
        with open(state_path, encoding="utf-8") as f:
            leftover = json.load(f)
        self.assertEqual(leftover, [])

    def test_plwt_fail_is_transient(self):
        self.assertTrue(h.plwt_fail_is_transient("安全门/连不上"))
        self.assertTrue(h.plwt_fail_is_transient("SSL: UNEXPECTED_EOF_WHILE_READING"))
        self.assertTrue(h.plwt_fail_is_transient("HTTPSConnectionPool timeout"))
        self.assertFalse(h.plwt_fail_is_transient("empty list"))
        self.assertFalse(h.plwt_fail_is_transient(""))

    def test_plwt_streak_resets_on_ok(self):
        state = {}
        self.assertEqual(h.update_plwt_streak(state, False), 1)
        self.assertEqual(h.update_plwt_streak(state, False), 2)
        self.assertEqual(h.update_plwt_streak(state, True), 0)
        self.assertEqual(state["plwt_fail_streak"], 0)

    def _probe_diag(self, **overrides):
        diag = {
            "qb_ok": True,
            "translation_ok": True,
            "plwt_ok": True,
            "plwt_msg": "list=30",
            "missing_files": 0,
        }
        diag.update(overrides)
        return diag

    def test_heal_probes_alert_skips_first_transient_plwt(self):
        state = {"plwt_fail_streak": 1}
        reports = []
        logs = []
        with mock.patch.object(h, "report", reports.append), mock.patch.object(h, "log", logs.append):
            acted = h.heal_probes_alert(
                state, self._probe_diag(plwt_ok=False, plwt_msg="安全门/连不上")
            )
        self.assertFalse(acted)
        self.assertEqual(reports, [])
        self.assertTrue(any("plwt probe miss 1/3" in msg for msg in logs))

    def test_heal_probes_alert_reports_after_streak(self):
        state = {"plwt_fail_streak": 3}
        reports = []
        with mock.patch.object(h, "report", reports.append), mock.patch.object(h, "log", lambda *_a, **_k: None):
            acted = h.heal_probes_alert(
                state, self._probe_diag(plwt_ok=False, plwt_msg="安全门/连不上")
            )
        self.assertTrue(acted)
        self.assertEqual(len(reports), 1)
        self.assertIn("连续 3 次未过", reports[0])
        self.assertNotIn("不可达", reports[0])

    def test_heal_probes_alert_reports_empty_list(self):
        state = {"plwt_fail_streak": 1}
        reports = []
        with mock.patch.object(h, "report", reports.append), mock.patch.object(h, "log", lambda *_a, **_k: None):
            acted = h.heal_probes_alert(
                state, self._probe_diag(plwt_ok=False, plwt_msg="empty list")
            )
        self.assertTrue(acted)
        self.assertIn("列表异常", reports[0])

    def test_plwt_health_view_holds_last_good_on_blip(self):
        state = {"plwt_fail_streak": 1, "plwt_last_ok_msg": "list=30"}
        view = h.plwt_health_view({"plwt_ok": False, "plwt_msg": "安全门/连不上"}, state)
        self.assertTrue(view["plwt_ok"])
        self.assertEqual(view["plwt_msg"], "list=30")

    def test_plwt_health_view_surfaces_persistent_fail(self):
        state = {"plwt_fail_streak": 3, "plwt_last_ok_msg": "list=30"}
        view = h.plwt_health_view({"plwt_ok": False, "plwt_msg": "安全门/连不上"}, state)
        self.assertFalse(view["plwt_ok"])
        self.assertEqual(view["plwt_msg"], "安全门/连不上")


if __name__ == "__main__":
    unittest.main()
