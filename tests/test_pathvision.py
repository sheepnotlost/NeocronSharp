"""Dashed Nav-Ray path detection on the user's real captures (2000x1125 stills)."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import pathvision

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return cv2.imread(str(FIXTURES / name))


class PathVisionTests(unittest.TestCase):
    def test_stairs_frame_finds_a_long_chain_and_aims_left(self):
        view = pathvision.find_path(load("navray_path_stairs_2000.png"))
        self.assertIsNotNone(view)
        self.assertGreaterEqual(len(view.points), 8)
        self.assertLess(view.error, -.2)            # the path leads well to the left of centre
        ys = [p[1] for p in view.points]
        self.assertEqual(ys, sorted(ys, reverse=True))   # nearest (lowest on screen) first
        self.assertTrue(310 <= min(ys) <= 330 and 520 <= max(ys) <= 620, (min(ys), max(ys)))

    def test_hall_frame_with_green_signs_still_aims_at_the_dashes(self):
        view = pathvision.find_path(load("navray_path_hall_2000.png"))
        self.assertIsNotNone(view)
        self.assertTrue(880 <= view.aim[0] <= 960, view.aim)   # dashes run down x ~ 900-940
        self.assertLess(abs(view.error), .1)

    def test_a_frame_without_a_path_returns_none(self):
        self.assertIsNone(pathvision.find_path(np.full((1125, 2000, 3), 40, np.uint8)))

    def test_green_posters_on_a_wall_are_not_a_path(self):
        # Live frame where the walk ended pressed against a wall of glowing signs: no dashes are visible.
        self.assertIsNone(pathvision.find_path(load("navray_no_path_posters_2560.png")))

    def test_a_big_glowing_sign_beside_the_character_is_not_the_path(self):
        # Live frame where a walk hugged the NCPD/Viarosso sign: the real path is the floor dashes to the right.
        view = pathvision.find_path(load("navray_sign_wall_with_path_2560.png"))
        self.assertIsNotNone(view)
        self.assertTrue(1650 <= view.aim[0] <= 1800, view.aim)
        self.assertGreater(view.error, .1)                         # the path lies to the right of the character
        self.assertTrue(all(x > 1500 for x, _ in view.points), view.points)  # nothing from the sign or the character

    def test_ignored_boxes_hide_candidates(self):
        frame = load("navray_path_stairs_2000.png")
        everything = (0, 0, frame.shape[1], frame.shape[0])
        self.assertIsNone(pathvision.find_path(frame, ignore=[everything]))
