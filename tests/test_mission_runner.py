"""TL60 jobs: what it reads, what it clicks, and when it stops (no engine, no game input)."""
import unittest

import numpy as np

import mission_runner
from mission_runner import MANAGER, RECRUITER, MissionRunner, answer, dialog_open, is_job, place, rn_page, text_lines
from macro_core import Control, Interrupted, default_profile

BRIGHT, PANEL = (115, 255, 168), (41, 105, 62)


def actor(name, distance=300., kind="npc", dead=False):
    return {"id": name, "name": name, "kind": kind, "distance": distance, "dead": dead}


def blank():
    return np.zeros((1440, 2560, 3), np.uint8)


def button(frame, point):
    x, y = place(frame, point)
    frame[y-14:y+14, x-30:x+30] = BRIGHT


def line(text):
    return {"text": text, "point": (10, 20)}


class ReadingTests(unittest.TestCase):
    def test_pages_by_their_buttons(self):
        self.assertIsNone(rn_page(blank()))
        factions, jobs, accepted = blank(), blank(), blank()
        button(factions, mission_runner.DOWNLOAD_SHOWS)
        for frame in (jobs, accepted):
            button(frame, mission_runner.BACK_SHOWS)
        button(jobs, mission_runner.NEXT_SHOWS)
        self.assertEqual([rn_page(f) for f in (factions, jobs, accepted)], ["factions", "list", "accepted"])

    def test_a_conversation_fills_its_window_with_green(self):
        frame = blank()
        self.assertFalse(dialog_open(frame))
        frame[:] = PANEL
        self.assertTrue(dialog_open(frame))

    def test_the_two_tl60_jobs_part_by_width(self):
        self.assertTrue(is_job("TtGO 36", .0359))
        self.assertFalse(is_job("TtGO 36", .0426))

    def test_other_research_jobs_are_not_it(self):
        self.assertFalse(is_job("20", .0359))
        self.assertFalse(is_job("", .0359))

    def test_answers_survive_what_the_ocr_did_to_them(self):
        lines = [line("A productive day,Runner"), line("Do you have workfomrne?"), line("> I wanted to talk to sometpdy else.")]
        self.assertEqual(answer(lines, RECRUITER), lines[1])
        lines = [line("We need 3 Pepper Park Wiretap Relay TS vO.6r Blueprints"), line("- > Good/ I'll start straightaway")]
        self.assertEqual(answer(lines, RECRUITER), lines[1])
        self.assertEqual(answer([line("Good luck,"), line("> (click)")], RECRUITER)["text"], "> (click)")

    def test_a_shop_greeting_is_left_with_the_wrong_person_line(self):
        lines = [line("Hello and welcome."), line("what do you sell?"), line("| know, show me the list please!"), line("Oh sorry I got the wrong person.")]
        self.assertEqual(answer(lines, MANAGER), lines[3])

    def test_words_it_does_not_know_are_not_answered(self):
        self.assertIsNone(answer([line("You do not have the blueprints.")], MANAGER))

    def test_words_on_one_height_are_one_line(self):
        found = text_lines([("for", 80, 10, 20, 12), ("Do", 10, 11, 20, 12), ("Next", 10, 40, 30, 12)], 100, 200)
        self.assertEqual([f["text"] for f in found], ["Do for", "Next"])
        self.assertEqual(found[0]["point"], (155, 216))


class Backend:
    def capture(self):
        return blank()

    def check_focus(self, size):
        pass

    def release_all(self):
        pass


class FakeEngine:
    def __init__(self, people):
        self.people, self.calls = people, []

    def nearby(self):
        return self.people

    def spot(self):
        self.calls.append("spot")
        return {"x": 1, "y": 2, "z": 3, "yaw": .5, "pitch": .1}

    def terminal(self, spot, tick):
        self.calls.append("terminal")
        return "Right-clicked the terminal."

    def walk(self, person, reach, tick):
        self.calls.append(("walk", person["name"]))
        return f"Reached {person['name']}, {reach} units away."

    def use(self, person, tick):
        self.calls.append(("use", person["name"]))
        return f"Right-clicked {person['name']}."


class Run(MissionRunner):
    """The loop's own order, with the screens replaced."""
    def __init__(self, engine, said, jobs=1):
        events = self.events = []
        super().__init__(default_profile(), Backend(), Control(), lambda kind, payload: events.append((kind, payload)), detector=object(), engine=engine)
        self.said, self.jobs = said, jobs

    def hide_pointer(self):
        pass

    def take_job(self, spot):
        if self.completed == self.jobs:
            raise Interrupted("Enough.")
        self.engine.terminal(spot, None)

    def wait(self, seconds, safe_pause=False):
        pass

    def open_talk(self, person):
        self.who = person["name"]
        self.screens = list(self.said[self.who])

    def dialog_lines(self):
        return [line(text) for text in self.screens[0]] if self.screens else None

    def click(self, point):
        self.screens.pop(0)


PEOPLE = [actor("Recruiter - Far", 900), actor("Recruiter - Near", 400), actor("Faction Supply Manager - Yul", 300),
          actor("Faction Supply Manager - Lao", 200), actor("Security - Bob", 10), actor("Recruiter - Player", 5, kind="player")]
RECRUITED = [["A productive day, Runner.", "> Do you have work for me?"], ["Here is your copy.", "> (click)"]]
PAID = [["Good Quality. Here is your payment, 6000 credits", "> (click)"]]
SHOP = [["Hello and welcome.", "> Oh sorry I got the wrong person."]]


class LoopTests(unittest.TestCase):
    def said(self, lao=SHOP, yul=PAID):
        return {"Recruiter - Near": RECRUITED, "Faction Supply Manager - Lao": lao, "Faction Supply Manager - Yul": yul}

    def test_nearest_recruiter_then_both_managers_then_back_to_the_terminal(self):
        engine = FakeEngine(PEOPLE)
        run = Run(engine, self.said(), jobs=2)
        spoken = []
        talk = run.talk
        run.talk = lambda person, known: spoken.append(person["name"]) or talk(person, known)
        run.run()
        self.assertEqual(spoken, ["Recruiter - Near", "Faction Supply Manager - Lao", "Faction Supply Manager - Yul"]*2)
        self.assertEqual(engine.calls.count("spot"), 1)
        self.assertEqual(engine.calls.count("terminal"), 2)
        self.assertEqual(run.events[-1], ("done", "Enough. 2 jobs done."))

    def test_stops_with_the_job_open_when_nobody_pays(self):
        run = Run(FakeEngine(PEOPLE), self.said(yul=SHOP))
        run.run()
        self.assertIn("Neither faction supply manager paid", run.events[-1][1])
        self.assertEqual(run.completed, 0)

    def test_stops_on_words_it_does_not_know(self):
        run = Run(FakeEngine(PEOPLE), self.said(yul=[["Where are my blueprints?", "> I'm working on it."]]))
        run.run()
        self.assertIn("said something new: Where are my blueprints?", run.events[-1][1])

    def test_will_not_start_away_from_the_headquarters(self):
        engine = FakeEngine([actor("Security - Bob")])
        run = Run(engine, {})
        run.run()
        self.assertIn("start at the terminal", run.events[-1][1])
        self.assertEqual(engine.calls, [])

    def test_walks_up_only_when_too_far_and_closer_if_nothing_opened(self):
        engine = FakeEngine([])
        run = MissionRunner(default_profile(), Backend(), Control(), lambda *a: None, detector=object(), engine=engine)
        run.wait = lambda seconds, safe_pause=False: None
        opened = iter([False]*8+[True])
        run.frame = lambda: None
        original, mission_runner.dialog_open = mission_runner.dialog_open, lambda frame: next(opened)
        try:
            run.open_talk(actor("Recruiter - Near", 150))
        finally:
            mission_runner.dialog_open = original
        self.assertEqual(engine.calls, [("use", "Recruiter - Near"), ("walk", "Recruiter - Near"), ("use", "Recruiter - Near")])

    def test_nobody_answering_stops_the_run(self):
        run = MissionRunner(default_profile(), Backend(), Control(), lambda *a: None, detector=object(), engine=FakeEngine([]))
        run.wait = lambda seconds, safe_pause=False: None
        with self.assertRaisesRegex(Interrupted, "Could not talk to Recruiter - Near"):
            run.open_talk(actor("Recruiter - Near", 150))


class EngineTests(unittest.TestCase):
    def test_the_terminal_passes_on_what_was_measured(self):
        engine = mission_runner.Engine(None, None)
        sent = []
        engine.live = lambda args, tick: sent.append(args) or "gains 0.002 0.0015\nRight-clicked the terminal."
        spot = {"x": 875.4, "y": -383.9, "z": 863.3, "yaw": 1.5, "pitch": -.2}
        engine.terminal(spot, None)
        engine.terminal(spot, None)
        self.assertEqual(sent[0][:3], ["usespot", "875.4,-383.9,863.3", "1.5,-0.2"])
        self.assertNotIn("--gains", sent[0])
        self.assertEqual(sent[1][-2:], ["--gains", "0.002,0.0015"])

    def test_talking_right_clicks_with_the_measured_mouse(self):
        engine = mission_runner.Engine(None, None)
        sent = []
        engine.live = lambda args, tick: sent.append(args) or "Right-clicked Rat."
        engine.use(actor("Rat"), None)
        self.assertEqual(sent[0][:3], ["camera", "Rat", "--use"])


if __name__ == "__main__":
    unittest.main()
