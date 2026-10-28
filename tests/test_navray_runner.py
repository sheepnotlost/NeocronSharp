"""Walk loop with a fake backend and the user's real path frames."""
from pathlib import Path
import unittest

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


def after_calibration(runner):
    """Mouse moves after the calibration nudges (each nudge is a move and a move back; a weak reading tries the next)."""
    moves = [e[1] for e in runner.backend.events if e[0] == "rel"]
    return moves[2*(1 if runner.px_per_count else len(navray_runner.CAL_NUDGES)):]


def pathvision_find(frame):
    return pathvision.find_path(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))


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
    def test_it_walks_when_the_dashes_ahead_are_lined_up_and_looks_all_round_before_reporting_arrival(self):
        runner, events = make_runner(lambda i: AHEAD if i <= 24 else DARK)
        runner.walk()
        recorded = runner.backend.events
        self.assertIn(("key", "w", True), recorded)
        self.assertEqual(recorded[-1], ("key", "w", False))
        self.assertIn(("key", "shift", True), recorded)                                    # running
        self.assertEqual(recorded[-2:], [("key", "shift", False), ("key", "w", False)])    # and everything released
        done = [p for k, p in events if k == "done"]
        self.assertEqual(len(done), 1)
        self.assertIn("arrived", done[0].lower())
        statuses = [p for k, p in events if k == "status"]
        self.assertTrue(any("sweeping all the way round" in p for p in statuses))       # it looked before giving up
        turns = after_calibration(runner)
        self.assertTrue(turns and all(t > 0 for t in turns))                             # a sweep, not a stop

    def test_it_turns_to_line_the_dashes_up_before_it_walks(self):
        runner, _ = make_runner(lambda i: STAIRS)                        # the dashes lie far to the left
        with self.assertRaisesRegex(Interrupted, "does not line the dashes up"):   # the fake mouse turns nothing
            runner.walk()
        turns = after_calibration(runner)
        self.assertTrue(turns and all(t < 0 for t in turns), turns)                # left, and in one bold move each
        self.assertFalse([e for e in runner.backend.events if e[:2] == ("key", "w") and e[2]])   # never walked unaligned

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

    def test_a_black_frame_is_a_loading_screen(self):
        runner, _ = make_runner(lambda i: AHEAD if i < 4 else np.zeros((1125, 2000, 3), np.uint8))
        with self.assertRaisesRegex(Interrupted, "Loading screen"):
            runner.walk()

    def test_an_unchanging_view_while_walking_backs_off_and_looks_elsewhere_before_giving_up(self):
        runner, events = make_runner(lambda i: AHEAD)
        with self.assertRaisesRegex(Interrupted, "Not moving"):
            runner.walk()
        recorded = runner.backend.events
        self.assertIn(("key", "s", True), recorded)                                # it backed off from the wall
        self.assertTrue(any("stuck" in p for k, p in events if k == "status"))      # and said so
        self.assertEqual(recorded[-1], ("key", "w", False))

    def test_a_health_drop_stops_the_walk(self):
        runner, _ = make_runner(lambda i: np.roll(AHEAD, (i % 5)*4, axis=1), health=(972, 972, 800))   # a moving picture, dashes ahead
        with self.assertRaisesRegex(Interrupted, "Health dropped"):
            runner.walk()
        self.assertEqual(runner.backend.events[-1], ("key", "w", False))


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
        runner.choose("select", "Faction HQs", reader)
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
        self.original = (navray.read_rows, navray.find_thumb)
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
        navray.read_rows, navray.find_thumb = rows, thumb
        self.runner = runner

    def tearDown(self):
        self.navray.read_rows, self.navray.find_thumb = self.original

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
