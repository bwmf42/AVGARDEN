import json
import os
import tempfile
import unittest

from weekly_store import atomic_write_json, weekly_update_lock


class TestWeeklyStore(unittest.TestCase):
    def test_lock_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "weekly.json")
            value = [{"id": "PEEP-180", "cover": "/file/PEEP-180-cover.jpg"}]
            with weekly_update_lock(path):
                atomic_write_json(path, value)

            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), value)
            leftovers = [name for name in os.listdir(directory) if name.endswith(".tmp")]
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
