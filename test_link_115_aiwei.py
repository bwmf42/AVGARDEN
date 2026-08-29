#!/usr/bin/env python3
import os
import tempfile
import unittest

from tools.maintenance.link_115_aiwei_into_data_root import remove_reverse_links


class TestRemoveReverseLinks(unittest.TestCase):
    def test_unlinks_placeholders_and_keeps_real_dirs(self):
        with tempfile.TemporaryDirectory() as root:
            lib = os.path.join(root, "ABF-376")
            aiwei = os.path.join(root, "115生活备份", "艾薇")
            os.makedirs(lib)
            os.makedirs(aiwei)
            os.symlink("../../ABF-376", os.path.join(aiwei, "ABF-376"))
            real = os.path.join(aiwei, "KEEP-001")
            os.makedirs(real)
            stats = remove_reverse_links(data_root=root)
            self.assertEqual(stats["removed"], 1)
            self.assertEqual(stats["kept_real"], 1)
            self.assertFalse(os.path.lexists(os.path.join(aiwei, "ABF-376")))
            self.assertTrue(os.path.isdir(real))
            self.assertTrue(os.path.isdir(lib))


if __name__ == "__main__":
    unittest.main()
