"""TL60 Research Jobs in a faction headquarters, one after another until Stop.

Start at the R.N. terminal with the crosshair on it. Each job: right-click the terminal, Missions, Easy, Download Missions,
Next until a TL60 Research Job shows, Accept, then the nearest recruiter, then both faction supply managers, and back.
traversal.exe does the walking, the aiming and the right-clicks; this file works the game's windows.
Places are in the 1920x1080 units of the video they were measured from, and scale with the client. No Esc: Tab closes the menus.
"""
import difflib
import re

import loot_runner
from loot_runner import LootRunner
from macro_core import Interrupted
from vision import cv2

MISSIONS_TAB = (1020, 376)
EASY = (1081, 491)
DOWNLOAD = (811, 691)
ACCEPT = (792, 691)
NEXT = (867, 691)
DOWNLOAD_SHOWS, NEXT_SHOWS, BACK_SHOWS = (762, 691), (890, 691), (1140, 691)     # beside each button's word
ROWS, ROW_TOP, ROW_STEP = 6, 490, 11.25
TITLE, NUMBERS = (754, 975), (752, 1100)
ROW_CLICK_X = 850
RESEARCH_WIDE = (.033, .039)     # of the client: TL60 Research Job .036, TL60 Construction Job .043
DIALOG_SPARE = (170, 620, 1290, 880)     # the empty lower part of a conversation window
DIALOG_TEXT = (150, 225, 1310, 600)

TALK_REACH = 180             # units: how close to walk before right-clicking a person
TALK_CLOSE = 90              # and from here if the first try opened nothing
MOST_PAGES = 20
MOST_SCREENS = 8             # of one conversation
SAME_WORDS = .7              # how alike the OCR's line and a known answer must be
RECRUITER = ("Do you have work for me?", "What kind of Blueprints do you require?", "Good, I'll start straightaway.", "(click)")
MANAGER = ("(click)", "Oh sorry I got the wrong person.")
JOB_MARK = re.compile(r"36|6[0O]{3}|T[^ ]{0,2}[6G][0O]")


def place(frame, point):
    height, width = frame.shape[:2]
    return round(point[0]/1920*width), round(point[1]/1080*height)


def area(frame, x0, y0, x1, y1):
    (left, top), (right, bottom) = place(frame, (x0, y0)), place(frame, (x1, y1))
    return frame[top:bottom, left:right]


def lit(frame, point):
    """A bright green button at this place?"""
    x, y = point
    box = area(frame, x-5, y-3, x+5, y+3).astype(int)
    return ((box[..., 1] > 200) & (box[..., 1]-box[..., 0] > 60)).mean() > .5


def rn_page(frame):
    """Which page of the R.N. window shows, by its buttons. None for its splash, or no window."""
    if lit(frame, NEXT_SHOWS) and lit(frame, BACK_SHOWS):
        return "list"
    if lit(frame, BACK_SHOWS):
        return "accepted"
    return "factions" if lit(frame, DOWNLOAD_SHOWS) else None


def dialog_open(frame):
    box = area(frame, *DIALOG_SPARE).astype(int)
    red, green, blue = box[..., 0], box[..., 1], box[..., 2]
    return ((green-red > 40) & (green-blue > 25) & (green > 90) & (green < 190)).mean() > .5


def row_y(row):
    return ROW_TOP+row*ROW_STEP


def row_is_blue(frame, row):
    x, y = place(frame, (ROW_CLICK_X+60, row_y(row)))
    red, green, blue = (int(v) for v in frame[y, x][:3])
    return blue > green and blue > red


def title_width(frame, row):
    """Of the client's width. The title's letters are near white on green."""
    cell = area(frame, TITLE[0], row_y(row)-5, TITLE[1], row_y(row)+5)
    columns = (cell.min(axis=2) > 120).any(axis=0).nonzero()[0]
    return 0. if columns.size == 0 else float(columns[-1]-columns[0]+1)/frame.shape[1]


def is_job(words, width):
    """The two TL60 jobs part by width, and the Research jobs by their numbers. The OCR rarely gets a whole row right."""
    return RESEARCH_WIDE[0] <= width <= RESEARCH_WIDE[1] and JOB_MARK.search(words) is not None


def row_words(reader, frame, row):
    cell = area(frame, NUMBERS[0], row_y(row)-7, NUMBERS[1], row_y(row)+7)
    return " ".join(word[0] for image in (cell.max(axis=2), cell.min(axis=2)) for word in reader.read_words(image))


def job_row(reader, frame):
    return next((row for row in range(ROWS) if is_job(row_words(reader, frame, row), title_width(frame, row))), None)


def letters(text):
    return "".join(c for c in text.lower() if c.isalpha())


def answer(lines, known):
    """The line to click: the first known answer, in the order given, that is on screen."""
    for phrase in known:
        for line in lines:
            if difflib.SequenceMatcher(None, letters(line["text"]), letters(phrase)).ratio() >= SAME_WORDS:
                return line
    return None


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
        found.append({"text": " ".join(word[1] for word in row["words"]),
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

    def watch_health(self):
        """Nothing fights back in a Secure Sector."""

    def tap(self, point):
        self.click(place(self.frame(), point))

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
                self.tap((ROW_CLICK_X, row_y(row)))
                self.wait(.5)
                if not row_is_blue(self.frame(), row):
                    raise Interrupted("The mission row did not select.")
                self.tap(ACCEPT)
                return True
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
        if not dialog_open(frame):
            return None
        left, top = place(frame, DIALOG_TEXT[:2])
        return text_lines(self.reader().read_words(self.detector.gray(area(frame, *DIALOG_TEXT)), up=2), left, top)

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

    def talk(self, person, known):
        """Everything they said. Clicks through to the end, on the answers it knows."""
        self.hide_pointer()
        self.open_talk(person)
        said = []
        for screen in range(MOST_SCREENS):
            lines = self.dialog_lines()
            if lines is None:
                return said
            words = " ".join(line["text"] for line in lines)
            said.append(words)
            line = answer(lines, known)
            if line is None:
                raise Interrupted(f"{person['name']} said something new: {words[:200]}")
            self.click(line["point"])
            for attempt in range(16):
                self.wait(.25)
                if self.dialog_lines() != lines:
                    break
        raise Interrupted(f"The conversation with {person['name']} did not end.")

    def run_job(self, spot):
        self.take_job(spot)
        recruiters = self.people("Recruiter")
        if not recruiters:
            raise Interrupted("No recruiter here.")
        self.emit("status", f"Talking to {recruiters[0]['name']}.")
        self.talk(recruiters[0], RECRUITER)
        paid = False
        for manager in self.people("Faction Supply Manager"):
            self.emit("status", f"Talking to {manager['name']}.")
            said = " ".join(self.talk(manager, MANAGER)).lower()
            paid = paid or "payment" in said or "credits" in said
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
