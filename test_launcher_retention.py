import unittest
from datetime import datetime

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


if __name__ == "__main__":
    unittest.main()
