"""Nav-Ray window geometry and list reading on the user's real captures."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import navray
from text_reader import TextReader

FIXTURES = Path(__file__).parent / "fixtures"


def gray(name, size=None, at=(100, 100)):
    image = cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2GRAY)
    if size is None:
        return image
    frame = np.zeros(size, np.uint8)
    frame[at[1]:at[1]+image.shape[0], at[0]:at[0]+image.shape[1]] = image
    return frame


class DestinationTextTests(unittest.TestCase):
    def test_parse_destination_needs_category_and_destination(self):
        self.assertEqual(navray.parse_destination("Faction HQs > Black Dragon"), ("Faction HQs", "Black Dragon"))
        for bad in ("", "Faction HQs", "a > b > c", " > x"):
            with self.assertRaises(ValueError, msg=bad):
                navray.parse_destination(bad)

    def test_find_row_matches_names_and_truncated_labels(self):
        rows = [(0, "UTILITIES"), (3, "PEPPER PARK APARTMEN ."), (7, "FACTION HQS")]
        self.assertEqual(navray.find_row(rows, "faction hqs"), 7)
        self.assertEqual(navray.find_row(rows, "Pepper Park Apartments"), 3)
        self.assertIsNone(navray.find_row(rows, "Plaza"))


class NavRayReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = TextReader()

    def test_window_and_buttons_at_scale_one(self):
        frame = gray("navray_window_1082.png", (1080, 1920))
        window = navray.find_navray(self.reader, frame)
        self.assertIsNotNone(window)
        self.assertAlmostEqual(window.scale, 1.0, delta=.05)
        sx, sy = window.start_point()
        self.assertLessEqual(abs(sx - (649 + 100 + 23)), 6)     # "Start" word centre in the capture
        self.assertLessEqual(abs(sy - (341 + 100 + 7)), 6)

    def test_window_at_a_smaller_ui_scale(self):
        frame = gray("navray_open_with_path_2000.png")
        window = navray.find_navray(self.reader, frame)
        self.assertIsNotNone(window)
        self.assertAlmostEqual(window.scale, .78, delta=.04)
        sx, sy = window.stop_point()
        self.assertLessEqual(abs(sx - 579), 8)                  # "Stop" word centre
        self.assertLessEqual(abs(sy - 514), 8)

    def test_category_rows_are_read_in_order(self):
        frame = gray("navray_window_1082.png", (1080, 1920))
        window = navray.find_navray(self.reader, frame)
        rows = navray.read_rows(frame, window, "select")
        self.assertEqual(navray.find_row(rows, "Faction HQs"), 7)
        self.assertEqual(navray.find_row(rows, "Utilities"), 0)
        self.assertEqual(navray.find_row(rows, "Pepper Park Apartments"), 3)

    def test_destination_rows_are_read(self):
        frame = gray("navray_window_destinations_924.png", (1080, 1920), at=(300, 200))
        window = navray.find_navray(self.reader, frame)
        rows = navray.read_rows(frame, window, "destination")
        self.assertEqual(navray.find_row(rows, "Protopharm"), 0)
        self.assertEqual(navray.find_row(rows, "Black Dragon"), 2)

    def test_every_row_of_both_lists_is_read_exactly_on_a_live_2560_frame(self):
        # Live frame: the clicked category (OUTZONE DUNGEONS) is highlighted and the cursor sits on a row.
        frame = gray("navray_lists_2560.png")
        window = navray.find_navray(self.reader, frame)
        self.assertIsNotNone(window)
        select = dict(navray.read_rows(frame, window, "select"))
        self.assertEqual([select[i] for i in range(8)], [
            "PLAZA DUNGEONS", "VIAROSSO DUNGEONS", "PEPPER PARK DUNGEONS", "OUTZONE DUNGEONS",
            "TECH HAVEN DUNGEONS", "MILITARY BASE DUNGEONS", "CANYON DUNGEONS", "WASTELAND DUNGEONS"])
        destination = dict(navray.read_rows(frame, window, "destination"))
        self.assertEqual(sorted(destination), list(range(7)))                 # the 8th row is under the buttons
        self.assertEqual(destination[0], "Outzone 3 - Storage Halls 3 (hard)")
        self.assertEqual(destination[4], "Outzone 3 - Water Cleaning Sec 9 (hard)")
        self.assertEqual(destination[6], "Outzone 5 - Storage Halls 5 (hard)")

    def test_tidy_removes_edge_junk_only(self):
        self.assertEqual(navray.tidy("lOUTZONE DUNGEONS ="), "OUTZONE DUNGEONS")
        self.assertEqual(navray.tidy("Outzone 4 - Storage Halls 4 (hard) ia"), "Outzone 4 - Storage Halls 4 (hard)")
        self.assertEqual(navray.tidy("FACTION HQS"), "FACTION HQS")

    def test_a_frame_without_the_window_is_not_found(self):
        self.assertIsNone(navray.find_navray(self.reader, np.zeros((1080, 1920), np.uint8)))
