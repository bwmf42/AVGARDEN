import os
import tempfile
import unittest
from unittest import mock

import main_video


class MainVideoTest(unittest.TestCase):
    def create_video(self, root, relative, size):
        path = os.path.join(root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.truncate(size)
        return path

    def test_allocation_threshold(self):
        self.assertFalse(main_video.has_sufficient_allocated_bytes(100, 94))
        self.assertTrue(main_video.has_sufficient_allocated_bytes(100, 95))

    def test_ignores_small_and_sparse_files(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_video(root, "ad.mp4", 50 * 1024 * 1024)
            self.create_video(root, "sparse.mp4", 600 * 1024 * 1024)
            self.assertIsNone(main_video.find_main_video(root))

    def test_supports_nested_layout_and_chooses_largest(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(
            main_video, "has_sufficient_allocation", return_value=True
        ):
            self.create_video(root, "nested/low.mp4", 200 * 1024 * 1024)
            expected = self.create_video(root, "nested/high.mp4", 500 * 1024 * 1024)
            self.assertEqual(main_video.find_main_video(root), expected)

    def test_multipart_starts_at_part_one(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(
            main_video, "has_sufficient_allocation", return_value=True
        ):
            expected = self.create_video(root, "DVMM-413-1.mp4", 400 * 1024 * 1024)
            self.create_video(root, "DVMM-413-2.mp4", 600 * 1024 * 1024)
            self.assertEqual(main_video.find_main_video(root), expected)


if __name__ == "__main__":
    unittest.main()
