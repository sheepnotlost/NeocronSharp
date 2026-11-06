"""TL60 and TL130 jobs: what it reads, what it clicks, and when it stops (no engine, no game input)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from vision import cv2

import job_aim
import mission_runner
from mission_runner import MissionRunner, answer, dialog_box, dialog_open, first_option, is_job, place, rn_open, rn_page, still_open, text_lines
from macro_core import Control, Interrupted, default_profile

BRIGHT, PANEL = (115, 255, 168), (41, 105, 62)


def actor(name, distance=300., kind="npc", dead=False):
    return {"id": name, "name": name, "kind": kind, "distance": distance, "dead": dead}


job_aim.AIM_FILE = None      # the tests never write this PC's learned aim


def blank():
    return np.zeros((1440, 2560, 3), np.uint8)


def button(frame, point):
    x, y = place(frame, point)
    frame[y-14:y+14, x-30:x+30] = BRIGHT


def rn_screenshot(name, left, top, size=(1440, 2560)):
    """A screenshot of the R.N. window that starts left and top pixels inside it, where the window would be."""
    frame = np.zeros((*size, 3), np.uint8)
    picture = np.asarray(Image.open(Path(__file__).parent / "fixtures" / name).convert("RGB"))
    x, y = place(frame, (left, top))
    frame[y:y+picture.shape[0], x:x+picture.shape[1]] = picture
    return frame


def difficulty_frame(easy=False, size=(1440, 2560)):
    """The supplied screenshot's selected-level label and first two difficulty rows."""
    frame = np.zeros((*size, 3), np.uint8)
    name = "mission_difficulty_easy.png" if easy else "mission_difficulty.png"
    panel = np.asarray(Image.open(Path(__file__).parent / "fixtures" / name).convert("RGB"))
    x, y = place(frame, (468, 105))
    frame[y:y+panel.shape[0], x:x+panel.shape[1]] = panel
    return frame


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


def panel():
    """A client filled with the R.N. window's dark green, which its sides blur into when stretched."""
    frame = blank()
    frame[:] = (26, 71, 46)
    return frame


def rn_sides(frame):
    """The R.N. window's one-pixel bright sides, where the game draws them at 640x480."""
    (left, top), (right, _) = place(frame, (0, 0)), place(frame, (mission_runner.RN_WIDE-1, 0))
    frame[top:top+mission_runner.RN_HIGH, [left, right]] = (78, 228, 145)
    return frame


def stretched(frame, scale):
    """The whole client drawn bigger or smaller, as another screen size or Windows' display scaling draws the game."""
    high, wide = frame.shape[:2]
    return cv2.resize(frame, (round(wide*scale), round(high*scale)), interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)


class ScaleTests(unittest.TestCase):
    """The R.N. window found at whatever size it is drawn: the clicks missed on another PC (5 Nov)."""
    def setUp(self):
        mission_runner.rn_scales.clear()
        self.addCleanup(mission_runner.rn_scales.clear)

    def test_the_window_is_found_at_every_size_and_its_buttons_are_placed_to_match(self):
        for scale in (.5, .625, .75, .9, 1, 1.25, 1.5, 1.75, 2):
            mission_runner.rn_scales.clear()
            frame = rn_sides(panel())
            button(frame, mission_runner.DOWNLOAD_SHOWS)
            frame = stretched(frame, scale)
            self.assertAlmostEqual(mission_runner.find_rn(frame), scale, delta=.006, msg=scale)
            self.assertEqual(rn_page(frame), "factions", scale)
            x, y = place(frame, mission_runner.DOWNLOAD)
            self.assertAlmostEqual(x, (1280+(mission_runner.DOWNLOAD[0]-320))*scale, delta=4)
            self.assertAlmostEqual(y, (720+(mission_runner.DOWNLOAD[1]-240))*scale, delta=4)

    def test_no_window_is_no_scale_and_the_last_one_found_is_kept(self):
        self.assertIsNone(mission_runner.find_rn(blank()))
        frame = stretched(rn_sides(blank()), 1.5)
        mission_runner.find_rn(frame)
        self.assertIsNone(mission_runner.find_rn(np.zeros_like(frame)))
        self.assertEqual(mission_runner.rn_scale(frame), 1.5)

    def test_the_difficulty_reads_in_a_stretched_window(self):
        for scale in (.75, .9, 1.25, 1.5, 2):
            mission_runner.rn_scales.clear()
            easy, very_easy = (stretched(rn_sides(difficulty_frame(easy=chosen)), scale) for chosen in (True, False))
            mission_runner.find_rn(easy)
            self.assertEqual([mission_runner.level_selected(easy, row) for row in (0, 1)], [False, True], scale)
            self.assertEqual([mission_runner.level_selected(very_easy, row) for row in (0, 1)], [True, False], scale)

    def test_labels_of_different_widths_never_match(self):
        word = np.full((10, 30), 200, np.uint8)
        self.assertFalse(mission_runner.same_label(word, np.full((10, 55), 200, np.uint8)))


class AimTests(unittest.TestCase):
    """The job loop corrects its own clicks and keeps what worked (the user's ask, 5 Nov)."""
    def run_at(self, path=None):
        run = Run(FakeEngine([]), {})
        run.aim = job_aim.Aim(path)
        run.frame = blank
        run.last_frame = blank()
        self.clicks = []
        run.move = lambda point: None
        run.click = self.clicks.append
        return run

    def test_a_missed_button_is_tried_a_little_to_the_side_and_the_shift_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"job-aim.json"
            run = self.run_at(path)
            pages = iter(["list"]*2 + ["accepted"]*99)       # two clicks at the usual place miss; the shifted one takes
            run.wait_for_page = lambda page, seconds: next(pages) == page
            run.accept()
            usual = place(blank(), mission_runner.ACCEPT)
            self.assertEqual(self.clicks[:2], [usual, usual])
            self.assertEqual(self.clicks[2], (usual[0]+4, usual[1]))
            self.assertEqual(run.aim.rn(blank()), (4, 0))
            again = self.run_at(path)                          # the next run starts from what worked
            again.wait_for_page = lambda page, seconds: True
            again.accept()
            self.assertEqual(self.clicks, [(usual[0]+4, usual[1])])
            self.assertTrue(any("kept for next time" in text for kind, text in run.events if kind == "log"))

    def test_a_click_that_takes_first_time_changes_nothing(self):
        run = self.run_at()
        run.wait_for_page = lambda page, seconds: True
        run.accept()
        self.assertEqual(run.aim.rn(blank()), (0, 0))
        self.assertEqual(run.trial, (0, 0))

    def test_shifts_never_reach_the_next_button(self):
        aim = job_aim.Aim(None)
        for _ in range(20):
            aim.learn_rn(blank(), (8, 2))
            aim.learn_chat(blank(), .012)
        self.assertEqual(aim.rn(blank()), job_aim.RN_MOST)
        self.assertEqual(aim.chat(blank()), job_aim.CHAT_MOST)

    def test_a_new_screen_size_says_so_and_a_known_one_starts_from_its_saved_scale(self):
        mission_runner.rn_scales.clear()
        self.addCleanup(mission_runner.rn_scales.clear)
        run = self.run_at()
        run.calibrate()
        self.assertIn("New screen size 2560x1440", run.events[-1][1])
        run.aim.learn_scale(blank(), 1.5)
        run.calibrate()
        self.assertEqual(mission_runner.rn_scale(blank()), 1.5)
        self.assertIn("1.5 times", run.events[-1][1])

    def test_a_chat_option_clicked_again_is_nudged_and_the_nudge_that_worked_is_kept(self):
        run = self.run_at()
        run.talk_high = 1000
        run.click_option((300, 400))
        run.click_option((300, 400), .006)
        self.assertEqual(self.clicks, [(300, 400), (300, 406)])
        run.chat_took(.006, "Recruiter")
        self.assertEqual(run.aim.chat(blank()), .006)
        run.click_option((300, 400))
        self.assertEqual(self.clicks[-1], (300, 406))


class ReadingTests(unittest.TestCase):
    def test_selected_difficulty_matches_the_whole_easy_label(self):
        for size in ((1440, 2560), (1080, 1920), (768, 1366)):
            self.assertFalse(mission_runner.level_selected(difficulty_frame(size=size), 1))
            self.assertTrue(mission_runner.level_selected(difficulty_frame(easy=True, size=size), 1))
        self.assertFalse(mission_runner.level_selected(blank(), 1))

    def test_very_hard_is_selected_only_once_its_label_shows(self):
        hovered, listed = rn_screenshot("very_hard_hovered.png", 20, 8), rn_screenshot("tl130_list.png", 7, 13)
        self.assertFalse(mission_runner.level_selected(hovered, 4))
        selected = hovered.copy()
        selected[place(selected, (0, 105))[1]:place(selected, (0, 120))[1]] = listed[place(listed, (0, 105))[1]:place(listed, (0, 120))[1]]
        self.assertTrue(mission_runner.level_selected(selected, 4))
        self.assertFalse(mission_runner.level_selected(selected, 3))       # hard, not very hard

    def test_the_tl130_research_job_is_found_by_width_and_number(self):
        frame = rn_screenshot("tl130_list.png", 7, 13)
        job = mission_runner.JOBS["TL130"]
        widths = [mission_runner.title_width(frame, row) for row in range(mission_runner.ROWS)]
        self.assertEqual([mission_runner.wide_enough(width, job) for width in widths], [False, True, True, False, False, False])
        self.assertTrue(is_job("Tt 130", widths[2], job))
        self.assertFalse(is_job("", widths[1], job))                       # TL150, which the OCR leaves blank
        self.assertFalse(is_job("Tt 130 Carztructian", widths[5], job))
        self.assertFalse(is_job("Tt 130", .144, mission_runner.JOBS["TL60"]))

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

    def test_a_darker_conversation_on_a_1024_window_is_found_and_the_communicator_is_not(self):
        # The other PC draws the panel at half the brightness, in scan lines (screenshot, 5 Nov).
        frame = np.zeros((768, 1024, 3), np.uint8)
        frame[:] = (45, 42, 36)                         # the walls
        frame[170:636, 78:702] = (0, 13, 0)
        frame[171:636:2, 78:702] = (73, 108, 87)
        self.assertEqual(dialog_box(frame), (78, 170, 624, 466))
        frame[170:636, 78:702] = (45, 42, 36)
        frame[600:683, 20:870] = (36, 60, 43)           # the Communicator, long and flat
        self.assertIsNone(dialog_box(frame))

    def test_goodbye_is_never_the_option_clicked(self):
        lines = [{"text": "If you have a problem, just ask.", "left": 87, "point": (0, 0)},
                 {"text": "> Forget it, Goodbye.", "left": 89, "point": (144, 248)}]
        self.assertIsNone(answer(lines, 624))

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
        self.assertEqual(first_option(frame, box), (262, 448))

    def test_an_option_under_the_pointer_lights_up_green_and_still_counts(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        words(frame, 380, 216)
        frame[412:435, 223:280:2] = (70, 204, 129)
        self.assertEqual(first_option(frame, box), (262, 422))

    def test_speech_without_descenders_still_counts_as_speech(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        words(frame, 383, 216, high=17)
        words(frame, 414, 223)
        words(frame, 445, 223)
        self.assertEqual(first_option(frame, box), (262, 425))

    def test_the_first_option_is_clicked_though_only_a_later_one_shows_yet(self):
        box = (200, 320, 1560, 870)
        frame = conversation(box)
        words(frame, 380, 216)
        words(frame, 442, 223)                          # They fade in from the last one up.
        self.assertEqual(first_option(frame, box), (262, 422))

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
        super().__init__(default_profile(), Backend(), Control(), lambda kind, payload: events.append((kind, payload)), detector=object(), engine=engine,
                         diagnostic_dir=Path(tempfile.gettempdir())/"neocronsharp-test-diagnostics")
        self.said, self.jobs = said, jobs
        self.screens = []
        self.opened = []

    def hide_pointer(self):
        pass

    def note_slip(self, error):
        pass

    def wait_alone(self):
        pass

    def move(self, point):
        pass

    def take_job(self, spot):
        if self.completed == self.jobs:
            raise Interrupted("Enough.")
        self.engine.terminal(spot, None)

    def quick_talk(self, person):
        return self.talk(person)

    def wait(self, seconds, safe_pause=False):
        pass

    def open_talk(self, person, reaches=None):
        self.who = person["name"]
        self.opened.append(self.who)
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

    def test_nearest_recruiter_then_the_nearest_manager_then_back_to_the_terminal(self):
        engine = FakeEngine(PEOPLE)
        run = Run(engine, self.said(), jobs=2)
        run.run()
        self.assertEqual(run.opened, ["Recruiter - Near", "Faction Supply Manager - Lao"]*2)
        self.assertEqual(engine.calls.count("spot"), 1)
        self.assertEqual(engine.calls.count("terminal"), 2)
        self.assertEqual(run.events[-1], ("done", "Enough. 2 jobs done."))

    def test_the_shop_is_never_answered_but_with_its_goodbye(self):
        lines = [{"text": t, "left": SPEECH if i == 0 else OPTION, "point": (0, i)} for i, t in enumerate(["Hello and welcome.", "> Buy something", "> 0h s0rry I g0t the wrong person."])]
        self.assertFalse(mission_runner.rewarded(lines, WIDTH))
        self.assertEqual(mission_runner.shop_goodbye(lines, WIDTH)["point"], (0, 2))

    def test_an_unread_shop_is_closed_never_clicked(self):
        run = Run(FakeEngine(PEOPLE), {"Faction Supply Manager - Lao": [["Hel1o and we1come.", "> Bvy", "> zzz"]]})
        clicked, closed = [], []
        run.click_option = lambda point, trial=0.: clicked.append(point)
        run.close_talk = lambda: closed.append(1)
        run.pixel_option = lambda: (1, 1)
        run.talk(actor("Faction Supply Manager - Lao"))
        self.assertEqual((clicked, closed), ([], [1]))

    def test_a_dim_click_option_read_without_its_mark_is_still_an_option(self):
        lines = [line("Here is your payment"), line("(click)")]
        self.assertEqual(answer(lines, WIDTH)["text"], "(click)")

    def test_a_slip_at_the_recruiter_keeps_the_job_and_tries_again(self):
        engine = FakeEngine(PEOPLE)
        run = Run(engine, self.said())
        talk, tries = run.quick_talk, []

        def slips(person):
            tries.append(person["name"])
            if len(tries) == 1:
                run.job_open = True
                raise Interrupted("Could not talk to them.")
            talk(person)
        run.quick_talk = slips
        run.run()
        self.assertEqual(run.completed, 1)
        self.assertEqual(len(tries), 2)
        self.assertEqual(engine.calls.count("terminal"), 1)

    def test_a_slip_at_a_manager_does_not_go_back_to_the_recruiter(self):
        run = Run(FakeEngine(PEOPLE), self.said())
        talk, tries = run.talk, []
        recruiter = []
        run.quick_talk = lambda person: recruiter.append(person["name"])

        def slips(person):
            tries.append(person["name"])
            run.job_open = True
            if len(tries) == 1:
                raise Interrupted("Could not talk to them.")
            return talk(person)
        run.talk = slips
        run.run()
        self.assertEqual(run.completed, 1)
        self.assertEqual(len(recruiter), 1)

    def test_tries_again_each_job_but_gives_up_after_tries_in_a_row(self):
        run = Run(FakeEngine(PEOPLE), self.said(), jobs=3)
        talk, tries = run.quick_talk, []

        def slips(person):
            tries.append(person["name"])
            if len(tries) % 3:
                raise Interrupted("Could not talk to them.")
            talk(person)
        run.quick_talk = slips
        run.run()
        self.assertEqual(run.completed, 3)

        run = Run(FakeEngine(PEOPLE), self.said())
        tries = []

        def never(person):
            tries.append(person["name"])
            raise Interrupted("Could not talk to them.")
        run.quick_talk = never
        run.run()
        self.assertEqual(len(tries), mission_runner.JOB_TRIES)
        self.assertEqual(run.events[-1], ("done", "Could not talk to them. 0 jobs done."))

    def test_stop_is_never_tried_again(self):
        run = Run(FakeEngine(PEOPLE), self.said())
        tries = []

        def stops(person):
            tries.append(person["name"])
            run.control.stopped.set()
            raise Interrupted("Could not talk to them.")
        run.quick_talk = stops
        run.run()
        self.assertEqual(len(tries), 1)
        self.assertIn("Stopped", run.events[-1][1])

    def test_a_stop_key_in_the_engine_is_never_tried_again(self):
        run = Run(FakeEngine(PEOPLE), self.said())
        tries = []

        def stops(person):
            tries.append(person["name"])
            raise Interrupted("Stopped: F8 pressed.")
        run.quick_talk = stops
        run.run()
        self.assertEqual(len(tries), 1)

    def test_a_conversation_left_open_is_shut_never_answered(self):
        run = Run(FakeEngine(PEOPLE), self.said())
        run.screens = list(RECRUITED)
        closed = []
        run.close_talk = lambda: closed.append(1)
        run.recover()
        self.assertEqual((run.screens, closed), (list(RECRUITED), [1]))

    def test_only_the_nearest_manager_is_opened_and_shut_never_clicked(self):
        run = Run(FakeEngine(PEOPLE), self.said())
        clicked, closed = [], []
        run.click_option = lambda point, trial=0.: clicked.append(run.who)
        run.close_talk = lambda: closed.append(run.who)
        run.run()
        self.assertNotIn("Faction Supply Manager - Lao", clicked)
        self.assertNotIn("Faction Supply Manager - Yul", clicked)
        self.assertEqual(next(who for who in closed if "Manager" in who), "Faction Supply Manager - Lao")
        self.assertNotIn("Faction Supply Manager - Yul", run.opened)
        self.assertEqual(run.completed, 1)

    def test_always_the_first_jobs_recruiter_even_when_another_is_nearer(self):
        engine = FakeEngine(PEOPLE)
        run = Run(engine, {**self.said(), "Recruiter - Far": RECRUITED}, jobs=2)
        took = run.take_job

        def nearer(spot):
            took(spot)
            if run.completed == 1:
                engine.people = [actor("Recruiter - Far", 50), *PEOPLE]
        run.take_job = nearer
        run.run()
        self.assertEqual([who for who in run.opened if who.startswith("Recruiter")], ["Recruiter - Near"]*2)

    def test_a_slip_leaves_a_picture_and_a_line(self):
        run = Run(FakeEngine([]), {})
        with tempfile.TemporaryDirectory() as folder:
            run.diagnostic_dir = Path(folder)
            run.last_frame = blank()
            MissionRunner.note_slip(run, Interrupted("Could not talk to them."))
            self.assertTrue((Path(folder)/"job-slip-1.png").exists())
            self.assertIn("Could not talk to them. (job-slip-1.png)", (Path(folder)/"job-slips.txt").read_text(encoding="utf-8"))

    def test_any_first_option_will_do(self):
        run = Run(FakeEngine(PEOPLE), {**self.said(), "Recruiter - Near": [["You are here about the job, right?", "> Yes, I am here because of the job you have..."], *RECRUITED]})
        run.run()
        self.assertEqual(run.completed, 1)

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


class AloneTests(unittest.TestCase):
    def wait(self, looks):
        """Each look is who is around then. How long it waited, and what it said."""
        engine = FakeEngine([])
        shown = list(looks)
        engine.nearby = lambda: shown.pop(0) if len(shown) > 1 else shown[0]
        run = Run(engine, {})
        now = [0.]
        run.clock = lambda: now[0]
        run.wait = lambda seconds, safe_pause=False: now.__setitem__(0, now[0]+seconds)
        MissionRunner.wait_alone(run)
        return now[0], run.events

    def test_nobody_about_costs_nothing(self):
        waited, said = self.wait([[actor("Recruiter - Near"), actor("Security - Bob", 10)]])
        self.assertEqual((waited, said), (0, []))

    def test_a_player_however_far_holds_it(self):
        waited, said = self.wait([[actor("Someone", 4000, kind="player")], []])
        self.assertEqual(waited, 1+mission_runner.PLAYER_GONE)

    def test_a_player_near_holds_it_until_they_have_gone_for_a_while(self):
        them = actor("Someone", 120, kind="player")
        waited, said = self.wait([[them], [them], [], [them], [], [], [], [], []])
        self.assertEqual(waited, 4+mission_runner.PLAYER_GONE)      # last seen at 3, gone from 4
        self.assertIn("Paused: Someone is in the zone, 120 units away", said[0][1])
        self.assertEqual(said[-1], ("log", "No other player in the zone: carrying on."))
        self.assertEqual(len(said), 2)

    def test_your_own_character_is_not_another_player(self):
        self.assertEqual(self.wait([[actor("Me", 0, kind="player")]])[0], 0)

    def test_it_waits_before_each_step(self):
        run = Run(FakeEngine(PEOPLE), LoopTests().said())
        steps = []
        run.wait_alone = lambda: steps.append("wait")
        opened = run.open_talk
        run.open_talk = lambda person, reaches=None: steps.append(person["name"]) or opened(person)
        run.run()
        self.assertEqual(steps[:5], ["wait", "wait", "Recruiter - Near", "wait", "Faction Supply Manager - Lao"])


class SnapTests(unittest.TestCase):
    def glide(self, start, end):
        run = Run(FakeEngine([]), {})
        moved = []
        run.backend = type("Pointer", (), {"cursor_client": lambda self: list(start), "move": lambda self, point: moved.append(point), "check_focus": lambda self, size: None})()
        MissionRunner.move(run, end)
        return moved

    def test_the_pointer_snaps_straight_there_in_one_move(self):
        self.assertEqual(self.glide((0, 0), (1000, 0)), [(1000, 0)])
        self.assertEqual(self.glide((500, 500), (501, 500)), [(501, 500)])

    def test_the_job_loop_steers_gently(self):
        self.assertEqual(mission_runner.Engine.pulse, "20")
        self.assertEqual(mission_runner.loot_runner.Engine.pulse, "24")


class SelectTests(unittest.TestCase):
    def test_a_new_page_is_not_taken_from_the_moment_it_downloads(self):
        run = Run(FakeEngine([]), {})
        old, empty, new = (np.full((2, 2), value) for value in (1, 0, 2))
        shown = [empty, empty, empty, new, new, new]
        run.frame = lambda: shown.pop(0)
        with patch.object(mission_runner, "list_picture", lambda frame: frame), \
                patch.object(mission_runner, "rn_page", lambda frame: "accepted" if frame is empty else "list"):
            run.next_page(old)
        self.assertEqual(len(shown), 1)

    def test_the_list_may_take_its_time_to_come_back(self):
        run = Run(FakeEngine([]), {})
        pages = ["accepted"]*5+["list"]
        run.tap = lambda point: None
        run.frame = blank
        run.next_page = lambda before: None
        run.accept = lambda: None
        run.detector = type("Detector", (), {"text_reader": lambda self: None})()
        rows = iter([None, 2])
        with patch.object(mission_runner, "job_row", lambda reader, frame, job: next(rows)), \
                patch.object(mission_runner, "row_is_blue", lambda frame, row: True), \
                patch.object(mission_runner, "rn_page", lambda frame: pages.pop(0) if len(pages) > 1 else "list"):
            self.assertTrue(run.choose_job())

    def test_easy_is_retried_until_the_selected_label_changes(self):
        run = Run(FakeEngine([]), {})
        tapped = []
        run.tap = tapped.append
        run.move = lambda point: None
        before, after = difficulty_frame(), difficulty_frame(easy=True)
        run.frame = lambda: after if len(tapped) >= 2 else before
        run.select_level()
        self.assertEqual(tapped, [mission_runner.level_point(1)]*2)

    def test_easy_that_never_selects_stops(self):
        run = Run(FakeEngine([]), {})
        tapped = []
        run.tap = tapped.append
        run.move = lambda point: None
        run.frame = lambda: difficulty_frame()
        with self.assertRaisesRegex(Interrupted, "Easy difficulty did not select"):
            run.select_level()
        self.assertEqual(tapped, [mission_runner.level_point(1)]*mission_runner.AIM_TRIES)

    def choose(self, selected_after):
        run = Run(FakeEngine([]), {})
        tapped = []
        run.tap = tapped.append
        run.frame = blank
        run.wait_for_page = lambda page, seconds: True
        run.detector = type("Detector", (), {"text_reader": lambda self: None})()
        with patch.object(mission_runner, "job_row", lambda reader, frame, job: 2), \
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
        run.select_level = lambda: None
        run.download_missions = lambda: None
        run.tap = lambda point: None
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

    def test_every_download_verifies_easy_even_when_a_list_was_remembered(self):
        for page in ("factions", "list"):
            run = Run(FakeEngine([]), {})
            run.take_job = MissionRunner.take_job.__get__(run)
            run.open_missions = lambda: page
            steps = []
            run.tap = steps.append
            run.wait_for_page = lambda wanted, seconds: steps.append(wanted) or True
            run.select_level = lambda: steps.append("verify Easy")
            run.download_missions = lambda: steps.append("download verified")
            run.choose_job = lambda: steps.append("choose TL60 Research Job") or True
            run.take_job({})
            expected = ([mission_runner.BACK, "factions"] if page == "list" else [])
            self.assertEqual(steps, expected + ["verify Easy", "download verified", "choose TL60 Research Job", "accepted"])

    def test_failed_easy_selection_never_downloads_or_accepts(self):
        run = Run(FakeEngine([]), {})
        run.take_job = MissionRunner.take_job.__get__(run)
        run.open_missions = lambda: "factions"
        run.move = lambda point: None
        run.frame = lambda: difficulty_frame()
        tapped = []
        run.tap = tapped.append
        run.choose_job = lambda: self.fail("Must not choose a job before Easy is selected")
        with self.assertRaisesRegex(Interrupted, "Easy difficulty did not select"):
            run.take_job({})
        self.assertNotIn(mission_runner.DOWNLOAD, tapped)
        self.assertNotIn(mission_runner.ACCEPT, tapped)

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


class DownloadTests(unittest.TestCase):
    def download(self, pages, loaded=True):
        run = Run(FakeEngine([]), {})
        run.frame = lambda: None
        tapped, waits = [], []
        run.tap = tapped.append
        run.wait_for_page = lambda page, seconds: waits.append(page) or loaded
        with patch.object(mission_runner, "rn_page", side_effect=pages):
            run.download_missions()
        return tapped, waits

    def test_download_that_only_highlights_the_button_is_retried(self):
        self.assertEqual(self.download(["factions"]*5+["list"]), ([mission_runner.DOWNLOAD]*2, []))

    def test_download_that_opens_immediately_is_clicked_once(self):
        self.assertEqual(self.download(["list"]), ([mission_runner.DOWNLOAD], []))

    def test_loading_page_waits_without_clicking_again(self):
        self.assertEqual(self.download(["accepted"]), ([mission_runner.DOWNLOAD], ["list"]))

    def test_loading_timeout_stops(self):
        with self.assertRaisesRegex(Interrupted, "download started but the list did not appear"):
            self.download(["accepted"], loaded=False)

    def test_unresponsive_download_stops_after_three_clicks(self):
        run = Run(FakeEngine([]), {})
        run.frame = blank
        tapped = []
        run.tap = tapped.append
        with patch.object(mission_runner, "rn_page", return_value="factions"), self.assertRaisesRegex(Interrupted, "did not respond"):
            run.download_missions()
        self.assertEqual(tapped, [mission_runner.DOWNLOAD]*mission_runner.AIM_TRIES)

    def test_focus_loss_stops_before_another_download_click(self):
        run = Run(FakeEngine([]), {})
        tapped = []
        run.tap = tapped.append
        run.frame = lambda: (_ for _ in ()).throw(Interrupted("Game lost focus."))
        with self.assertRaisesRegex(Interrupted, "Game lost focus"):
            run.download_missions()
        self.assertEqual(tapped, [mission_runner.DOWNLOAD])


class RewardTests(unittest.TestCase):
    BOX = (78, 168, 624, 468)

    def screen(self, *widths):
        frame = conversation(self.BOX)
        for i, wide in enumerate(widths):
            words(frame, 204+16*i, 87, wide=round(wide*self.BOX[2]), high=12)
        return frame

    def test_the_reward_is_known_by_its_short_last_line(self):
        self.assertEqual(mission_runner.reward_click(self.screen(.75, .5, .07), self.BOX), (87+16, 236+6))

    def test_the_shop_is_not_the_reward(self):
        self.assertIsNone(mission_runner.reward_click(self.screen(.2, .5, .3), self.BOX))
        self.assertIsNone(mission_runner.reward_click(self.screen(.05, .4, .07), self.BOX))
        self.assertIsNone(mission_runner.reward_click(self.screen(.6), self.BOX))

    def test_the_screenshot_from_the_other_pc(self):
        """Its rows as text_rows found them on that PC's reward screen, 5 Nov."""
        frame = conversation(self.BOX)
        for top, bottom, wide in ((204, 217, .74), (219, 231, .52), (238, 250, .07)):
            frame[top:bottom, 87:87+round(wide*self.BOX[2]):2] = (200, 230, 200)
        self.assertIsNotNone(mission_runner.reward_click(frame, self.BOX))


class QuickTalkTests(unittest.TestCase):
    BOX = (200, 320, 1560, 870)

    def talk(self, screens):
        """Each screen shows until its option is clicked. None is the conversation gone."""
        run = Run(FakeEngine([]), {})
        run.open_talk = lambda person: None
        self.moved = []
        run.move = self.moved.append
        self.waited = []
        run.wait = self.waited.append
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
        self.assertEqual(clicks, [(262, 422), (262, 448)])

    def test_the_pointer_leaves_the_words_after_each_click(self):
        self.talk([self.screen(216, 223, 223), self.screen(216, 217, 223), blank()])
        self.assertEqual(len(self.moved), 4)
        for x, y in self.moved[1::2]:
            self.assertGreater(y, self.BOX[1]+self.BOX[3]*.55)

    def test_the_pointer_rests_on_the_option_before_the_click_and_after_it(self):
        clicks = self.talk([self.screen(216, 223, 223), blank()])
        self.assertEqual(self.moved[0], clicks[0])
        self.assertEqual(self.waited[:2], [mission_runner.SETTLE, mission_runner.QUICK_LEAVE])

    def test_the_ocr_finds_the_option_the_pixels_miss(self):
        run = Run(FakeEngine([]), {})
        run.open_talk = lambda person: None
        run.move = lambda point: None
        shown, clicks = [self.screen(216), blank()], []
        run.frame = lambda: shown[0]
        now = iter(x*.1 for x in range(100000))
        run.clock = lambda: next(now)
        run.talk_wide = self.BOX[2]
        run.dialog_lines = lambda: [{"text": "Well then", "left": 216, "point": (300, 390)}, {"text": "> Yes", "left": 223, "point": (300, 420)}]

        def click(point):
            clicks.append(point)
            shown.pop(0)
        run.click = click
        run.quick_talk = MissionRunner.quick_talk.__get__(run)
        with patch.object(mission_runner, "dialog_box", lambda frame: self.BOX):
            run.quick_talk(actor("Recruiter - Near"))
        self.assertEqual(clicks, [(300, 420)])

    def test_an_option_read_off_the_chat_panel_is_never_clicked_and_is_pictured(self):
        run = Run(FakeEngine([]), {})
        run.open_talk = lambda person: None
        run.close_talk = lambda: None
        moved, clicks = [], []
        run.move = moved.append
        run.click = clicks.append
        frame = self.screen(216)
        run.frame = lambda: frame
        now = iter(x*.1 for x in range(100000))
        run.clock = lambda: next(now)
        run.talk_wide = self.BOX[2]
        run.dialog_lines = lambda: [{"text": "Well then", "left": 216, "point": (300, 390)}, {"text": "> Yes", "left": 223, "point": (2500, 420)}]
        run.quick_talk = MissionRunner.quick_talk.__get__(run)
        with tempfile.TemporaryDirectory() as folder, patch.object(mission_runner, "dialog_box", lambda frame: self.BOX):
            run.diagnostic_dir = Path(folder)
            with self.assertRaises(Interrupted):
                run.quick_talk(actor("Recruiter - Near"))
            self.assertTrue((Path(folder)/"chat-off-panel.png").exists())
        self.assertEqual(clicks, [])
        self.assertFalse([point for point in moved if not mission_runner.inside(point, self.BOX)])
        self.assertTrue(any("off the chat panel" in text for kind, text in run.events if kind == "log"))

    def test_the_ocr_waits_for_every_option_to_fade_in(self):
        run = Run(FakeEngine([]), {})
        run.open_talk = lambda person: None
        looks = []
        run.read_option = lambda: looks.append(run.clock()) or None
        run.close_talk = lambda: None
        run.frame = lambda: self.screen(216)
        now = iter(x*.1 for x in range(1000))
        run.clock = lambda: next(now)
        run.quick_talk = MissionRunner.quick_talk.__get__(run)
        with patch.object(mission_runner, "dialog_box", lambda frame: self.BOX), self.assertRaisesRegex(Interrupted, "did not end"):
            run.quick_talk(actor("Recruiter - Near"))
        self.assertGreater(looks[0], mission_runner.QUICK_READ)

    def test_a_screen_with_nothing_to_answer_is_closed_and_opened_again(self):
        run = Run(FakeEngine([]), {})
        opened, closed, clicks = [], [], []
        run.open_talk = lambda person: opened.append(person["name"])
        run.move = lambda point: None
        run.read_option = lambda: None
        shown = [self.screen(216), self.screen(216, 223, 223), blank()]
        run.frame = lambda: shown[0]
        run.close_talk = lambda: closed.append(shown.pop(0))
        now = iter(x*.1 for x in range(100000))
        run.clock = lambda: next(now)

        def click(point):
            clicks.append(point)
            shown.pop(0)
        run.click = click
        run.quick_talk = MissionRunner.quick_talk.__get__(run)
        with patch.object(mission_runner, "dialog_box", lambda frame: self.BOX):
            run.quick_talk(actor("Recruiter - Near"))
        self.assertEqual((len(opened), len(closed), clicks), (2, 1, [(262, 422)]))

    def test_esc_is_pressed_only_on_an_open_conversation(self):
        for shown, presses in (([True, True, False], ["esc"]), ([False], [])):
            run = Run(FakeEngine([]), {})
            pressed = []
            run.press = pressed.append
            run.frame = blank
            with patch.object(mission_runner, "dialog_open", lambda frame: shown.pop(0)):
                run.close_talk()
            self.assertEqual(pressed, presses)

    def test_stops_when_it_never_ends(self):
        run = Run(FakeEngine([]), {})
        run.open_talk = lambda person: None
        run.frame = lambda: self.screen(216)
        run.dialog_lines = lambda: None
        run.close_talk = lambda: None
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

    def test_an_engine_that_hangs_is_ended(self):
        engine = self.engine()
        stopped = []
        with patch.object(mission_runner.tt, "clear_stop", lambda: None), patch.object(mission_runner.tt, "stop_walk", stopped.append), \
                patch.object(mission_runner, "ASK_MOST", 0), self.assertRaisesRegex(Interrupted, "took too long over camera"):
            engine.live(["camera"], lambda: None)
        self.assertEqual(len(stopped), 1)
        self.assertIsNone(engine.server)

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
