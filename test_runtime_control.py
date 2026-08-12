import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from process_control import clear_cancel_request, request_cancel, run_tracked
from queue_store import append_unique, clear_if_matches, pop_first, read_queue, write_queue


class RuntimeControlTest(unittest.TestCase):
    def test_cancel_stops_tracked_process(self):
        with tempfile.TemporaryDirectory() as directory:
            queue_path = os.path.join(directory, "queue.txt")
            result = {}
            with patch.dict(os.environ, {"QUEUE_PATH": queue_path}):
                thread = threading.Thread(
                    target=lambda: result.setdefault(
                        "code",
                        run_tracked([sys.executable, "-c", "import time; time.sleep(30)"], "OMG-032"),
                    )
                )
                thread.start()
                time.sleep(0.5)
                request_cancel("OMG032")
                thread.join(timeout=8)
                self.assertFalse(thread.is_alive())
                self.assertEqual(result.get("code"), 130)
                clear_cancel_request("OMG-032")

    def test_queue_operations_are_atomic_and_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            queue_path = os.path.join(directory, "queue.txt")
            append_unique(queue_path, "ABC-000")
            threads = [threading.Thread(target=append_unique, args=(queue_path, f"ABC-{i:03d}")) for i in range(1, 20)]
            threads += [threading.Thread(target=append_unique, args=(queue_path, "ABC-001")) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(read_queue(queue_path)), 20)
            self.assertEqual(pop_first(queue_path), "ABC-000")
            self.assertEqual(len(read_queue(queue_path)), 19)

    def test_compare_and_clear_preserves_a_new_current_download(self):
        with tempfile.TemporaryDirectory() as directory:
            current_path = os.path.join(directory, "current.txt")
            write_queue(current_path, ["OLD-001"])
            write_queue(current_path, ["NEW-002"])
            self.assertFalse(clear_if_matches(current_path, "OLD-001"))
            self.assertEqual(read_queue(current_path), ["NEW-002"])
            self.assertTrue(clear_if_matches(current_path, "NEW-002"))
            self.assertEqual(read_queue(current_path), [])


if __name__ == "__main__":
    unittest.main()
