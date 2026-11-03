"""TL60 Research Jobs in a faction headquarters, one after another until Stop.

Start at the R.N. terminal with the crosshair on it. Each job: right-click the terminal, Missions, Easy, Download Missions,
Next until a TL60 Research Job shows, Accept, then the nearest recruiter, then the faction supply managers until one pays, and back.
traversal.exe does the walking, the aiming and the right-clicks; this file works the game's windows.
The R.N. window is 640x480 pixels, centred, whatever the client's size or UI scale, so its places are pixels from its corner.
A conversation sits where the UI scale puts it, so it is found by its colour. Tab closes the menus. Esc only ever closes a
conversation with nothing to answer, which the user said to do (2 Nov).
"""
import difflib
import json
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime

import numpy as np

import loot_runner
from loot_runner import LootRunner
from macro_core import Interrupted
from vision import cv2

tt = loot_runner.tt
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
TALK_WIDE = 1550             # pixels: a conversation on the 2560x1440 client at UI scale 1.7
TALK_SMALLEST = .05          # of the client: a conversation's panel fills .37 there, the HUD's under .03
TALK_SOLID = .7              # of its outline: the other windows' panels are broken up
TALK_FULL = .6               # of the block's widest row: a row of the panel, not the gap under the name bar
LETTER_GREEN = 150           # a letter's green channel: the panel's stays under 135. Red won't do: an option under the pointer lights up green (live, 2 Nov)
PANEL_EDGE = .04             # of the panel's height: its top border, as bright as the letters, ends here
LINE_HIGH = .015             # of the panel: shorter than this is the pointer or its border. A line with no descenders is .0195 (live, 2 Nov)
LINE_STEP = .0355            # of the panel: from the last line of speech to the first option
LINE_MIDDLE = .013           # of the panel: below a line's top. The pointer on a line makes it look taller
OPTION_INDENT = .002         # of the panel's width: an option starts with a ">", 7 pixels right of the speech at 1550
OPTION_FURTHEST = .02        # and further than this is the pointer on an empty line
OPTION_CLICK = .025          # of the panel's width: how far along an option to click, short as "> (click)" is
QUICK_AGAIN = .25            # seconds before an option that did nothing is clicked again
QUICK_MOST = 10              # seconds a recruiter may take
QUICK_READ = 1               # seconds of seeing no option before the OCR looks: all options are up by then
QUICK_PARK = .75             # of the panel, both ways: below the words, where the pointer can't touch them
QUICK_LEAVE = .06            # seconds the pointer stays after a click, for the game to see the button come up on the option
QUICK_STUCK = 3              # seconds with nothing to answer before the conversation is closed and opened again
QUICK_REOPEN = 2             # times, in one talk
SERVE_DONE = "<<done>>"

TALK_REACH = 180             # units: how close to walk before right-clicking a person
TALK_CLOSE = 90              # and from here if the first try opened nothing
MOST_PAGES = 20
SELECT_TRIES = 3
SETTLE = .15                 # seconds between the pointer arriving and a click
MOST_SCREENS = 8             # of one conversation
OPTIONS_WAIT = 5             # seconds: a screen's options draw after its words (live, 2 Nov)
OPEN_LOOKS = 40              # tenths of a second for the terminal's window to reach Missions
MISSIONS_EVERY = 8           # looks between clicks on its tab
OPEN_GIVE_UP = 15            # looks with no window before the right-click counts as missed
LIST_WAIT = 1.5              # seconds for a new list page to show
LIST_SLOW = 15               # seconds a page of the list may take to download
ACCEPT_TRIES, ACCEPT_WAIT = 12, .4
JOB_TRIES = 6                # tries in a row without a job done before the loop gives up
UNPAID_TRIES = 2             # tries with nobody paying before the job counts as lost: it may have paid unread, and the fee for a new one is small
ASK_MOST = 90                # seconds any one engine command may take: the longest walk here is some 15
KEPT_PICTURES = 20           # of what went wrong, the oldest written over
RECOVER_WAIT = .5            # seconds for the next screen, when putting things right
PAID_WORDS = ("payment", "credits", "quality")
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


def rn_open(frame):
    """The R.N. window's sides, on any of its pages."""
    left, top = place(frame, (0, 0))
    sides = frame[top+120:top+420, [left, left+RN_WIDE-1]].astype(int)
    return bool(((sides[..., 1] > 200) & (sides[..., 1]-sides[..., 0] > 60)).mean() > .5)


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


def panel_green(frame):
    box = frame.astype(int)
    red, green, blue = box[..., 0], box[..., 1], box[..., 2]
    return (green-red > 40) & (green-blue > 25) & (green > 90) & (green < 190)


def longest_run(flags):
    """Where the longest stretch of True starts and ends."""
    edges = np.diff(np.concatenate(([0], flags.astype(np.int8), [0]))).nonzero()[0].reshape(-1, 2)
    start, end = edges[(edges[:, 1]-edges[:, 0]).argmax()]
    return int(start), int(end)


def dialog_box(frame):
    """The conversation's panel as (left, top, wide, high), or None. A big solid block of its green, which no other window is.
    Green scenery and the name bar above it can touch the block (live, 2 Nov), so the panel is its longest run of full rows."""
    small = cv2.resize(frame, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)     # at full size this takes 150 ms. Averaged, for the panel's scan lines.
    panel = panel_green(small).astype(np.uint8)
    size = small.shape[1]//300 | 1      # closes over the words
    count, parts, stats, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(panel, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8)), connectivity=4)
    if count < 2:
        return None
    block = parts == 1+stats[1:, cv2.CC_STAT_AREA].argmax()
    filled = block.sum(axis=1)
    top, bottom = longest_run(filled > filled.max()*TALK_FULL)
    columns = (block[top:bottom].sum(axis=0) > (bottom-top)*TALK_FULL).nonzero()[0]
    if columns.size == 0:
        return None
    left, right = int(columns[0]), int(columns[-1])+1
    size = block[top:bottom, left:right].sum()
    if size < TALK_SMALLEST*small.shape[0]*small.shape[1] or size < TALK_SOLID*(bottom-top)*(right-left):
        return None
    return left*2, top*2, (right-left)*2, (bottom-top)*2


def dialog_open(frame):
    return dialog_box(frame) is not None


def still_open(frame, box):
    """Is the conversation that was at box still there? Its empty lower part, a look that costs next to nothing."""
    left, top, wide, high = box
    return bool(panel_green(frame[top+high*7//10:top+high*9//10, left+wide//4:left+wide*3//4].mean(axis=(0, 1))))


def text_rows(frame, box):
    """The panel's lines of text as (top, bottom, left), by their pixels: the OCR takes half a second a look."""
    left, top, wide, high = box
    edge = wide//200
    x0, y0 = left+edge, top+round(high*PANEL_EDGE)
    letters = frame[y0:top+round(high*.55), x0:left+wide-edge, 1] > LETTER_GREEN
    rows = np.diff(np.concatenate(([0], (letters.sum(axis=1) >= 2).astype(np.int8), [0]))).nonzero()[0].reshape(-1, 2)
    return [(y0+int(start), y0+int(end), x0+int(letters[start:end].any(axis=0).argmax())) for start, end in rows if end-start >= high*LINE_HIGH]


def first_option(frame, box):
    """Where to click the first option, or None while none shows: the line after the speech, once any line that doesn't start
    level with the speech is up. Never the line it saw: options fade in from the last one up, and the first can read dimmest."""
    rows = text_rows(frame, box)
    speech = rows[0][0] if rows else 0
    for top, bottom, left in rows[1:]:
        indent = left-rows[0][2]
        if abs(indent) <= box[2]*OPTION_INDENT:
            speech = top
        elif 0 < indent < box[2]*OPTION_FURTHEST:
            return left+round(box[2]*OPTION_CLICK), speech+round(box[3]*(LINE_STEP+LINE_MIDDLE))
    return None


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


def wide_enough(width):
    return RESEARCH_WIDE[0] <= width <= RESEARCH_WIDE[1]


def is_job(words, width):
    """The two TL60 jobs part by width, and the Research jobs by their numbers. The OCR rarely gets a whole row right."""
    return wide_enough(width) and JOB_MARK.search(words) is not None


def list_picture(frame):
    return area(frame, TITLE[0], ROW_TOP-9, NUMBERS[1], row_y(ROWS)).copy()


def row_words(reader, frame, row):
    cell = area(frame, NUMBERS[0], row_y(row)-9, NUMBERS[1], row_y(row)+9)
    return " ".join(word[0] for image in (cell.max(axis=2), cell.min(axis=2)) for word in reader.read_words(image))


def job_row(reader, frame):
    """The first row of the right width that reads as a job. Width first: it costs nothing, and reading a row takes two OCRs."""
    return next((row for row in range(ROWS) if wide_enough(title_width(frame, row)) and is_job(row_words(reader, frame, row), title_width(frame, row))), None)


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
    """One traversal.exe for the whole loop: it keeps the sector's map, which each new one spent 2 s baking."""
    def __init__(self, log, control):
        super().__init__(log, control)
        self.server = None
        self.lines = queue.Queue()

    def start(self):
        self.lines = queue.Queue()
        self.server = subprocess.Popen([str(tt.EXE), "serve"], cwd=tt.PROJECT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace", creationflags=tt.NO_WINDOW, bufsize=1)
        threading.Thread(target=self.pump, args=(self.server, self.lines), daemon=True, name="jobs-engine").start()

    @staticmethod
    def pump(server, lines):
        for line in server.stdout:
            lines.put(line.strip())
        lines.put(None)

    def ask(self, args, tick=lambda: None):
        """Run one command to its end and return the lines it printed. tick() runs while it does, and may raise."""
        if self.server is None or self.server.poll() is not None:
            self.start()
        tt.clear_stop()
        said, ends = [], time.monotonic()+ASK_MOST
        try:
            self.server.stdin.write("\t".join(args)+"\n")
            self.server.stdin.flush()
            while True:
                if self.control.stopped.is_set():
                    raise Interrupted("Stopped.")
                if time.monotonic() >= ends:
                    raise Interrupted(f"The engine took too long over {args[0]}.")
                tick()
                try:
                    line = self.lines.get(timeout=.05)
                except queue.Empty:
                    continue
                if line is None or line == SERVE_DONE:
                    return said
                if line:
                    said.append(line)
        except BaseException:
            tt.stop_walk(self.server)
            self.server = None
            raise

    def tool(self, args):
        said = self.ask(args)
        found = [line for line in said if line.startswith("{")]
        if not found:
            raise Interrupted(said[-1] if said else "The engine printed nothing.")
        return json.loads(found[-1])

    def live(self, args, tick):
        return "\n".join(line for line in self.ask(args, tick) if not line.startswith("{"))

    def close(self):
        if self.server is not None:
            try:
                self.server.stdin.close()
                self.server.wait(2)
            except (OSError, subprocess.TimeoutExpired):
                self.server.kill()
            self.server = None

    def spot(self):
        data = self.tool(["spot"])
        if not data.get("live"):
            raise Interrupted(f"Cannot read the game: {data.get('why')}")
        return data

    def use(self, actor, tick):
        return self.run([actor["id"], "--use"], tick)

    def terminal(self, spot, tick, exact=False):
        args = ["usespot", f"{spot['x']},{spot['y']},{spot['z']}", f"{spot['yaw']},{spot['pitch']}", "--pulse", "24", *(["--exact"] if exact else [])]
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
        self.talk_wide = TALK_WIDE   # the open conversation's width
        self.job_open = self.recruited = False    # how far this job got, for a try after something went wrong
        self.unpaid = self.slips = 0

    def watch_health(self):
        """Nothing fights back in a Secure Sector."""

    def tap(self, point):
        """The game must see the pointer arrive first: a click straight after a move only lit the row up (live, 2 Nov)."""
        at = place(self.frame(), point)
        self.move(at)
        self.wait(SETTLE)
        self.click(at)

    def hide_pointer(self):
        """Tab, looking as often as the OCR allows instead of the fixed .6 s of set_ui."""
        reader = self.reader()
        if not self.ui_visible(reader):
            return
        self.press("tab")
        ends = self.clock()+2
        while self.ui_visible(reader):
            if self.clock() >= ends:
                raise Interrupted("Could not hide the pointer for mouse-look.")
            self.wait(.03)

    def people(self, word):
        found = [a for a in self.engine.nearby() if a["kind"] == "npc" and not a["dead"] and word.lower() in a["name"].lower()]
        return sorted(found, key=lambda a: a["distance"])

    def wait_for_page(self, wanted, seconds):
        ends = self.clock()+seconds
        while self.clock() < ends:
            if rn_page(self.frame()) == wanted:
                return True
            self.wait(.05)
        return False

    def open_missions(self):
        """The page it reached, or None when the right-click missed the terminal. It shows its splash first. Past that, the
        Missions tab holds wherever the last job left it."""
        opened = False
        for look in range(OPEN_LOOKS):
            self.wait(.1)
            frame = self.frame()
            kind = rn_page(frame)
            if kind in ("factions", "list"):
                return kind
            if not opened and rn_open(frame):
                opened = True
                self.tap(MISSIONS_TAB)
            elif look >= OPEN_GIVE_UP and look % MISSIONS_EVERY == 0:
                if not opened and not self.ui_visible(self.reader()):
                    return None
                self.tap(MISSIONS_TAB)
        raise Interrupted("Could not reach the Missions page of the terminal.")

    def choose_job(self):
        """True when one was accepted."""
        for number in range(MOST_PAGES):
            frame = self.frame()
            row = job_row(self.reader(), frame)
            if row is not None:
                for attempt in range(SELECT_TRIES):
                    self.tap((ROW_CLICK_X, row_y(row)))
                    for look in range(5):
                        self.wait(.1)
                        if row_is_blue(self.frame(), row):
                            self.accept()
                            return True
                raise Interrupted("The mission row did not select.")
            self.tap(NEXT)
            self.next_page(list_picture(frame))
            if not self.wait_for_page("list", LIST_SLOW):
                raise Interrupted("The mission list went away.")
        return False

    def accept(self):
        """Until it takes: a row turns blue before its details load, and a click before they have is ignored (live, 2 Nov)."""
        for attempt in range(ACCEPT_TRIES):
            self.tap(ACCEPT)
            if self.wait_for_page("accepted", ACCEPT_WAIT):
                return
        raise Interrupted("The job was not accepted.")

    def next_page(self, before):
        """Wait until the list has changed and stopped changing, or LIST_WAIT. Each page downloads first: for a quarter of a
        second the list is empty and Next is gone, which reads as still and changed (live, 2 Nov)."""
        ends, last = self.clock()+LIST_WAIT, before
        while self.clock() < ends:
            self.wait(.05)
            frame = self.frame()
            now = list_picture(frame)
            if rn_page(frame) == "list" and np.array_equal(now, last) and not np.array_equal(now, before):
                return
            last = now

    def take_job(self, spot):
        self.emit("status", "Going to the terminal.")
        for exact in (False, True):        # The quick way stops a few units off, which can leave the crosshair beside it.
            last = self.engine.terminal(spot, lambda: None, exact)
            if not last or not last.splitlines()[-1].startswith("Right-clicked"):
                raise Interrupted(last.splitlines()[-1] if last else "The engine said nothing.")
            page = self.open_missions()
            if page is not None:
                break
        else:
            raise Interrupted("The terminal did not open: stand at it with the crosshair on it.")
        if page == "factions":
            self.tap(EASY)
            self.wait(.2)
            self.tap(DOWNLOAD)
            if not self.wait_for_page("list", 15):
                raise Interrupted("The mission list did not download.")
        if not self.choose_job():
            raise Interrupted(f"No TL60 Research Job in {MOST_PAGES} pages.")
        if not self.wait_for_page("accepted", 10):
            raise Interrupted("The job was not accepted.")
        self.job_open = True
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
        words = self.detector.gray(frame[top:top+round(high*.55), left:left+wide])    # The lower part of the panel stays empty.
        return text_lines(self.reader().read_words(words, up=max(2, round(2*TALK_WIDE/wide))), left, top)

    def open_talk(self, person):
        """Walk up and right-click until the conversation shows."""
        for reach in (TALK_REACH, TALK_CLOSE):
            if person["distance"] > reach and not self.walk_to(person, reach):
                continue
            last = self.ended(self.engine.use(person, lambda: None))
            self.emit("log", last)
            for attempt in range(20):
                self.wait(.1)
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
            self.wait(.05)

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
            self.click_option(line["point"])
            for attempt in range(40):      # By its words: the pointer now sits on an option and lights it up.
                self.wait(.1)
                now = self.dialog_lines()
                if now is None or not now or now[0]["text"] != lines[0]["text"]:
                    break
        raise Interrupted(f"The conversation with {person['name']} did not end.")

    def click_option(self, point):
        """The pointer rests on an option first, or the game only lights it up, and a moment after, for the button to come up on it."""
        self.move(point)
        self.wait(SETTLE)
        self.click(point)
        self.wait(QUICK_LEAVE)

    def close_talk(self):
        """Esc, and only on an open conversation: some screens show words and no option, and no click moves them on (live, 2 Nov)."""
        if not dialog_open(self.frame()):
            return
        self.press("esc")
        for look in range(20):
            self.wait(.1)
            if not dialog_open(self.frame()):
                return
        raise Interrupted("Esc did not close the conversation.")

    def read_option(self):
        """Where the OCR finds the option to click, for a screen the pixels make nothing of."""
        lines = self.dialog_lines()
        line = answer(lines, self.talk_wide) if lines else None
        return line["point"] if line else None

    def quick_talk(self, person):
        """A recruiter sells nothing and what they say doesn't matter: click the first option as each screen shows it, unread.
        The pointer leaves after each click: left on the words it joins their lines into one (live, 2 Nov)."""
        self.hide_pointer()
        self.open_talk(person)
        ends, clicked, at, reopened = self.clock()+QUICK_MOST, None, self.clock(), 0
        box = dialog_box(self.frame())
        while box is not None and self.clock() < ends:
            frame = self.frame()
            if not still_open(frame, box):
                return
            point = first_option(frame, box)
            if point is None and self.clock() >= at+QUICK_READ:
                point = self.read_option()
            if point is None and self.clock() >= at+QUICK_STUCK and reopened < QUICK_REOPEN:
                self.emit("log", f"{person['name']} gave nothing to answer: closing the conversation and opening it again.")
                self.close_talk()
                self.hide_pointer()
                self.open_talk(person)
                reopened += 1
                ends, clicked, at = self.clock()+QUICK_MOST, None, self.clock()
                box = dialog_box(self.frame())
                continue
            if point is not None and (point != clicked or self.clock() >= at+QUICK_AGAIN):
                self.click_option(point)
                self.move((box[0]+round(box[2]*QUICK_PARK), box[1]+round(box[3]*QUICK_PARK)))
                clicked, at = point, self.clock()
            self.wait(.02)
        if box is not None:
            raise Interrupted(f"The conversation with {person['name']} did not end.")

    def run_job(self, spot):
        """From wherever the last try broke off: taking a new job over an open one fails it, for a fee."""
        if not self.job_open:
            self.take_job(spot)
            self.recruited = False
        if not self.recruited:
            recruiters = self.people("Recruiter")
            if not recruiters:
                raise Interrupted("No recruiter here.")
            self.emit("status", f"Talking to {recruiters[0]['name']}.")
            self.quick_talk(recruiters[0])
            self.recruited = True
        paid = False
        for manager in self.people("Faction Supply Manager"):
            self.emit("status", f"Talking to {manager['name']}.")
            said = " ".join(self.talk(manager)).lower()
            paid = any(word in said for word in PAID_WORDS)
            if paid:      # Either may be the one, and it changes from job to job.
                break
        if not paid:
            self.recruited = False
            self.unpaid += 1
            self.job_open = self.job_open and self.unpaid % UNPAID_TRIES != 0
            raise Interrupted("Neither faction supply manager paid. Are the blueprints in your Inventory? The job is still open.")
        self.job_open, self.unpaid = False, 0

    def recover(self):
        """Back in the world from wherever a try stopped: answer any conversation to its end, then Tab the menus away. Never Esc."""
        for screen in range(MOST_SCREENS):
            point = self.read_option()
            if point is None:
                break
            self.click_option(point)
            self.wait(RECOVER_WAIT)
        self.close_talk()
        self.hide_pointer()

    def note_slip(self, error):
        """A picture and a line in diagnostics for each: nobody is watching an hour's run."""
        self.slips += 1
        name = f"job-slip-{self.slips%KEPT_PICTURES}.png"
        path = self.save_failure(error)
        if path is None:
            return
        try:
            shutil.copy(path, path.with_name(name))
            with open(path.with_name("job-slips.txt"), "a", encoding="utf-8") as notes:
                notes.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} after {self.completed} jobs: {error} ({name})\n")
        except OSError:
            pass

    def execute(self):
        self.hide_pointer()
        if not self.people("Recruiter") or not self.people("Faction Supply Manager"):
            raise Interrupted("No recruiters or faction supply managers here: start at the terminal in the headquarters.")
        spot = self.engine.spot()
        tries = 0
        while True:
            self.checkpoint()
            try:
                if tries:
                    self.recover()
                self.run_job(spot)
            except Exception as error:
                self.checkpoint(True)      # Stop, lost focus and a closed game end the run here. A pause waits.
                tries += 1
                if tries >= JOB_TRIES or "pressed" in str(error):
                    raise
                self.note_slip(error)
                self.emit("log", f"{error} Trying again ({tries} of {JOB_TRIES-1}).")
                continue
            tries = 0
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
            self.engine.close()
            self.backend.release_all()
