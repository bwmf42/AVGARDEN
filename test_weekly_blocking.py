import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from src.weekly import blocking


class WeeklyBlockingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = self.temp.name
        values = {
            "blocked_actresses.txt": "Blocked Actress\n",
            "blocked_genres.txt": "Blocked Genre\n",
            "favorite_actresses.txt": "Favorite Actress\n",
            "blocked_keywords.txt": "blocked word\n",
        }
        for name, value in values.items():
            with open(os.path.join(self.db, name), "w") as handle:
                handle.write(value)
        with open(os.path.join(self.db, "actress_ages.json"), "w") as handle:
            json.dump({"Older Actress": datetime.now().year - 50}, handle)
        self.env = mock.patch.dict(os.environ, {
            "DB_PATH": os.path.join(self.db, "downloaded.db"),
            "BLOCKED_ACTRESSES_FILE": os.path.join(self.db, "blocked_actresses.txt"),
            "BLOCKED_GENRES_FILE": os.path.join(self.db, "blocked_genres.txt"),
            "FAV_ACTRESSES_FILE": os.path.join(self.db, "favorite_actresses.txt"),
            "BLOCKED_KEYWORDS_FILE": os.path.join(self.db, "blocked_keywords.txt"),
            "ACTRESS_AGES_FILE": os.path.join(self.db, "actress_ages.json"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.rules = blocking.load_rules()

    def test_matches_same_filters_as_weekly_api(self):
        self.assertEqual(blocking.match_reason({"actresses": ["Blocked Actress"]}, self.rules), "blocked_actress")
        self.assertEqual(blocking.match_reason({"genres": ["Blocked Genre"]}, self.rules), "blocked_genre")
        self.assertEqual(blocking.match_reason({"title": "contains blocked word"}, self.rules), "blocked_keyword")
        self.assertEqual(blocking.match_reason({"actresses": ["Older Actress"]}, self.rules), "blocked_age")

    def test_favorite_actress_bypasses_genre_only(self):
        item = {"actresses": ["Favorite Actress"], "genres": ["Blocked Genre"]}
        self.assertEqual(blocking.match_reason(item, self.rules), "")
        item["actresses"].append("Blocked Actress")
        self.assertEqual(blocking.match_reason(item, self.rules), "blocked_actress")


if __name__ == "__main__":
    unittest.main()
