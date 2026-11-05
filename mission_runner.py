"""TL60 or TL130 Research Jobs in a faction headquarters, one after another until Stop.

Start at the R.N. terminal with the crosshair on it. Each job: right-click the terminal, Missions, Easy or Very Hard, Download
Missions, Next until the job shows, Accept, then the nearest recruiter, then the faction supply managers until one pays, and back.
traversal.exe does the walking, the aiming and the right-clicks; this file works the game's windows.
The R.N. window is 640x480 pixels, centred, whatever the client's size or UI scale, so its places are pixels from its corner.
A conversation sits where the UI scale puts it, so it is found by its colour. Tab closes the menus. Esc only ever closes a
conversation with nothing to answer, which the user said to do (2 Nov).
"""
import difflib
import json
import math
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import namedtuple
from datetime import datetime

import numpy as np

import job_aim
import loot_runner
import pointer
from loot_runner import LootRunner
from macro_core import Interrupted
from vision import cv2

tt = loot_runner.tt
RN_WIDE, RN_HIGH = 640, 480
MISSIONS_TAB = (400, 21)
LEVEL_X, LEVEL_Y, LEVEL_STEP = 481, 159, 16     # the difficulty list: very easy, easy, normal, hard, very hard
DOWNLOAD = (121, 441)
ACCEPT = (96, 441)
NEXT = (196, 441)
BACK = (520, 441)
DOWNLOAD_SHOWS, NEXT_SHOWS, BACK_SHOWS = (56, 441), (227, 441), (560, 441)     # beside each button's word
ROWS, ROW_TOP, ROW_STEP = 6, 173, 15
TITLE, NUMBERS = (45, 340), (43, 507)
ROW_CLICK_X, ROW_BLUE_X = 173, 253
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
QUICK_AGAIN = 1              # seconds before an option that did nothing is clicked again: one click, then a wait, not a burst
QUICK_MOST = 10              # seconds a recruiter may take
QUICK_READ = 1               # seconds of seeing no option before the OCR looks: all options are up by then
QUICK_PARK = .75             # of the panel, both ways: below the words, where the pointer can't touch them
QUICK_LEAVE = .08            # seconds the pointer stays after a click, for the game to see the button come up on the option
QUICK_STUCK = 3              # seconds with nothing to answer before the conversation is closed and opened again
QUICK_REOPEN = 2             # times, in one talk
SERVE_DONE = "<<done>>"

TALK_REACH = 180             # units: how close to walk before right-clicking a person
TALK_CLOSE = 90              # and from here if the first try opened nothing
MOST_PAGES = 20
SELECT_TRIES = 3
SETTLE = .2                  # seconds between the pointer arriving and a click
GLIDE_SPEED = 2500           # pixels a second: the pointer glides to a place, never jumps there (the user's word, 3 Nov)
GLIDE_LEAST, GLIDE_MOST, GLIDE_STEP = .08, .35, .012     # seconds
PROBE = 12                   # pixels: the nudge that shows which arrow on the screen is the game's pointer
STEER_CLOSE = 2              # pixels: the pointer's tip this near the target is on it
STEER_TRIES = 12             # corrections before giving up
STEER_LOOK = .05             # seconds for the game to draw the pointer where it went
STEER_SLACK = 120            # pixels around where the pointer should be that a correction looks in
STEER_PACKET = 16            # pixels a step when it glides: the probe's size, so the measured gain holds
STAGE_REST = .5              # seconds between the terminal, the recruiter and each manager, for the game to catch up
PLAYER_GONE = 3              # seconds with no other player in sight before it carries on
PLAYER_LOOK = 1              # seconds between looks while it waits
MOST_SCREENS = 8             # of one conversation
OPTIONS_WAIT = 5             # seconds: a screen's options draw after its words (live, 2 Nov)
OPEN_LOOKS = 40              # tenths of a second for the terminal's window to reach Missions
MISSIONS_EVERY = 8           # looks between clicks on its tab
OPEN_GIVE_UP = 15            # looks with no window before the right-click counts as missed
LIST_WAIT = 1.5              # seconds for a new list page to show
LIST_SLOW = 15               # seconds a page of the list may take to download
ACCEPT_WAIT = 1              # seconds after each Accept: one click a second, not a burst
AIM_TRIES = len(job_aim.RN_TRIES)    # clicks on an R.N. button before giving up: the usual place twice, then a little to each side
JOB_TRIES = 6                # tries in a row without a job done before the loop gives up
UNPAID_TRIES = 2             # tries with nobody paying before the job counts as lost: it may have paid unread, and the fee for a new one is small
ASK_MOST = 90                # seconds any one engine command may take: the longest walk here is some 15
KEPT_PICTURES = 20           # of what went wrong, the oldest written over
RECOVER_WAIT = .6            # seconds for the next screen, when putting things right
PAID_WORDS = ("payment", "credits", "quality")
SAME_WORDS = .7              # how alike the OCR's line and a known line must be
SHOP_GOODBYE = "Oh sorry I got the wrong person."    # a supply manager with nothing to pay shows the shop: its first option buys
LEAVING = "somebodyelse"     # the line under the first option, which ends the talk: it can be read first while the options fade in
SPEECH_INDENT = .0013        # of the conversation's width: an option starts with a ">", so it never lines up with the words above
Job = namedtuple("Job", "name level row wide mark")
JOBS = {      # wide: of the window, the title. The OCR reads 130 well and 150 not at all (screenshot, 3 Nov)
    "TL60": Job("TL60 Research Job", "Easy", 1, (.132, .156), re.compile(r"36|6[0O]{3}|T[^ ]{0,2}[6G][0O]")),   # Construction .170
    "TL130": Job("TL130 Research Job", "Very Hard", 4, (.146, .162), re.compile(r"1[3B][0O]")),             # .153, as is TL150; Construction .181
}


RN_SCALES = [round(.5+step*.005, 3) for step in range(501)]    # the R.N. window's size against 640x480, from half to three times
SIDE_GREEN = 120              # the R.N. window's sides: its panels stay under 80
LABEL_ALIKE = .7            # how alike two stretched labels must be: the same word scored .76 to 1, 'easy' on 'very easy' under .55
rn_scales = {}               # (height, width) of the client -> the scale the window was last found at


def rn_scale(frame):
    """How big the R.N. window is drawn, 1 for 640x480. It is 640x480 at 2560x1440 whatever the UI scale, but another screen size
    or Windows' display scaling stretches it, and the clicks missed (5 Nov). The last size it was found at, or 1."""
    return rn_scales.get(frame.shape[:2], 1.)


def rn_sides(frame, scale):
    """Both of the window's bright green sides, at this size, centred on the client?"""
    height, width = frame.shape[:2]
    left, top = round((width-RN_WIDE*scale)/2), round((height-RN_HIGH*scale)/2)
    right = left+round(RN_WIDE*scale)-1
    if left < 2 or right >= width-2 or top < 0:
        return False
    for x in (left, right):
        band = frame[top+round(120*scale):top+round(420*scale), x-2:x+3].astype(int)
        # A one-pixel line, which a stretched picture blurs: 228 green at 640x480 is 202 at 1.5 times and 169 at .625.
        if not ((band[..., 1] > SIDE_GREEN) & (band[..., 1]-band[..., 0] > 60)).any(axis=1).mean() > .5:
            return False
    return True


def find_rn(frame):
    """The R.N. window's scale, or None with no window open. Remembered for the clicks that follow."""
    known = rn_scale(frame)
    if rn_sides(frame, known):
        return known
    height, width = frame.shape[:2]
    middle = frame[height//2-20:height//2+20].astype(int)        # the sides cross the middle of the client: try only sizes that put them on a line there
    lines = set(((middle[..., 1] > SIDE_GREEN) & (middle[..., 1]-middle[..., 0] > 60)).any(axis=0).nonzero()[0].tolist())
    found = [scale for scale in RN_SCALES if round((width-RN_WIDE*scale)/2) in lines | {x+1 for x in lines} | {x-1 for x in lines}
             and rn_sides(frame, scale)]
    if not found:
        return None
    rn_scales[frame.shape[:2]] = found[len(found)//2]      # its sides are a few pixels wide: the middle of the sizes that fit
    return rn_scales[frame.shape[:2]]


def place(frame, point):
    """A place in the R.N. window, on the client."""
    height, width = frame.shape[:2]
    scale = rn_scale(frame)
    return round((width-RN_WIDE*scale)/2+point[0]*scale), round((height-RN_HIGH*scale)/2+point[1]*scale)


def area(frame, x0, y0, x1, y1):
    (left, top), (right, bottom) = place(frame, (x0, y0)), place(frame, (x1, y1))
    return frame[top:bottom, left:right]


def rn_open(frame):
    """The R.N. window's sides, on any of its pages."""
    return find_rn(frame) is not None


def lit(frame, point):
    """A bright green button at this place?"""
    x, y = point
    box = area(frame, x-7, y-4, x+7, y+4).astype(int)
    return ((box[..., 1] > 200) & (box[..., 1]-box[..., 0] > 60)).mean() > .5


def label_pixels(cell):
    """The near-white letters' brightness, trimmed so labels at different places can be compared. They are over 120 at 640x480;
    a stretched window's are blurred, so they are trimmed where they reach 100."""
    light = cell.min(axis=2)
    rows, columns = (light > 100).nonzero()
    if not rows.size:
        return None
    return light[rows.min():rows.max()+1, columns.min():columns.max()+1]


def level_point(row):
    return LEVEL_X, LEVEL_Y+row*LEVEL_STEP


def level_selected(frame, row):
    """Match the whole selected-level label to the row's, not the 'easy' in 'very easy' or the 'hard' in 'very hard'.
    Both labels use the same fixed-size font. Hovering a row does not change the selected label.
    """
    top = LEVEL_Y-6+row*LEVEL_STEP
    selected = label_pixels(area(frame, 468, 105, 572, 119))
    level = label_pixels(area(frame, 468, top, 572, top+13))
    return same_label(selected, level)


def same_label(one, other):
    """The same word: pixel for pixel at 640x480. A stretched window blurs each label its own way, so there they must be the
    same size to a pixel or two and their brightness alike. 'easy' and 'very easy' are nowhere near (5 Nov)."""
    if one is None or other is None:
        return False
    if one.shape == other.shape and np.array_equal(one > 120, other > 120):
        return True
    slack = max(2, round(.04*one.shape[1]))
    if abs(one.shape[0]-other.shape[0]) > 2 or abs(one.shape[1]-other.shape[1]) > slack:
        return False
    # Each is blurred at its own fraction of a pixel: compare them four times bigger, shifted up to two pixels to line up.
    a = cv2.resize(one.astype(np.float32), None, fx=4, fy=4, interpolation=cv2.INTER_LINEAR)
    b = cv2.resize(other.astype(np.float32), (a.shape[1], a.shape[0]), interpolation=cv2.INTER_LINEAR)
    b = cv2.copyMakeBorder(b, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=float(other.min()))
    return float(cv2.matchTemplate(b, a, cv2.TM_CCOEFF_NORMED).max()) >= LABEL_ALIKE


def rn_page(frame):
    """Which page of the R.N. window shows, by its buttons. None for its splash, or no window."""
    find_rn(frame)
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


def inside(point, box, margin=0):
    """Is the point on the conversation's panel?"""
    left, top, wide, high = box
    return left-margin <= point[0] < left+wide+margin and top-margin <= point[1] < top+high+margin


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
    return 0. if columns.size == 0 else float(columns[-1]-columns[0]+1)/(RN_WIDE*rn_scale(frame))


def wide_enough(width, job):
    return job.wide[0] <= width <= job.wide[1]


def is_job(words, width, job=JOBS["TL60"]):
    """A Research and a Construction job part by width, and the Research jobs of a level by their numbers. The OCR rarely
    gets a whole row right."""
    return wide_enough(width, job) and job.mark.search(words) is not None


def list_picture(frame):
    return area(frame, TITLE[0], ROW_TOP-9, NUMBERS[1], row_y(ROWS)).copy()


def row_words(reader, frame, row):
    cell = area(frame, NUMBERS[0], row_y(row)-9, NUMBERS[1], row_y(row)+9)
    return " ".join(word[0] for image in (cell.max(axis=2), cell.min(axis=2)) for word in reader.read_words(image))


def job_row(reader, frame, job):
    """The first row of the right width that reads as a job. Width first: it costs nothing, and reading a row takes two OCRs."""
    return next((row for row in range(ROWS) if wide_enough(title_width(frame, row), job) and is_job(row_words(reader, frame, row), title_width(frame, row), job)), None)


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
    pulse = "16"                 # gentler than a hunt's 24: no jerky turns while walking (the user's word, 3 Nov)
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
        args = ["usespot", f"{spot['x']},{spot['y']},{spot['z']}", f"{spot['yaw']},{spot['pitch']}", "--pulse", self.pulse, *(["--exact"] if exact else [])]
        if self.gains:
            args += ["--gains", self.gains]
        if self.calibration:
            args += ["--calibration", self.calibration]
        return self.keep_gains(self.live(args, tick))


class MissionRunner(LootRunner):
    def __init__(self, *args, job="TL60", aim=None, **kwargs):
        kwargs.setdefault("engine", None)
        super().__init__(*args, **kwargs)
        self.job = JOBS[job]
        self.aim = aim if aim is not None else job_aim.Aim()    # what this PC's clicks needed, learned as it runs
        self.trial = (0, 0)          # a shift being tried on the R.N. window's clicks after a miss
        self.talk_high = 0           # the open conversation's height
        self.tip, self.gain = None, 1.   # where the game's pointer was last seen, and how far it goes per pixel sent
        if kwargs["engine"] is None:
            self.engine = Engine(lambda text: self.emit("log", text), self.control)
        self.talk_wide = TALK_WIDE   # the open conversation's width
        self.job_open = self.recruited = False    # how far this job got, for a try after something went wrong
        self.unpaid = self.slips = 0

    def watch_health(self):
        """Nothing fights back in a Secure Sector."""

    def sees_pointer(self):
        """A real mouse to steer: the tests' fake backends have none, and keep the plain moves."""
        return callable(getattr(self.backend, "move_relative", None))

    def look_moves(self, sent):
        """Send a relative move and look: (before, after) pictures around it."""
        before = self.frame()
        self.glide_relative(*sent)
        self.wait(STEER_LOOK)
        return before, self.frame()

    def glide_relative(self, dx, dy):
        """The pointer moved by mouse motion, as a hand moves it, in small steps eased in and out. Windows' cursor position
        alone did not move the game's pointer on another PC (5 Nov): motion moves it on every PC."""
        distance = math.hypot(dx, dy)
        steps = max(1, math.ceil(distance/STEER_PACKET))
        seconds = 0 if steps == 1 else min(GLIDE_MOST, max(GLIDE_LEAST, distance/GLIDE_SPEED))
        sent_x = sent_y = 0
        for step in range(1, steps+1):
            share = step/steps
            eased = share*share*(3-2*share)
            x, y = round(dx*eased), round(dy*eased)
            if (x, y) != (sent_x, sent_y):
                self.checkpoint()
                self.backend.move_relative(x-sent_x, y-sent_y)
                sent_x, sent_y = x, y
            if step < steps:
                self.wait(seconds/steps)

    def probe(self):
        """(tip, gain) of the game's pointer, found as the one arrow that moves when the mouse does. None: no pointer moved,
        so none shows, and the game is in mouse-look, where any move turns the camera instead."""
        # Right, left, down, up, then further: off the screen's edge, or off green the pointer sits on, it shows on its own.
        for size in (PROBE, 3*PROBE):
            for nudge in ((size, 0), (-size, 0), (0, size), (0, -size)):
                before, after = self.look_moves(nudge)
                along = 0 if nudge[0] else 1
                pairs = [(a, b) for a, b in pointer.moves(before, after)
                         if abs(b[1-along]-a[1-along]) <= 2 and (b[along]-a[along])*nudge[along] > 0
                         and 2 <= abs(b[along]-a[along]) <= 8*size]
                if pairs:
                    a, b = min(pairs, key=lambda pair: abs(pair[1][1-along]-pair[0][1-along]))
                    return b, abs(b[along]-a[along])/size
        return None

    def free_pointer(self):
        """In a conversation the game frees its pointer; when it has not, Tab does, once. Never Esc."""
        if not dialog_open(self.frame()):
            raise Interrupted("The game's pointer is nowhere on the screen, so no click was made. Is a window open?")
        self.emit("log", "The pointer is hidden in this conversation (mouse-look): pressing Tab to free it.")
        self.press("tab")
        self.wait(.6)
        found = self.probe() if dialog_open(self.frame()) else None
        if found is None:
            self.press("tab")       # put it back as it was
            raise Interrupted("The game's pointer did not show in the conversation, so no click was made.")
        return found

    def point_at(self, target):
        """Steer the game's own pointer until its tip is on target, by sight: probe for it, glide most of the way, then correct
        until it is there. Returns where it is."""
        found = self.probe()
        if found is None:
            found = self.free_pointer()
        tip, self.gain = found
        for attempt in range(STEER_TRIES):
            error = (target[0]-tip[0], target[1]-tip[1])
            if abs(error[0]) <= STEER_CLOSE and abs(error[1]) <= STEER_CLOSE:
                self.tip = tip
                return tip
            share = 1 if attempt == 0 else .9          # corrections stop short rather than overshoot
            sent = (round(error[0]/self.gain*share) or (1 if error[0] > 0 else -1 if error[0] < 0 else 0),
                    round(error[1]/self.gain*share) or (1 if error[1] > 0 else -1 if error[1] < 0 else 0))
            before, after = self.look_moves(sent)
            expected = (tip[0]+sent[0]*self.gain, tip[1]+sent[1]*self.gain)
            reach = STEER_SLACK+abs(sent[0]*self.gain)+abs(sent[1]*self.gain)     # the pointer is between where it was and where it went
            region = (min(tip[0], expected[0])-reach, min(tip[1], expected[1])-reach,
                      max(tip[0], expected[0])+reach, max(tip[1], expected[1])+reach)
            pairs = pointer.moves(before, after, start=tip, region=region)
            if not pairs:
                found = self.probe()
                if found is None:
                    raise Interrupted("Lost sight of the game's pointer while moving it, so no click was made.")
                tip, self.gain = found
                continue
            new = min((b for a, b in pairs), key=lambda b: (b[0]-expected[0])**2+(b[1]-expected[1])**2)
            went, size = math.hypot(new[0]-tip[0], new[1]-tip[1]), math.hypot(*sent)
            if size >= 4 and went > 0:
                self.gain = min(5., max(.2, .5*self.gain+.5*went/size))
            tip = new
        raise Interrupted(f"The game's pointer would not reach {target[0]},{target[1]} (it got to {tip[0]},{tip[1]}), so no click was made.")

    def click_here(self):
        """Click where the pointer is, without moving it again."""
        self.checkpoint()
        self.backend.button("left", True)
        try:
            self.wait(.06)
        finally:
            self.backend.button("left", False)

    def aim_click(self, point):
        """Onto it by sight, then click. Without a real mouse (the tests), the plain move and click."""
        if self.sees_pointer():
            self.point_at(point)
            self.wait(SETTLE)
            self.click_here()
        else:
            self.move(point)
            self.wait(SETTLE)
            self.click(point)

    def move(self, point):
        """Glide there, starting and stopping gently as a hand would, then land exactly on it. With the pointer seen, by mouse
        motion from where it was: an unchecked move, for keeping it off the words."""
        if self.tip is not None and self.sees_pointer():
            self.glide_relative(round((point[0]-self.tip[0])/self.gain), round((point[1]-self.tip[1])/self.gain))
            self.tip = tuple(point)
            return
        try:
            start = self.backend.cursor_client()
        except (AttributeError, RuntimeError):
            start = None
        if start is not None:
            dx, dy = point[0]-start[0], point[1]-start[1]
            seconds = min(GLIDE_MOST, max(GLIDE_LEAST, math.hypot(dx, dy)/GLIDE_SPEED)) if math.hypot(dx, dy) > 2 else 0
            steps = round(seconds/GLIDE_STEP)
            for step in range(1, steps):
                share = step/steps
                eased = share*share*(3-2*share)
                super().move((round(start[0]+dx*eased), round(start[1]+dy*eased)))
                self.wait(GLIDE_STEP)
        super().move(point)

    def tap(self, point):
        """The game must see the pointer arrive first: a click straight after a move only lit the row up (live, 2 Nov).
        On the R.N. window, shifted as this PC's clicks have needed, and by any shift being tried after a miss."""
        frame = self.aim_frame = self.frame()
        shift = self.aim.rn(frame)
        at = place(frame, (point[0]+shift[0]+self.trial[0], point[1]+shift[1]+self.trial[1]))
        self.aim_click(at)

    def aim_try(self, attempt):
        """The shift for this try at a click: none twice, then a little to each side."""
        self.trial = job_aim.RN_TRIES[attempt % len(job_aim.RN_TRIES)]

    def took(self, what):
        """The click worked. A shift that made it work is kept for the next one."""
        trial, self.trial = self.trial, (0, 0)
        frame = getattr(self, "aim_frame", None)
        if trial != (0, 0) and frame is not None:
            now = self.aim.learn_rn(frame, trial)
            self.emit("log", f"{what} took a click shifted {trial[0]:+d},{trial[1]:+d}: terminal clicks now shift {now[0]:+d},{now[1]:+d}, kept for next time.")

    def hide_pointer(self):
        """Tab, looking as often as the OCR allows instead of the fixed .6 s of set_ui."""
        self.tip = None          # hidden now, and the engine turns the view: found again by sight before the next click
        reader = self.reader()
        if not self.ui_visible(reader):
            return
        self.press("tab")
        ends = self.clock()+2
        while self.ui_visible(reader):
            if self.clock() >= ends:
                raise Interrupted("Could not hide the pointer for mouse-look.")
            self.wait(.03)

    def wait_alone(self):
        """Hold still between steps while the game shows any other player, near or far, in this zone, until none has for
        PLAYER_GONE (the user's word, 3 Nov). Your own character is never among them: it stands at no distance from you."""
        told, clear = False, None
        while True:
            near = [a for a in self.engine.nearby() if a["kind"] == "player" and a["distance"] >= 1]
            if near:
                clear = None
                if not told:
                    self.emit("status", f"Paused: {near[0]['name']} is in the zone, {near[0]['distance']:.0f} units away. Waiting until no other player is.")
                    told = True
            elif not told:
                return
            else:
                clear = self.clock() if clear is None else clear
                if self.clock()-clear >= PLAYER_GONE:
                    self.emit("log", "No other player in the zone: carrying on.")
                    return
            self.wait(PLAYER_LOOK)

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
                self.aim.learn_scale(frame, rn_scale(frame))
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
            row = job_row(self.reader(), frame, self.job)
            if row is not None:
                for attempt in range(AIM_TRIES):
                    self.aim_try(attempt)
                    self.tap((ROW_CLICK_X, row_y(row)))
                    for look in range(5):
                        self.wait(.1)
                        if row_is_blue(self.frame(), row):
                            self.took("The mission row")
                            self.accept()
                            return True
                self.trial = (0, 0)
                raise Interrupted("The mission row did not select.")
            self.tap(NEXT)
            self.next_page(list_picture(frame))
            if not self.wait_for_page("list", LIST_SLOW):
                raise Interrupted("The mission list went away.")
        return False

    def select_level(self):
        """A click may only highlight the row: require the selected-level label to change."""
        for attempt in range(AIM_TRIES):
            self.aim_try(attempt)
            self.tap(level_point(self.job.row))
            self.move(place(self.frame(), (600, 400)))   # Keep the pointer off the letters being compared.
            for look in range(5):
                self.wait(.1)
                if level_selected(self.frame(), self.job.row):
                    self.took(f"{self.job.level} difficulty")
                    return
        self.trial = (0, 0)
        raise Interrupted(f"{self.job.level} difficulty did not select; missions were not downloaded.")

    def download_missions(self):
        """Retry a missed Download click only while its original page is still visible."""
        for attempt in range(AIM_TRIES):
            self.aim_try(attempt)
            self.tap(DOWNLOAD)
            for look in range(5):
                self.wait(.1)
                page = rn_page(self.frame())
                if page == "list":
                    self.took("Download Missions")
                    return
                if page != "factions":
                    # The button worked; let the download finish without clicking into the next page.
                    self.took("Download Missions")
                    if self.wait_for_page("list", 15):
                        return
                    raise Interrupted("The mission download started but the list did not appear.")
            self.emit("log", f"Download did not open the list (click {attempt+1} of {AIM_TRIES}).")
        self.trial = (0, 0)
        raise Interrupted(f"Download Missions did not respond after {AIM_TRIES} clicks.")

    def accept(self):
        """Until it takes: a row turns blue before its details load, and a click before they have is ignored (live, 2 Nov)."""
        for attempt in range(AIM_TRIES):
            self.aim_try(attempt)
            self.tap(ACCEPT)
            if self.wait_for_page("accepted", ACCEPT_WAIT):
                self.took("Accept")
                return
        self.trial = (0, 0)
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
        if page == "list":
            for attempt in range(AIM_TRIES):
                self.aim_try(attempt)
                self.tap(BACK)
                if self.wait_for_page("factions", 1.5):
                    self.took("Back")
                    break
            else:
                self.trial = (0, 0)
                raise Interrupted("Could not return to the mission difficulty selection.")
        self.emit("status", f"Selecting {self.job.level} difficulty.")
        self.select_level()
        self.emit("log", f"{self.job.level} difficulty confirmed.")
        self.emit("status", f"Downloading {self.job.level} missions.")
        self.download_missions()
        self.emit("log", f"{self.job.level} mission list downloaded.")
        self.emit("status", f"Searching for {self.job.name}.")
        if not self.choose_job():
            raise Interrupted(f"No {self.job.name} in {MOST_PAGES} pages.")
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
        self.talk_wide, self.talk_high = wide, high
        words = self.detector.gray(frame[top:top+round(high*.55), left:left+wide])    # The lower part of the panel stays empty.
        return text_lines(self.reader().read_words(words, up=max(2, round(2*TALK_WIDE/wide))), left, top)

    def open_talk(self, person):
        """Walk up and right-click until the conversation shows."""
        self.tip = None
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

    def click_option(self, point, trial=0.):
        """The pointer rests on an option first, or the game only lights it up, and a moment after, for the button to come up on it.
        Nudged up or down as this PC's chat clicks have needed, and by any nudge being tried after a miss."""
        nudge = (self.aim.chat(self.last_frame) if self.last_frame is not None else 0.)+trial
        point = (point[0], point[1]+round(nudge*self.talk_high))
        self.aim_click(point)
        self.wait(QUICK_LEAVE)

    def chat_took(self, trial, who):
        if trial:
            now = self.aim.learn_chat(self.last_frame, trial)
            self.emit("log", f"{who} took a chat click nudged {trial:+.3f} of the panel: chat clicks now nudge {now:+.3f}, kept for next time.")

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
        misses, trial = 0, 0.
        box = dialog_box(self.frame())
        while box is not None and self.clock() < ends:
            self.talk_high = box[3]
            frame = self.frame()
            if not still_open(frame, box):
                if clicked is not None:
                    self.chat_took(trial, person["name"])
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
            if point is not None and not inside(point, box):
                self.note_pointer(frame, box, point)
                point = None
            if point is not None and (point != clicked or self.clock() >= at+QUICK_AGAIN):
                if clicked is not None and point != clicked:
                    self.chat_took(trial, person["name"])      # the last click moved the talk on
                    misses, trial = 0, 0.
                elif point == clicked:
                    misses += 1         # the same option again: the last click missed it
                    trial = job_aim.CHAT_TRIES[misses % len(job_aim.CHAT_TRIES)]
                if clicked is None and not getattr(self, "chat_pictured", False):
                    self.chat_pictured = True
                    self.emit("log", f"Chat panel at {box[0]},{box[1]} {box[2]}x{box[3]}; first option at {point[0]},{point[1]}.")
                    self.picture(frame, box, point, "recruiter-chat.png")
                self.click_option(point, trial)
                self.move((box[0]+round(box[2]*QUICK_PARK), box[1]+round(box[3]*QUICK_PARK)))
                clicked, at = point, self.clock()
            self.wait(.02)
        if box is not None:
            raise Interrupted(f"The conversation with {person['name']} did not end.")

    def note_pointer(self, frame, box, point):
        """An option read outside the chat panel is never clicked (the pointer drifted off to the right, 5 Nov). One picture a run."""
        self.emit("log", f"Option read at {point[0]},{point[1]}, off the chat panel at {box[0]},{box[1]} {box[2]}x{box[3]}: not clicked.")
        if not getattr(self, "pointer_noted", False):
            self.pointer_noted = True
            self.picture(frame, box, point, "chat-off-panel.png")

    def picture(self, frame, box, point, name):
        """The game's view with the chat panel (red) and the place to click (pink) marked, in diagnostics."""
        try:
            marked = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            cv2.rectangle(marked, (box[0], box[1]), (box[0]+box[2], box[1]+box[3]), (0, 0, 255), 3)
            cv2.circle(marked, (int(point[0]), int(point[1])), 18, (255, 0, 255), 3)
            folder = self.diagnostic_dir
            folder.mkdir(parents=True, exist_ok=True)
            written, data = cv2.imencode(".png", marked)
            if written:
                data.tofile(folder/name)
        except (OSError, cv2.error):
            pass

    def calibrate(self):
        """Start from what this screen size needed last time: the terminal window's size and the clicks' shifts."""
        frame = self.frame()
        saved = self.aim.entry(frame).get("rn_scale") if self.aim.known(frame) else None
        self.emit("log", self.aim.describe(frame))
        if saved:
            rn_scales[frame.shape[:2]] = saved

    def run_job(self, spot):
        """From wherever the last try broke off: taking a new job over an open one fails it, for a fee."""
        self.wait_alone()
        if not self.job_open:
            self.take_job(spot)
            self.recruited = False
            self.wait(STAGE_REST)
        if not self.recruited:
            self.wait_alone()
            recruiters = self.people("Recruiter")
            if not recruiters:
                raise Interrupted("No recruiter here.")
            self.emit("status", f"Talking to {recruiters[0]['name']}.")
            self.quick_talk(recruiters[0])
            self.recruited = True
            self.wait(STAGE_REST)
        paid = False
        for manager in self.people("Faction Supply Manager"):
            self.wait(STAGE_REST)
            self.wait_alone()
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
        try:
            self.emit("log", self.backend.describe())
        except (AttributeError, RuntimeError, OSError):
            pass
        self.calibrate()
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
            self.emit("log", f"{self.job.name} {self.completed} done.")

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
