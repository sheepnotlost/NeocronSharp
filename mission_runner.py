"""TL60 Research Jobs in a faction headquarters, one after another until Stop.

Start at the R.N. terminal with the crosshair on it. Each job: right-click the terminal, Missions, Easy, Download Missions,
Next until a TL60 Research Job shows, Accept, then the nearest recruiter, then the faction supply managers until one pays, and back.
traversal.exe does the walking, the aiming and the right-clicks; this file works the game's windows.
The R.N. window is 640x480 pixels, centred, whatever the client's size or UI scale, so its places are pixels from its corner.
A conversation sits where the UI scale puts it, so it is found by its colour. No Esc: Tab closes the menus.
"""
import difflib
import re

import numpy as np

import loot_runner
from loot_runner import LootRunner
from macro_core import Interrupted
from vision import cv2

RN_WIDE, RN_HIGH = 640, 480
MISSIONS_TAB = (400, 21)
EASY = (481, 175)
DOWNLOAD = (121, 441)
ACCEPT = (96, 441)
NEXT = (196, 441)
DOWNLOAD_SHOWS, NEXT_SHOWS, BACK_SHOWS = (56, 441), (227, 441), (560, 441)     # beside each button's word
ROWS, ROW_TOP, ROW_STEP = 6, 173, 15
TITLE, NUMBERS = (45, 340), (43, 507)
ROW_CLICK_X, ROW_BLUE_X = 173, 253
RESEARCH_WIDE = (.132, .156)     # of the window: TL60 Research Job .144, TL60 Construction Job .170
TALK_WIDE = 1547             # pixels: a conversation on the 2560x1440 client at UI scale 1.7
TALK_SMALLEST = .05          # of the client: a conversation's panel fills .37 there, the HUD's under .03
TALK_SOLID = .7              # of its outline: the other windows' panels are broken up

TALK_REACH = 180             # units: how close to walk before right-clicking a person
TALK_CLOSE = 90              # and from here if the first try opened nothing
MOST_PAGES = 20
SELECT_TRIES = 3
SETTLE = .15                 # seconds between the pointer arriving and a click
MOST_SCREENS = 8             # of one conversation
OPTIONS_WAIT = 5             # seconds: a screen's options draw after its words (live, 2 Nov)
SAME_WORDS = .7              # how alike the OCR's line and a known line must be
SHOP_GOODBYE = "Oh sorry I got the wrong person."    # a supply manager with nothing to pay shows the shop: its first option buys
LEAVING = "somebodyelse"     # the line under the first option, which ends the talk: it can be read first while the options fade in
SPEECH_INDENT = .0013        # of the conversation's width: an option starts with a ">", so it never lines up with the words above
JOB_MARK = re.compile(r"36|6[0O]{3}|T[^ ]{0,2}[6G][0O]")


def place(frame, point):
    """A place in the R.N. window, on the client."""
    height, width = frame.shape[:2]
    return round((width-RN_WIDE)/2+point[0]), round((height-RN_HIGH)/2+point[1])


def area(frame, x0, y0, x1, y1):
    (left, top), (right, bottom) = place(frame, (x0, y0)), place(frame, (x1, y1))
    return frame[top:bottom, left:right]


def lit(frame, point):
    """A bright green button at this place?"""
    x, y = point
    box = area(frame, x-7, y-4, x+7, y+4).astype(int)
    return ((box[..., 1] > 200) & (box[..., 1]-box[..., 0] > 60)).mean() > .5


def rn_page(frame):
    """Which page of the R.N. window shows, by its buttons. None for its splash, or no window."""
    if lit(frame, NEXT_SHOWS) and lit(frame, BACK_SHOWS):
        return "list"
    if lit(frame, BACK_SHOWS):
        return "accepted"
    return "factions" if lit(frame, DOWNLOAD_SHOWS) else None


def dialog_box(frame):
    """The conversation's panel as (left, top, wide, high), or None. A big solid block of its green, which no other window is."""
    box = frame.astype(int)
    red, green, blue = box[..., 0], box[..., 1], box[..., 2]
    panel = ((green-red > 40) & (green-blue > 25) & (green > 90) & (green < 190)).astype(np.uint8)
    size = frame.shape[1]//300 | 1      # closes over the words
    count, _, stats, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(panel, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8)), connectivity=4)
    if count < 2:
        return None
    left, top, wide, high, filled = (int(v) for v in stats[1+stats[1:, cv2.CC_STAT_AREA].argmax()])
    return None if filled < TALK_SMALLEST*frame.shape[0]*frame.shape[1] or filled < TALK_SOLID*wide*high else (left, top, wide, high)


def dialog_open(frame):
    return dialog_box(frame) is not None


def row_y(row):
    return ROW_TOP+row*ROW_STEP


def row_is_blue(frame, row):
    x, y = place(frame, (ROW_BLUE_X, row_y(row)))
    red, green, blue = (int(v) for v in frame[y, x][:3])
    return blue > green and blue > red


def title_width(frame, row):
    """Of the window's width. The title's letters are near white on green."""
    cell = area(frame, TITLE[0], row_y(row)-7, TITLE[1], row_y(row)+7)
    columns = (cell.min(axis=2) > 120).any(axis=0).nonzero()[0]
    return 0. if columns.size == 0 else float(columns[-1]-columns[0]+1)/RN_WIDE


def is_job(words, width):
    """The two TL60 jobs part by width, and the Research jobs by their numbers. The OCR rarely gets a whole row right."""
    return RESEARCH_WIDE[0] <= width <= RESEARCH_WIDE[1] and JOB_MARK.search(words) is not None


def row_words(reader, frame, row):
    cell = area(frame, NUMBERS[0], row_y(row)-9, NUMBERS[1], row_y(row)+9)
    return " ".join(word[0] for image in (cell.max(axis=2), cell.min(axis=2)) for word in reader.read_words(image))


def job_row(reader, frame):
    return next((row for row in range(ROWS) if is_job(row_words(reader, frame, row), title_width(frame, row))), None)


def letters(text):
    return "".join(c for c in text.lower() if c.isalpha())


def options(lines, width):
    """The lines to answer with. The first line is always speech, and speech that wraps starts level with it."""
    return [line for line in lines[1:] if ">" in line["text"][:3] or abs(line["left"]-lines[0]["left"]) > width*SPEECH_INDENT]


def answer(lines, width):
    """The line to click: the first option, except in the shop."""
    found = [line for line in options(lines, width) if LEAVING not in letters(line["text"])]
    for line in found:
        if difflib.SequenceMatcher(None, letters(line["text"]), letters(SHOP_GOODBYE)).ratio() >= SAME_WORDS:
            return line
    return found[0] if found else None


def text_lines(words, left=0, top=0):
    """OCR words joined into lines, each with where to click it."""
    lines = []
    for text, x, y, wide, high in sorted(words, key=lambda w: (w[2], w[1])):
        row = next((r for r in lines if abs(r["y"]-y) <= max(r["high"], high)*.6), None)
        if row is None:
            row = {"y": y, "high": high, "words": []}
            lines.append(row)
        row["words"].append((x, text, wide))
    found = []
    for row in lines:
        row["words"].sort()
        first, last = row["words"][0], row["words"][-1]
        found.append({"text": " ".join(word[1] for word in row["words"]), "left": left+first[0],
                      "point": (left+(first[0]+last[0]+last[2])//2, top+row["y"]+row["high"]//2)})
    return found


class Engine(loot_runner.Engine):
    def spot(self):
        data = loot_runner.tt.run_tool(["spot"])
        if not data.get("live"):
            raise Interrupted(f"Cannot read the game: {data.get('why')}")
        return data

    def use(self, actor, tick):
        return self.run([actor["id"], "--use"], tick)

    def terminal(self, spot, tick):
        args = ["usespot", f"{spot['x']},{spot['y']},{spot['z']}", f"{spot['yaw']},{spot['pitch']}", "--pulse", "24"]
        if self.gains:
            args += ["--gains", self.gains]
        if self.calibration:
            args += ["--calibration", self.calibration]
        return self.keep_gains(self.live(args, tick))


class MissionRunner(LootRunner):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("engine", None)
        super().__init__(*args, **kwargs)
        if kwargs["engine"] is None:
            self.engine = Engine(lambda text: self.emit("log", text), self.control)
        self.pictures = set()        # list pages saved so far, for tuning what reads them
        self.talk_wide = TALK_WIDE   # the open conversation's width

    def watch_health(self):
        """Nothing fights back in a Secure Sector."""

    def tap(self, point):
        """The game must see the pointer arrive first: a click straight after a move only lit the row up (live, 2 Nov)."""
        at = place(self.frame(), point)
        self.move(at)
        self.wait(SETTLE)
        self.click(at)

    def save_page(self, number):
        if number in self.pictures:
            return
        self.pictures.add(number)
        written, data = cv2.imencode(".png", cv2.cvtColor(self.last_frame, cv2.COLOR_RGB2BGR))
        if written:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            data.tofile(self.diagnostic_dir/f"mission-list-{number}.png")

    def people(self, word):
        found = [a for a in self.engine.nearby() if a["kind"] == "npc" and not a["dead"] and word.lower() in a["name"].lower()]
        return sorted(found, key=lambda a: a["distance"])

    def wait_for_page(self, wanted, seconds):
        ends = self.clock()+seconds
        while self.clock() < ends:
            if rn_page(self.frame()) == wanted:
                return True
            self.wait(.2)
        return False

    def open_missions(self):
        """The terminal shows its splash first. Past that, the Missions tab holds wherever the last job left it."""
        for attempt in range(12):
            self.wait(.5)
            kind = rn_page(self.frame())
            if kind in ("factions", "list"):
                return kind
            if attempt == 2 and not self.ui_visible(self.reader()):
                raise Interrupted("The terminal did not open: stand at it with the crosshair on it.")
            if attempt % 3 == 2:
                self.tap(MISSIONS_TAB)
        raise Interrupted("Could not reach the Missions page of the terminal.")

    def choose_job(self):
        """True when one was accepted."""
        for number in range(MOST_PAGES):
            frame = self.frame()
            self.save_page(number)
            row = job_row(self.reader(), frame)
            if row is not None:
                for attempt in range(SELECT_TRIES):
                    self.tap((ROW_CLICK_X, row_y(row)))
                    self.wait(.5)
                    if row_is_blue(self.frame(), row):
                        self.tap(ACCEPT)
                        return True
                raise Interrupted("The mission row did not select.")
            self.tap(NEXT)
            self.wait(1.5)
            if rn_page(self.frame()) != "list":
                raise Interrupted("The mission list went away.")
        return False

    def take_job(self, spot):
        self.emit("status", "Going to the terminal.")
        last = self.engine.terminal(spot, lambda: None)
        if not last or not last.splitlines()[-1].startswith("Right-clicked"):
            raise Interrupted(last.splitlines()[-1] if last else "The engine said nothing.")
        if self.open_missions() == "factions":
            self.tap(EASY)
            self.wait(.5)
            self.tap(DOWNLOAD)
            if not self.wait_for_page("list", 15):
                raise Interrupted("The mission list did not download.")
        if not self.choose_job():
            raise Interrupted(f"No TL60 Research Job in {MOST_PAGES} pages.")
        if not self.wait_for_page("accepted", 10):
            raise Interrupted("The job was not accepted.")
        self.emit("log", "Job accepted.")
        self.hide_pointer()

    def dialog_lines(self):
        """The conversation's lines, or None with no conversation open."""
        frame = self.frame()
        box = dialog_box(frame)
        if box is None:
            return None
        left, top, wide, high = box
        self.talk_wide = wide
        x0, y0 = left+round(wide*.017), max(0, top-round(high*.02))     # The lower part of the panel stays empty.
        words = self.detector.gray(frame[y0:top+round(high*.55), x0:left+wide-round(wide*.01)])
        return text_lines(self.reader().read_words(words, up=max(2, round(2*TALK_WIDE/wide))), x0, y0)

    def open_talk(self, person):
        """Walk up and right-click until the conversation shows."""
        for reach in (TALK_REACH, TALK_CLOSE):
            if person["distance"] > reach and not self.walk_to(person, reach):
                continue
            last = self.ended(self.engine.use(person, lambda: None))
            self.emit("log", last)
            for attempt in range(8):
                self.wait(.25)
                if dialog_open(self.frame()):
                    return
            person = dict(person, distance=reach+1)
        raise Interrupted(f"Could not talk to {person['name']}.")

    def screen(self):
        """The conversation's lines once its options have drawn and two readings agree, as they fade in, or as they are
        when they never do. None when it has closed."""
        ends, before = self.clock()+OPTIONS_WAIT, None
        while True:
            lines = self.dialog_lines()
            if lines is None or (lines == before and answer(lines, self.talk_wide)) or self.clock() >= ends:
                return lines
            before = lines
            self.wait(.2)

    def talk(self, person):
        """Everything they said. Clicks through to the end."""
        self.hide_pointer()
        self.open_talk(person)
        said = []
        for screen in range(MOST_SCREENS):
            lines = self.screen()
            if lines is None:
                return said
            words = " ".join(line["text"] for line in lines)
            said.append(words)
            line = answer(lines, self.talk_wide)
            if line is None:
                raise Interrupted(f"{person['name']} gave no options to answer: {words[:200]}")
            self.click(line["point"])
            for attempt in range(16):      # By its words: the pointer now sits on an option and lights it up.
                self.wait(.25)
                now = self.dialog_lines()
                if now is None or not now or now[0]["text"] != lines[0]["text"]:
                    break
        raise Interrupted(f"The conversation with {person['name']} did not end.")

    def run_job(self, spot):
        self.take_job(spot)
        recruiters = self.people("Recruiter")
        if not recruiters:
            raise Interrupted("No recruiter here.")
        self.emit("status", f"Talking to {recruiters[0]['name']}.")
        self.talk(recruiters[0])
        paid = False
        for manager in self.people("Faction Supply Manager"):
            self.emit("status", f"Talking to {manager['name']}.")
            said = " ".join(self.talk(manager)).lower()
            paid = "payment" in said or "credits" in said
            if paid:      # Either may be the one, and it changes from job to job.
                break
        if not paid:
            raise Interrupted("Neither faction supply manager paid. Are the blueprints in your Inventory? The job is still open.")

    def execute(self):
        self.hide_pointer()
        if not self.people("Recruiter") or not self.people("Faction Supply Manager"):
            raise Interrupted("No recruiters or faction supply managers here: start at the terminal in the headquarters.")
        spot = self.engine.spot()
        while True:
            self.checkpoint()
            self.run_job(spot)
            self.completed += 1
            self.emit("log", f"TL60 Research Job {self.completed} done.")

    def run(self):
        try:
            self.guard()
            self.execute()
        except Exception as exc:
            diagnostic = self.save_failure(exc)
            if diagnostic is not None:
                self.emit("log", f"Last game frame saved locally: {diagnostic}")
            self.emit("done", f"{exc} {self.completed} jobs done.")
        finally:
            self.backend.release_all()
