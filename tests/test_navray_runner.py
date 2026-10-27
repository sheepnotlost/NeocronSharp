"""Walk loop with a fake backend and the user's real path frames."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import navray_runner
from macro_core import Control, Interrupted
from navray_runner import NavRayRunner

FIXTURES = Path(__file__).parent / "fixtures"


def rgb(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)


HALL, STAIRS = rgb("navray_path_hall_2000.png"), rgb("navray_path_stairs_2000.png")
DARK = np.full((1125, 2000, 3), 40, np.uint8)


class FakeBackend:
    def __init__(self):
        self.events = []
    def key(self, name, down):self.events.append(("key", name, down))
    def move_relative(self, dx, dy):self.events.append(("rel", dx, dy))
    def scroll(self, notches):self.events.append(("scroll", notches))
    def release_all(self):self.events.append(("release",))
    def check_focus(self, size):pass


class Reader:
    """Pretends to be the OCR: the health region reads the next scripted value."""
    def __init__(self, health):
        self.health = list(health)
    def read_words(self, gray, up=3):
        if not self.health:
            return []
        value = self.health.pop(0) if len(self.health) > 1 else self.health[0]
        return [("HLT", 0, 0, 10, 10), (str(value), 20, 0, 10, 10), ("/", 40, 0, 5, 10), ("972", 50, 0, 10, 10)]


def make_runner(frames, health=(972,)):
    """frames: callable(index) -> RGB frame. Each frame() call advances the fake clock by .1 s."""
    clock = {"t": 0.0, "i": 0}
    runner = NavRayRunner.__new__(NavRayRunner)
    runner.backend = FakeBackend()
    runner.control = Control()
    runner.events = events = []
    runner.emit = lambda kind, payload=None: events.append((kind, payload))
    runner.clock = lambda: clock["t"]
    runner.sleep = lambda seconds: clock.__setitem__("t", clock["t"] + seconds)
    runner.profile = {"client_size": [2000, 1125], "navray": {"destination": "Faction HQs > Black Dragon"}}
    reader = Reader(health)

    class Detector:
        def text_reader(self):return reader
        def gray(self, frame):return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    runner.detector = Detector()

    def frame():
        clock["t"] += .1
        clock["i"] += 1
        return frames(clock["i"])
    runner.frame = frame
    return runner, events


class WalkTests(unittest.TestCase):
    def test_walks_steers_towards_the_path_and_reports_arrival_when_it_ends(self):
        runner, events = make_runner(lambda i: STAIRS if i <= 12 else DARK)
        runner.walk()
        recorded = runner.backend.events
        self.assertEqual(recorded[0], ("key", "w", True))
        self.assertEqual(recorded[-1], ("key", "w", False))
        turns = [e[1] for e in recorded if e[0] == "rel" and e[1] != 0]
        self.assertTrue(turns and all(t < 0 for t in turns[:5]), turns[:5])      # path is to the left
        self.assertTrue(all(abs(t) <= navray_runner.MAX_STEP for t in turns))
        done = [p for k, p in events if k == "done"]
        self.assertEqual(len(done), 1)
        self.assertIn("arrived", done[0].lower())

    def test_no_path_at_all_stops_with_a_clear_reason(self):
        runner, _ = make_runner(lambda i: DARK)
        with self.assertRaisesRegex(Interrupted, "No Nav-Ray path"):
            runner.walk()
        self.assertEqual(runner.backend.events[-1], ("key", "w", False))

    def test_a_black_frame_is_a_loading_screen(self):
        runner, _ = make_runner(lambda i: STAIRS if i < 4 else np.zeros((1125, 2000, 3), np.uint8))
        with self.assertRaisesRegex(Interrupted, "Loading screen"):
            runner.walk()

    def test_an_unchanging_view_with_a_path_is_stuck(self):
        runner, _ = make_runner(lambda i: STAIRS)
        with self.assertRaisesRegex(Interrupted, "Not moving"):
            runner.walk()

    def test_a_health_drop_stops_the_walk(self):
        runner, _ = make_runner(lambda i: STAIRS if i % 2 else HALL, health=(972, 972, 800))
        with self.assertRaisesRegex(Interrupted, "Health dropped"):
            runner.walk()
        self.assertEqual(runner.backend.events[-1], ("key", "w", False))

    def test_steering_step_is_proportional_and_clamped(self):
        self.assertEqual(navray_runner.steer_step(0.0), 0)
        self.assertEqual(navray_runner.steer_step(.01), 0)                       # inside the dead zone
        self.assertLess(navray_runner.steer_step(-.05), 0)
        self.assertEqual(navray_runner.steer_step(-.5), -navray_runner.MAX_STEP)
        self.assertEqual(navray_runner.steer_step(.5), navray_runner.MAX_STEP)


class SelectionTests(unittest.TestCase):
    def test_choose_clicks_the_row_of_the_wanted_category_on_a_real_capture(self):
        from text_reader import TextReader
        image = cv2.imread(str(FIXTURES / "navray_window_1082.png"))
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[100:100+image.shape[0], 100:100+image.shape[1]] = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        reader = TextReader()
        runner, _ = make_runner(lambda i: frame)
        runner.profile["client_size"] = [1920, 1080]
        runner.detector.text_reader = lambda: reader
        clicks = []
        runner.move = lambda point: None
        runner.click = clicks.append
        runner.choose("select", "Faction HQs", reader)
        # FACTION HQS is the 8th row of the Select list (text at x 204, y 345 in the capture, +100 offset).
        self.assertEqual(len(clicks), 1)
        self.assertLessEqual(abs(clicks[0][0] - (204 + 100 + 60)), 8)
        self.assertLessEqual(abs(clicks[0][1] - (345 + 100 + 8)), 8)
        self.assertIn(("scroll", 10), runner.backend.events)

    def test_a_missing_window_or_destination_stops_with_a_clear_reason(self):
        from text_reader import TextReader
        reader = TextReader()
        runner, _ = make_runner(lambda i: np.zeros((1080, 1920, 3), np.uint8))
        runner.detector.text_reader = lambda: reader
        runner.wait = lambda seconds, safe_pause=False: None
        with self.assertRaisesRegex(Interrupted, "Nav-Ray window not found"):
            runner.find_window(reader)
