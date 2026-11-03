"""TL60 jobs: what it reads, what it clicks, and when it stops (no engine, no game input)."""
import unittest
from unittest.mock import patch

import numpy as np

import mission_runner
from mission_runner import MissionRunner, answer, dialog_box, dialog_open, first_option, is_job, place, rn_open, rn_page, still_open, text_lines
from macro_core import Control, Interrupted, default_profile

BRIGHT, PANEL = (115, 255, 168), (41, 105, 62)


def actor(name, distance=300., kind="npc", dead=False):
    return {"id": name, "name": name, "kind": kind, "distance": distance, "dead": dead}


def blank():
    return np.zeros((1440, 2560, 3), np.uint8)


def button(frame, point):
    x, y = place(frame, point)
    frame[y-14:y+14, x-30:x+30] = BRIGHT


WIDTH = mission_runner.TALK_WIDE
SPEECH, OPTION, UNREAD = 216, 222, 244      # where each kind of line starts, measured on the video: an unread ">" leaves the words


def line(text, left=SPEECH):
    return {"text": text, "left": left, "point": (10, 20)}


def conversation(box):
    frame = blank()
    left, top, wide, high = box
    frame[top:top+high, left:left+wide] = PANEL
    return frame


def words(frame, top, left, wide=400, high=23):
    frame[top:top+high, left:left+wide:2] = (200, 230, 200)


class ReadingTests(unittest.TestCase):
    def test_pages_by_their_buttons(self):
        self.assertIsNone(rn_page(blank()))
        factions, jobs, accepted = blank(), blank(), blank()
        button(factions, mission_runner.DOWNLOAD_SHOWS)
        for frame in (jobs, accepted):
            button(frame, mission_runner.BACK_SHOWS)
        button(jobs, mission_runner.NEXT_SHOWS)
        self.assertEqual([rn_page(f) for f in (factions, jobs, accepted)], ["factions", "list", "accepted"])

    def test_the_terminal_window_is_the_same_pixels_on_every_client(self):
        for high, wide, left, top in ((1440, 2560, 960, 480), (1080, 1920, 640, 300), (768, 1366, 363, 144), (1050, 1680, 520, 285)):
            frame = np.zeros((high, wide, 3), np.uint8)
            self.assertEqual(place(frame, (0, 0)), (left, top))
            self.assertEqual(place(frame, mission_runner.MISSIONS_TAB), (left+400, top+21))
            button(frame, mission_runner.DOWNLOAD_SHOWS)
            self.assertEqual(rn_page(frame), "factions")

    def test_a_conversation_is_found_wherever_it_sits(self):
        frame = blank()
        self.assertIsNone(dialog_box(frame))
        frame[300:1100, 100:1300] = PANEL
        frame[400:430, 200:900:8] = (230, 240, 230)     # words on it
        self.assertTrue(dialog_open(frame))
        self.assertEqual(dialog_box(frame), (100, 300, 1200, 800))

    def test_the_name_bar_and_scenery_touching_it_are_not_the_conversation(self):
        frame = blank()
        frame[320:1190, 200:1760] = PANEL
        frame[250:308, 200:1760] = PANEL                # the name bar over its gap
        frame[250:320, 0:300] = PANEL                   # a green sign behind, joining the two
        self.assertEqual(dialog_box(frame), (200, 320, 1560, 870))

    def test_the_first_option_is_read_from_the_pixels(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        for row in (380, 406):
            words(frame, row, 216)
        self.assertIsNone(first_option(frame, box))     # Only the speech so far, wrapped onto two lines.
        words(frame, 438, 223)
        words(frame, 468, 223)
        self.assertEqual(first_option(frame, box), (262, 449))

    def test_an_option_under_the_pointer_lights_up_green_and_still_counts(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        words(frame, 380, 216)
        frame[438:461, 223:280:2] = (70, 204, 129)
        self.assertEqual(first_option(frame, box), (262, 449))

    def test_the_panels_top_border_is_no_line_of_speech(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        words(frame, 330, 208)
        words(frame, 380, 216)
        self.assertIsNone(first_option(frame, box))

    def test_a_speech_line_a_pixel_off_is_no_option(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        words(frame, 380, 216)
        words(frame, 406, 217)
        self.assertIsNone(first_option(frame, box))

    def test_the_pointer_over_the_panel_is_no_option(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        words(frame, 380, 216)
        frame[420:428, 500:504] = (255, 255, 255)
        self.assertIsNone(first_option(frame, box))
        frame[420:445, 262:270] = (255, 255, 255)       # as tall as a line, where the last click left it
        self.assertIsNone(first_option(frame, box))

    def test_a_closed_conversation_shows_at_once(self):
        box = (200, 320, 1560, 870)
        self.assertTrue(still_open(conversation(box), box))
        self.assertFalse(still_open(blank(), box))

    def test_the_terminal_window_shows_by_its_sides(self):
        frame = blank()
        self.assertFalse(rn_open(frame))
        left, top = place(frame, (0, 0))
        frame[top:top+480, [left, left+639]] = BRIGHT
        self.assertTrue(rn_open(frame))

    def test_the_hud_is_no_conversation(self):
        frame = blank()
        frame[1200:1400, 280:800] = PANEL               # small
        self.assertIsNone(dialog_box(frame))
        frame[:] = 0
        for x in range(1000, 2500, 60):                 # as wide, but broken up
            frame[450:1400, x:x+30] = PANEL
        self.assertIsNone(dialog_box(frame))

    def test_the_two_tl60_jobs_part_by_width(self):
        self.assertTrue(is_job("TtGO 36", .144))
        self.assertFalse(is_job("TtGO 36", .170))

    def test_other_research_jobs_are_not_it(self):
        self.assertFalse(is_job("20", .144))
        self.assertFalse(is_job("", .144))

    def test_always_the_first_option_however_the_ocr_read_it(self):
        for first in (OPTION, UNREAD, 210):
            lines = [line("You are here about the job, right?"), line("Yes, I am here", first), line("> I wanted to talk to somebody else.", OPTION)]
            self.assertEqual(answer(lines, WIDTH), lines[1])

    def test_speech_that_wraps_is_not_an_option(self):
        lines = [line("We need 3 Pepper Park Wiretap Relay"), line("the TSUNAMI SYNDICATE HEADQUARTERS section", SPEECH+1), line("- > Good/ I'll start straightaway", 210)]
        self.assertEqual(answer(lines, WIDTH), lines[2])

    def test_words_alone_wait_for_their_options(self):
        self.assertIsNone(answer([line("You are here about the job, right?")], WIDTH))

    def test_a_marked_option_counts_however_near_the_speech_it_starts(self):
        lines = [line("0k so you got the wrong person.Who's next?"), line("_> (click)", 213)]
        self.assertEqual(answer(lines, WIDTH), lines[1])

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

    def terminal(self, spot, tick, exact=False):
        self.calls.append("exact" if exact else "terminal")
        return "Right-clicked the terminal."

    def close(self):
        self.calls.append("close")

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

    def quick_talk(self, person):
        return self.talk(person)

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

    def test_once_a_manager_pays_the_other_is_left_alone(self):
        run = Run(FakeEngine(PEOPLE), self.said(lao=PAID))
        run.run()
        self.assertEqual(run.who, "Faction Supply Manager - Lao")
        self.assertEqual(run.completed, 1)

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
        self.assertEqual(engine.calls, ["close"])

    def test_walks_up_only_when_too_far_and_closer_if_nothing_opened(self):
        engine = FakeEngine([])
        run = MissionRunner(default_profile(), Backend(), Control(), lambda *a: None, detector=object(), engine=engine)
        run.wait = lambda seconds, safe_pause=False: None
        opened = iter([False]*20+[True])
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


class SelectTests(unittest.TestCase):
    def choose(self, selected_after):
        run = Run(FakeEngine([]), {})
        tapped = []
        run.tap = tapped.append
        run.frame = blank
        run.wait_for_page = lambda page, seconds: True
        run.detector = type("Detector", (), {"text_reader": lambda self: None})()
        with patch.object(mission_runner, "job_row", lambda reader, frame: 2), \
                patch.object(mission_runner, "row_is_blue", lambda frame, row: len(tapped) >= selected_after):
            run.choose_job()
        return tapped

    def test_a_click_that_only_lit_the_row_is_tried_again(self):
        row = (mission_runner.ROW_CLICK_X, mission_runner.row_y(2))
        self.assertEqual(self.choose(2), [row, row, mission_runner.ACCEPT])

    def test_a_row_that_never_selects_stops_without_accepting(self):
        with self.assertRaisesRegex(Interrupted, "did not select"):
            self.choose(99)

    def accept(self, takes):
        run = Run(FakeEngine([]), {})
        tapped = []
        run.tap = tapped.append
        run.wait_for_page = lambda page, seconds: len(tapped) >= takes
        run.accept()
        return tapped

    def test_accept_is_clicked_until_it_takes(self):
        self.assertEqual(self.accept(3), [mission_runner.ACCEPT]*3)

    def test_accept_that_never_takes_stops(self):
        with self.assertRaisesRegex(Interrupted, "not accepted"):
            self.accept(99)

    def test_the_pointer_settles_before_the_click(self):
        run = Run(FakeEngine([]), {})
        steps = []
        run.frame = blank
        run.move = lambda point: steps.append("move")
        run.wait = lambda seconds, safe_pause=False: steps.append("wait")
        run.click = lambda point: steps.append("click")
        run.tap((100, 100))
        self.assertEqual(steps, ["move", "wait", "click"])


class TerminalTests(unittest.TestCase):
    def job(self, opens):
        engine = FakeEngine([])
        run = MissionRunner(default_profile(), Backend(), Control(), lambda *a: None, detector=object(), engine=engine)
        run.open_missions = lambda: next(opens)
        run.choose_job = lambda: True
        run.wait_for_page = lambda page, seconds: True
        run.hide_pointer = lambda: None
        run.take_job({})
        return engine.calls

    def test_quick_arrival_is_enough_when_the_terminal_opens(self):
        self.assertEqual(self.job(iter(["list"])), ["terminal"])

    def test_a_missed_right_click_comes_back_exactly(self):
        self.assertEqual(self.job(iter([None, "list"])), ["terminal", "exact"])

    def test_missing_twice_stops(self):
        with self.assertRaisesRegex(Interrupted, "did not open"):
            self.job(iter([None, None]))

    def test_the_tab_is_clicked_as_soon_as_the_window_shows(self):
        run = MissionRunner(default_profile(), Backend(), Control(), lambda *a: None, detector=object(), engine=FakeEngine([]))
        run.wait = lambda seconds, safe_pause=False: None
        run.frame = blank
        tapped = []
        run.tap = tapped.append
        looks = iter([None, None, None, "list"])
        with patch.object(mission_runner, "rn_page", lambda frame: next(looks)), patch.object(mission_runner, "rn_open", lambda frame: True):
            self.assertEqual(run.open_missions(), "list")
        self.assertEqual(tapped, [mission_runner.MISSIONS_TAB])

    def test_nothing_on_screen_means_the_right_click_missed(self):
        run = MissionRunner(default_profile(), Backend(), Control(), lambda *a: None, detector=object(), engine=FakeEngine([]))
        run.wait = lambda seconds, safe_pause=False: None
        run.frame = blank
        run.detector = type("Detector", (), {"text_reader": lambda self: None})()
        run.ui_visible = lambda reader: False
        self.assertIsNone(run.open_missions())


class QuickTalkTests(unittest.TestCase):
    BOX = (200, 320, 1560, 870)

    def talk(self, screens):
        """Each screen shows until its option is clicked. None is the conversation gone."""
        run = Run(FakeEngine([]), {})
        run.open_talk = lambda person: None
        shown, clicks = list(screens), []
        run.frame = lambda: shown[0]
        now = iter(x*.01 for x in range(100000))
        run.clock = lambda: next(now)

        def click(point):
            clicks.append(point)
            shown.pop(0)
        run.click = click
        run.quick_talk = MissionRunner.quick_talk.__get__(run)
        with patch.object(mission_runner, "dialog_box", lambda frame: self.BOX):
            run.quick_talk(actor("Recruiter - Near"))
        return clicks

    def screen(self, *lefts):
        frame = conversation(self.BOX)
        for i, left in enumerate(lefts):
            words(frame, 380+26*i, left)
        return frame

    def test_each_screen_is_clicked_once_and_it_ends_with_the_conversation(self):
        clicks = self.talk([self.screen(216, 223, 223), self.screen(216, 217, 223), blank()])
        self.assertEqual(clicks, [(262, 417), (262, 443)])

    def test_stops_when_it_never_ends(self):
        run = Run(FakeEngine([]), {})
        run.open_talk = lambda person: None
        run.frame = lambda: self.screen(216)
        now = iter(range(1000))
        run.clock = lambda: next(now)
        run.quick_talk = MissionRunner.quick_talk.__get__(run)
        with patch.object(mission_runner, "dialog_box", lambda frame: self.BOX), self.assertRaisesRegex(Interrupted, "did not end"):
            run.quick_talk(actor("Recruiter - Near"))


class FakeServer:
    def __init__(self, replies):
        self.sent, self.replies = [], list(replies)
        self.stdin = self
        self.stdout = iter(())

    def write(self, text):
        self.sent.append(text)

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def poll(self):
        return None

    def wait(self, seconds):
        return 0


class ServeTests(unittest.TestCase):
    def engine(self, *replies):
        engine = mission_runner.Engine(None, Control())
        engine.server = FakeServer(replies)
        for reply in replies:
            engine.lines.put(reply)
        return engine

    def test_one_engine_answers_every_command(self):
        engine = self.engine("Right-clicked Rat.", "", "{\"x\": 1}", mission_runner.SERVE_DONE)
        with patch.object(mission_runner.tt, "clear_stop", lambda: None):
            self.assertEqual(engine.live(["camera", "Rat", "--use"], lambda: None), "Right-clicked Rat.")
        self.assertEqual(engine.server.sent, ["camera\tRat\t--use\n"])

    def test_a_tool_reads_its_json(self):
        engine = self.engine("{\"live\": true, \"x\": 1}", mission_runner.SERVE_DONE)
        with patch.object(mission_runner.tt, "clear_stop", lambda: None):
            self.assertEqual(engine.spot()["x"], 1)

    def test_an_engine_that_died_ends_the_command(self):
        engine = self.engine("Stopped: F8 pressed.", None)
        with patch.object(mission_runner.tt, "clear_stop", lambda: None):
            self.assertEqual(engine.live(["camera"], lambda: None), "Stopped: F8 pressed.")

    def test_stop_ends_the_engine(self):
        engine = self.engine()
        server = engine.server
        engine.control.stopped.set()
        stopped = []
        with patch.object(mission_runner.tt, "clear_stop", lambda: None), patch.object(mission_runner.tt, "stop_walk", stopped.append), \
                self.assertRaisesRegex(Interrupted, "Stopped"):
            engine.live(["camera"], lambda: None)
        self.assertEqual(stopped, [server])
        self.assertIsNone(engine.server)

    def test_closing_ends_the_engine(self):
        engine = self.engine()
        server = engine.server
        engine.close()
        self.assertTrue(server.closed)
        self.assertIsNone(engine.server)


class HidePointerTests(unittest.TestCase):
    def run_it(self, visible):
        run = MissionRunner(default_profile(), Backend(), Control(), lambda *a: None, detector=object(), engine=FakeEngine([]))
        run.detector = type("Detector", (), {"text_reader": lambda self: None})()
        looks = iter(visible)
        run.ui_visible = lambda reader: next(looks)
        run.wait = lambda seconds, safe_pause=False: None
        pressed = []
        run.press = pressed.append
        run.hide_pointer()
        return pressed

    def test_no_tab_with_the_menus_already_closed(self):
        self.assertEqual(self.run_it([False]), [])

    def test_one_tab_and_it_watches_them_close(self):
        self.assertEqual(self.run_it([True, True, False]), ["tab"])


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
