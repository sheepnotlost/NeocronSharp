"""Two clients at once (turns.py): research on one takes turns at the mouse with the job loop on the other."""
import threading
import time
import unittest

from macro_core import Control, Interrupted, default_profile
from test_blueprints import BlueprintBackend, BlueprintDetector
from test_macro import FakeClock
from turns import Turns
from vision_runner import BlueprintRunner

JOBS, RESEARCH = 100, 200       # the two clients' windows


class TurnsTests(unittest.TestCase):
    def setUp(self):
        self.front = []
        self.turns = Turns(bring=lambda hwnd: self.front.append(hwnd) or True, sleep=lambda s: None)
        self.stopped = threading.Event()

    def test_research_waits_for_a_gap_in_the_jobs_then_the_job_client_comes_back(self):
        self.turns.hold("jobs", self.stopped, home=JOBS)
        clicked = threading.Event()

        def research():
            with self.turns.turn(RESEARCH, self.stopped):
                clicked.set()
        worker = threading.Thread(target=research)
        worker.start()
        time.sleep(.2)
        self.assertFalse(clicked.is_set(), "research must not click during a job step")
        self.assertTrue(self.turns.give_way(self.stopped))
        worker.join(2)
        self.assertTrue(clicked.is_set())
        self.assertEqual(self.turns.holder, "jobs")
        self.assertEqual(self.front[0], RESEARCH)
        self.assertEqual(self.front[-1], JOBS)

    def test_a_gap_with_no_research_waiting_changes_nothing(self):
        self.turns.hold("jobs", self.stopped, home=JOBS)
        self.assertFalse(self.turns.give_way(self.stopped))
        self.assertEqual(self.front, [])

    def test_stop_ends_a_wait_for_a_turn(self):
        self.turns.hold("jobs", self.stopped, home=JOBS)
        self.stopped.set()
        with self.assertRaises(Interrupted):
            with self.turns.turn(RESEARCH, self.stopped):
                pass
        self.assertEqual(self.turns.waiting, 0)

    def test_a_client_windows_will_not_bring_up_gives_the_turn_back(self):
        turns = Turns(bring=lambda hwnd: False, clock=FakeClock().clock, sleep=lambda s: None)
        clock = FakeClock()
        turns.clock, turns.sleep = clock.clock, clock.sleep
        with self.assertRaises(Interrupted):
            with turns.turn(RESEARCH, self.stopped):
                pass
        self.assertIsNone(turns.holder)


class ResearchBesideJobsTests(unittest.TestCase):
    def test_start_is_clicked_only_on_researchs_turn_in_front(self):
        profile = default_profile()
        profile.update(operation="blueprints", blueprints={"count": 2}, client_size=[2560, 1440])
        clock = FakeClock()
        backend = BlueprintBackend(clock)
        backend.hwnd, backend.in_turn = RESEARCH, False
        clicks = []
        down = backend.button
        backend.button = lambda name, is_down: clicks.append(backend.in_turn) or down(name, is_down)
        front = []
        turns = Turns(bring=lambda hwnd: front.append(hwnd) or True, sleep=lambda s: None)
        messages = []
        runner = BlueprintRunner(profile, backend, Control(), lambda k, v: messages.append((k, v)),
                                 clock.clock, clock.sleep, detector=BlueprintDetector(), turns=turns)
        runner.run()
        self.assertFalse([v for k, v in messages if k == "error"], messages)
        self.assertEqual(runner.completed, 2)
        self.assertTrue(clicks and all(clicks), "every press and release on research's turn")
        self.assertFalse(backend.in_turn)
        self.assertEqual(front, [RESEARCH, RESEARCH])
        self.assertEqual(turns.turns_given, 2)


if __name__ == "__main__":
    unittest.main()
