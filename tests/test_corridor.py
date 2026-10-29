"""Corridor following near a zone change, on frames from the user's 2026-10-28 clips (1280x720 stills)."""
from pathlib import Path
import time
import unittest

import cv2
import numpy as np

import corridor

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    frame = cv2.imread(str(FIXTURES / name))
    assert frame is not None, name
    return frame


class CorridorHeadingTests(unittest.TestCase):
    def test_straight_corridor_heads_on_down_it(self):
        # 18-07-59 at 40 s: long straight corridor, copbot at the far end
        error, confidence, debug = corridor.corridor_heading(load("corridor_straight_C40.png"))
        self.assertIsNotNone(error)
        self.assertLess(abs(error), .15)
        self.assertGreater(confidence, .8)

    def test_wall_with_floor_off_to_the_left_turns_left(self):
        # 18-07-59 at 33 s: walked into the corner wall, the floor carries on out of view to the left
        error, _, debug = corridor.corridor_heading(load("corridor_wall_open_left_C33.png"))
        self.assertIsNone(error)
        self.assertEqual(debug["side"], -1)

    def test_corner_wall_with_a_copbot_turns_left(self):
        # 21-52-47 at 29 s: corner wall dead ahead, NCPD copbot standing to the right of the character
        error, _, debug = corridor.corridor_heading(load("corridor_wall_copbot_open_left_A29.png"))
        self.assertIsNone(error)
        self.assertEqual(debug["side"], -1)

    def test_blank_wall_receding_to_the_right_turns_right(self):
        # 19-59-39 at 28 s: no floor in view; the wall's trim line falls to the left, so it recedes right
        error, _, debug = corridor.corridor_heading(load("corridor_wall_open_right_B28.png"))
        self.assertIsNone(error)
        self.assertEqual(debug["side"], 1)

    def test_corridor_turning_right_after_the_corner_aims_right(self):
        # 18-07-59 at 37.5 s: past the corner the corridor bends right towards a copbot
        error, _, _ = corridor.corridor_heading(load("corridor_after_turn_right_C37.png"))
        self.assertIsNotNone(error)
        self.assertGreater(error, .15)

    def test_floor_ending_close_ahead_and_running_off_right_aims_right(self):
        # 17-17-10 at 160 s: short wall ahead, the floor runs out of view to the right (the L-turn)
        error, _, _ = corridor.corridor_heading(load("corridor_turns_right_D160.png"))
        self.assertIsNotNone(error)
        self.assertGreater(error, .15)

    def test_a_featureless_frame_has_no_way_and_no_side(self):
        error, confidence, debug = corridor.corridor_heading(np.full((1080, 1920, 3), 60, np.uint8))
        self.assertIsNone(error)
        self.assertEqual(confidence, 0.0)
        self.assertEqual(debug["side"], 0)

    def test_fast_enough_at_2560x1440(self):
        frame = cv2.resize(load("corridor_straight_C40.png"), (2560, 1440))
        corridor.corridor_heading(frame)
        start = time.perf_counter()
        for _ in range(10):
            corridor.corridor_heading(frame)
        self.assertLess((time.perf_counter() - start) / 10, .06)   # about 15 ms measured; slack for slow CI


if __name__ == "__main__":
    unittest.main()
