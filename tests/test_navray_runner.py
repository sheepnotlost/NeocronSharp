"""Walk loop with a fake backend and the user's real path frames."""
from pathlib import Path
import math
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import navray_runner
import pathvision
from macro_core import Control, Interrupted
from navray_runner import NavRayRunner

FIXTURES = Path(__file__).parent / "fixtures"


def rgb(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)


HALL, STAIRS = rgb("navray_path_hall_2000.png"), rgb("navray_path_stairs_2000.png")
DARK = np.full((1125, 2000, 3), 40, np.uint8)


def moving_dark(i):
    """An empty floor while walking: the picture changes a little from look to look (so it is not 'stuck')."""
    return np.full((1125, 2000, 3), 40 + (i % 9)*4, np.uint8)


def after_calibration(runner):
    """Mouse moves after the calibration nudges (each nudge is a move and a move back; a weak reading tries the next)."""
    moves = [e[1] for e in runner.backend.events if e[0] == "rel"]
    return moves[2*(1 if runner.px_per_count else len(navray_runner.CAL_NUDGES)):]


def pathvision_find(frame):
    return pathvision.find_path(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))


class FakeBackend:
    def __init__(self):
        self.events = []
        self.held_keys = set()
    def key(self, name, down):
        self.events.append(("key", name, down))
        if down:self.held_keys.add(name)
        else:self.held_keys.discard(name)
    def button(self, name, down):self.events.append(("button", name, down))
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
    runner.use_telemetry = False                 # never start the real NeocronSharp feed in tests
    runner.clock = lambda: clock["t"]
    runner.sleep = lambda seconds: clock.__setitem__("t", clock["t"] + seconds)
    runner.last_frame = None
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


AHEAD = rgb("navray_straight_ahead_2000.png")      # dashes dead ahead: lined up without turning


def turning_runner(sign, pixels_per_count=2.0, frame=STAIRS, stop_after=9):
    """A runner whose picture slides with the mouse: sign +1 = turning right slides the scene left (normal),
    -1 = an inverted mouse. The HUD stays put, as in the game."""
    holder = {}

    def frames(i):
        picture = frame.copy()
        height, width = picture.shape[:2]
        left, top, right, bottom = navray_runner.SCENE_BOX
        part = picture[int(top*height):int(bottom*height), int(left*width):int(right*width)]
        picture[int(top*height):int(bottom*height), int(left*width):int(right*width)] = \
            np.roll(part, -sign*round(holder["b"].yaw*pixels_per_count), axis=1)
        return picture
    runner, events = make_runner(frames)
    backend = holder["b"] = runner.backend
    backend.yaw = 0
    backend.calls = 0
    original = backend.move_relative

    def move_relative(dx, dy):
        backend.yaw += dx
        backend.calls += 1
        original(dx, dy)
        if backend.calls > stop_after:                    # the calibration nudges and a few turns are enough
            raise Interrupted("enough")
    backend.move_relative = move_relative
    return runner


class WalkTests(unittest.TestCase):
    def test_door_target_detected_on_real_blocked_frames(self):
        for name in ("navray_blocked_door_47s.png", "navray_blocked_door_50s.png"):
            frame = rgb(name)
            for width in (1280, 1920, 2560):
                with self.subTest(frame=name, width=width):
                    scaled = cv2.resize(frame, (width, width*9//16))
                    self.assertTrue(navray_runner.door_target(scaled, 70))
        self.assertFalse(navray_runner.door_target(rgb("navray_blocked_pepper_44s.png"), 70))
        self.assertTrue(navray_runner.door_target(rgb("navray_door_target_234452.png"), 70))

    def test_copbot_at_door_is_a_competing_target(self):
        self.assertFalse(navray_runner.actor_target(rgb("navray_door_target_234452.png"), 70))
        self.assertTrue(navray_runner.actor_target(rgb("navray_door_copbot_234452.png"), 70))

    def test_door_click_waits_for_a_competing_target_to_clear(self):
        actor = rgb("navray_door_copbot_234452.png")
        door = rgb("navray_door_target_234452.png")
        runner, _ = make_runner(lambda i: actor if i < 3 else door)
        runner.dash_color = 70
        self.assertTrue(runner.try_open_door(runner.detector.text_reader()))
        self.assertEqual([event for event in runner.backend.events if event[0] == "button"],
                         [("button", "right", True), ("button", "right", False)])

    def test_door_click_is_cancelled_if_target_changes_to_copbot(self):
        actor = rgb("navray_door_copbot_234452.png")
        door = rgb("navray_door_target_234452.png")
        runner, _ = make_runner(lambda i: door if i == 1 else actor)
        runner.dash_color = 70
        self.assertFalse(runner.try_open_door(runner.detector.text_reader()))
        self.assertFalse(any(event[0] == "button" for event in runner.backend.events))

    def test_blocked_door_gets_one_guarded_right_click_without_mouse_movement(self):
        runner, events = make_runner(lambda i: rgb("navray_blocked_door_50s.png"))
        runner.dash_color = 70
        self.assertTrue(runner.try_open_door(runner.detector.text_reader()))
        self.assertEqual(runner.backend.events, [("button", "right", True), ("button", "right", False)])
        self.assertTrue(any("door" in payload.lower() for kind, payload in events if kind == "status"))

    def test_blockage_without_a_door_never_right_clicks(self):
        runner, _ = make_runner(lambda i: rgb("navray_blocked_pepper_44s.png"))
        runner.dash_color = 70
        self.assertFalse(runner.try_open_door(runner.detector.text_reader()))
        self.assertFalse(any(event[0] == "button" for event in runner.backend.events))

    def test_ocr_can_recognise_another_door_label(self):
        class DoorReader:
            def read_words(self, gray, up=3):
                return [("Security", 20, 20, 60, 10), ("Door", 90, 20, 40, 10)]
        self.assertTrue(navray_runner.door_target(rgb("navray_blocked_pepper_44s.png"), 70, DoorReader()))

    def test_walk_tries_a_door_before_backing_away(self):
        frame = rgb("navray_blocked_door_50s.png")
        runner, _ = make_runner(lambda i: frame)
        runner.dash_color = 70
        runner.area_name = lambda: ""
        runner.calibrate_turn = lambda: -4.2
        runner.vitals = lambda *args: None
        view = pathvision_find(AHEAD)
        runner.evaluate = lambda *args, **kwargs: (view, frame)
        calls = []
        def leg(view, track, reader, state, tether=False):
            calls.append(1)
            if len(calls) == 1:
                return view, 0, "stuck against something"
            raise Interrupted("test complete")
        runner.walk_leg = leg
        with self.assertRaisesRegex(Interrupted, "test complete"):
            runner.walk()
        self.assertEqual(len(calls), 2)
        self.assertEqual([event for event in runner.backend.events if event[0] == "button"],
                         [("button", "right", True), ("button", "right", False)])
        events = runner.backend.events
        click = events.index(("button", "right", True))
        self.assertEqual(events[click - 1], ("key", "shift", False))
        self.assertEqual(events[click + 2], ("key", "shift", True))
        self.assertNotIn(("key", "s", True), runner.backend.events)

    def test_a_failed_door_attempt_is_not_immediately_repeated(self):
        frame = rgb("navray_blocked_door_50s.png")
        runner, _ = make_runner(lambda i: frame)
        runner.dash_color = 70
        runner.area_name = lambda: ""
        runner.calibrate_turn = lambda: -4.2
        runner.vitals = lambda *args: None
        view = pathvision_find(AHEAD)
        runner.evaluate = lambda *args, **kwargs: (view, frame)
        calls = []
        def leg(view, track, reader, state, tether=False):
            calls.append(1)
            if len(calls) <= 2:
                return view, 0, "stuck against something"
            raise Interrupted("test complete")
        runner.walk_leg = leg
        with self.assertRaisesRegex(Interrupted, "test complete"):
            runner.walk()
        self.assertEqual([event for event in runner.backend.events if event[0] == "button"],
                         [("button", "right", True), ("button", "right", False)])
        self.assertNotIn(("key", "s", True), runner.backend.events)

    def test_right_button_is_released_when_focus_is_lost_during_click(self):
        runner, _ = make_runner(lambda i: rgb("navray_blocked_door_50s.png"))
        runner.dash_color = 70
        runner.backend.key("shift", True)
        runner.wait = lambda seconds: (_ for _ in ()).throw(Interrupted("focus lost"))
        with self.assertRaisesRegex(Interrupted, "focus lost"):
            runner.try_open_door(runner.detector.text_reader())
        self.assertEqual(runner.backend.events[-2:], [("button", "right", True), ("button", "right", False)])
        self.assertNotIn("shift", runner.backend.held_keys)

    def test_scene_comparison_finds_real_obstacles_but_not_forward_progress(self):
        # 23:07:58: moving at 35-38s, then stuck running in place at 44-47s.
        # 23:11:35: running against a closed door at 47-50s, with an animated vehicle.
        pairs = (("navray_progress_pepper_35s.png", "navray_progress_pepper_38s.png", False),
                 ("navray_blocked_pepper_44s.png", "navray_blocked_pepper_47s.png", True),
                 ("navray_blocked_door_47s.png", "navray_blocked_door_50s.png", True))
        for first, second, same in pairs:
            with self.subTest(first=first, second=second):
                a = NavRayRunner.scene_thumbnail(rgb(first))
                b = NavRayRunner.scene_thumbnail(rgb(second))
                self.assertEqual(NavRayRunner.same_scene(a, b), same)

    def test_moving_animation_does_not_prevent_stuck_recovery(self):
        # Alternate two real frames of the 23:07:58 obstacle. The animated player
        # and swaying view defeat the old consecutive-frame difference check.
        frames = (rgb("navray_blocked_pepper_44s.png"), rgb("navray_blocked_pepper_47s.png"))
        runner, _ = make_runner(lambda i: frames[i % 2])
        runner.px_per_count = -4.2
        view = pathvision_find(AHEAD)
        runner.find_dashes = lambda *args, **kwargs: view
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        self.assertEqual(reason, "stuck against something")
        self.assertLess(runner.clock(), 6.0)
        self.assertEqual(runner.backend.events[-1], ("key", "w", False))

    def test_deliberate_turn_in_place_does_not_count_as_stuck_walking(self):
        from unittest.mock import patch
        view = pathvision_find(STAIRS)
        runner, _ = make_runner(lambda i: STAIRS)
        runner.px_per_count = -4.2
        runner.find_dashes = lambda *args, **kwargs: view
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        with patch.object(navray_runner, "TETHER_SECONDS", 2.0):
            _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        self.assertEqual(reason, "tether time limit")
        self.assertIn(("key", "w", False), runner.backend.events)

    def test_a_real_turn_onto_pale_tiles_keeps_the_path_lined_up(self):
        # 22:24:13 video at 52.7s: the old detector lost these near-centre dashes
        # after turning and the walk backed out of an already aligned heading.
        frame = rgb("navray_pale_tiles_after_turn_1920.jpg")
        runner, _ = make_runner(lambda i: frame)
        runner.dash_color = 70
        got = runner.evaluate(None, 0)
        self.assertIsNotNone(got)
        view, seen_frame = got
        self.assertLess(abs(runner.aim_error(view, seen_frame)), navray_runner.TURN_FIRST)

    def test_it_walks_when_the_dashes_ahead_are_lined_up_and_looks_all_round_before_reporting_arrival(self):
        runner, events = make_runner(lambda i: AHEAD if i <= 24 else moving_dark(i))
        runner.walk()
        recorded = runner.backend.events
        self.assertIn(("key", "w", True), recorded)
        self.assertIn(("key", "w", False), recorded)
        self.assertIn(("key", "shift", True), recorded)                                    # running
        self.assertFalse(runner.backend.held_keys)                                            # everything released
        done = [p for k, p in events if k == "done"]
        self.assertEqual(len(done), 1)
        self.assertIn("arrived", done[0].lower())
        statuses = [p for k, p in events if k == "status"]
        self.assertTrue(any("searching nearby from a stop" in p for p in statuses))
        turns = after_calibration(runner)
        self.assertTrue(any(t > 0 for t in turns) and any(t < 0 for t in turns))       # look to both sides

    def test_it_turns_to_line_the_dashes_up_before_it_walks(self):
        runner, _ = make_runner(lambda i: STAIRS)                        # the dashes lie far to the left
        with self.assertRaisesRegex(Interrupted, "does not line the dashes up"):   # the fake mouse turns nothing
            runner.walk()
        turns = after_calibration(runner)
        self.assertTrue(turns and all(t < 0 for t in turns), turns)                # left, and in one bold move each
        self.assertFalse([e for e in runner.backend.events if e[:2] == ("key", "w") and e[2]])   # never walked unaligned

    def test_the_nav_ray_menu_item_is_found_even_when_lit_and_unreadable(self):
        # Live (28 Oct, 2560 x 1440): the lit NAV-RAY item was missing from the OCR reading of the top menu.
        words = [("MISSIONS", 1178, 14, 112, 22), ("TEAM", 1429, 14, 62, 22), ("OPTIONS", 1513, 14, 100, 22)]
        self.assertEqual(NavRayRunner.navray_menu_point(words), (1359, 25))
        self.assertEqual(NavRayRunner.navray_menu_point(words + [("NAV-RAY", 1310, 14, 100, 22)]), (1360, 25))
        self.assertIsNone(NavRayRunner.navray_menu_point([("OPTIONS", 1513, 14, 100, 22)]))

    def test_a_moderate_heading_error_is_corrected_on_the_move_once_turning_is_calibrated(self):
        frame = np.roll(AHEAD, -300, axis=1)                      # the dashes lie to the left, not far
        runner, _ = make_runner(lambda i: frame)
        runner.area_name = lambda: ""
        runner.calibrate_turn = lambda: -4.2
        runner.vitals = lambda *args: None
        view = pathvision_find(frame)
        error = runner.aim_error(view, frame)
        self.assertTrue(navray_runner.TURN_FIRST < abs(error) < navray_runner.TETHER_TURN_IN_PLACE, error)
        runner.evaluate = lambda *args, **kwargs: (view, frame)
        legs = []

        def leg(view, track, reader, state, tether=False):
            legs.append(tether)
            raise Interrupted("test complete")
        runner.walk_leg = leg
        with self.assertRaisesRegex(Interrupted, "test complete"):
            runner.walk()
        self.assertEqual(legs, [True])                            # straight into the tethered walk
        self.assertFalse([e for e in runner.backend.events if e[0] == "rel"])     # no stop-and-turn first

    def test_three_looks_must_agree_before_a_move_and_disagreeing_ones_are_repeated(self):
        runner, _ = make_runner(lambda i: AHEAD)
        looks = {"n": 0}
        errors = iter([-.20, .15, .02,  .01, .02, .015])       # first round disagrees, second agrees

        def aim_error(view, frame):
            looks["n"] += 1
            return next(errors)
        runner.aim_error = aim_error
        got = runner.evaluate(None, 0)
        self.assertIsNotNone(got)
        self.assertGreaterEqual(looks["n"], 6)                   # it looked again rather than trusting round one

    def test_it_steers_gently_while_walking_so_a_drift_does_not_grow_into_a_veer(self):
        drifted = np.roll(AHEAD, -160, axis=1)             # the dashes lie a little to the left of straight ahead
        runner, _ = make_runner(lambda i: drifted)
        runner.px_per_count = -4.2
        view = pathvision_find(drifted)
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state)
        self.assertEqual(reason, "stuck against something")    # identical frames: a wall, after steering
        moves = [e[1] for e in runner.backend.events if e[0] == "rel"]
        self.assertTrue(moves and all(m < 0 for m in moves), moves)        # left, towards the dashes
        self.assertTrue(all(abs(m) <= navray_runner.CAL_MAX_PX/4.2 + 1 for m in moves), moves)

    def test_it_stops_immediately_when_dashes_drop_out_of_view(self):
        seen = {"n": 0}

        def frames(i):
            seen["n"] += 1
            return np.roll(AHEAD, (i % 7)*5, axis=1) if i <= 4 else moving_dark(i)
        runner, _ = make_runner(frames)
        view = pathvision_find(AHEAD)
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        started = runner.clock()
        _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state)
        self.assertEqual(reason, "lost the dashes")
        self.assertLess(runner.clock() - started, 1.0)
        self.assertNotIn("w", runner.backend.held_keys)

    def test_near_a_zone_line_it_walks_on_when_the_dashes_stop_until_the_zone_changes(self):
        # Live (28 Oct): "Entering new district: PLAZA SEC-3" showed, the dashes stopped, and the walk stood searching.
        runner, _ = make_runner(lambda i: AHEAD if i <= 3 else moving_dark(i))
        runner.px_per_count = -4.2
        runner.zone_seen = 0.0
        runner.area_name = lambda: "PLAZA SEC-2" if runner.clock() < 3 else "PLAZA SEC-3"
        view = pathvision_find(AHEAD)
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        self.assertEqual(reason, "entered a new zone")
        self.assertGreater(runner.clock(), 3)
        w = [e[2] for e in runner.backend.events if e[:2] == ("key", "w")]
        self.assertEqual(w, [True, False])                         # held all the way through, let go at the end

    def test_a_fading_banner_is_still_recognised_and_its_place_ignored_for_a_while(self):
        # Live (28 Oct): the OCR read a fading banner as "Entering.peygjstrict", and one or two of its letters were
        # still chained as dashes when too few showed to make a row.
        runner, _ = make_runner(lambda i: DARK)
        runner.detector.text_reader = lambda: type("R", (), {"read_words": lambda self, g: [("Entering.peygjstrict", 0, 0, 1, 1)]})()
        frame = cv2.cvtColor(DARK, cv2.COLOR_RGB2BGR)
        self.assertTrue(runner.district_banner(frame, (500, 590, 1500, 620)))
        seen = []
        original = navray_runner.pathvision.find_path
        navray_runner.pathvision.find_path = lambda bgr, ignore=(), **kwargs: seen.append(ignore)
        try:
            runner.dash_color = 70
            runner.find_dashes(frame)
            runner.sleep(navray_runner.BANNER_HOLD + 1)
            runner.find_dashes(frame)
        finally:
            navray_runner.pathvision.find_path = original
        self.assertEqual([tuple(round(v) for v in box) for box in seen[0]], [(500, 590, 1500, 620)])
        self.assertEqual(seen[1], ())                              # forgotten once the hold is over

    def test_one_misread_location_name_is_not_a_new_zone(self):
        # Live (28 Oct, 18:08): a garbled reading of the Location ended the push towards the zone line early.
        readings = iter(["PLAZA SEC-2", "PLAZA SEC-2", "_PLAC-2_J", "PLAZA SEC-2", "", "PLAZA SEC-2", "PLAZA SEC-3",
                         "PLAZA SEC-3"])
        runner, _ = make_runner(lambda i: DARK)
        runner.area_name = lambda: next(readings)
        state, results = {}, []
        for second in range(8):
            results.append(runner.zone_changed(state, float(second)))
        self.assertEqual(results, [False]*7 + [True])             # only the second reading of PLAZA SEC-3 counts

    def test_a_wall_ends_the_push_towards_a_zone_line(self):
        # Live (28 Oct, 18:08): the corridor bent before the zone line and the push ran into the corner.
        runner, _ = make_runner(lambda i: AHEAD if i <= 3 else DARK)        # an unchanging view: a wall
        runner.px_per_count = -4.2
        runner.zone_seen = 0.0
        runner.area_name = lambda: "PLAZA SEC-2"
        view = pathvision_find(AHEAD)
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        self.assertEqual(reason, "stuck against something")
        self.assertLess(runner.clock(), navray_runner.ZONE_PUSH_SECONDS)

    def test_near_a_zone_line_with_no_dashes_it_follows_the_corridor(self):
        # The user's rule (28 Oct): the dashes vanish near a zone change; walk the corridor itself until the zone
        # changes. Open way to the left: steer left while walking. A wall ahead, open on the right: stop and turn right.
        for way, side, expect_turn, expect_walking in ((-.2, 0, -1, True), (None, 1, 1, False)):
            with self.subTest(way=way, side=side):
                runner, _ = make_runner(lambda i: AHEAD if i <= 3 else moving_dark(i))
                runner.px_per_count = -4.2
                runner.zone_seen = 0.0
                runner.area_name = lambda: "PLAZA SEC-1"
                runner.corridor = lambda bgr, _w=way, _s=side: (_w, _s)
                view = pathvision_find(AHEAD)
                state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
                with patch.object(navray_runner, "ZONE_PUSH_SECONDS", 3.0):
                    runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
                moves = [e[1] for e in runner.backend.events if e[0] == "rel"]
                turns = moves[-5:]
                self.assertTrue(turns and all(m*expect_turn > 0 for m in turns), turns)   # right = positive counts here
                events = runner.backend.events
                released = max(i for i, e in enumerate(events) if e == ("key", "w", False))
                last_turn = max(i for i, e in enumerate(events) if e[0] == "rel")
                self.assertEqual(released > last_turn, expect_walking)   # steering on the move, or stopped to turn

    def test_walking_the_sector_map_turns_onto_the_planned_path_and_ends_in_the_new_zone(self):
        # The dashes vanish near a zone change; the live position and the game's own sector map give the way to the
        # exit. A simulated character: the mouse turns its heading (the opposite way to the first guess, which the
        # walk must learn), W moves it forward, and crossing Z = 600 is the zone change.
        import telemetry
        runner, events = make_runner(lambda i: moving_dark(i))
        runner.px_per_count = -4.0
        backend = runner.backend
        body = {"x": 0.0, "z": 0.0, "bearing": 90.0}             # facing +X; the exit is due +Z
        original = backend.move_relative

        def move(dx, dy):
            original(dx, dy)
            body["bearing"] = (body["bearing"] - .18*dx) % 360   # the mouse turns the other way to the guess
        backend.move_relative = move

        class Feed:
            def latest(self, max_age=1.0, now=None):
                if "w" in backend.held_keys:
                    rad = math.radians(body["bearing"])
                    body["x"] += 20*math.sin(rad); body["z"] += 20*math.cos(rad)
                return telemetry.Sample(runner.clock(), 2 if body["z"] > 600 else 1, 270.0, body["x"], 0.0, body["z"],
                                        (180.0 - body["bearing"]) % 360)

        class Exit:
            label, bearing, beyond, world = "3", 0.0, (0.0, 650.0), (0.0, 600.0)

        class Planner:
            def plan_to_exit(self, here, hint):
                return Exit(), [here, (0.0, 300.0), (0.0, 600.0)]
        runner.feed = Feed()
        runner.planner_for = lambda sample: Planner()
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        result = runner.map_walk(runner.detector.text_reader(), state, "the dashes ended at the zone line")
        self.assertEqual(result, "entered a new zone")
        self.assertLess(abs(body["x"]), 120)                       # it stayed near the planned line X = 0
        self.assertLess(runner.deg_per_count, 0)                   # learned which way the mouse really turns
        self.assertNotIn("w", backend.held_keys)
        self.assertTrue(any("walking the sector map to exit 3" in p for k, p in events if k == "status"))

    def test_arrival_waits_for_the_location_to_change_and_trusts_the_banner(self):
        # Live (28 Oct 23:47): after the loading screen the Location still read the old sector, so arriving in
        # PEPPER PARK SEC-1 was missed.
        runner, events = make_runner(lambda i: DARK)
        runner.route_destination = "NEOCRON CITY SECTORS > PEPPER PARK SEC-1"
        runner.current_area = "plazasec3"
        readings = iter(["PLAZA SEC-3", "PLAZA SEC-3", "PEPPER PARK SEC-1"])
        runner.area_name = lambda: next(readings, "PEPPER PARK SEC-1")
        runner.finish_route = lambda started: None
        self.assertTrue(runner.entered_zone(0.0))
        self.assertIn("Nav-Ray: arrived in PEPPER PARK SEC-1.", [p for k, p in events if k == "done"])
        runner, events = make_runner(lambda i: DARK)                 # the Location cannot be read: the banner decides
        runner.route_destination = "NEOCRON CITY SECTORS > PEPPER PARK SEC-1"
        runner.current_area, runner.banner_name = "plazasec3", "pepperparksec1"
        runner.area_name = lambda: ""
        runner.finish_route = lambda started: None
        self.assertTrue(runner.entered_zone(0.0))

    def test_a_halt_at_the_exit_while_the_zone_loads_is_not_a_wall(self):
        # Live (28 Oct 23:55): the position froze at the exit while Plaza 1 loaded; the map walk called it stuck.
        import telemetry
        runner, _ = make_runner(lambda i: moving_dark(i))
        runner.px_per_count = -4.0
        frozen = {"sector": 101}

        class Feed:
            def latest(self, max_age=1.0, now=None):
                if runner.clock() > 4.0:
                    frozen["sector"] = 1                                 # the new zone, after the halt
                return telemetry.Sample(runner.clock(), frozen["sector"], 270.0, 0.0, 0.0, 590.0, 180.0)

        class Exit:
            label, bearing, beyond, world = "1", 0.0, (0.0, 650.0), (0.0, 600.0)

        class Planner:
            def plan_to_exit(self, here, hint):
                return Exit(), [here, (0.0, 600.0)]
        runner.feed, runner.planner_for = Feed(), (lambda sample: Planner())
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        self.assertEqual(runner.map_walk(runner.detector.text_reader(), state, "test"), "entered a new zone")

    def test_a_gap_in_the_dashes_is_crossed_on_the_tracked_route_only_when_it_is_sure(self):
        import telemetry
        runner, _ = make_runner(lambda i: DARK)
        runner.px_per_count = -4.0
        pose = telemetry.Sample(0.0, 1, 270.0, 0.0, 0.0, 0.0, 90.0)

        class Tracker:
            def __init__(self, confidence):
                self.confidence = confidence

            def steer(self, sample):
                return type("Steer", (), {"error": 20.0, "point": (100.0, 0.0), "confidence": self.confidence})()
        runner.tracker = Tracker(.3)
        self.assertFalse(runner.follow_track(pose, 2000))                  # not sure enough: the old behaviour
        self.assertFalse([e for e in runner.backend.events if e[0] == "rel"])
        runner.tracker = Tracker(.9)
        self.assertTrue(runner.follow_track(pose, 2000))
        self.assertTrue([e for e in runner.backend.events if e[0] == "rel"])   # steered towards the route
        self.assertFalse(runner.follow_track(None, 2000))                  # no live position: no tracked route

    def test_the_live_sector_changing_is_a_zone_change_and_names_the_arrival(self):
        # Live (29 Oct 01:18): the sector became PEPPER PARK SEC-1 (5) at 172 s, unnoticed; the walk turned back.
        import telemetry
        runner, events = make_runner(lambda i: DARK)
        sector = {"id": 101}

        class Feed:
            def latest(self, max_age=1.0, now=None):
                return telemetry.Sample(runner.clock(), sector["id"], 270.0, 10.0, 0.0, 20.0, 90.0)
        runner.feed = Feed()
        state = {"health": None, "health_checked": runner.clock(), "last_path": 0.0}
        runner.vitals(None, DARK, state)
        self.assertNotIn("zoned", state)
        sector["id"] = 5
        runner.vitals(None, DARK, state)
        self.assertTrue(state.get("zoned"))
        runner.sector_name = lambda: "PEPPER PARK SEC-1"
        runner.route_destination = "NEOCRON CITY SECTORS > PEPPER PARK SEC-1"
        runner.current_area = "plazasec3"
        runner.finish_route = lambda started: None
        self.assertTrue(runner.entered_zone(0.0))

    def test_the_exit_is_chosen_by_the_way_the_walk_was_going_not_the_facing(self):
        import telemetry, mapplan
        runner, _ = make_runner(lambda i: DARK)
        runner.trail = [(0.0, 0.0, 0.0, 101), (2.0, 0.0, 400.0, 101)]          # going +Z for the last seconds
        facing_back = telemetry.Sample(3.0, 101, 270.0, 0.0, 0.0, 420.0, 0.0)  # heading 0 = facing -Z (a wall turn)
        self.assertAlmostEqual(runner.travel_bearing(facing_back), mapplan.bearing_of(0.0, 420.0))
        runner.trail = []
        self.assertAlmostEqual(runner.travel_bearing(facing_back), runner.map_bearing(facing_back))

    def test_the_navmesh_picks_the_exit_that_leads_to_the_destination(self):
        import navmesh, telemetry
        runner, _ = make_runner(lambda i: DARK)
        runner.route_destination = "NEOCRON CITY SECTORS > PLAZA SEC-3"
        asked = {}

        def exit_(name, to, known=True, length=500.0):
            return navmesh.Exit(name, 0, 0, 0, 1, None, to, 1 if known else 0, known, 0.0, 300.0, length, True)

        class Planner:
            def exits(self):
                return [exit_("WorldChange4", "PLAZA SEC-2", length=200.0), exit_("WorldChange3", "PLAZA SEC-3"),
                        exit_("WorldChange9", "PLAZA SEC-3", known=False)]

            def plan_to_exit(self, name=None, bearing=None):
                asked.update(name=name, bearing=bearing)
                return navmesh.Plan(1, "PLAZA SEC-1", (0, 0), [(0.0, 0.0), (0.0, 400.0)], [0.0, 0.0], True, 400.0,
                                    exit_(name or "WorldChange4", "PLAZA SEC-3"))
        runner.navplanner = Planner()
        sample = telemetry.Sample(0.0, 1, 270.0, 0.0, 0.0, 0.0, 90.0)
        exit_found, path = runner.navmesh_route(sample)
        self.assertEqual(asked["name"], "WorldChange3")                 # leads to the destination, though longer
        self.assertEqual(path[-1], (0.0, 400.0))
        self.assertGreater(exit_found.beyond[1], 400.0)                 # the push goes on past the exit
        runner.route_destination = "NEOCRON CITY SECTORS > PEPPER PARK SEC-1"     # no exit leads straight there
        runner.navmesh_route(sample)
        self.assertIsNone(asked["name"])
        self.assertIsNotNone(asked["bearing"])

    def test_on_a_navmesh_path_it_aims_at_the_next_corner_and_a_long_halt_is_a_wall(self):
        # Live (29 Oct 01:44): aiming 220 units on along an L-shaped path cut the corner into the wall, and the halt
        # there was waited out for 12 s as if the zone were loading.
        import telemetry
        from types import SimpleNamespace
        runner, _ = make_runner(lambda i: moving_dark(i))
        runner.px_per_count = -4.0
        aims = []
        original = runner.map_turn
        runner.map_turn = lambda degrees, width: aims.append(degrees) or 0

        class Feed:                                                   # facing +Z (bearing 0), never moving: a wall
            def latest(self, max_age=1.0, now=None):
                return telemetry.Sample(runner.clock(), 101, 270.0, 0.0, 0.0, 0.0, 180.0)
        runner.feed = Feed()
        corner = SimpleNamespace(label="X (navmesh)", world=(300.0, 100.0), beyond=(360.0, 100.0), corners=True)
        runner.navmesh_route = lambda sample: (corner, [(0.0, 0.0), (0.0, 100.0), (300.0, 100.0)])
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        started = runner.clock()
        result = runner.map_walk(runner.detector.text_reader(), state, "test")
        self.assertEqual(result, "stuck against something")
        self.assertLess(runner.clock() - started, navray_runner.MAP_STUCK_SECONDS + navray_runner.MAP_LOAD_SECONDS + 2)
        self.assertFalse([a for a in aims if abs(a) > 20])            # aimed at the corner straight ahead, not past it

    def test_a_box_label_is_never_taken_for_a_door(self):
        # Live (29 Oct 01:44): the walk right-clicked a ROTTEN BOX it was stuck against and looted it.
        frame = rgb("navray_blocked_door_50s.png")
        reads = {"words": [("ROTTEN", 0, 0, 1, 1), ("BOX", 0, 0, 1, 1)]}
        reader = type("R", (), {"read_words": lambda self, image, up=3: reads["words"]})()
        self.assertFalse(navray_runner.door_target(frame, 70, reader))
        reads["words"] = [("TECH", 0, 0, 1, 1)]                            # a half-read door label: the picture decides
        self.assertTrue(navray_runner.door_target(frame, 70, reader))
        reads["words"] = [("DOOR", 0, 0, 1, 1)]
        self.assertTrue(navray_runner.door_target(frame, 70, reader))

    def test_stuck_is_seen_from_the_live_position_and_it_steps_round(self):
        import telemetry
        runner, events = make_runner(lambda i: AHEAD if i % 2 else np.roll(AHEAD, 9, axis=1))   # the picture keeps changing
        runner.px_per_count = -4.0

        class Feed:                                                    # but the character does not move
            def latest(self, max_age=1.0, now=None):
                return telemetry.Sample(runner.clock(), 1, 270.0, 100.0, 0.0, 200.0, 90.0)
        runner.feed = Feed()
        view = pathvision_find(AHEAD)
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        self.assertEqual(reason, "stuck against something")
        self.assertLess(runner.clock(), 4.0)
        self.assertTrue(runner.sidestep(-1, 2000))
        rel = [e[1] for e in runner.backend.events if e[0] == "rel"]
        self.assertEqual(rel[-2], -rel[-1])                                # turned aside, then back
        self.assertNotIn(("key", "s", True), runner.backend.events)       # never backs away
        self.assertNotIn("w", runner.backend.held_keys)

    def test_without_a_live_position_the_map_walk_steps_aside(self):
        runner, _ = make_runner(lambda i: DARK)
        runner.feed = None
        self.assertIsNone(runner.map_walk(runner.detector.text_reader(), {}, "test"))

    def test_away_from_a_zone_line_losing_the_dashes_still_stops_at_once(self):
        runner, _ = make_runner(lambda i: AHEAD if i <= 3 else moving_dark(i))
        runner.px_per_count = -4.2
        view = pathvision_find(AHEAD)
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        _, _, reason = runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        self.assertEqual(reason, "lost the dashes")
        self.assertLess(runner.clock(), 2.0)

    def test_the_banner_of_the_zone_just_entered_is_not_a_zone_line_ahead(self):
        runner, _ = make_runner(lambda i: DARK)
        runner.area_name = lambda: "PLAZA SEC-3"
        runner.entered_zone(runner.clock())
        runner.detector.text_reader = lambda: type("R", (), {"read_words": lambda self, g: [("Entering", 0, 0, 1, 1)]})()
        box = (10, 10, 50, 20)
        self.assertTrue(runner.district_banner(DARK, box))         # its letters are still ignored...
        self.assertFalse(runner.near_zone(runner.clock()))         # ...but it does not mean a zone line is ahead

    def test_tethered_walking_is_one_continuous_run_that_keeps_steering(self):
        drifted = np.roll(AHEAD, -160, axis=1)            # the dashes lie a little to the left
        frames = lambda i: np.roll(drifted, (i % 5)*3, axis=1)
        runner, _ = make_runner(frames)
        runner.px_per_count = -4.2
        view = pathvision_find(drifted)
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        presses = [e for e in runner.backend.events if e[:2] == ("key", "w")]
        self.assertEqual(presses, [("key", "w", True), ("key", "w", False)])        # held the whole time, released at the end
        steering = [e[1] for e in runner.backend.events if e[0] == "rel"]
        self.assertGreaterEqual(len(steering), 3)                                    # corrected on look after look
        self.assertTrue(all(m < 0 for m in steering), steering)                      # always towards the dashes (left)

    def test_a_large_heading_error_turns_in_place_then_resumes_while_tethered(self):
        runner, _ = make_runner(lambda i: np.roll(AHEAD, -520 + min(i, 12)*45, axis=1))   # far off, swinging into line
        runner.px_per_count = -4.2
        view = pathvision_find(np.roll(AHEAD, -520, axis=1))
        state = {"health": None, "health_checked": 0.0, "last_path": 0.0}
        runner.walk_leg(view, view, runner.detector.text_reader(), state, tether=True)
        w = [e[2] for e in runner.backend.events if e[:2] == ("key", "w")]
        self.assertIn(False, w[:-1])                      # it stopped to turn in place...
        self.assertTrue(w.count(True) >= 2)               # ...and went on again

    def test_the_dash_colour_comes_from_the_hud_not_from_whatever_looks_like_a_path(self):
        # Live (video of a run): red HUD scheme, red dashes on the floor, and a wall of GREEN signs in view.
        # Learning the colour from the first path-like thing locked the macro onto the green signs; it walked into them.
        import cv2 as cv
        frame = cv.imread(str(FIXTURES / "navray_red_hud_green_signs_1920.jpg"))
        runner, events = make_runner(lambda i: frame)
        view = runner.find_dashes(frame)
        self.assertIsNotNone(view)
        self.assertLessEqual(runner.dash_color, 12)                                 # a red hue (it wraps round 0)
        self.assertGreaterEqual(len(view.points), 4)
        self.assertTrue(all(y > 300 for _, y in view.points))                        # the floor dashes, not the signs above
        self.assertTrue(any("HUD colour" in p for k, p in events if k == "status"))
        green_runner, _ = make_runner(lambda i: frame)
        green_runner.dash_color = "green"                                            # what the old logic had locked onto
        wrong = green_runner.find_dashes(frame)
        self.assertTrue(wrong is None or len(wrong.points) <= 3)                     # only the sign marks

    def test_after_a_turn_the_old_path_line_is_not_used_to_filter_the_new_picture(self):
        # Live (video): every turn was followed by "the turn lost the dashes; coming back" because the new frames were
        # filtered against the path line of the picture before the turn, which had slid hundreds of pixels.
        seen_priors = []
        runner, _ = make_runner(lambda i: STAIRS)
        original = runner.find_dashes

        def find_dashes(bgr, ignore=(), prior=None, tube=.18):
            seen_priors.append(prior)
            return original(bgr, ignore=ignore, prior=prior, tube=tube)
        runner.find_dashes = find_dashes
        runner.turn = lambda error, width: -45                                       # a turn happens, the fake picture does not change
        with self.assertRaises(Interrupted):
            runner.walk()
        first_turn_at = next(i for i, p in enumerate(seen_priors) if p is not None) if any(p is not None for p in seen_priors) else None
        # the evaluation straight after a turn must be a clean look at the whole picture (no prior)
        self.assertTrue(all(p is None for p in seen_priors[:6]), seen_priors[:6])

    def test_it_reads_the_next_four_dashes(self):
        view = pathvision_find(AHEAD)
        ahead = NavRayRunner.next_dashes(view, AHEAD.shape[0])
        self.assertEqual(len(ahead), navray_runner.DASHES_PER_LEG)
        self.assertEqual(ahead, sorted(ahead, key=lambda p: -p[1]))                # nearest first

    def test_no_path_at_all_scans_all_the_way_round_before_giving_up(self):
        runner, events = make_runner(lambda i: DARK)
        with self.assertRaisesRegex(Interrupted, "turning all the way round"):
            runner.walk()
        turns = after_calibration(runner)
        self.assertTrue(turns and all(t > 0 for t in turns))                       # sweeping round in one direction
        self.assertFalse([e for e in runner.backend.events if e[:2] == ("key", "w") and e[2]])   # never walked blind

    def test_a_loading_screen_that_never_ends_stops_the_walk(self):
        runner, _ = make_runner(lambda i: AHEAD if i < 4 else np.zeros((1125, 2000, 3), np.uint8))
        with self.assertRaisesRegex(Interrupted, "Loading screen"):
            runner.walk()
        self.assertGreaterEqual(runner.clock(), navray_runner.ZONE_LOAD_SECONDS)     # waited it out first

    def test_a_loading_screen_is_waited_out_and_the_walk_goes_on_in_the_new_zone(self):
        black = np.zeros((1125, 2000, 3), np.uint8)
        runner, events = make_runner(lambda i: AHEAD if i < 4 else black if i < 40 else DARK)
        runner.area_name = lambda: ""
        with self.assertRaisesRegex(Interrupted, "turning all the way round"):     # the new zone shows no dashes here
            runner.walk()
        statuses = [p for k, p in events if k == "status"]
        self.assertTrue(any("loading screen" in p for p in statuses), statuses)
        self.assertTrue(any("entered a new zone" in p for p in statuses), statuses)

    def test_arriving_in_the_destination_zone_ends_the_walk(self):
        black = np.zeros((1125, 2000, 3), np.uint8)
        runner, events = make_runner(lambda i: AHEAD if i < 4 else black if i < 40 else DARK)
        runner.route_destination = "NEOCRON CITY SECTORS > PEPPER PARK SEC-1"
        runner.area_name = lambda: "PEPPER PARK SEC-1"
        runner.walk()
        done = [p for k, p in events if k == "done"]
        self.assertEqual(done, ["Nav-Ray: arrived in PEPPER PARK SEC-1."])
        self.assertFalse(runner.backend.held_keys)

    def test_an_unchanging_view_while_walking_backs_off_and_looks_elsewhere_before_giving_up(self):
        runner, events = make_runner(lambda i: AHEAD)
        with self.assertRaisesRegex(Interrupted, "Not moving"):
            runner.walk()
        recorded = runner.backend.events
        self.assertNotIn(("key", "s", True), recorded)                             # search without running backward
        self.assertTrue(any("stuck" in p for k, p in events if k == "status"))      # and said so
        self.assertFalse(runner.backend.held_keys)

    def test_a_health_drop_stops_the_walk(self):
        runner, _ = make_runner(lambda i: np.roll(AHEAD, (i % 5)*4, axis=1), health=(972, 972, 800))   # a moving picture, dashes ahead
        with self.assertRaisesRegex(Interrupted, "Health dropped"):
            runner.walk()
        self.assertFalse(runner.backend.held_keys)

    @staticmethod
    def zone_runner():
        """A calibrated walk (-4 px per count, 2000 wide) that sees AHEAD's dashes once, then none."""
        runner, events = make_runner(lambda i: DARK)
        runner.area_name = lambda: "PLAZA SEC-2"
        runner.calibrate_turn = lambda: -4.0
        runner.vitals = lambda *args: None
        runner.try_open_door = lambda reader: False
        view = pathvision_find(AHEAD)
        sightings = {"n": 2}                               # a quick look while sweeping, then confirmed standing
        runner.looks = 0

        def evaluate(track, lost, quick=False):
            runner.looks += 1
            if sightings["n"]:
                sightings["n"] -= 1
                return view, AHEAD
            return None
        runner.evaluate = evaluate
        return runner, events

    @staticmethod
    def rel_total(runner):
        return sum(e[1] for e in runner.backend.events if e[0] == "rel")

    def test_near_a_zone_line_a_wall_turns_the_push_to_each_side_then_looks_all_round_before_giving_up(self):
        # Live (28 Oct, 20:00): the corridor turned right just before the zone line, the push ran into the corner, and
        # a local search ended the walk with "path lost or ended" 3 m from the line, still in PLAZA SEC-2.
        runner, events = self.zone_runner()
        legs = []

        def leg(view, track, reader, state, tether=False):
            legs.append((view is not None, tether, runner.near_zone(runner.clock()), self.rel_total(runner)))
            if len(legs) == 1:
                runner.zone_seen = runner.clock()          # "Entering new district" was read on the way
                state["last_side"] = 1                     # the dashes bent right before they stopped
            runner.sleep(2.0)
            return view, 0, "stuck against something"
        runner.sidestep = lambda side, width: False          # this test is about the pushes
        runner.walk_leg = leg
        runner.walk()
        quarter = round(navray_runner.ZONE_SIDE_TURN*2000/4.0)
        self.assertEqual([l[:3] for l in legs[1:]], [(False, True, True)]*2)            # two pushes with no dashes
        self.assertEqual(len(legs), 1 + navray_runner.ZONE_SIDE_TRIES)                    # and no more
        self.assertEqual([l[3] for l in legs], [0, quarter, -quarter])     # right first, then left, from the first heading
        statuses = [p for k, p in events if k == "status"]
        self.assertTrue(any("all round" in p for p in statuses), statuses)
        local = round(navray_runner.LOCAL_SCAN_WIDTH*2000/4.0)
        self.assertGreater(abs(self.rel_total(runner) - -quarter), 2*local)    # swept further than a local search
        done = [p for k, p in events if k == "done"]
        self.assertEqual(done, ["Nav-Ray: path lost or ended. Arrived, or the route was lost."])
        self.assertFalse(runner.backend.held_keys)

    def test_near_a_zone_line_losing_the_dashes_looks_all_round_then_pushes_on(self):
        for when in ("before", "during"):                  # the banner read before the dashes went, or while searching
            with self.subTest(when=when):
                runner, events = self.zone_runner()
                original = runner.evaluate

                def evaluate(track, lost, quick=False, _original=original, _when=when, _runner=runner):
                    if _when == "during" and _runner.looks == 5:
                        _runner.zone_seen = _runner.clock()
                    return _original(track, lost, quick)
                runner.evaluate = evaluate
                legs, offsets = [], []

                def leg(view, track, reader, state, tether=False, _runner=runner, _when=when):
                    legs.append(view is not None)
                    if len(legs) == 1:
                        if _when == "before":
                            _runner.zone_seen = _runner.clock()
                        return view, 0, "lost the dashes"
                    raise Interrupted("test complete")
                runner.walk_leg = leg
                moves = runner.backend.move_relative

                def move(dx, dy, _moves=moves):
                    _moves(dx, dy)
                    offsets.append(self.rel_total(runner))
                runner.backend.move_relative = move
                with self.assertRaisesRegex(Interrupted, "test complete"):
                    runner.walk()
                self.assertEqual(legs, [True, False])                  # the second leg is a push with no dashes in view
                self.assertFalse([k for k, p in events if k == "done"])
                local = round(navray_runner.LOCAL_SCAN_WIDTH*2000/4.0)
                if when == "before":
                    # Live (28 Oct 21:53): the dashes end at the zone line; walk straight on, do not spin round first.
                    self.assertLess(max((abs(o) for o in offsets), default=0), local)
                else:
                    self.assertGreater(max(abs(o) for o in offsets), 2*local)    # beyond where a local search reaches

    def test_a_turn_that_keeps_losing_the_dashes_comes_back_once_then_steps_towards_them(self):
        # Live (28 Oct, 19:37): "turn N, aim -0.3, 3 marks, nearest (392, 981)", "the turn lost the dashes; coming
        # back", found again, turn, lost... six times, then "path lost or ended". The marks were near the feet.
        far = np.roll(AHEAD, -700, axis=1)                 # aim -.34: a stop-and-turn after a leg
        runner, events = make_runner(lambda i: far)
        runner.area_name = lambda: ""
        runner.calibrate_turn = lambda: -4.0
        runner.vitals = lambda *args: None
        view = pathvision_find(far)
        visible = {"on": True}

        def turn(error, width):
            visible["on"] = False                          # turning to the marks hides them under the body
            runner.last_turn = -100
            return -100
        runner.turn = turn
        moves = runner.backend.move_relative

        def move(dx, dy):
            visible["on"] = True                           # coming back, or a sweep, finds them again
            moves(dx, dy)
        runner.backend.move_relative = move
        runner.evaluate = lambda track, lost, quick=False: (view, far) if visible["on"] else None
        legs = []

        def leg(view, track, reader, state, tether=False):
            legs.append(len([p for k, p in events if k == "status" and p.startswith("Nav-Ray: turn ")]))
            if len(legs) == 1:
                return view, 0, "tether time limit"
            raise Interrupted("test complete")
        runner.walk_leg = leg
        with self.assertRaisesRegex(Interrupted, "test complete"):
            runner.walk()
        statuses = [p for k, p in events if k == "status"]
        self.assertEqual(legs, [0, 2])            # found by the first look: walked at once; after the step: no third turn
        self.assertEqual(len([p for p in statuses if "coming back" in p]), 1)
        self.assertEqual(len([p for p in statuses if "stepping towards" in p]), 1)
        step = statuses.index(next(p for p in statuses if "stepping towards" in p))
        self.assertTrue(any("searching nearby" in p for p in statuses[step:]))
        self.assertEqual([e[2] for e in runner.backend.events if e[:2] == ("key", "w")], [True, False])   # the step


class CornerSteeringTests(unittest.TestCase):
    """At a close corner the macro steers for the way beyond it (a sharp turn), not for the dash in front."""

    @staticmethod
    def view(route, corner, points=None):
        points = tuple(points or route[:2])
        return pathvision.PathView(points, points[-1], 0.0, route=tuple(route), corner=corner)

    def test_a_close_corner_aims_past_it(self):
        route = [(960.0, 1000.0), (960.0, 900.0), (960.0, 800.0), (1100.0, 790.0), (1240.0, 780.0)]
        frame = np.zeros((1080, 1920, 3), np.uint8)
        view = self.view(route, 2)
        self.assertEqual(NavRayRunner.corner_point(view, 1080, 1920), (1170.0, 785.0))
        self.assertGreater(NavRayRunner.steer_error(NavRayRunner, view, frame), navray_runner.CORNER_TURN_IN_PLACE)

    def test_a_far_corner_waits_until_it_is_close(self):
        route = [(960.0, 1000.0), (960.0, 800.0), (960.0, 500.0), (1100.0, 495.0), (1240.0, 490.0)]
        self.assertIsNone(NavRayRunner.corner_point(self.view(route, 2), 1080, 1920))

    def test_a_line_across_the_view_close_by_is_a_turn_onto_its_far_end(self):
        route = [(1000.0, 800.0), (1150.0, 795.0), (1300.0, 790.0)]
        self.assertEqual(NavRayRunner.corner_point(self.view(route, -1), 1080, 1920), (1300.0, 790.0))


class FocusTests(unittest.TestCase):
    def test_a_view_that_swings_too_far_for_one_nudge_is_measured_with_the_next_nudge(self):
        # Live: 150 counts swung the view by hundreds of pixels (certainty .03). A weak reading tries the next nudge.
        readings = iter([(-200.0, .03), (-50.0, .8)])
        original = navray_runner.slide_pixels
        navray_runner.slide_pixels = lambda a, b: next(readings)
        try:
            runner, _ = make_runner(lambda i: STAIRS)
            result = runner.calibrate_turn()
        finally:
            navray_runner.slide_pixels = original
        scene_width = 2000*(navray_runner.SCENE_BOX[2] - navray_runner.SCENE_BOX[0])
        self.assertAlmostEqual(result, -50.0*(scene_width/480)/navray_runner.CAL_NUDGES[1], places=6)

    def test_calibration_measures_how_the_view_slides_per_count(self):
        self.assertAlmostEqual(turning_runner(+1).calibrate_turn(), -2.0, delta=.3)   # scene slides left when turning right
        self.assertAlmostEqual(turning_runner(-1).calibrate_turn(), +2.0, delta=.3)
        static, _ = make_runner(lambda i: STAIRS)
        self.assertIsNone(static.calibrate_turn())                               # nothing moved: no reading

    def test_the_turn_follows_the_dashes_even_with_an_inverted_mouse(self):
        for sign in (+1, -1):
            with self.subTest(sign=sign):
                runner = turning_runner(sign)
                try:
                    runner.walk()
                except Interrupted:
                    pass
                steering = [m for m in after_calibration(runner) if m != 0][:2]
                # the dashes in the frame lie to the left: a normal mouse turns left (negative counts), an inverted one right
                self.assertTrue(steering and all(m*sign < 0 for m in steering), steering)

    def test_one_turn_covers_the_whole_error_in_moves_the_game_can_follow(self):
        runner, _ = make_runner(lambda i: STAIRS)
        runner.px_per_count = -2.0
        runner.wait = lambda seconds, safe_pause=False: None
        total = runner.turn(-.2, 2000)                                           # 400 px to the left
        moves = [e[1] for e in runner.backend.events if e[0] == "rel"]
        self.assertEqual(sum(moves), total)
        self.assertLess(total, 0)
        self.assertTrue(all(abs(m) <= navray_runner.CAL_MAX_PX/2.0 + 1 for m in moves), moves)


class RecordingTests(unittest.TestCase):
    def test_every_status_line_is_saved_with_the_game_frame_and_a_new_run_replaces_the_old_record(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            runner, events = make_runner(lambda i: AHEAD)
            runner.last_frame = AHEAD
            runner.start_recording(folder)
            runner.emit("status", "Nav-Ray: leg 1, 4 dashes ahead")
            runner.emit("status", "Nav-Ray: leg 1 ended after 3s: stuck against something.")
            lines = [json.loads(l) for l in (Path(folder) / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([l["text"] for l in lines], ["Nav-Ray: leg 1, 4 dashes ahead", "Nav-Ray: leg 1 ended after 3s: stuck against something."])
            self.assertTrue(all((Path(folder) / l["frame"]).exists() for l in lines))
            self.assertEqual(len(events), 2)                                        # the normal emit still happens
            again, _ = make_runner(lambda i: AHEAD)
            again.last_frame = AHEAD
            again.start_recording(folder)
            self.assertEqual(list(Path(folder).glob("*.jpg")), [])                  # the old frames are gone
            again.emit("status", "second run")
            self.assertEqual(len(list(Path(folder).glob("*.jpg"))), 1)


class InterfaceModeTests(unittest.TestCase):
    """Tab toggles the game's interactive-UI mode, so the macro must look at the screen, not assume the state."""

    def runner(self, ui_on):
        state = {"ui": ui_on}
        runner, _ = make_runner(lambda i: DARK)
        runner.wait = lambda seconds, safe_pause=False: None
        original = runner.backend.key

        def key(name, down):
            original(name, down)
            if name == "tab" and down:
                state["ui"] = not state["ui"]
        runner.backend.key = key

        class Reader:
            def read_words(self, gray, up=3):
                return [("HYPERCOM", 0, 0, 10, 10), ("INVENTORY", 20, 0, 10, 10)] if state["ui"] else [("Location", 0, 0, 10, 10)]
        return runner, Reader(), state

    def test_it_presses_tab_only_when_the_ui_is_in_the_wrong_state(self):
        for start, want in ((True, False), (False, False), (False, True), (True, True)):
            with self.subTest(start=start, want=want):
                runner, reader, state = self.runner(start)
                self.assertTrue(runner.set_ui(reader, want))
                self.assertEqual(state["ui"], want)
                presses = [e for e in runner.backend.events if e == ("key", "tab", True)]
                self.assertEqual(len(presses), 0 if start == want else 1)


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
        runner.drag = lambda a, b: None
        import navray
        original = navray.selected_row
        navray.selected_row = lambda gray, window, which: 7              # a still capture cannot highlight
        try:
            runner.choose("select", "Faction HQs", reader)
        finally:
            navray.selected_row = original
        # FACTION HQS is the 8th row of the Select list (text at x 204, y 345 in the capture, +100 offset).
        self.assertEqual(len(clicks), 1)
        self.assertLessEqual(abs(clicks[0][0] - (204 + 100 + 60)), 8)
        self.assertLessEqual(abs(clicks[0][1] - (345 + 100 + 8)), 8)
        self.assertEqual(runner.backend.events, [])                    # no wheel events: lists scroll by their thumb

    def test_a_missing_window_or_destination_stops_with_a_clear_reason(self):
        from text_reader import TextReader
        reader = TextReader()
        runner, _ = make_runner(lambda i: np.zeros((1080, 1920, 3), np.uint8))
        runner.detector.text_reader = lambda: reader
        runner.wait = lambda seconds, safe_pause=False: None
        with self.assertRaisesRegex(Interrupted, "Nav-Ray window not found"):
            runner.find_window(reader)


class OccurrenceTests(unittest.TestCase):
    """choose() against a simulated Nav-Ray whose lists scroll only by dragging their scroll thumb."""

    TRACK = 150

    def setUp(self):
        import navray
        self.navray = navray
        self.catalog = navray.load_catalog()
        self.window = navray.NavRay(1000, 1000, 1.0)
        self.original = (navray.read_rows, navray.find_thumb, navray.selected_row)
        self.start = {"select": 0, "destination": 0}
        self.lists = {"select": list(self.catalog), "destination": []}
        self.last = {"which": "select"}
        self.clicks, self.drags = [], []
        runner, self.events = make_runner(lambda i: DARK)
        runner.frame = lambda: DARK
        runner.wait = lambda seconds, safe_pause=False: None
        runner.find_window = lambda reader: self.window
        runner.move = lambda point: None
        runner.click = self.clicks.append

        def thumb(gray, window, which):
            self.last["which"] = which
            size, visible = len(self.lists[which]), navray.LIST_ROWS[which]
            if size <= visible:
                return None
            length = round(self.TRACK*visible/size)
            track_top = self.window.thumb_strip(which)[1] + 14
            top = track_top + round((self.TRACK - length)*self.start[which]/(size - visible))
            return (500, top, top + length)

        def drag(source, destination):
            which = self.last["which"]
            size, visible = len(self.lists[which]), navray.LIST_ROWS[which]
            length = round(self.TRACK*visible/size)
            rows = (destination[1] - source[1])*visible/length
            self.drags.append(rows)
            self.start[which] = max(0, min(size - visible, round(self.start[which] + rows)))
        runner.drag = drag

        def rows(gray, window, which):
            page = self.lists[which][self.start[which]:self.start[which] + navray.LIST_ROWS[which]]
            return list(enumerate(page))
        def selected(gray, window, which):
            # The game highlights a clicked row, unless the click missed every visible row.
            if not self.clicks:
                return None
            dy = navray.DEST_DY if which == "destination" else navray.SELECT_DY
            row = round((self.clicks[-1][1] - (window.y + dy + navray.ROW_H/2))/navray.ROW_PITCH)
            return row if 0 <= row < navray.LIST_ROWS[which] else None
        navray.read_rows, navray.find_thumb, navray.selected_row = rows, thumb, selected
        self.runner = runner

    def tearDown(self):
        self.navray.read_rows, self.navray.find_thumb, self.navray.selected_row = self.original

    def pick(self, category, wanted):
        self.lists["destination"] = list(self.catalog[category])
        self.start["destination"] = 0
        self.clicks.clear()
        self.runner.choose("destination", wanted, None)
        point = self.clicks[-1]
        row = round((point[1] - (self.window.y + self.navray.DEST_DY + self.navray.ROW_H/2))/self.navray.ROW_PITCH)
        return self.start["destination"] + row         # the clicked entry's index in the whole list

    def test_a_plain_name_is_found_after_scrolling_by_the_scroll_thumb(self):
        index = self.pick("VIAROSSO APARTMENTS", "Viarosso / Alamo Living / Enter C")
        self.assertEqual(self.catalog["VIAROSSO APARTMENTS"][index], "Viarosso / Alamo Living / Enter C")
        self.assertTrue(self.drags)
        self.assertEqual(self.runner.backend.events, [])         # never the mouse wheel

    def test_a_row_that_cannot_be_read_is_still_clicked_by_working_it_out_from_its_neighbours(self):
        # Live: the selected first row (WEAPONS) read blank, and the cursor garbled the one below it.
        real = self.navray.read_rows

        def unreadable(gray, window, which):
            rows = real(gray, window, which)
            return [(r, "garbled ———" if t == "AMMUNITION" else t) for r, t in rows if t != "WEAPONS"]
        self.navray.read_rows = unreadable
        self.runner.entries = list(self.catalog["TRADER DIRECTORY"])
        index = self.pick("TRADER DIRECTORY", "WEAPONS")
        self.assertEqual(self.catalog["TRADER DIRECTORY"][index], "WEAPONS")
        self.assertTrue(any("worked out" in p for k, p in self.events if k == "status"))

    def test_a_garbled_category_over_a_lit_wall_is_worked_out_from_its_neighbours(self):
        # Live (28 Oct, Plaza 1): a light wall behind the window garbled the wanted row to INEGGRON'CITY SECTORS.
        real = self.navray.read_rows
        self.navray.read_rows = lambda g, w, which: [(r, "INEGGRON'CITY SECTORS" if t == "NEOCRON CITY SECTORS" else t)
                                                     for r, t in real(g, w, which)]
        self.runner.categories = list(self.catalog)
        self.runner.choose("select", "NEOCRON CITY SECTORS", None)
        point = self.clicks[-1]
        row = round((point[1] - (self.window.y + self.navray.SELECT_DY + self.navray.ROW_H/2))/self.navray.ROW_PITCH)
        self.assertEqual(self.start["select"] + row, list(self.catalog).index("NEOCRON CITY SECTORS"))
        self.assertTrue(any("worked out" in p for k, p in self.events if k == "status"))

    def test_a_row_that_reads_as_another_real_entry_is_never_clicked_for_the_wanted_one(self):
        real = self.navray.read_rows
        self.navray.read_rows = lambda g, w, which: [(r, "ADMINISTRATION" if t == "NEOCRON CITY SECTORS" else t)
                                                     for r, t in real(g, w, which)]
        self.runner.categories = list(self.catalog)
        with self.assertRaisesRegex(Interrupted, "was not found"):
            self.runner.choose("select", "NEOCRON CITY SECTORS", None)
        self.assertEqual(self.clicks, [])

    def test_scrolling_stops_when_the_window_disappears_instead_of_dragging_the_scenery(self):
        # Live (28 Oct): the game left the interactive UI mid-list; "thumbs" were then found in the scenery
        # and twenty seconds of drags spun the camera round.
        state = {"drags_left": 2}
        real_drag, real_thumb = self.runner.drag, self.navray.find_thumb

        def drag(source, destination):
            real_drag(source, destination)
            state["drags_left"] -= 1
        self.runner.drag = drag
        self.navray.find_thumb = lambda g, w, which: (500, 300, 340) if state["drags_left"] <= 0 else real_thumb(g, w, which)

        def find_window(reader):
            if state["drags_left"] <= 0:
                raise Interrupted("Nav-Ray window not found.")
            return self.window
        self.runner.find_window = find_window
        with self.assertRaisesRegex(Interrupted, "disappeared"):
            self.runner.choose("select", "WASTELAND DUNGEONS", None)
        self.assertLessEqual(len(self.drags), 3)
        self.assertEqual(self.clicks, [])

    def test_an_entry_worked_out_to_lie_under_the_buttons_is_scrolled_to_not_clicked_there(self):
        # Live (28 Oct): PEPPER PARK SEC-1 was worked out to be row 7, under Start/Stop; the click selected nothing.
        real = self.navray.read_rows
        self.navray.read_rows = lambda g, w, which: [(r, "PEPPER PARK SEC-1 garbled" if t == "PEPPER PARK SEC-1" else t)
                                                     for r, t in real(g, w, which)]
        self.runner.entries = list(self.catalog["NEOCRON CITY SECTORS"])
        index = self.pick("NEOCRON CITY SECTORS", "PEPPER PARK SEC-1")
        self.assertEqual(self.catalog["NEOCRON CITY SECTORS"][index], "PEPPER PARK SEC-1")
        self.assertEqual(len(self.clicks), 1)

    def test_a_click_that_selects_nothing_stops_instead_of_starting(self):
        self.navray.selected_row = lambda gray, window, which: None
        with self.assertRaisesRegex(Interrupted, "did not become selected"):
            self.pick("TRADER DIRECTORY", "WEAPONS")
        self.assertEqual(len(self.clicks), 2)                    # tried once more first

    def test_scrolling_up_finds_a_row_the_first_move_to_the_top_missed(self):
        self.lists["destination"] = list(self.catalog["TRADER DIRECTORY"])
        self.start["destination"] = len(self.lists["destination"]) - self.navray.LIST_ROWS["destination"]   # list left scrolled to the bottom
        self.runner.to_top = lambda which, window: None            # the move to the top did not happen
        self.clicks.clear()
        self.runner.choose("destination", "WEAPONS", None)         # first entry: only reachable by going up
        self.assertEqual(self.start["destination"], 0)
        self.assertTrue(self.clicks)

    def test_each_page_overlaps_by_two_rows_so_nothing_is_skipped(self):
        self.pick("VIAROSSO APARTMENTS", "Viarosso / Alamo Living / Enter C")
        pages = [d for d in self.drags if d > 0]
        self.assertTrue(all(d <= self.navray.LIST_ROWS["destination"] - 2 + .6 for d in pages), pages)

    def test_a_list_that_has_not_redrawn_yet_is_read_again_instead_of_giving_up(self):
        real = self.navray.read_rows
        calls = {"n": 0}

        def slow(gray, window, which):
            calls["n"] += 1
            return [] if calls["n"] <= 3 else real(gray, window, which)
        self.navray.read_rows = slow
        index = self.pick("TRADER DIRECTORY", "WEAPONS")
        self.assertEqual(self.catalog["TRADER DIRECTORY"][index], "WEAPONS")

    def test_not_found_names_what_was_read(self):
        self.lists["destination"] = ["ALPHA", "BETA"]
        with self.assertRaisesRegex(Interrupted, "Last rows read: ALPHA; BETA"):
            self.runner.choose("destination", "GAMMA TOWERS", None)

    def test_every_catalog_entry_can_be_reached(self):
        for category in ("PEPPER PARK DUNGEONS", "OUTZONE DUNGEONS", "JONES MISSION LOCATIONS"):
            for entry in self.catalog[category]:
                with self.subTest(category=category, entry=entry):
                    index = self.pick(category, entry)
                    self.assertEqual(self.catalog[category][index].rstrip("…"), entry.rstrip("…"))

    def test_numbered_duplicates_pick_the_right_one_even_across_pages(self):
        for category, count in (("VIAROSSO APARTMENTS", 4), ("PEPPER PARK APARTMENTS", 6), ("PLAZA DUNGEONS", 2)):
            entries = self.catalog[category]
            label = max(set(entries), key=entries.count)
            first = entries.index(label)
            for n in range(1, count + 1):
                with self.subTest(category=category, n=n):
                    self.assertEqual(self.pick(category, f"{label} #{n}"), first + n - 1)
