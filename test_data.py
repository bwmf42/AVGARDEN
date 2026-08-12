import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

comm_module = types.ModuleType("src.comm")
comm_module.logger = mock.Mock()
sys.modules.setdefault("src.comm", comm_module)
from src import data
if sys.modules.get("src.comm") is comm_module:
    del sys.modules["src.comm"]


class DataStoreTest(unittest.TestCase):
    def test_rejects_unapproved_table_name(self):
        with self.assertRaises(ValueError):
            data.find_in_db("ABF-123", ":memory:", "MissAV; DROP TABLE MissAV")

    def test_lookup_error_is_not_reported_as_missing(self):
        connection = mock.Mock()
        connection.cursor.return_value.execute.side_effect = sqlite3.OperationalError("locked")
        with mock.patch.object(data, "_connect", return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                data.find_in_db("ABF-123", ":memory:", "MissAV")
        connection.close.assert_called_once_with()

    def test_insert_and_lookup(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "downloaded.db")
            data.initialize_db(path, "MissAV")
            self.assertTrue(data.batch_insert_bvids(["ABF-123"], path, "MissAV"))
            self.assertTrue(data.find_in_db("ABF-123", path, "MissAV"))


if __name__ == "__main__":
    unittest.main()
