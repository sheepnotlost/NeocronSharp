"""Stand and hunt: shoot whatever comes in range from where you stand, over and over (no engine, no game input)."""
from pathlib import Path
import unittest

import stand_runner
from loot_runner import Engine as RealEngine
from macro_core import Control, Interrupted, default_profile
from stand_runner import StandRunner
from test_loot_runner import Backend, Detect, Engine, actor


class FakeEngine(Engine):
    """Mobs come and go by script: each look round takes the next list; when the script ends, Stop is pressed."""

    def __init__(self, fights, seen, looks):
        super().__init__(fights, seen)
        self.looks = list(looks)
        self.now = []

    def nearby(self):
        if not self.looks:
            raise Interrupted("Stopped.")
        self.now = self.looks.pop(0)
        return [dict(a, dead=a["name"] in self.dead) for a in self.now]


class Sequence(StandRunner):
    def set_ui(self, reader, on):
        return True

    def reader(self):
        return None

    def my_health(self):
        return self.judge((900, 900))


class StandTests(unittest.TestCase):
    def run_hunt(self, looks, fights=(), reach=1000):
        seen, events, clock = [], [], {"now": 0.}
        engine = FakeEngine(fights, seen, looks)
        profile = default_profile()
        profile["client_size"] = [2000, 1125]
        runner = Sequence(profile, Backend(), Control(), lambda kind, text: events.append((kind, text)), engine=engine, detector=Detect(),
                          spare=["parasite"], reach=reach, clock=lambda: clock["now"], sleep=lambda s: clock.__setitem__("now", clock["now"]+s))
        runner.diagnostic_dir = Path("nowhere")
        runner.save_failure = lambda error: None
        self.engine, self.clock, self.runner = engine, clock, runner
        runner.run()
        return seen, events

    def test_it_shoots_the_nearest_in_range_and_never_walks(self):
        rat, spider = actor("Rat", distance=300.), actor("Spider", distance=200.)
        seen, events = self.run_hunt([[rat, spider], [rat, spider], [rat]], fights=[True, True])
        self.assertEqual([s for s in seen if s[0] != "fight"], [])        # no walk, no flee
        self.assertEqual(seen, [("fight", "Spider"), ("fight", "Rat")])
        self.assertEqual(self.engine.backs, [False, False])
        self.assertIn("2 killed", events[-1][1])

    def test_out_of_range_spared_and_humans_are_left_alone_and_it_waits(self):
        far, spared = actor("Rat", distance=1500.), actor("Genotoxic Parasite", distance=50.)
        human = actor("CityMerc", distance=50., faction=2)
        seen, events = self.run_hunt([[far, spared, human]]*3)
        self.assertEqual(seen, [])
        self.assertTrue(any("nothing within 1000 units" in text for kind, text in events if kind == "status"))
        self.assertGreaterEqual(self.clock["now"], 2*stand_runner.LOOK_EVERY)

    def test_one_behind_something_is_looked_at_again_in_a_few_seconds_and_others_meanwhile(self):
        rat, spider = actor("Rat", distance=300.), actor("Spider", distance=600.)
        looks = [[rat, spider], [rat, spider], [rat, spider]] + [[rat]]*(stand_runner.BLOCKED_AGAIN+2)
        seen, events = self.run_hunt(looks, fights=["No line of sight to Rat: a crate is in the way. Camera follow stopped.", True, True])
        self.assertEqual(seen, [("fight", "Rat"), ("fight", "Spider"), ("fight", "Rat")])
        self.assertTrue(any("Not starting on Rat: no clear shot from here" in text for _, text in events))

    def test_one_that_takes_no_damage_waits_longer(self):
        rat = actor("Rat", distance=300.)
        looks = [[rat], [rat]] + [[rat]]*(stand_runner.UNHURT_AGAIN+2)
        seen, _ = self.run_hunt(looks, fights=["No damage to Rat for 20 s. Camera follow stopped.", True])
        self.assertEqual(seen, [("fight", "Rat"), ("fight", "Rat")])
        self.assertGreaterEqual(self.clock["now"], stand_runner.UNHURT_AGAIN)

    def test_one_that_went_out_of_view_is_let_go_for_the_next_and_tried_again_later(self):
        rat, spider = actor("Rat", distance=300.), actor("Spider", distance=600.)
        looks = [[rat, spider], [rat, spider], [rat, spider]] + [[rat]]*(stand_runner.LOST_AGAIN+2)
        seen, events = self.run_hunt(looks, fights=["No line of sight to Rat for 8 s: it went out of view. Camera follow stopped.", True, True])
        self.assertEqual(seen, [("fight", "Rat"), ("fight", "Spider"), ("fight", "Rat")])
        self.assertTrue(any("Rat went out of view: on to the nearest in view. Looking at it again in 15 s." in text for _, text in events))
        self.assertGreaterEqual(self.clock["now"], stand_runner.LOST_AGAIN)

    def test_it_never_switches_to_one_that_gets_on_you(self):
        self.run_hunt([[]])
        self.assertFalse(self.runner.engine.pushers)
        self.assertTrue(self.runner.engine.stay)

    def test_the_engine_is_told_to_stay(self):
        runner_engine = RealEngine(lambda text: None, Control())
        runner_engine.stay = True
        sent = []
        runner_engine.run = lambda args, tick=lambda: None: sent.append(args) or "Rat died."
        runner_engine.fight({"id": "7"}, lambda: None)
        self.assertIn("--stay", sent[0])
