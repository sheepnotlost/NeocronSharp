"""Hunt: what it picks, what it reads on screen, and the order it does things (no engine, no game input)."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import loot_runner
from loot_runner import LootRunner, hunted, pick_target
from macro_core import Control, Interrupted, default_profile
from vision import Detector

FIXTURE = Path(__file__).parent / "fixtures" / "loot_window_2000.png"


def actor(name, kind="npc", distance=50., dead=False, id=None, faction=17):
    return {"id": id or name, "name": name, "kind": kind, "distance": distance, "dead": dead, "faction": faction}


class PickTests(unittest.TestCase):
    def test_a_spared_name_may_be_part_of_one(self):
        parasite = {"kind": "npc", "faction": 17, "name": "Genotoxic  Parasite"}
        self.assertFalse(hunted(parasite, ["parasite"]))
        self.assertFalse(hunted(parasite, ["genotoxic parasite"]))
        self.assertTrue(hunted(parasite, ["slugger", ""]))

    def test_nearest_living_creature_in_range_not_spared(self):
        actors = [actor("Rat", distance=90), actor("Rat", distance=30, id="near"), actor("Spider", distance=5),
                  actor("Rat", distance=1, dead=True, id="body"), actor("Rat", distance=900, id="far")]
        self.assertEqual(pick_target(actors, ["spider"], 400)["id"], "near")
        self.assertEqual(pick_target(actors, ["Spider"], 400, skip={"near"})["distance"], 90)
        self.assertIsNone(pick_target(actors, ["Spider", "Rat"], 400))
        self.assertEqual(pick_target(actors)["name"], "Spider")         # nothing ticked: everything

    def test_never_a_player_or_a_human(self):
        self.assertIsNone(pick_target([actor("Rat", kind="player", distance=1, faction=None)]))
        for faction in (None, 0, 1, 11, 19, 20):
            self.assertIsNone(pick_target([actor("Corporal Lines / CityMercs", faction=faction)]))
        for faction in (16, 17, 18):
            self.assertIsNotNone(pick_target([actor("Genotoxic Parasite", faction=faction)]))

    def test_only_attack_and_the_area_limit_the_pick(self):
        snake, robot = actor("Sand Snake", distance=900, id="s", faction=18), actor("Dome of York Guardian", distance=50, id="r", faction=16)
        far_snake = actor("Poisonous Sand Snake", distance=100, id="far", faction=18)
        snake.update(x=-9000, z=-4000); robot.update(x=-9100, z=-4100); far_snake.update(x=-3000, z=5000)
        self.assertEqual(pick_target([snake, robot, far_snake])["id"], "r")
        self.assertEqual(pick_target([snake, robot, far_snake], only=["snake"])["id"], "far")
        self.assertEqual(pick_target([snake, robot, far_snake], only=["snake"], area=(-9270, -4490, 2900))["id"], "s")
        self.assertIsNone(pick_target([actor("Sand Snake", id="unplaced")], area=(0, 0, 2900)))   # no position: not known to be inside

    def test_anywhere_in_the_zone_unless_limited(self):
        self.assertEqual(pick_target([actor("Rat", distance=30000)])["distance"], 30000)


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

    def test_a_fight_only_shoots_on_target_and_backs_off_when_asked(self):
        engine = loot_runner.Engine(None, None)
        sent = []
        engine.live = lambda args, tick: sent.append(args) or "Target limit 4210 units.\nRat died."
        engine.fight(actor("Rat"), None)
        self.assertIn("--sight", sent[0])
        self.assertNotIn("--back-off", sent[0])
        self.assertEqual(engine.limit, 4210)
        engine.fight(actor("Rat"), None, True)
        self.assertEqual(sent[1][sent[1].index("--back-off")+1], "2500")

    def test_keep_away_kites_from_that_far(self):
        engine = loot_runner.Engine(None, None)
        sent = []
        engine.live = lambda args, tick: sent.append(args) or "Rat died."
        engine.keep_away = 800
        engine.fight(actor("Rat"), None)
        self.assertEqual(sent[0][sent[0].index("--kite-at")+1], "800")
        self.assertIn("--kite", sent[0])

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
        self.limit = None
        self.backs = []
        self.flees = []

    def nearby(self):
        return [actor(n, distance=self.distance, dead=n in self.dead) for n in ("Rat", "Spider")]

    def walk(self, target, reach, tick):
        self.seen.append(("walk", target["name"], reach))
        return self.walks.pop(0) if self.walks else f"Following.\nReached {target['name']}, {reach} units away."

    def fight(self, target, tick, back=False):
        self.seen.append(("fight", target["name"]))
        self.backs.append(back)
        if isinstance(self.fights[0], str):
            return self.fights.pop(0)
        died = self.fights.pop(0)
        if died:
            self.dead.add(target["name"])
        return f"{target['name']} died. Camera follow stopped." if died else "No damage to it. Camera follow stopped."

    def flee(self, tick):
        self.seen.append(("flee",))
        return self.flees.pop(0) if self.flees else "Running to cover.\nReached cover."

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
        return self.judge(self.health_readings.pop(0) if self.health_readings else (900, 900))


class Detect:
    last_scale = None
    shut = False
    stuck = False

    def loot_window(self, frame):
        return None if self.shut else {"close": (1, 1)}

    def loot_parts(self, frame, window):
        return []


class SequenceTests(unittest.TestCase):
    def run_sequence(self, fights, health=(), names=("Rat", "Spider"), distance=50., walks=(), boxes=(), stuck=False, flees=()):
        seen, events, clock = [], [], {"now": 0.}
        engine = Engine(fights, seen)
        detect = Detect()
        engine.distance, engine.walks, engine.boxes, engine.detect = distance, list(walks), list(boxes), detect
        engine.flees = list(flees)
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        control = Control()
        runner = Sequence(profile, Backend(), control, lambda kind, text: events.append((kind, text)),
                          spare=[n for n in ("Rat", "Spider") if n not in names],
                          engine=engine, detector=detect,
                          clock=lambda: clock["now"], sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.health_readings = [(900, 900), *health]
        runner.click = lambda point: (seen.append(("close",)), setattr(detect, "shut", not stuck))
        runner.move = lambda point: None
        runner.diagnostic_dir = Path("nowhere")
        runner.save_failure = lambda error: None
        self.engine = engine
        loot_runner.IDLE_LIMIT, limit = 0, loot_runner.IDLE_LIMIT
        self.addCleanup(setattr, loot_runner, "IDLE_LIMIT", limit)
        runner.run()
        return seen, events

    def test_walks_to_a_far_target_before_attacking(self):
        seen, _ = self.run_sequence([True], names=("Rat",), distance=9000.)
        self.assertEqual(seen[:2], [("walk", "Rat", 4000), ("fight", "Rat")])

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
            self.assertEqual(seen, [("walk", "Rat", 4000)])
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
        runner = Sequence(profile, Backend(), Control(), lambda kind, text: events.append((kind, text)), spare=["Spider"],
                          engine=Engine([], []), detector=Detect(), clock=lambda: clock["now"],
                          sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.my_health = lambda: None
        runner.save_failure = lambda error: None
        runner.run()
        self.assertIn("Could not read your health", events[-1][1])

    def test_keep_away_with_an_area_kites_the_pack_in_one_run_then_loots_every_body(self):
        seen, events, clock = [], [], {"now": 0.}

        class PackEngine(Engine):
            def nearby(self):
                return [dict(actor(n, distance=1500., dead=n in self.dead, faction=18), x=-9000., z=-4000.) for n in ("Sand Snake", "Poisonous Sand Snake")]

            def pack(self, target, tick, area, ring, only):
                self.seen.append(("pack", target["name"], tuple(round(v) for v in area), ring, tuple(only)))
                self.dead.update({"Sand Snake", "Poisonous Sand Snake"})
                return ("Killed Sand Snake Sand Snake\nKilled Poisonous Sand Snake Poisonous Sand Snake\nPack cleared: 2 killed.",
                        [("Sand Snake", "Sand Snake"), ("Poisonous Sand Snake", "Poisonous Sand Snake")])

        engine = PackEngine([], seen)
        detect = Detect()
        engine.detect = detect
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        runner = Sequence(profile, Backend(), Control(), lambda kind, text: events.append((kind, text)), engine=engine, detector=detect,
                          clock=lambda: clock["now"], sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.health_readings = [(900, 900)]
        runner.click = lambda point: (seen.append(("close",)), setattr(detect, "shut", True))
        runner.move, runner.save_failure = (lambda point: None), (lambda error: None)
        runner.only, runner.stay, runner.centre, runner.keep_away = ["snake"], 2900, (-9270, -4490), 800
        loot_runner.IDLE_LIMIT, limit = 0, loot_runner.IDLE_LIMIT
        self.addCleanup(setattr, loot_runner, "IDLE_LIMIT", limit)
        runner.run()
        self.assertEqual(seen[0], ("walk", "Sand Snake", 1344), "farther than 1,456: walks in to 1,344 first")
        self.assertEqual(seen[1], ("pack", "Sand Snake", (-9270, -4490, 2900), 1600, ("snake",)))
        self.assertEqual([s for s in seen if s[0] == "box"], [("box", "Sand Snake"), ("box", "Poisonous Sand Snake")])
        self.assertIn("2 killed", events[-1][1])

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
        self.assertEqual([s for s in seen if s[0] == "walk"][:6], [("walk", "Rat", r) for r in (4000, 2000, 1000, 500, 250, 200)])
        self.assertEqual([s[1] for s in seen if s[0] == "fight"], ["Rat"]*6)

    def test_a_blocked_shot_goes_closer_without_giving_up_the_range(self):
        blocked = "No line of sight to Rat. Camera follow stopped."
        seen, _ = self.run_sequence([blocked, True, True], distance=9000.)
        self.assertEqual([s for s in seen if s[0] == "walk"][:2], [("walk", "Rat", 4000), ("walk", "Rat", 2000)])
        self.assertIn(("walk", "Spider", 4000), seen)
        self.assertEqual(self.engine.backs, [True, False, True])

    def test_a_target_limit_only_ever_brings_the_range_in(self):
        real = Engine.fight

        def measured(engine, target, tick, back=False):
            engine.limit = 3000
            return real(engine, target, tick, back)
        self.addCleanup(setattr, Engine, "fight", real)
        Engine.fight = measured
        seen, _ = self.run_sequence([True, True], distance=9000.)
        self.assertIn(("walk", "Spider", 2900), seen)

    def test_a_weapon_shorter_than_the_target_limit_stops_the_backing(self):
        seen, _ = self.run_sequence([False, True, True])
        self.assertEqual(self.engine.backs, [True, False, False])

    def test_the_range_that_worked_is_kept(self):
        seen, _ = self.run_sequence([False, True, True], distance=9000.)
        self.assertEqual([s for s in seen if s[0] == "walk"][:2], [("walk", "Rat", 4000), ("walk", "Rat", 2000)])
        self.assertIn(("walk", "Spider", 2000), seen)

    def test_low_health_runs_to_cover_then_hunts_on(self):
        seen, events = self.run_sequence([True, True], [(300, 900), (400, 900), (700, 900)], walks=[])
        self.assertIn(("flee",), seen)
        self.assertLess(seen.index(("flee",)), seen.index(("fight", "Spider")))
        self.assertIn("Healed", " ".join(str(e[1]) for e in events))
        self.assertIn("2 killed", events[-1][1])

    def test_health_that_never_comes_back_ends_the_hunt(self):
        seen, events = self.run_sequence([True], [(300, 900)]*700, names=("Rat",))
        self.assertEqual(seen.count(("flee",)), loot_runner.FLEE_TRIES)
        self.assertIn("did not help", events[-1][1])

    def test_being_caught_in_cover_runs_again(self):
        seen, _ = self.run_sequence([True], [(300, 900), (320, 900), (200, 900), (800, 900)], names=("Rat",))
        self.assertEqual(seen.count(("flee",)), 2)

    def test_a_stop_while_running_ends_the_hunt(self):
        low = [(300, 900)]*3
        seen, events = self.run_sequence([True], low, names=("Rat",), flees=["Stopped: Neocron lost focus."])
        self.assertEqual(seen.count(("flee",)), 1)
        self.assertIn("lost focus", events[-1][1])

    def test_a_mob_on_you_is_fought_first_then_the_target_again(self):
        engine = Engine(["Switching to Spider Spider: it is on you.", True, True], [])
        engine.pushers = True
        flags = []
        real = Engine.fight

        def noted(e, target, tick, back=False):
            flags.append(e.pushers)
            return real(e, target, tick, back)
        self.addCleanup(setattr, Engine, "fight", real)
        Engine.fight = noted
        runner = LootRunner(default_profile(), Backend(), Control(), engine=engine, detector=Detect())
        self.assertTrue(runner.attack(actor("Rat")))
        self.assertEqual([s[1] for s in engine.seen if s[0] == "fight"], ["Rat", "Spider", "Rat"])
        self.assertEqual(flags, [True, False, True], "the one on you is fought without switching again")
        self.assertEqual(runner.kills, 1)
        self.assertTrue(engine.pushers)

    def test_the_fight_asks_the_engine_for_pin_pushers_and_kite(self):
        engine = loot_runner.Engine(None, None)
        sent = []
        engine.run = lambda args, tick: sent.append(args) or "Rat died."
        engine.fight(actor("Rat"), None)
        self.assertNotIn("--pin", sent[0])
        engine.pin, engine.pushers, engine.kite, engine.avoid = True, True, True, ["slugger"]
        engine.fight(actor("Rat"), None)
        self.assertTrue({"--pin", "--pushers", "--kite"} <= set(sent[1]))
        self.assertEqual(sent[1][sent[1].index("--avoid")+1], "slugger")

    def test_stops_on_low_health(self):
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        runner = LootRunner(profile, Backend(), Control(), spare=["Spider"], engine=Engine([], []), detector=Detect())
        runner.frame = lambda: None
        runner.reader = lambda: None
        runner.health = lambda reader, frame: (300, 900)
        with self.assertRaisesRegex(Interrupted, "300 of 900"):
            runner.my_health()


if __name__ == "__main__":
    unittest.main()
