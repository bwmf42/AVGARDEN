import unittest
from datetime import datetime
import os
import tempfile

import launcher


class LauncherRetentionTest(unittest.TestCase):
    def test_next_retention_runs_at_next_0430(self):
        self.assertEqual(
            launcher.next_retention_target(datetime(2026, 7, 29, 3, 0)),
            datetime(2026, 7, 29, 4, 30),
        )
        self.assertEqual(
            launcher.next_retention_target(datetime(2026, 7, 29, 5, 0)),
            datetime(2026, 7, 30, 4, 30),
        )

    def test_daily_completion_log_requires_full_scrape_pipeline(self):
        day = "2026-08-13"
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "av-garden.log")
            previous_state = launcher.DAILY_UPDATE_STATE_PATH
            launcher.DAILY_UPDATE_STATE_PATH = os.path.join(directory, "missing-state.json")
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(f"{day} 15:00:00 [DailyUpdater] 每日推荐阶段完成 (weekly_updater)\n")
                with unittest.mock.patch.dict(os.environ, {"LOG_FILE": path}):
                    self.assertFalse(launcher.daily_update_completed_on(day))

                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(f"{day} 16:00:00 [DailyUpdater] 刮削完成（含未看中文补链）\n")
                with unittest.mock.patch.dict(os.environ, {"LOG_FILE": path}):
                    self.assertTrue(launcher.daily_update_completed_on(day))
            finally:
                launcher.DAILY_UPDATE_STATE_PATH = previous_state


if __name__ == "__main__":
    unittest.main()
