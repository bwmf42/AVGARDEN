"""Regression coverage for candidate budgets and subprocess cleanup."""
import subprocess
import unittest
from unittest import mock

import run_scrape_followups as followup


class TestFollowupSupervisor(unittest.TestCase):
    def test_large_batch_can_finish_after_one_hour(self):
        proc = mock.Mock()
        proc.wait.return_value = 0
        proc.poll.return_value = 0
        with mock.patch.object(followup.subprocess, "Popen") as popen, \
             mock.patch.object(followup, "read_status", return_value={"progress": {"total": 228}}), \
             mock.patch.object(followup.time, "monotonic", side_effect=[0, 3601]), \
             mock.patch.object(followup, "write_status") as write:
            popen.return_value.__enter__.return_value = proc
            self.assertEqual(followup.run_with_budget("refill.py"), 0)
        proc.kill.assert_not_called()
        write.assert_not_called()

    def test_timeout_kills_and_reaps_child_before_writing_progress(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        progress = {"current": 108, "total": 228}
        with mock.patch.object(followup.subprocess, "Popen") as popen, \
             mock.patch.object(followup, "read_status", return_value={"progress": progress}), \
             mock.patch.object(followup.time, "monotonic", side_effect=[0, 22321]), \
             mock.patch.object(followup, "write_status") as write:
            popen.return_value.__enter__.return_value = proc
            write.side_effect = lambda _: proc.wait.assert_called_once_with()
            self.assertEqual(followup.run_with_budget("refill.py"), 124)
        proc.kill.assert_called_once_with()
        error = write.call_args.args[0]["last_error"]
        self.assertIn("超时", error)
        self.assertIn("107/228", error)

    def test_polling_wait_timeout_is_not_job_failure(self):
        proc = mock.Mock()
        proc.wait.side_effect = [subprocess.TimeoutExpired("refill", 5), 0]
        proc.poll.return_value = 0
        with mock.patch.object(followup.subprocess, "Popen") as popen, \
             mock.patch.object(followup, "read_status", return_value={"progress": {"total": 209}}), \
             mock.patch.object(followup.time, "monotonic", side_effect=[0, 10, 15]):
            popen.return_value.__enter__.return_value = proc
            self.assertEqual(followup.run_with_budget("refill.py"), 0)
        self.assertEqual(proc.wait.call_count, 2)

    def test_real_failure_reason_survives_finish(self):
        with mock.patch.object(followup, "set_phase"), \
             mock.patch.object(followup, "run_with_budget", return_value=1), \
             mock.patch.object(followup, "read_status", return_value={"last_error": "98堂 SSL 连接失败"}), \
             mock.patch.object(followup, "finish_pipeline") as finish:
            self.assertEqual(followup.main(), 1)
        self.assertEqual(finish.call_args.kwargs["error"], "98堂 SSL 连接失败")


if __name__ == "__main__":
    unittest.main()
