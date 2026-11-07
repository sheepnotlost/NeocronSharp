"""Regant's Legacy hunt: sweep, fight what it stops for, go out, wait, come back in (no engine, no game input)."""
from pathlib import Path
import unittest

import dungeon_runner
from dungeon_runner import DungeonEngine, DungeonRunner, INSIDE, OUTSIDE, RESPAWN_WAIT
from macro_core import Control, default_profile
from test_loot_runner import Backend, Detect, Engine


class FakeEngine(Engine):
    def __init__(self, fights, seen, sweeps, where=INSIDE, travels=None):
        super().__init__(fights, seen)
        self.sweeps, self.sector, self.travels = list(sweeps), where, travels or {}

    def where(self):
        return self.sector

    def sweep(self, at, skip, tick):
        self.seen.append(("sweep", at, tuple(sorted(skip))))
        return self.sweeps.pop(0) if self.sweeps else "Stopped: Stop pressed."

    def travel(self, sector, tick):
        self.seen.append(("travel", sector))
        self.sector = self.travels.get(sector, sector)
        return f"Arrived in sector {self.sector}."


class Sequence(DungeonRunner):
    def set_ui(self, reader, on):
        return True

    def reader(self):
        return None

    def my_health(self):
        return self.judge((900, 900))


def swept(points=3):
    return "\n".join(f"sweep next {k} left {points-k} of {points}" for k in range(points)) + f"\nsweep next 0 left 0 of {points}\nswept"


class DungeonTests(unittest.TestCase):
    def run_hunt(self, sweeps, fights=(), where=INSIDE, travels=None, distance=50.):
        seen, events, clock = [], [], {"now": 0.}
        engine = FakeEngine(fights, seen, sweeps, where, travels)
        engine.distance = distance
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        runner = Sequence(profile, Backend(), Control(), lambda kind, text: events.append((kind, text)), engine=engine, detector=Detect(),
                          clock=lambda: clock["now"], sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.diagnostic_dir = Path("nowhere")
        runner.save_failure = lambda error: None
        self.engine, self.clock = engine, clock
        runner.run()
        return seen, events

    def test_fights_what_the_sweep_stops_for_then_walks_on_from_the_same_point(self):
        seen, events = self.run_hunt(["Sweeping.\nsweep next 4 left 10 of 12\nenemy Rat 640 Rat"], fights=[True])
        self.assertEqual(seen[:3], [("sweep", None, ()), ("fight", "Rat"), ("sweep", (4, 10), ())])
        self.assertEqual(self.engine.backs, [False])          # never backs away indoors
        self.assertIn("1 killed", events[-1][1])
        self.assertIn("Stop pressed", events[-1][1])

    def test_it_walks_up_close_before_the_first_shot(self):
        seen, _ = self.run_hunt(["sweep next 4 left 10 of 12" + chr(10) + "enemy Rat 1400 Rat"], fights=[True], distance=1400.)
        self.assertEqual(seen[1:3], [("walk", "Rat", dungeon_runner.CLOSE_IN), ("fight", "Rat")])

    def test_one_it_cannot_hurt_is_left_alone_for_the_rest_of_the_sweep(self):
        seen, _ = self.run_hunt(["sweep next 2 left 5 of 9\nenemy Rat 300 Rat"], fights=["No damage to Rat in 20 s."]*2)
        self.assertEqual(seen[-1], ("sweep", (2, 5), ("Rat",)))

    def test_all_walked_it_goes_out_waits_and_comes_back_in_to_sweep_again(self):
        seen, events = self.run_hunt([swept(), swept()])
        self.assertEqual(seen, [("sweep", None, ()), ("travel", OUTSIDE), ("travel", INSIDE), ("sweep", None, ()),
                                ("travel", OUTSIDE), ("travel", INSIDE), ("sweep", None, ())])
        self.assertGreaterEqual(self.clock["now"], 2*RESPAWN_WAIT)
        self.assertTrue(any("Waiting outside" in text for kind, text in events if kind == "status"))

    def test_started_outside_it_goes_in_first(self):
        seen, _ = self.run_hunt([], where=OUTSIDE)
        self.assertEqual(seen[:2], [("travel", INSIDE), ("sweep", None, ())])

    def test_started_anywhere_else_it_refuses(self):
        seen, events = self.run_hunt([], where=5)
        self.assertEqual(seen, [])
        self.assertIn("Start inside Regant's Legacy", events[-1][1])

    def test_a_trip_that_ends_somewhere_else_stops_it(self):
        seen, events = self.run_hunt([swept()], travels={OUTSIDE: 7})
        self.assertEqual(seen[-1], ("travel", OUTSIDE))
        self.assertIn("Could not get to the swamp outside", events[-1][1])

    def test_anything_else_the_sweep_says_ends_the_hunt(self):
        seen, events = self.run_hunt(["Stopped: Neocron lost focus."])
        self.assertEqual(seen, [("sweep", None, ())])
        self.assertIn("Neocron lost focus", events[-1][1])


class EngineTests(unittest.TestCase):
    def test_sweep_and_travel_commands(self):
        engine = DungeonEngine(None, None)
        sent = []
        engine.live = lambda args, tick: sent.append(args) or ""
        engine.sweep(None, set(), None)
        self.assertEqual(sent[0][:3], ["sweep", "--world", str(INSIDE)])
        self.assertNotIn("--names", sent[0])
        self.assertNotIn("--avoid", sent[0])
        self.assertEqual(sent[0][sent[0].index("--engage")+1], str(dungeon_runner.ENGAGE))
        self.assertNotIn("--from", sent[0])
        engine.calibration = "190,0.0024"
        engine.sweep((7, 3), {"b2", "a1"}, None)
        self.assertEqual(sent[1][sent[1].index("--calibration")+1], "190,0.0024")
        self.assertEqual(sent[1][sent[1].index("--from")+1:sent[1].index("--from")+4], ["7", "--left", "3"])
        self.assertEqual(sent[1][sent[1].index("--skip")+1], "a1,b2")
        engine.travel(OUTSIDE, None)
        self.assertEqual(sent[2][:2], ["travel", str(OUTSIDE)])
        engine.avoid = ["parasite", "Genotoxic Slugger"]
        engine.sweep(None, set(), None)
        self.assertEqual(sent[3][sent[3].index("--avoid")+1], "parasite,Genotoxic Slugger")

    def test_the_runner_hands_dont_attack_to_the_sweep(self):
        runner = DungeonRunner(default_profile(), Backend(), Control(), lambda *a: None, spare=["parasite"])
        self.assertEqual(runner.engine.avoid, ["parasite"])


if __name__ == "__main__":
    unittest.main()
