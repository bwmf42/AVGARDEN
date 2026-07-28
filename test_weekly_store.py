import json
import os
import tempfile
import unittest
import multiprocessing

from weekly_store import atomic_write_json, update_json, weekly_update_lock


def increment_json(path, count):
    for _ in range(count):
        update_json(path, {"count": 0}, lambda value: {"count": value.get("count", 0) + 1})


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

    def test_cross_process_updates_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "weekly.json")
            atomic_write_json(path, {"count": 0})
            processes = [multiprocessing.Process(target=increment_json, args=(path, 10)) for _ in range(3)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"count": 30})


if __name__ == "__main__":
    unittest.main()
