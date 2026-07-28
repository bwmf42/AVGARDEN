import json
import os
import tempfile
import unittest
from unittest import mock

import plwt_translate_missing


class TranslateMissingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.weekly_json = os.path.join(self.temp.name, "weekly.json")
        with open(self.weekly_json, "w", encoding="utf-8") as handle:
            json.dump([{"id": "KEEP-001", "title": "Title", "titleZh": "标题"}], handle)

    def test_noop_run_does_not_rewrite_weekly_json(self):
        with mock.patch.object(plwt_translate_missing, "WEEKLY_JSON", self.weekly_json), mock.patch.object(
            plwt_translate_missing, "strip_actresses_from_title_zh", return_value=0
        ), mock.patch.object(
            plwt_translate_missing, "batch_translate", return_value=(0, 0)
        ), mock.patch.object(plwt_translate_missing, "atomic_write_json") as write_json:
            plwt_translate_missing.main()
        write_json.assert_not_called()

    def test_changed_run_writes_weekly_json(self):
        with mock.patch.object(plwt_translate_missing, "WEEKLY_JSON", self.weekly_json), mock.patch.object(
            plwt_translate_missing, "strip_actresses_from_title_zh", return_value=1
        ), mock.patch.object(
            plwt_translate_missing, "batch_translate", return_value=(0, 0)
        ), mock.patch.object(plwt_translate_missing, "atomic_write_json") as write_json:
            plwt_translate_missing.main()
        write_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
