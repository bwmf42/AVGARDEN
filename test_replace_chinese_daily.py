"""Offline regression tests for the library replacement scheduler and scan."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import date, datetime
from unittest import mock

import launcher
import replace_chinese as rc
import download_source
from qb_task_guard import ACTIVE_QB_STATES, DONE_QB_STATES
from src.weekly import chinese_forum as forum


class ReplacementScanTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {"CHINESE_FORUM_BACKFILL_SINCE": ""}))
        self.mocks = {}
        replacements = {
            "BACKFILL": False, "DRY_RUN": False, "SAVE_PATH": "/fixture",
            "DAILY_PAGES": 2, "BACKFILL_MAX_PAGES": 0,
        }
        for key, value in replacements.items():
            self.stack.enter_context(mock.patch.object(rc, key, value))
        for key in ("merge_completed_chinese", "scan_library", "qb_has_cn_avid",
                    "avid_exists_in_system", "pause_superseded_tasks", "qb_add_magnet",
                    "save_pending", "load_pending", "update_weekly_magnet",
                    "update_weekly_magnet_if_unwatched", "_refill_weekly_gaps", "log_write", "log"):
            self.mocks[key] = self.stack.enter_context(mock.patch.object(rc, key))
        self.stack.enter_context(mock.patch.object(rc.time, "sleep"))
        self.client = mock.Mock(request_failed=False)
        self.client.ensure_safe.return_value = True
        self.factory = self.stack.enter_context(mock.patch.object(forum, "ForumClient", return_value=self.client))
        self.listing = self.stack.enter_context(mock.patch.object(forum, "get_list_until"))
        self.magnets = self.stack.enter_context(mock.patch.object(forum, "fetch_magnets_for_targets"))
        self.lib = dict(missing={"SNOS-279": {"target_dir": "SNOS-279-original"}},
                        earliest=date(2020, 1, 1), existing_cn=0, total=1, no_nfo_date=0)
        self.mocks["scan_library"].return_value = self.lib
        self.listing.return_value = [{"id": "SNOS-279"}, {"id": "OTHER-123"}, {"id": "SNOS-279"}]
        self.magnets.return_value = {"SNOS-279": {"magnet": "magnet:?xt=urn:btih:" + "a" * 40}}
        self.mocks["qb_has_cn_avid"].return_value = False
        self.mocks["avid_exists_in_system"].return_value = (False, None, "")
        self.mocks["load_pending"].return_value = {}
        self.mocks["qb_add_magnet"].return_value = ("chinese", {"index": 0})
        self.mocks["pause_superseded_tasks"].return_value = ["original"]
        self.opener = mock.Mock()
        self.opener.open.return_value.read.return_value = b"[]"
        self.stack.enter_context(mock.patch.object(rc, "qb_login", return_value=self.opener))

    def test_daily_order_and_pause_path(self):
        calls = mock.Mock()
        calls.attach_mock(self.mocks["merge_completed_chinese"], "merge")
        calls.attach_mock(self.mocks["scan_library"], "scan")
        calls.attach_mock(self.listing, "listing")
        calls.attach_mock(self.magnets, "threads")
        calls.attach_mock(self.mocks["pause_superseded_tasks"], "pause")
        calls.attach_mock(self.mocks["qb_add_magnet"], "add")
        self.assertEqual(rc.main(daily=True), 0)
        self.assertEqual([x[0] for x in calls.mock_calls], ["merge", "scan", "listing", "threads", "pause", "add"])
        self.listing.assert_called_once_with(stop_date=None, max_pages=2, client=self.client)
        self.factory.assert_called_once_with(fid="103", coordinated_requests=True)
        self.magnets.assert_called_once_with([{"id": "SNOS-279"}], {"SNOS-279"}, client=self.client)
        pending = self.mocks["save_pending"].call_args.args[0]
        self.assertEqual(pending["chinese"]["superseded_hashes"], ["original"])
        summary = self.mocks["log_write"].call_args.args
        self.assertEqual(summary[0], "ReplaceCN")
        self.assertIn("hits=1 added=1 skip=0", summary[1])

    def test_merge_before_empty_library_or_failed_gate(self):
        for empty in (True, False):
            with self.subTest(empty=empty):
                self.lib["missing"] = {} if empty else {"SNOS-279": {"target_dir": "SNOS-279"}}
                self.client.ensure_safe.return_value = False
                self.assertEqual(rc.main(), 0 if empty else 1)
        self.assertEqual(self.mocks["merge_completed_chinese"].call_count, 2)
        self.listing.assert_not_called()

    def test_since_overrides_old_or_missing_nfo_date(self):
        for earliest in (date(2020, 1, 1), None):
            with self.subTest(earliest=earliest), mock.patch.object(rc, "BACKFILL", True), \
                 mock.patch.dict(os.environ, {"CHINESE_FORUM_BACKFILL_SINCE": "2026-08-13"}):
                self.lib["earliest"] = earliest
                self.assertEqual(rc.main(), 0)
                self.assertEqual(self.listing.call_args.kwargs["stop_date"], "2026-08-13")

    def test_backfill_without_since_keeps_nfo_fallback(self):
        with mock.patch.object(rc, "BACKFILL", True):
            self.assertEqual(rc.main(), 0)
        self.assertEqual(self.listing.call_args.kwargs["stop_date"], "2020-01-01")

    def test_invalid_since_is_explicit_and_has_no_actions(self):
        for value in ("2026-8-13", "2026-02-30", "nonsense", "2026-08-13junk"):
            with self.subTest(value=value), mock.patch.object(rc, "BACKFILL", True), \
                 mock.patch.dict(os.environ, {"CHINESE_FORUM_BACKFILL_SINCE": value}):
                with self.assertRaisesRegex(ValueError, "CHINESE_FORUM_BACKFILL_SINCE"):
                    rc.main()
        self.mocks["merge_completed_chinese"].assert_not_called()
        self.listing.assert_not_called()

    def test_since_requires_backfill(self):
        with mock.patch.dict(os.environ, {"CHINESE_FORUM_BACKFILL_SINCE": "2026-08-13"}):
            with self.assertRaisesRegex(ValueError, "requires"):
                rc.main()

    def test_daily_ignores_one_time_mode_environment(self):
        with mock.patch.object(rc, "BACKFILL", True), mock.patch.object(rc, "DRY_RUN", True), \
             mock.patch.dict(os.environ, {"CHINESE_FORUM_BACKFILL_SINCE": "bad"}):
            self.assertEqual(rc.main(daily=True), 0)
        self.mocks["merge_completed_chinese"].assert_called_once()
        self.assertIsNone(self.listing.call_args.kwargs["stop_date"])

    def test_dry_run_outputs_targets_and_counts_without_mutations(self):
        for exists in (False, True):
            with self.subTest(exists=exists), mock.patch.object(rc, "BACKFILL", True), mock.patch.object(rc, "DRY_RUN", True):
                self.mocks["avid_exists_in_system"].return_value = (exists, "queue", "queued")
                self.assertEqual(rc.main(), 0)
        output = "\n".join(c.args[0] for c in self.mocks["log"].call_args_list)
        self.assertIn("SNOS-279: target=/fixture/SNOS-279-original magnet=magnet:?xt=urn:btih:", output)
        self.assertIn("hits=1 added=1", output)
        self.assertIn("hits=1 added=0 skip=1", output)
        for key in ("merge_completed_chinese", "qb_add_magnet", "save_pending", "pause_superseded_tasks",
                    "update_weekly_magnet", "update_weekly_magnet_if_unwatched", "_refill_weekly_gaps", "log_write"):
            self.mocks[key].assert_not_called()
        self.opener.open.assert_not_called()

    def test_duplicates_skip_and_keep_unwatched_update(self):
        self.mocks["avid_exists_in_system"].return_value = (True, "queue", "downloading")
        self.mocks["update_weekly_magnet_if_unwatched"].return_value = (True, "updated")
        self.assertEqual(rc.main(), 0)
        self.mocks["update_weekly_magnet_if_unwatched"].assert_called_once()
        self.mocks["qb_add_magnet"].assert_not_called()

    def test_existing_chinese_skips_add(self):
        self.mocks["qb_has_cn_avid"].return_value = True
        self.assertEqual(rc.main(), 0)
        self.mocks["qb_add_magnet"].assert_not_called()

    def test_failed_list_or_add_returns_failure(self):
        self.client.request_failed = True
        self.assertEqual(rc.main(), 1)
        self.client.request_failed = False
        self.mocks["qb_add_magnet"].return_value = (None, None)
        self.assertEqual(rc.main(), 1)


class ReplacementGuardTest(unittest.TestCase):
    def test_queue_and_qb_branches(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(rc, "QUEUE_FILE", os.path.join(root, "queue.json")), \
             mock.patch.object(rc, "SAVE_PATH", root), mock.patch.object(rc, "load_pending", return_value={}), \
             mock.patch.object(rc, "qb_login") as login, \
             mock.patch.object(rc, "collect_main_video_candidates", return_value=[{"path": "valid.mp4"}]) as candidates:
            response = login.return_value.open.return_value.read
            response.return_value = b"[]"
            for status in ("pending", "queued", "processing", "downloading", "done", "failed"):
                with self.subTest(status=status):
                    with open(rc.QUEUE_FILE, "w") as f:
                        json.dump([{"code": "SNOS-279", "status": status}], f)
                    self.assertEqual(rc.avid_exists_in_system("SNOS-279")[0], status not in ("done", "failed"))
            with open(rc.QUEUE_FILE, "w") as f:
                json.dump([], f)
            for state in ACTIVE_QB_STATES | DONE_QB_STATES | {"checkingUP", "error", "unknown", "missingFiles"}:
                with self.subTest(state=state):
                    response.return_value = json.dumps([dict(name="SNOS-279", hash="original", state=state)]).encode()
                    self.assertEqual(rc.avid_exists_in_system("SNOS-279")[0], state not in DONE_QB_STATES)
            candidates.return_value = []
            response.return_value = json.dumps([dict(name="SNOS-279", state="uploading")]).encode()
            self.assertTrue(rc.avid_exists_in_system("SNOS-279")[0])
            candidates.return_value = [{"path": "valid.mp4"}]
            for fields in ({"tags": "plwt_chinese"}, {"name": "SNOS-279-C"}, {"hash": "cn"}):
                with self.subTest(chinese=fields), mock.patch.object(rc, "load_pending", return_value={"cn": {"source": "forum-103"}}):
                    response.return_value = json.dumps([dict(name="SNOS-279", state="uploading") | fields]).encode()
                    self.assertTrue(rc.avid_exists_in_system("SNOS-279")[0])
                    self.assertTrue(rc.qb_has_cn_avid("SNOS-279"))

    def test_unavailable_duplicate_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(rc, "QUEUE_FILE", os.path.join(root, "queue.json")), \
             mock.patch.object(rc, "qb_login", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "qB tasks"):
                rc.avid_exists_in_system("SNOS-279")
            with open(rc.QUEUE_FILE, "w") as f:
                f.write("invalid")
            with self.assertRaisesRegex(RuntimeError, "queue"):
                rc.avid_exists_in_system("SNOS-279")


class DailyWatcherTest(unittest.TestCase):
    def run_watcher(self, results, completed=False):
        marks = []
        fake = mock.Mock()
        fake.main.side_effect = results
        now = datetime(2026, 11, 17, 14)
        def sleep(seconds):
            if completed or fake.main.call_count >= len(results):
                launcher.running = False
        with mock.patch.object(launcher, "running", True), mock.patch.object(launcher, "datetime") as clock, \
             mock.patch.object(launcher, "next_merge_target", return_value=now), \
             mock.patch.object(launcher, "merge_completed_on", side_effect=lambda d: completed or bool(marks)), \
             mock.patch.object(launcher, "mark_merge_completed", side_effect=marks.append), \
             mock.patch.object(launcher.time, "sleep", side_effect=sleep), \
             mock.patch.object(launcher, "log"), mock.patch.object(launcher, "log_write"), \
             mock.patch("importlib.import_module", return_value=fake), mock.patch.dict(os.environ, {"MERGE_ENABLE": "1"}):
            clock.now.return_value = now
            launcher.merge_watcher()
        return fake, marks

    def test_success_marks_today_and_next_pass_skips(self):
        fake, marks = self.run_watcher([0])
        fake.main.assert_called_once_with(daily=True)
        self.assertEqual(marks, ["2026-11-17"])

    def test_completed_today_skips(self):
        fake, marks = self.run_watcher([0], completed=True)
        fake.main.assert_not_called()
        self.assertEqual(marks, [])

    def test_nonzero_and_exception_retry_without_mark(self):
        for error in (1, RuntimeError("failure")):
            with self.subTest(error=error):
                fake, marks = self.run_watcher([error, 0])
                self.assertEqual(fake.main.call_args_list, [mock.call(daily=True), mock.call(daily=True)])
                self.assertEqual(marks, ["2026-11-17"])


class ForumRequestSlotTest(unittest.TestCase):
    def test_scan_gate_list_thread_and_retries_share_existing_slot(self):
        events = []
        @contextmanager
        def slot():
            events.append("enter")
            yield
            events.append("exit")
        def get(*args, **kwargs):
            self.assertEqual(events[-1], "enter")
            return mock.Mock(text="Discuz", status_code=200)
        with mock.patch.object(forum, "_load_safe_token", return_value=""), \
             mock.patch.object(forum, "_save_safe_token"), \
             mock.patch.object(forum.requests, "Session") as session, \
             mock.patch.object(download_source, "_plwt_search_slot", side_effect=slot) as shared, \
             mock.patch.object(forum.time, "sleep"):
            session.return_value.get.side_effect = get
            client = forum.ForumClient(coordinated_requests=True)
            self.assertTrue(client.ensure_safe())
            client.fetch_list_page(1)
            client.fetch_thread_magnet(client.base + "/thread-1-1-1.html")
            self.assertEqual(shared.call_count, 3)
            session.return_value.get.side_effect = [RuntimeError("offline"), mock.Mock(text="Discuz", status_code=200)]
            client.fetch_list_page(2)
            self.assertEqual(shared.call_count, 5)

    def test_backfill_list_stops_by_post_date_including_boundary(self):
        client = mock.Mock(fid="103", base="https://forum.test", _safe_ok=True)
        items = [dict(id="SNOS-279", postDate="2026-08-13"),
                 dict(id="OTHER-123", postDate="2026-08-12")]
        with mock.patch.object(forum, "parse_list_html", return_value=(items, dict(threads=2, with_id=2))), \
             mock.patch.object(forum, "_log"):
            result = forum.get_list_until(stop_date="2026-08-13", client=client)
        self.assertEqual(result, [items[0]])
        client.fetch_list_page.assert_called_once_with(1)

    def test_search_client_does_not_nest_existing_outer_lock(self):
        with mock.patch.object(forum, "_load_safe_token", return_value=""), \
             mock.patch.object(forum.requests, "Session"), \
             mock.patch.object(download_source, "_plwt_search_slot") as shared:
            forum.ForumClient()._raw_get("https://forum.test/search.php")
            shared.assert_not_called()
