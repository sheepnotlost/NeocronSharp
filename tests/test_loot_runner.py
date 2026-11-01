"""Loot sequence: what it picks, what it reads on screen, and the order it does things (no engine, no game input)."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import loot_runner
from loot_runner import LootRunner, dropped, pick_target
from macro_core import Control, Interrupted, default_profile
from target_tab import loot_names
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

    def test_names_and_health(self):
        self.assertEqual(loot_names(" Rat, Small Spider,,rat ,Rat"), ["Rat", "Small Spider", "rat"])
        self.assertTrue(dropped((800, 900), (700, 900)))
        self.assertFalse(dropped((800, 900), (795, 900)))
        self.assertFalse(dropped((800, 900), None))


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

    def nearby(self):
        return [actor(n, dead=n in self.dead) for n in ("Rat", "Spider")]

    def fight(self, target, tick):
        self.seen.append(("fight", target["name"]))
        died = self.fights.pop(0)
        if died:
            self.dead.add(target["name"])
        return f"{target['name']} died. Camera follow stopped." if died else "No damage to it. Camera follow stopped."

    def box(self, target, tick):
        self.seen.append(("box", target["name"]))
        return "Right-clicked."


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

    def loot_window(self, frame):
        return {"close": (1, 1)}

    def loot_parts(self, frame, window):
        return []


class SequenceTests(unittest.TestCase):
    def run_sequence(self, fights, health=(), names=("Rat", "Spider")):
        seen, events, clock = [], [], {"now": 0.}
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        control = Control()
        runner = Sequence(profile, Backend(), control, lambda kind, text: events.append((kind, text)), names=names,
                          engine=Engine(fights, seen), detector=Detect(),
                          clock=lambda: clock["now"], sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.health_readings = list(health)
        runner.click = lambda point: seen.append(("close",))
        runner.move = lambda point: None
        runner.diagnostic_dir = Path("nowhere")
        runner.save_failure = lambda error: None
        loot_runner.IDLE_LIMIT, limit = 0, loot_runner.IDLE_LIMIT
        self.addCleanup(setattr, loot_runner, "IDLE_LIMIT", limit)
        runner.run()
        return seen, events

    def test_kill_then_loot_then_the_next(self):
        seen, events = self.run_sequence([True, True], names=("Rat", "Spider"))
        self.assertEqual(seen, [("fight", "Rat"), ("box", "Rat"), ("close",), ("fight", "Spider"), ("box", "Spider"), ("close",)])
        self.assertIn("2 killed", events[-1][1])

    def test_a_threat_dies_before_any_looting(self):
        hurt = [(900, 900), (800, 900), (800, 900), (800, 900)]
        seen, _ = self.run_sequence([True, True], hurt)
        self.assertEqual(seen, [("fight", "Rat"), ("fight", "Spider"), ("box", "Rat"), ("close",), ("box", "Spider"), ("close",)])

    def test_stops_when_hurt_with_nothing_listed_near(self):
        seen, events = self.run_sequence([True], [(900, 900), (800, 900)], names=("Rat",))
        self.assertEqual(seen, [("fight", "Rat")])
        self.assertIn("no ticked NPC", events[-1][1])

    def test_a_target_it_cannot_hurt_is_left_alone(self):
        seen, events = self.run_sequence([False], names=("Rat",))
        self.assertEqual(seen, [("fight", "Rat")])
        self.assertIn("0 killed", events[-1][1])

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
