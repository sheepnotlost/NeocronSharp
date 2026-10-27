"""The shipped Nav-Ray destination list and the helpers that make repeated labels pickable."""
import unittest

import navray


class CatalogTests(unittest.TestCase):
    def test_shipped_lists_cover_every_category_and_keep_game_order(self):
        catalog = navray.load_catalog()
        self.assertEqual(len(catalog), 23)
        self.assertEqual(list(catalog)[:3], ["UTILITIES", "PLAZA APARTMENTS", "VIAROSSO APARTMENTS"])
        self.assertEqual(list(catalog)[-1], "WASTELAND DUNGEONS")
        self.assertEqual(catalog["FACTION HQS"][7], "BLACK DRAGON")
        self.assertEqual(catalog["TECH HAVEN APARTMENTS"][0], "Tech Haven 1A")
        self.assertTrue(all(isinstance(v, list) and v and all(isinstance(i, str) for i in v) for v in catalog.values()))

    def test_repeated_labels_are_numbered_so_every_choice_is_unique(self):
        entries = ["A", "Cut…", "Cut…", "B", "Cut…"]
        self.assertEqual(navray.numbered(entries), ["A", "Cut… #1", "Cut… #2", "B", "Cut… #3"])
        for category, entries in navray.load_catalog().items():
            shown = navray.numbered(entries)
            self.assertEqual(len(set(shown)), len(shown), category)

    def test_split_label_and_row_shift(self):
        self.assertEqual(navray.split_label("Plaza / Daton Hale Apartment Complex / E… #2"),
                         ("Plaza / Daton Hale Apartment Complex / E…", 2))
        self.assertEqual(navray.split_label("FACTION HQS"), ("FACTION HQS", 1))
        self.assertEqual(navray.row_shift(list("abcdefg"), list("cdefghi")), 2)
        self.assertIsNone(navray.row_shift(list("abcdefg"), list("hijklmn")))

    def test_a_scan_replaces_the_shipped_lists_when_saved_in_the_profile(self):
        profile = {"navray": {"destination": "", "catalog": {"X": ["one", "two"]}}}
        self.assertEqual(navray.load_catalog(profile), {"X": ["one", "two"]})
        self.assertEqual(len(navray.load_catalog({"navray": {}})), 23)
