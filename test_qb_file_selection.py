import unittest

from qb_file_selection import select_strict_largest_video, strict_priority_plan


class StrictQBFileSelectionTest(unittest.TestCase):
    def test_selects_only_largest_mp4_and_disables_everything_else(self):
        files = [
            {"index": 0, "name": "MNGS-071-U/main.mp4", "size": 4_900_000_000, "progress": 0.3},
            {"index": 1, "name": "MNGS-071-U/part2.mp4", "size": 4_800_000_000, "progress": 0},
            {"index": 2, "name": "MNGS-071-U/ad.mp4", "size": 15_000_000, "progress": 0.2},
            {"index": 3, "name": "MNGS-071-U/site.html", "size": 120, "progress": 1},
        ]
        plan = strict_priority_plan(files)
        self.assertEqual(plan["selected"]["index"], 0)
        self.assertEqual(plan["disabled"], [1, 2, 3])

    def test_rejects_torrent_without_a_main_mp4(self):
        self.assertIsNone(select_strict_largest_video([
            {"index": 0, "name": "ad.mp4", "size": 15_000_000},
            {"index": 1, "name": "archive.zip", "size": 4_000_000_000},
        ]))


if __name__ == "__main__":
    unittest.main()
