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
        self.assertGreaterEqual(len(view.points), 6)
        self.assertLess(view.error, -.2)            # the path leads well to the left of centre
        ys = [p[1] for p in view.points]
        self.assertEqual(ys, sorted(ys, reverse=True))   # nearest (lowest on screen) first
        self.assertTrue(min(ys) <= 330 and 520 <= max(ys) <= 620, (min(ys), max(ys)))

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

    def test_following_a_path_ignores_marks_away_from_it(self):
        stairs = load("navray_path_stairs_2000.png")
        view = pathvision.find_path(stairs)
        again = pathvision.find_path(stairs, prior=view)
        self.assertIsNotNone(again)
        self.assertEqual(len(again.points), len(view.points))
        far_off = pathvision.PathView(view.points, view.aim, view.error, view.lateral, 0.0, 1900.0, (1900.0, 300.0))
        self.assertIsNone(pathvision.find_path(stairs, prior=far_off, tube=.05))

    def test_the_far_end_of_the_dashes_ahead_is_the_way_on(self):
        view = pathvision.find_path(load("navray_straight_ahead_2000.png"))
        self.assertLess(view.forward_point[1], view.points[0][1])      # the far (upper) end, not the near one

    def test_dashes_wholly_behind_the_character_are_not_followed(self):
        import cv2
        import numpy as np
        frame = np.full((1440, 2560, 3), 35, np.uint8)
        colour = tuple(int(v) for v in cv2.cvtColor(np.uint8([[[70, 110, 130]]]), cv2.COLOR_HSV2BGR)[0, 0])
        direction = np.array([-70.0, 40.0]); direction /= np.hypot(*direction)
        normal = np.array([-direction[1], direction[0]])
        for i, centre in enumerate([(1000, 1160), (930, 1200), (860, 1240), (790, 1280), (720, 1320), (650, 1360)]):
            c = np.array(centre, float)
            corners = [c + s1*(14 + 4*i)*direction + s2*(5 + i)*normal for s1, s2 in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
            cv2.fillConvexPoly(frame, np.round(corners).astype(np.int32), colour)
        self.assertIsNone(pathvision.find_path(frame))

    def test_dashes_running_straight_ahead_beat_a_bigger_chain_on_a_far_sign(self):
        # Live frame: the real path leads straight up from the character; a glowing sign top right has more marks.
        view = pathvision.find_path(load("navray_straight_ahead_2000.png"))
        self.assertIsNotNone(view)
        self.assertLess(abs(view.error), .05)                          # the next dash is dead ahead
        self.assertTrue(all(900 < x < 1100 for x, _ in view.points), view.points)

    def test_the_next_dash_is_the_nearest_one_ahead_of_the_character(self):
        view = pathvision.find_path(load("navray_straight_ahead_2000.png"))
        ahead = [p for p in view.points if p[1] <= pathvision.REACH_Y*1125]
        self.assertEqual(view.aim, ahead[0])                           # nearest first, then the next one as it is reached

    def test_teal_lit_walls_and_a_text_panel_are_not_a_path(self):
        # Live frame where a walk reported 20-30 "dashes" with none on screen: green-lit walls and a lettered panel.
        self.assertIsNone(pathvision.find_path(load("navray_teal_walls_no_path_2560.png")))

    def test_specks_of_lettering_never_pass_for_the_path_being_followed(self):
        # Live frame with no dashes at all: the walk, holding a path, "found" vertical strokes of text on a screen.
        frame = load("navray_plaza_no_dashes_2560.png")
        self.assertIsNone(pathvision.find_path(frame))
        prior = pathvision.PathView(((1016.0, 480.0), (1000.0, 250.0)), (1016.0, 480.0), 0.0, 0.0, .07, 1258.0, (1000.0, 250.0))
        self.assertIsNone(pathvision.find_path(frame, prior=prior, tube=.25))

    def test_one_big_dash_of_the_path_being_followed_is_enough_to_carry_on(self):
        # Live frame: the walk was following a path and only one big dash (lower left) and a marker were still in view.
        frame = load("navray_one_dash_left_2560.png")
        prior = pathvision.PathView(((900.0, 1000.0), (700.0, 1050.0), (500.0, 1100.0)), (700.0, 1050.0),
                                    -.1, -.1, -1.95, 2393.0, (900.0, 1000.0))
        view = pathvision.find_path(frame, prior=prior, tube=.25)
        self.assertIsNotNone(view)
        self.assertTrue(380 <= view.points[0][0] <= 480, view.points)    # the nearest mark is that dash
        self.assertTrue(380 <= view.aim[0] <= 480, view.aim)             # the dash at the left
        self.assertLess(view.error, -.25)                                # so turn left towards it

    def test_first_person_dashes_running_across_the_floor_are_found_and_clutter_is_not(self):
        # Live first-person frames. The real dashes are big, a rich flat green (saturation ~110, hue spread ~2), some dim.
        view = pathvision.find_path(load("navray_first_person_dashes_row_2560.jpg"))
        self.assertIsNotNone(view)
        self.assertGreaterEqual(len(view.points), 3)
        self.assertTrue(all(500 < y < 650 for _, y in view.points), view.points)       # the row of dashes on the floor
        self.assertLess(abs(view.error), .12)                                        # nearest dash roughly ahead
        # the same scene a moment earlier showed shop plants, glass and signs but no dashes
        self.assertIsNone(pathvision.find_path(load("navray_first_person_no_dashes_2560.jpg")))

    def test_ignored_boxes_hide_candidates(self):
        frame = load("navray_path_stairs_2000.png")
        everything = (0, 0, frame.shape[1], frame.shape[0])
        self.assertIsNone(pathvision.find_path(frame, ignore=[everything]))
