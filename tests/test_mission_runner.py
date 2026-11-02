"""TL60 jobs: what it reads, what it clicks, and when it stops (no engine, no game input)."""
import unittest

import numpy as np

import mission_runner
from mission_runner import MissionRunner, answer, dialog_open, is_job, place, rn_page, text_lines
from macro_core import Control, Interrupted, default_profile

BRIGHT, PANEL = (115, 255, 168), (41, 105, 62)


def actor(name, distance=300., kind="npc", dead=False):
    return {"id": name, "name": name, "kind": kind, "distance": distance, "dead": dead}


def blank():
    return np.zeros((1440, 2560, 3), np.uint8)


def button(frame, point):
    x, y = place(frame, point)
    frame[y-14:y+14, x-30:x+30] = BRIGHT


WIDTH = 2560
SPEECH, OPTION, UNREAD = 216, 222, 244      # where each kind of line starts, measured on the video: an unread ">" leaves the words


def line(text, left=SPEECH):
    return {"text": text, "left": left, "point": (10, 20)}


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

    def test_always_the_first_option_however_the_ocr_read_it(self):
        for first in (OPTION, UNREAD, 210):
            lines = [line("You are here about the job, right?"), line("Yes, I am here", first), line("> I wanted to talk to somebody else.", OPTION)]
            self.assertEqual(answer(lines, WIDTH), lines[1])

    def test_speech_that_wraps_is_not_an_option(self):
        lines = [line("We need 3 Pepper Park Wiretap Relay"), line("the TSUNAMI SYNDICATE HEADQUARTERS section", SPEECH+1), line("- > Good/ I'll start straightaway", 210)]
        self.assertEqual(answer(lines, WIDTH), lines[2])

    def test_words_alone_wait_for_their_options(self):
        self.assertIsNone(answer([line("You are here about the job, right?")], WIDTH))

    def test_leaving_is_never_the_answer(self):
        self.assertIsNone(answer([line("A productive day,Runner"), line("o somebody else.", 456)], WIDTH))

    def test_a_screen_is_answered_only_once_it_stops_changing(self):
        run = Run(FakeEngine(PEOPLE), {})
        reads = iter([[line("A productive day,Runner"), line("> Do yo", OPTION)]]+[[line("A productive day,Runner"), line("> Do you have work for me?", OPTION)]]*2)
        run.dialog_lines = lambda: next(reads)
        run.last_frame = blank()
        self.assertEqual(run.screen()[1]["text"], "> Do you have work for me?")

    def test_a_shop_is_left_with_the_wrong_person_line(self):
        lines = [line("Hello and welcome."), line("what do you sell?", 317), line("| know, show me the list please!", UNREAD), line("Oh sorry I got the wrong person.", 210)]
        self.assertEqual(answer(lines, WIDTH), lines[3])

    def test_words_on_one_height_are_one_line(self):
        found = text_lines([("for", 80, 10, 20, 12), ("Do", 10, 11, 20, 12), ("Next", 10, 40, 30, 12)], 100, 200)
        self.assertEqual([f["text"] for f in found], ["Do for", "Next"])
        self.assertEqual(found[0]["point"], (155, 216))
        self.assertEqual(found[0]["left"], 110)


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
        self.last_frame = blank()
        if not self.screens:
            return None
        return [line(text, SPEECH if i == 0 else OPTION) for i, text in enumerate(self.screens[0])]

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
        run.talk = lambda person: spoken.append(person["name"]) or talk(person)
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

    def test_any_first_option_will_do(self):
        run = Run(FakeEngine(PEOPLE), {**self.said(), "Recruiter - Near": [["You are here about the job, right?", "> Yes, I am here because of the job you have..."], *RECRUITED]})
        run.run()
        self.assertEqual(run.completed, 1)

    def test_stops_when_the_options_never_come(self):
        run = Run(FakeEngine(PEOPLE), self.said(yul=[["Where are my blueprints?"]]))
        now = iter(range(1000))
        run.clock = lambda: next(now)
        run.run()
        self.assertIn("gave no options to answer: Where are my blueprints?", run.events[-1][1])

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
