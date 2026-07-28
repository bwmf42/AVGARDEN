import os
import tempfile
import unittest

from video_id import normalize_video_id, safe_local_dir, safe_video_dir


CASES = {
    "omg-032": "OMG-032",
    "OMG032": "OMG-032",
    "ABP984": "ABP-984",
    "ＡＢＰ９８４": "ABP-984",
    "300MIUM-1395": "300MIUM-1395",
    "300mium1395": "300MIUM-1395",
    "259luxu1234": "259LUXU-1234",
    "857OMG-032": "857OMG-032",
    "FC2 PPV 1234567": "FC2-1234567",
    "fc2ppv_1234567": "FC2-1234567",
    "062620_001": "062620-001",
    "HEYZO1009": "HEYZO-1009",
    "heydouga-4017-0123": "HEYDOUGA-4017-123",
    "T28557": "T28-557",
    "IBW123Z": "IBW-123Z",
    "START-612V": "START-612",
    "start612v": "START-612",
    "N1234": "N1234",
    "h_086abc00123": "H_086ABC00123",
}


class VideoIDTest(unittest.TestCase):
    def test_known_formats(self):
        for raw, expected in CASES.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_video_id(raw), expected)

    def test_rejects_unsafe_or_ambiguous_input(self):
        for raw in ("../OMG-032", "OMG-032; touch X", "ABC", "123456", "A/B-123", ""):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_video_id(raw), "")

    def test_safe_video_dir_stays_under_base(self):
        with tempfile.TemporaryDirectory() as base:
            target = safe_video_dir(base, "300mium1395")
            self.assertEqual(target, os.path.join(os.path.realpath(base), "300MIUM-1395"))
            with self.assertRaises(ValueError):
                safe_video_dir(base, "../outside")

    def test_local_folder_name_can_be_noncanonical_but_not_escape(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(
                safe_local_dir(base, "source prefix OMG-032"),
                os.path.join(os.path.realpath(base), "source prefix OMG-032"),
            )
            with self.assertRaises(ValueError):
                safe_local_dir(base, "../outside")


if __name__ == "__main__":
    unittest.main()
