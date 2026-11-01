"""Hunt: what it picks, what it reads on screen, and the order it does things (no engine, no game input)."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import loot_runner
from loot_runner import LootRunner, pick_target
from macro_core import Control, Interrupted, default_profile
from vision import Detector

FIXTURE = Path(__file__).parent / "fixtures" / "loot_window_2000.png"


def actor(name, kind="npc", distance=50., dead=False, id=None):
    return {"id": id or name, "name": name, "kind": kind, "distance": distance, "dead": dead}


class PickTests(unittest.TestCase):
    def test_nearest_ticked_living_npc_in_range(self):
        actors = [actor("Rat", distance=90), actor("Rat", distance=30, id="near"), actor("Copbot", distance=5),
                  actor("Rat", distance=1, dead=True, id="body"), actor("Rat", distance=900, id="far")]
        self.assertEqual(pick_target(actors, ["rat"], 400)["id"], "near")
        self.assertEqual(pick_target(actors, ["Rat"], 400, skip={"near"})["distance"], 90)
        self.assertIsNone(pick_target(actors, ["Spider"], 400))

    def test_never_a_player_even_when_named(self):
        self.assertIsNone(pick_target([actor("Rat", kind="player", distance=1)], ["Rat"], 400))

    def test_anywhere_in_the_zone_unless_limited(self):
        self.assertEqual(pick_target([actor("Rat", distance=30000)], ["Rat"])["distance"], 30000)


class WalkTests(unittest.TestCase):
    def test_a_hunt_runs_and_passes_on_the_first_calibration(self):
        engine = loot_runner.Engine(None, None)
        sent = []
        engine.live = lambda args, tick: sent.append(args) or "calibration 300 0.002\nReached Rat, 190 units away."
        engine.walk(actor("Rat"), 200, None)
        engine.walk(actor("Rat"), 200, None)
        self.assertIn("--run", sent[0])
        self.assertNotIn("--calibration", sent[0])
        self.assertEqual(sent[1][-2:], ["--calibration", "300,0.002"])
        self.assertNotIn("--body", sent[0])

    def test_a_walk_to_a_body_says_so(self):
        engine = loot_runner.Engine(None, None)
        sent = []
        engine.live = lambda args, tick: sent.append(args) or "Reached Rat, 100 units away."
        engine.walk(actor("Rat", dead=True), 110, None)
        self.assertIn("--body", sent[0])


class ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.cvtColor(cv2.imread(str(FIXTURE)), cv2.COLOR_BGR2RGB)
        cls.detector = Detector()
        cls.window = cls.detector.loot_window(cls.frame)

    def test_finds_the_window_by_take_all(self):
        self.assertAlmostEqual(self.window["left"], 307, delta=3)
        self.assertAlmostEqual(self.window["top"], 323, delta=3)
        self.assertAlmostEqual(self.window["close"][0], 829, delta=4)
        self.assertAlmostEqual(self.window["close"][1], 301, delta=4)

    def test_no_window_means_none(self):
        self.assertIsNone(self.detector.loot_window(np.zeros_like(self.frame)))

    def test_r9_and_r10_are_not_parts(self):
        self.assertEqual(self.detector.loot_parts(self.frame, self.window), [])

    def test_finds_a_part_put_in_the_box(self):
        # The T x5 stack from Inventory, moved into the box's second cell.
        frame = self.frame.copy()
        source = frame[622:668, 1341:1387].copy()
        frame[323:369, 403:449] = source
        frame[323:369, 428:474] = np.maximum(frame[323:369, 428:474], source)
        parts = self.detector.loot_parts(frame, self.window)
        self.assertEqual([p["letter"] for p in parts], ["T"])
        self.assertAlmostEqual(parts[0]["point"][0], 451, delta=6)

    def test_drops_on_its_own_stack_or_an_empty_cell(self):
        inventory = self.detector.inventory(self.frame)
        self.assertEqual(self.detector.inventory_drop(self.frame, inventory, "T"), self.detector.stacks(self.frame)["T"][0])
        x, y = self.detector.inventory_drop(self.frame, inventory, "E")
        patch = self.detector.gray(self.frame[y-12:y+12, x-12:x+12])
        self.assertLess(patch.std(), 8)

    def test_reads_your_health(self):
        self.assertEqual(LootRunner.health(type("R", (), {"detector": self.detector})(), self.detector.text_reader(), self.frame), (626, 913))


class Backend:
    def __init__(self):
        self.size = [2000, 1125]

    def check_focus(self, size):
        pass

    def capture(self):
        return "frame"

    def release_all(self):
        pass


class Engine:
    def __init__(self, fights, seen):
        self.fights, self.seen = list(fights), seen
        self.dead = set()
        self.walks = []
        self.boxes = []
        self.distance = 50.

    def nearby(self):
        return [actor(n, distance=self.distance, dead=n in self.dead) for n in ("Rat", "Spider")]

    def walk(self, target, reach, tick):
        self.seen.append(("walk", target["name"], reach))
        return self.walks.pop(0) if self.walks else f"Following.\nReached {target['name']}, {reach} units away."

    def fight(self, target, tick):
        self.seen.append(("fight", target["name"]))
        if isinstance(self.fights[0], str):
            return self.fights.pop(0)
        died = self.fights.pop(0)
        if died:
            self.dead.add(target["name"])
        return f"{target['name']} died. Camera follow stopped." if died else "No damage to it. Camera follow stopped."

    def box(self, target, tick):
        self.seen.append(("box", target["name"]))
        self.detect.shut = False
        return self.boxes.pop(0) if self.boxes else "Right-clicked."


class Sequence(LootRunner):
    """Everything on screen is scripted."""
    health_readings = ()

    def set_ui(self, reader, on):
        return True

    def reader(self):
        return None

    def my_health(self):
        return self.health_readings.pop(0) if self.health_readings else (900, 900)


class Detect:
    last_scale = None
    shut = False
    stuck = False

    def loot_window(self, frame):
        return None if self.shut else {"close": (1, 1)}

    def loot_parts(self, frame, window):
        return []


class SequenceTests(unittest.TestCase):
    def run_sequence(self, fights, health=(), names=("Rat", "Spider"), distance=50., walks=(), boxes=(), stuck=False):
        seen, events, clock = [], [], {"now": 0.}
        engine = Engine(fights, seen)
        detect = Detect()
        engine.distance, engine.walks, engine.boxes, engine.detect = distance, list(walks), list(boxes), detect
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        control = Control()
        runner = Sequence(profile, Backend(), control, lambda kind, text: events.append((kind, text)), names=names,
                          engine=engine, detector=detect,
                          clock=lambda: clock["now"], sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.health_readings = [(900, 900), *health]
        runner.click = lambda point: (seen.append(("close",)), setattr(detect, "shut", not stuck))
        runner.move = lambda point: None
        runner.diagnostic_dir = Path("nowhere")
        runner.save_failure = lambda error: None
        loot_runner.IDLE_LIMIT, limit = 0, loot_runner.IDLE_LIMIT
        self.addCleanup(setattr, loot_runner, "IDLE_LIMIT", limit)
        runner.run()
        return seen, events

    def test_walks_to_a_far_target_before_attacking(self):
        seen, _ = self.run_sequence([True], names=("Rat",), distance=9000.)
        self.assertEqual(seen[:2], [("walk", "Rat", 5000), ("fight", "Rat")])

    def test_a_target_in_reach_needs_no_walk(self):
        seen, _ = self.run_sequence([True], names=("Rat",))
        self.assertEqual(seen[0], ("fight", "Rat"))

    def test_a_target_with_no_way_to_it_is_left_alone_and_the_next_is_tried(self):
        seen, events = self.run_sequence([True], distance=9000., walks=["No walkable way to Rat for 15 s. Follow stopped."])
        self.assertEqual([s[:2] for s in seen[:3]], [("walk", "Rat"), ("walk", "Spider"), ("fight", "Spider")])
        self.assertIn("1 killed", events[-1][1])

    def test_anything_not_about_the_target_ends_the_hunt_wherever_it_happens(self):
        for reason in ("Stopped: Stop pressed.", "Stopped: You changed zone. Follow stopped.",
                       "Stopped: Your character could not be read (zoning?). Follow stopped.",
                       "Stopped: The test step went 0 units. Is a menu, chat or the free pointer active?", "Stopped: Neocron lost focus."):
            seen, events = self.run_sequence([], distance=9000., walks=[reason])
            self.assertEqual(seen, [("walk", "Rat", 5000)])
            self.assertIn(reason, events[-1][1])
            seen, events = self.run_sequence([reason])
            self.assertEqual(seen, [("fight", "Rat")])
            self.assertIn(reason, events[-1][1])
            seen, events = self.run_sequence([True], names=("Rat",), boxes=[reason])
            self.assertEqual(seen, [("fight", "Rat"), ("box", "Rat")])
            self.assertIn(reason, events[-1][1])

    def test_a_body_it_could_not_aim_at_is_left_and_the_hunt_goes_on(self):
        seen, events = self.run_sequence([True, True], boxes=["Stopped: Could not aim at the body of Rat."])
        self.assertEqual(seen, [("fight", "Rat"), ("box", "Rat"), ("fight", "Spider"), ("box", "Spider"), ("close",)])
        self.assertIn("2 killed", events[-1][1])

    def test_a_loot_box_that_will_not_close_stops_it(self):
        seen, events = self.run_sequence([True], names=("Rat",), stuck=True)
        self.assertEqual(seen.count(("close",)), 3)
        self.assertIn("did not close", events[-1][1])

    def test_no_hunt_without_a_health_reading(self):
        events = []
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        clock = {"now": 0.}
        runner = Sequence(profile, Backend(), Control(), lambda kind, text: events.append((kind, text)), names=["Rat"],
                          engine=Engine([], []), detector=Detect(), clock=lambda: clock["now"],
                          sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.my_health = lambda: None
        runner.save_failure = lambda error: None
        runner.run()
        self.assertIn("Could not read your health", events[-1][1])

    def test_kill_then_loot_then_the_next(self):
        seen, events = self.run_sequence([True, True], names=("Rat", "Spider"))
        self.assertEqual(seen, [("fight", "Rat"), ("box", "Rat"), ("close",), ("fight", "Spider"), ("box", "Spider"), ("close",)])
        self.assertIn("2 killed", events[-1][1])

    def test_loots_before_the_next_even_while_hurt(self):
        hurt = [(900, 900), (800, 900), (800, 900), (800, 900)]
        seen, _ = self.run_sequence([True, True], hurt)
        self.assertEqual(seen, [("fight", "Rat"), ("box", "Rat"), ("close",), ("fight", "Spider"), ("box", "Spider"), ("close",)])

    def test_a_far_body_gets_a_route_then_the_run(self):
        seen, _ = self.run_sequence([True], names=("Rat",), distance=1000.)
        self.assertEqual(seen, [("fight", "Rat"), ("walk", "Rat", 110), ("box", "Rat"), ("close",)])

    def test_a_body_with_no_way_to_it_is_left(self):
        seen, events = self.run_sequence([True], names=("Rat",), distance=1000., walks=["No walkable way to Rat for 15 s. Follow stopped."])
        self.assertEqual(seen, [("fight", "Rat"), ("walk", "Rat", 110)])
        self.assertIn("1 killed", events[-1][1])

    def test_a_target_it_cannot_hurt_is_left_alone(self):
        seen, events = self.run_sequence([False, False], names=("Rat",))
        self.assertEqual(seen, [("fight", "Rat"), ("walk", "Rat", 200), ("fight", "Rat")])
        self.assertIn("0 killed", events[-1][1])

    def test_a_target_it_cannot_hurt_is_closed_on_before_any_other(self):
        seen, _ = self.run_sequence([False, True, True])
        self.assertEqual(seen[:3], [("fight", "Rat"), ("walk", "Rat", 200), ("fight", "Rat")])
        seen, _ = self.run_sequence([False]*5 + [True], names=("Rat",), distance=9000.)
        self.assertEqual([s for s in seen if s[0] == "walk"][:6], [("walk", "Rat", r) for r in (5000, 2500, 1250, 625, 312, 200)])
        self.assertEqual([s[1] for s in seen if s[0] == "fight"], ["Rat"]*6)

    def test_the_range_that_worked_is_kept(self):
        seen, _ = self.run_sequence([False, True, True], distance=9000.)
        self.assertEqual([s for s in seen if s[0] == "walk"][:2], [("walk", "Rat", 5000), ("walk", "Rat", 2500)])
        self.assertIn(("walk", "Spider", 2500), seen)

    def test_stops_on_low_health(self):
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        runner = LootRunner(profile, Backend(), Control(), names=["Rat"], engine=Engine([], []), detector=Detect())
        runner.frame = lambda: None
        runner.reader = lambda: None
        runner.health = lambda reader, frame: (300, 900)
        with self.assertRaisesRegex(Interrupted, "300 of 900"):
            runner.my_health()


if __name__ == "__main__":
    unittest.main()
