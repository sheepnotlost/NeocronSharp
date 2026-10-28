"""Nav-Ray auto-walk: pick a destination in the Nav-Ray window, press Start, then follow the
dashed path by steering the camera (relative mouse motion) while holding W.

All constants below are starting values to be tuned against live runs (mouse sensitivity, speed).
"""
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

import navray
import pathvision
import routes
from macro_core import Interrupted
from vision_runner import VisualRunner

GAIN = .16               # mouse counts per pixel of steering error at 2560 wide (only until the turn is calibrated)
MAX_STEP = 45            # largest single mouse move (before the turn is calibrated)
CAL_NUDGES = (40, 20, 80, 10)    # mouse counts tried, in turn, to measure how far the view slides per count
SCENE_BOX = (.22, .10, .82, .52)   # the part of the screen that is only scene: no HUD, not the character
CAL_DAMP = .5            # share of a measured correction applied in one turn (the next look corrects the rest)
CAL_MAX_PX = 260         # largest single mouse move, in screen pixels
LOST_FRAMES = 10         # looks without the followed path before the macro searches the whole screen again
DASHES_PER_LEG = 4       # dashes read in front of the character, then walked, before reading the next four
LINED_UP = .03           # steering error (fraction of width) the on-the-move corrections aim for
TURN_FIRST = .08         # a bigger heading error than this: stand still and turn before walking (a smaller one is corrected on the move)
AGREE = .05              # the three looks before a move must agree on the heading to within this
VEER = .22               # while walking, an error this big (after corrections) stops the leg and re-reads the path (a corner)
WALK_DAMP = .5           # share of the measured error corrected on each look while walking
LEG_SECONDS = 8.0        # longest a leg may last
TETHER_SECONDS = 90.0      # a tethered walk may run this long before it re-reads the path from standing
TETHER_DAMP = .7         # share of the measured error corrected on every look while tethered
TETHER_TURN_IN_PLACE = .22   # while tethered, a heading error this big stops forward motion until the turn catches up
TETHER_RESUME = .10      # ...and forward motion resumes below this
CORNER_NEAR = .55        # a corner in the traced route lower on screen than this (fraction of the height) is close:
                         # steer for the way beyond it, so the character turns at the corner instead of overshooting
CORNER_TURN_IN_PLACE = .10   # at a close corner, a heading error this big stops forward motion for a sharp pivot
CORNER_RESUME = .05      # ...and forward motion resumes below this
CORNER_DAMP = 1.0        # share of the error corrected on each look at a close corner (no gradual drift round it)
LOST_GRACE = .4          # seconds the dashes may drop out of view while walking a straight stretch before stopping
MAX_TURNS = 6            # turns in a row that do not line the dashes up before giving up
SEARCH_STEP = 60         # mouse counts per look while turning to find the path (until calibrated)
SEARCH_COUNTS = 7000     # most turning allowed to find the first path (a safety stop)
SCAN_PX = 220            # how far the view sweeps per look while scanning all round for the path
LOCAL_SCAN_WIDTH = .45   # after losing a path, search both sides of the last heading without turning all the way back
SAME_VIEW = 9            # mean picture difference below which the view is back where the scan began
END_SECONDS = 4.0        # no path for this long after seeing one = arrived (or the route ended)
STUCK_SECONDS = 1.2       # the view not changing this long while walking means a wall: back off and look for the way round
SCENE_SAMPLE_SECONDS = 1.0  # compare the background over several seconds, not only adjacent frames
SCENE_STUCK_SECONDS = 3.0
SCENE_HISTORY_SECONDS = 6.0
DOOR_RETRY_SECONDS = 10.0  # do not immediately toggle a door again if the first interaction did not clear the obstruction
DOOR_TARGET_WAIT = 2.0    # allow a moving character or NPC to clear the target before attempting the door
MAX_STUCK = 6            # wall recoveries in one walk before giving up
MAX_SECONDS = 600.0
HEALTH_EVERY = 1.0
REPORT_EVERY = 2.0       # progress line in the log
HEALTH_BOX = (.85, .84, .95, .875)      # "HLT 972 / 972" (fractions of the frame)
PAGES = 30
LIST_PAGES = 250


def steer_step(error):
    """Mouse counts to turn for a steering error (fraction of the view width)."""
    return max(-MAX_STEP, min(MAX_STEP, round(error*2560*GAIN)))


def _bgr(frame):
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def door_target(frame, color="green", reader=None):
    """Is a door label near the crosshair? Called only after forward progress stops.

    The in-game TECH DOOR label is often drawn across bright scenery where OCR misses
    letters; its real-frame mask is a fallback. OCR also accepts other labels with
    the complete word DOOR. Neither a route dash nor a generic obstacle is enough.
    """
    height, width = frame.shape[:2]
    roi = frame[int(.12*height):int(.48*height), int(.25*width):int(.75*width)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    low, high, _ = pathvision._hue_window(color)
    hue, saturation, value = cv2.split(hsv)
    match_hue = (hue >= low) & (hue <= high) if low <= high else ((hue >= low) | (hue <= high))
    mask = (match_hue & (saturation >= 45) & (value >= 60)).astype(np.uint8)*255
    template = cv2.imread(str(Path(__file__).parent / "assets" / "navray_tech_door.png"), cv2.IMREAD_GRAYSCALE)
    if template is not None:
        for adjustment in (.8, .9, 1.0, 1.1, 1.2):
            scale = width/1920*adjustment
            sample = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            if sample.shape[0] <= mask.shape[0] and sample.shape[1] <= mask.shape[1]:
                score = cv2.minMaxLoc(cv2.matchTemplate(mask, sample, cv2.TM_CCOEFF_NORMED))[1]
                if score >= .56:
                    return True
    if reader is not None:
        for image in (cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY), mask):
            try:
                words = reader.read_words(image, up=3)
            except Exception:
                continue
            if any(re.sub(r"[^A-Z]", "", str(word[0]).upper()) == "DOOR" for word in words):
                return True
    return False


def actor_target(frame, color="green"):
    """The game's large top-centre target bar indicates an actor rather than a door."""
    height, width = frame.shape[:2]
    roi = frame[int(.02*height):int(.075*height), int(.35*width):int(.65*width)]
    hue, saturation, value = cv2.split(cv2.cvtColor(roi, cv2.COLOR_RGB2HSV))
    low, high, _ = pathvision._hue_window(color)
    match = (hue >= low) & (hue <= high) if low <= high else ((hue >= low) | (hue <= high))
    return bool(np.mean(match & (saturation >= 80) & (value >= 100)) >= .30)


def slide_pixels(first_gray, second_gray):
    """How far (in pixels of the inputs) the picture slid horizontally between two frames, and how sure we are."""
    first, second = np.float32(first_gray), np.float32(second_gray)
    window = cv2.createHanningWindow((first.shape[1], first.shape[0]), cv2.CV_32F)
    (dx, _), response = cv2.phaseCorrelate(first, second, window)
    return float(dx), float(response)


RECORD_FRAMES = 400            # frames kept per run
RECORD_SIZE = (1280, 720)


class NavRayRunner(VisualRunner):
    # ---- every run leaves a record: the game frame at each decision, and what was decided ----
    record_dir = None            # set to a folder to record; the app and tools point it at diagnostics/last_run
    record_count = 0
    record_started = 0.0

    def start_recording(self, folder):
        """Begin a fresh record in `folder` (the previous run's record is replaced). Every status line the run
        emits is saved with the game frame at that moment, so a failed run can be replayed and studied, and
        its frames turned into test cases."""
        self.record_dir = Path(folder)
        self.record_dir.mkdir(parents=True, exist_ok=True)
        for old in list(self.record_dir.glob("*.jpg")) + list(self.record_dir.glob("events.jsonl")):
            try:
                old.unlink()
            except OSError:
                pass
        self.record_count, self.record_started = 0, time.monotonic()
        plain = self.emit

        def recording_emit(kind, payload=None, _plain=plain):
            self.record(kind, payload)
            _plain(kind, payload)
        self.emit = recording_emit

    def record(self, kind, payload):
        if self.record_dir is None or self.record_count >= RECORD_FRAMES:
            return
        self.record_count += 1
        name = f"{self.record_count:03d}"
        frame = getattr(self, "last_frame", None)
        saved = False
        if frame is not None and hasattr(frame, "shape"):
            try:
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), RECORD_SIZE, interpolation=cv2.INTER_AREA)
                saved = bool(cv2.imwrite(str(self.record_dir / f"{name}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 85]))
            except (cv2.error, OSError):
                pass
        try:
            line = {"n": self.record_count, "t": round(time.monotonic() - self.record_started, 2), "kind": kind,
                    "text": payload if isinstance(payload, str) else None, "frame": f"{name}.jpg" if saved else None,
                    "px_per_count": getattr(self, "px_per_count", None), "dash_color": getattr(self, "dash_color", None)}
            with open(self.record_dir / "events.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + chr(10))
        except (OSError, TypeError):
            pass


    # ---- setup: choose the destination in the open Nav-Ray window ----
    def find_window(self, reader):
        # The OCR occasionally misses the button row on one capture, so look a few times.
        for attempt in range(3):
            window = navray.find_navray(reader, self.detector.gray(self.frame()), checkpoint=self.guard)
            if window is not None:
                return window
            self.wait(.3)
        raise Interrupted("Nav-Ray window not found. Press Tab, open Nav-Ray (F9) with its Small / Sector / World Map buttons visible, then Start.")

    # ---- scrolling: drag the list's own scroll thumb (the wheel jumps too far in this small window) ----
    def clear_pointer(self):
        """The game's cursor would cover list text and the scroll thumb, so park it away before reading."""
        self.move((24, 80))
        self.wait(.12)

    def read_page(self, which, window):
        self.clear_pointer()
        return navray.read_rows(self.detector.gray(self.frame()), window, which)

    def drag_thumb(self, which, window, rows):
        """Scroll the list `rows` rows (negative = up) by dragging its scroll thumb, falling back to single
        mouse-wheel notches when the thumb cannot be found or does not move.

        Returns how many rows it moved, measured from the thumb (right even at the end of a list, where
        the page cannot tell), or None when nothing could move the list at all.
        """
        found = navray.find_thumb(self.detector.gray(self.frame()), window, which)
        if found is None:
            self.emit("status", f"Nav-Ray: no scroll thumb found on the {which} list.")
            return self.wheel(which, window, rows)
        x, top, bottom = found
        middle = (top + bottom)//2
        # The thumb moves the list in proportion to its size: d pixels = d * visible rows / thumb length.
        distance = rows*(bottom - top)/navray.LIST_ROWS[which]
        distance = max(-3000, min(3000, distance))                 # a drag far past the bar is the same as to its end
        self.drag((x, middle), (x, round(middle + distance)))
        self.move((24, 80))
        self.wait(.3)
        after = navray.find_thumb(self.detector.gray(self.frame()), window, which)
        moved = 0.0 if after is None else (after[1] - top)*navray.LIST_ROWS[which]/(bottom - top)
        self.emit("status", f"Nav-Ray: {which} list asked {rows:+.0f} rows, thumb {top}-{bottom} -> "
                  f"{'none' if after is None else after[1]}, moved {moved:+.1f}.")
        if abs(rows) <= 2*navray.LIST_ROWS[which] and abs(moved) < .3*abs(rows) and not self.at_end(which, window, rows):
            return self.wheel(which, window, rows)
        return moved

    def at_end(self, which, window, rows):
        """Is the thumb already at the end the move was heading for (so no movement is expected)?"""
        found = navray.find_thumb(self.detector.gray(self.frame()), window, which)
        if found is None:
            return False
        left, top, right, bottom = window.thumb_strip(which)
        margin = 26*window.scale                                  # the track starts a little inside the strip
        return found[1] <= top + margin if rows < 0 else found[2] >= bottom - margin

    def wheel(self, which, window, rows):
        """Fallback: one mouse-wheel notch at a time over the list (a notch may be several rows)."""
        notches = 12 if abs(rows) > 2*navray.LIST_ROWS[which] else 1
        self.move(window.wheel_point(which))
        self.backend.scroll(notches if rows < 0 else -notches)
        self.move((24, 80))
        self.wait(.3)
        self.emit("status", f"Nav-Ray: {which} list scrolled with the mouse wheel instead ({'up' if rows < 0 else 'down'}).")
        return float(navray.LIST_ROWS[which] - 2) if rows > 0 else -float(navray.LIST_ROWS[which] - 2)

    def to_top(self, which, window):
        self.clear_pointer()
        self.drag_thumb(which, window, -10000)
        for _ in range(3):
            if navray.find_thumb(self.detector.gray(self.frame()), window, which) is None or self.at_end(which, window, -1):
                break
            self.wheel(which, window, -10000)                      # the drag did not reach the top: use the wheel
        self.wait(.1)

    def page_down(self, which, window):
        return self.drag_thumb(which, window, navray.LIST_ROWS[which] - 2)

    def page_up(self, which, window):
        return self.drag_thumb(which, window, -(navray.LIST_ROWS[which] - 2))

    def step_to_occurrence(self, which, window, label, row, occurrence):
        """Row of the n-th of several identical-looking entries that follow each other, scrolling if needed."""
        target = row + occurrence - 1
        visible = navray.LIST_ROWS[which]
        while target >= visible:
            moved = self.page_down(which, window)
            if moved is None or round(moved) < 1:
                raise Interrupted(f"Nav-Ray: could not scroll to '{label}' number {occurrence}. Nothing was clicked.")
            target -= round(moved)
        shown = dict(self.read_page(which, window))
        if target < 0 or navray.find_row([(0, shown.get(target, ""))], label) is None:
            raise Interrupted(f"Nav-Ray: could not locate '{label}' number {occurrence}. Nothing was clicked.")
        return target

    def sweep(self, which, window, label, step, saw):
        """Read pages while moving with `step` (page_down or page_up) until `label` shows or the list ends.
        Returns the row it was found on, or None."""
        previous, empty = None, 0
        for _ in range(PAGES):
            rows = self.read_page(which, window)
            if not rows and empty < 8:
                empty += 1                       # the list may not have redrawn after the last click yet
                self.wait(.3)
                continue
            saw[:] = [text for _, text in rows] or saw
            row = navray.find_row(rows, label)
            if row is not None:
                return row
            if which == "destination" and self.entries:
                row = navray.infer_row(rows, self.entries, label)
                if row is not None and row not in dict(rows):
                    self.emit("status", f"Nav-Ray: {label} could not be read; worked out to be row {row} from its neighbours.")
                    return row
            if rows == previous or step(which, window) is None:
                return None
            previous = rows
        return None

    entries = None                # the known entries of the chosen category, for working out an unreadable row

    def choose(self, which, wanted, reader):
        label, occurrence = navray.split_label(wanted)
        window = self.find_window(reader)
        saw = []
        self.to_top(which, window)
        row = self.sweep(which, window, label, self.page_down, saw)
        if row is None and occurrence == 1:
            # Not found going down: the first move to the top may not have got all the way, so go back
            # up from the bottom as well before giving up.
            row = self.sweep(which, window, label, self.page_up, saw)
        if row is None:
            shown = "; ".join(saw[:8]) if saw else "nothing readable"
            raise Interrupted(f"Nav-Ray: '{label}' was not found in the {which} list. Last rows read: {shown}.")
        if occurrence > 1:
            row = self.step_to_occurrence(which, window, label, row, occurrence)
        self.click(window.row_point(which, row))
        self.wait(.4)

    def read_list(self, which, window, reader):
        """Every entry of a list, top to bottom, plus how many rows could not be read (a highlighted row reads blank)."""
        self.to_top(which, window)
        names, gaps, previous = [], 0, None
        for _ in range(LIST_PAGES):
            rows = self.read_page(which, window)
            numbers = [row for row, _ in rows]
            if numbers:
                gaps += max(numbers) - min(numbers) + 1 - len(numbers)
            for _, text in rows:
                label = navray.clean_label(text)
                if label and label not in names:
                    names.append(label)
            if rows == previous or self.page_down(which, window) is None:
                break
            previous = rows
        return names, gaps

    def scan(self):
        """Read every category and its destinations from the open Nav-Ray window."""
        reader = self.detector.text_reader()
        catalog, unread = {}, 0
        for sweep in range(3):
            window = self.find_window(reader)
            categories, gaps = self.read_list("select", window, reader)
            pending = [name for name in categories if name not in catalog]
            if not pending:
                break
            for name in pending:
                self.emit("status", f"Nav-Ray: reading {name} ({len(catalog) + 1}).")
                self.choose("select", name, reader)
                entries, gaps = self.read_list("destination", self.find_window(reader), reader)
                catalog[name] = entries
                unread += gaps
        if not catalog:
            raise Interrupted("Nav-Ray: no categories could be read from the Select list.")
        self.emit("navray_catalog", catalog)
        total = sum(len(v) for v in catalog.values())
        note = f" {unread} rows could not be read." if unread else ""
        self.emit("done", f"Nav-Ray: read {len(catalog)} categories and {total} destinations.{note}")

    dash_color = None            # a hue (0-179) read from the HUD colour scheme, or "green" when it has no clear colour

    def find_dashes(self, bgr, ignore=(), prior=None, tube=.18):
        """pathvision.find_path in the dash colour. The dashes are drawn in the HUD colour scheme, so the colour is
        read from the HUD (top-left panel) at the start of every walk and nothing else is searched for: a chain of
        green signs in a red-scheme game is never mistaken for a path. (Learning the colour from whatever first
        looked like a path locked a live run onto green signs while the dashes were red.)"""
        if self.dash_color is None:
            hue = pathvision.hud_hue(bgr)
            self.dash_color = hue if hue is not None else "green"
            self.emit("status", f"Nav-Ray: the HUD colour is hue {hue}, so the dashes are "
                      f"{'that colour' if hue is not None else 'green (no clear HUD colour)'}.")
        return pathvision.find_path(bgr, ignore=ignore, prior=prior, tube=tube, color=self.dash_color)

    def wait_for_path(self, window):
        started = self.clock()
        while self.clock() - started < 3:
            view = self.find_dashes(_bgr(self.frame()), ignore=[window.window_box()])
            if view is not None:
                return
            self.wait(.25)
        # The route starts at the character and may lead out of the camera's view: carry on, the walk sweeps
        # all the way round for the dashes.
        self.emit("status", "Nav-Ray: no dashes in view yet; the walk will look all round for them.")

    def menu_words(self, reader):
        """[(text, x, y, w, h)] of the words in the top menu strip, which shows only in interactive-UI mode."""
        gray = self.detector.gray(self.frame())
        return reader.read_words(gray[:max(40, int(.06*gray.shape[0]))])

    def ui_visible(self, reader):
        """Is the game in interactive-UI mode (cursor free, menu bar HYPERCOM / INVENTORY ... on screen)?"""
        words = {t.upper() for t, *_ in self.menu_words(reader)}
        return bool({"HYPERCOM", "INVENTORY", "IMPLANTS", "PROCESSOR"} & words)

    def set_ui(self, reader, on):
        """Put the game into (or out of) interactive-UI mode. Tab toggles it, so look at the screen each time
        instead of assuming which state it was in."""
        for _ in range(3):
            if self.ui_visible(reader) == on:
                return True
            self.press("tab")
            self.wait(.6)
        return self.ui_visible(reader) == on

    def open_navray(self, reader):
        """Make sure the Nav-Ray window is open: interactive UI on, then NAV-RAY in the top menu."""
        for _ in range(3):
            if navray.find_navray(reader, self.detector.gray(self.frame())) is not None:
                return True
            self.set_ui(reader, True)
            for text, x, y, w, h in self.menu_words(reader):
                if text.upper().startswith("NAV"):
                    self.emit("status", "Nav-Ray: opening the window from the top menu.")
                    self.click((x + w//2, y + h//2))
                    self.wait(1.0)
                    break
        return navray.find_navray(reader, self.detector.gray(self.frame())) is not None

    def press(self, name):
        self.backend.key(name, True)
        try:
            self.wait(.05)
        finally:
            self.backend.key(name, False)

    def try_open_door(self, reader):
        """Try the currently targeted door once, keeping mouse-look and focus guards."""
        color = getattr(self, "dash_color", None) or "green"
        deadline = self.clock() + DOOR_TARGET_WAIT
        obstructed = False
        while True:
            frame = self.frame()
            if actor_target(frame, color):
                obstructed = True
            elif door_target(frame, color, reader):
                self.emit("status", "Nav-Ray: door ahead; checking target before right-click.")
                fresh = self.frame()  # target may change while recording/logging or as an NPC walks past
                if not actor_target(fresh, color) and door_target(fresh, color, reader):
                    break
                obstructed = True
            elif not obstructed:
                return False
            if self.clock() >= deadline:
                self.emit("status", "Nav-Ray: door target unclear; no right-click sent.")
                return False
            self.wait(.15)
        self.checkpoint()
        running = "shift" in getattr(self.backend, "held_keys", ())
        if running:
            self.backend.key("shift", False)    # send an unmodified right-click; only release our own key
        self.checkpoint()
        self.backend.button("right", True)
        try:
            self.wait(.06)
        finally:
            self.backend.button("right", False)
        self.wait(.8)  # allow the door animation to begin before looking for the route again
        if running:
            self.checkpoint()
            self.backend.key("shift", True)
        return True

    # ---- the walk ----
    def health(self, reader, frame):
        height, width = frame.shape[:2]
        x0, y0, x1, y1 = HEALTH_BOX
        crop = self.detector.gray(frame)[int(y0*height):int(y1*height), int(x0*width):int(x1*width)]
        text = " ".join(word for word, *_ in sorted(reader.read_words(crop), key=lambda w: w[1]))
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        return (int(match.group(1)), int(match.group(2))) if match else None

    @staticmethod
    def thumbnail(frame):
        height, width = frame.shape[:2]
        centre = cv2.cvtColor(frame[int(.3*height):int(.75*height), int(.3*width):int(.7*width)], cv2.COLOR_RGB2GRAY)
        return cv2.resize(centre, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)

    @staticmethod
    def scene_thumbnail(frame):
        """Background above the character and floor overlays, for longer-term progress checks."""
        height, width = frame.shape[:2]
        scene = frame[int(.15*height):int(.48*height), int(.23*width):int(.82*width)]
        gray = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY)
        return cv2.resize(gray, (300, 120), interpolation=cv2.INTER_AREA).astype(np.float32)

    @staticmethod
    def same_scene(first, second):
        """Match a previous scene after compensating for modest camera movement.

        A mostly unchanged background over several seconds of forward input indicates
        no progress even when the character animates and the camera sways. Unclear
        alignments are not evidence of a blockage.
        """
        if first.std() < 4 or second.std() < 4:
            return False
        (dx, dy), response = cv2.phaseCorrelate(first, second)
        if response < .35 or abs(dx) > 80 or abs(dy) > 30:
            return False
        aligned = cv2.warpAffine(second, np.float32([[1, 0, -dx], [0, 1, -dy]]),
                                 (300, 120), borderMode=cv2.BORDER_REPLICATE)
        difference = np.abs(first[10:-10, 20:-20] - aligned[10:-10, 20:-20])
        return bool(np.median(difference) < 3 and np.mean(difference > 10) < .18)

    px_per_count = None
    route_book = None            # a routes.RouteBook, set by the app/tool; None in tests
    route_destination = ""
    route_legs = ()
    route_start = ""
    route_hint = 0

    def calibrate_turn(self):
        """Measure how far the view slides per mouse count (negative = turning right slides the scene left).
        This makes the steering independent of mouse sensitivity and of an inverted mouse. None if the
        picture does not give a clear reading, in which case the default gain is used."""
        def grab():
            # Only the scene counts: the HUD never moves and would hold the measurement at zero.
            frame = self.frame()
            height, width = frame.shape[:2]
            left, top, right, bottom = SCENE_BOX
            scene = cv2.cvtColor(frame[int(top*height):int(bottom*height), int(left*width):int(right*width)], cv2.COLOR_RGB2GRAY)
            return cv2.resize(scene, (480, 240), interpolation=cv2.INTER_AREA), scene.shape[1]
        for nudge in CAL_NUDGES:
            first, scene_width = grab()
            self.backend.move_relative(nudge, 0)
            self.wait(.3)
            second, _ = grab()
            self.backend.move_relative(-nudge, 0)              # put the view back
            self.wait(.25)
            dx, response = slide_pixels(first, second)
            if response >= .1 and abs(dx) >= 1.0:
                return dx*(scene_width/480)/nudge
            self.emit("status", f"Nav-Ray: calibration with {nudge} counts was weak (shift {dx:+.1f}, certainty {response:.2f}).")
        return None

    def counts(self, error, width):
        """Mouse counts that turn the view by a steering error (fraction of the width)."""
        if self.px_per_count:
            return round(-(error*width)*CAL_DAMP/self.px_per_count)
        return steer_step(error)*3                                # uncalibrated: a bolder version of the old gain

    def scene_picture(self):
        frame = self.frame()
        height, width = frame.shape[:2]
        left, top, right, bottom = SCENE_BOX
        scene = cv2.cvtColor(frame[int(top*height):int(bottom*height), int(left*width):int(right*width)], cv2.COLOR_RGB2GRAY)
        return cv2.resize(scene, (480, 240), interpolation=cv2.INTER_AREA), scene.shape[1]

    def turn(self, error, width):
        """Turn the camera by (part of) `error`, in moves the game can follow, then let it settle. The view's
        real rotation is measured and the pixels-per-count figure adapted, because large quick moves can
        turn further than the small calibration nudge did (mouse acceleration)."""
        remaining = self.counts(error, width)
        limit = max(10, round(CAL_MAX_PX/abs(self.px_per_count))) if self.px_per_count else MAX_STEP*3
        total = remaining
        before = self.scene_picture() if self.px_per_count and abs(total) >= 20 else None
        while remaining:
            chunk = max(-limit, min(limit, remaining))
            self.backend.move_relative(chunk, 0)
            remaining -= chunk
            self.wait(.02)
        self.wait(.15)
        if before is not None:
            after, scene_width = self.scene_picture()
            dx, response = slide_pixels(before[0], after)
            if response >= .15 and abs(dx) >= 2:
                measured = dx*(scene_width/480)/total
                if measured*self.px_per_count > 0:                    # same direction as calibrated
                    self.px_per_count = .5*self.px_per_count + .5*measured
                    self.emit("status", f"Nav-Ray: turn of {total:+d} counts slid the view {dx*(scene_width/480):+.0f}px; now {self.px_per_count:+.2f} px per count.")
        self.last_turn = total
        return total

    def evaluate(self, track, lost, quick=False):
        """Stand still and take three quick looks at the dashes. The heading is only trusted when they agree
        (a stray mark or a moving picture makes them differ), otherwise look again. Returns the middle
        reading as (view, frame), or None if no dashes were seen. `quick` is a single look, for sweeping."""
        if quick:
            frame = self.frame()
            view = self.find_dashes(_bgr(frame), prior=track if lost < LOST_FRAMES else None,
                                        tube=min(.18 + .03*lost, .4))
            return (view, frame) if view is not None else None
        readings, errors = [], []
        for _ in range(3):
            readings = []
            for _ in range(3):
                frame = self.frame()
                view = self.find_dashes(_bgr(frame), prior=track if lost < LOST_FRAMES else None,
                                            tube=min(.18 + .03*lost, .4))
                if view is not None:
                    readings.append((view, frame))
            if not readings:
                return None
            errors = [self.aim_error(v, f) for v, f in readings]
            if len(readings) >= 2 and max(errors) - min(errors) <= AGREE:
                break
        order = sorted(range(len(readings)), key=lambda i: errors[i])
        return readings[order[len(order)//2]]                  # the median reading

    @staticmethod
    def next_dashes(view, height, count=DASHES_PER_LEG):
        """The next `count` dashes ahead of the character, nearest first."""
        return [p for p in view.points if p[1] <= pathvision.REACH_Y*height][:count]

    @staticmethod
    def corner_point(view, height, width):
        """Where to head when the traced line ahead turns close by, else None. A corner low on screen (near the
        character): the two marks just past it, the way the path goes on. A line running across the view close by
        (the character is at the turn already): its far end. Turning for these at the corner, not after it, keeps
        the character on the path round sharp bends."""
        route = view.route or view.points
        if view.corner >= 0 and route[view.corner][1] >= CORNER_NEAR*height:
            beyond = route[view.corner + 1:view.corner + 3]
            return (sum(p[0] for p in beyond)/len(beyond), sum(p[1] for p in beyond)/len(beyond))
        if len(route) >= 2:
            near, far = route[0], route[-1]
            if near[1] >= CORNER_NEAR*height and abs(far[1] - near[1]) < .25*abs(far[0] - near[0]):
                return far
        return None

    def aim_error(self, view, frame):
        """Where the next dashes lie sideways of straight ahead, as a fraction of the width: the first two
        dashes together, so that one odd mark cannot decide the heading; past a close corner, its way on."""
        height, width = frame.shape[:2]
        corner = self.corner_point(view, height, width)
        ahead = [corner] if corner is not None else self.next_dashes(view, height)[:2] or [view.aim]
        return (sum(p[0] for p in ahead)/len(ahead) - width/2)/width

    def steer_error(self, view, frame):
        """The error to steer on while walking: the second and third dashes ahead, which move less from look to
        look than the one at the character's feet; past a close corner, its way on."""
        height, width = frame.shape[:2]
        corner = self.corner_point(view, height, width)
        if corner is not None:
            return (corner[0] - width/2)/width
        ahead = self.next_dashes(view, height, 3)
        pick = ahead[1:3] or ahead or [view.aim]
        return (sum(p[0] for p in pick)/len(pick) - width/2)/width

    def correct_while_walking(self, view, frame, damp=WALK_DAMP):
        """A small calibrated turn towards the dashes, made on the move, so a drift never grows into a veer."""
        if not self.px_per_count:
            return 0
        error = self.steer_error(view, frame)
        if abs(error) <= LINED_UP:
            return 0
        limit = max(5, round(CAL_MAX_PX/abs(self.px_per_count)))
        counts = round(max(-limit, min(limit, -(error*frame.shape[1])*damp/self.px_per_count)))
        if counts:
            self.backend.move_relative(counts, 0)
        return counts

    def vitals(self, reader, frame, state):
        if frame.mean() < 6:
            raise Interrupted("Loading screen or black frame. Stopped; walking across zones is not supported yet.")
        now = self.clock()
        if now - state["health_checked"] >= HEALTH_EVERY:
            state["health_checked"] = now
            reading = self.health(reader, frame)
            if reading:
                if state["health"] is None:
                    state["health"] = reading[0]
                elif reading[0] < state["health"] - max(1, reading[1]*.02):
                    raise Interrupted(f"Health dropped ({state['health']} to {reading[0]}). Stopped.")

    def walk_leg(self, view, track, reader, state, tether=False):
        """Walk towards the next dashes with W held; stop after DASHES_PER_LEG of them have been passed, or when
        the path bends away, is lost, or the character is stuck. Returns the last path seen.

        `tether` walks without those limits: one continuous loop that keeps steering on the dashes (the
        dashes march towards the destination, so it follows the line they trace), stopping forward motion
        only to turn in place when the heading is far off, and ending only when the dashes are lost for good,
        the character is stuck, or TETHER_SECONDS pass."""
        started = self.clock()
        forward = True
        self.backend.key("w", True)
        passed, last_y, reason = 0, None, "time"
        missing_since, at_corner = None, False
        scene_history, next_scene = [], started
        state["still_mark"] = started                      # stuck time counts only while walking, but carries over from leg to leg
        try:
            while self.clock() - started < (TETHER_SECONDS if tether else LEG_SECONDS):
                self.checkpoint()
                frame = self.frame()
                self.vitals(reader, frame, state)
                now = self.clock()
                seen = self.find_dashes(_bgr(frame), prior=track, tube=.25)
                if seen is None and track is not None:
                    seen = self.find_dashes(_bgr(frame))   # a pivot at a corner moves the line out of the old tube
                if seen is None:
                    # A straight stretch may blink out for a moment (stairs, a passer-by): keep going briefly. Never
                    # coast blind at a corner: release W at once and search from standing.
                    missing_since = now if missing_since is None else missing_since
                    if not at_corner and now - missing_since < LOST_GRACE:
                        self.sleep(.005)
                        continue
                    reason = "lost the dashes"
                    break
                else:
                    missing_since = None
                    at_corner = self.corner_point(seen, frame.shape[0], frame.shape[1]) is not None
                    track = seen
                    state["last_path"] = now
                    if last_y is not None and seen.aim[1] < last_y - .12*frame.shape[0]:
                        passed += 1                          # the dash we were heading for was reached: on to the next
                    last_y = seen.aim[1]
                    if tether:
                        error = self.steer_error(seen, frame)
                        stop_at = CORNER_TURN_IN_PLACE if at_corner else TETHER_TURN_IN_PLACE
                        go_at = CORNER_RESUME if at_corner else TETHER_RESUME
                        if forward and abs(error) > stop_at:
                            self.backend.key("w", False)               # far off, or a corner: pivot, then go on
                            forward = False
                        elif not forward and abs(error) <= go_at:
                            self.backend.key("w", True)
                            forward = True
                        self.correct_while_walking(seen, frame, CORNER_DAMP if at_corner else TETHER_DAMP)
                    else:
                        if passed >= DASHES_PER_LEG:
                            reason = f"passed {passed} dashes"
                            break
                        if abs(self.steer_error(seen, frame)) > VEER:
                            reason = "the path bends away"
                            break
                        self.correct_while_walking(seen, frame)
                thumb = self.thumbnail(frame)
                previous = state.get("thumb")
                if not forward:
                    state["still_time"] = 0.0
                elif previous is not None and float(np.abs(thumb - previous).mean()) < 1.5:
                    state["still_time"] = state.get("still_time", 0.0) + max(0.0, now - state["still_mark"])
                else:
                    state["still_time"] = 0.0
                state["still_mark"], state["thumb"] = now, thumb
                if state["still_time"] >= STUCK_SECONDS:
                    state["still_time"] = 0.0
                    reason = "stuck against something"
                    break
                if not forward:
                    # Turning in place is intentional and cannot establish lack of walking progress.
                    scene_history, next_scene = [], now
                elif now >= next_scene:
                    scene = self.scene_thumbnail(frame)
                    scene_history = [(when, old) for when, old in scene_history
                                     if now - when <= SCENE_HISTORY_SECONDS]
                    if any(now - when >= SCENE_STUCK_SECONDS and self.same_scene(old, scene)
                           for when, old in scene_history):
                        state["still_time"] = 0.0
                        reason = "stuck against something"
                        break
                    scene_history.append((now, scene))
                    next_scene = now + SCENE_SAMPLE_SECONDS
                self.sleep(.005)
        finally:
            if "w" in self.backend.held_keys:
                self.backend.key("w", False)
        self.wait(.05)
        return track, passed, reason if reason != "time" or not tether else "tether time limit"

    def finish_route(self, started):
        """Hand the finished walk to whoever keeps the route library (a single event; no file access here)."""
        end = self.area_name()
        self.emit("navray_route", {"start": self.route_start, "destination": self.route_destination, "end": end,
                                   "legs": list(self.route_legs), "seconds": self.clock() - started})

    def area_name(self):
        try:
            return routes.read_area(self.detector.gray(self.frame()))
        except Exception:                                  # OCR trouble must never stop a walk
            return ""

    def walk(self):
        reader = self.detector.text_reader()
        self.route_legs, self.route_start = [], self.area_name()
        self.route_hint = 0
        if self.route_book is not None:
            self.route_hint = self.route_book.first_turn(self.route_start, self.route_destination)
            known = self.route_book.best(self.route_start, self.route_destination)
            if known:
                self.emit("status", f"Nav-Ray: this route is known ({known['walks']} walks, best {known['seconds']}s, "
                          f"{self.route_start} to {known.get('end')}).")
        self.px_per_count = self.calibrate_turn()
        if self.px_per_count:
            self.emit("status", f"Nav-Ray: turning calibrated, the view slides {self.px_per_count:+.2f} px per mouse count.")
        else:
            self.emit("status", "Nav-Ray: turning could not be calibrated; using the default gain.")
        self.backend.key("shift", True)                  # run: Shift only acts while the character moves
        started = self.clock()
        state = {"health": None, "health_checked": started, "last_path": started}
        track, lost, legs, turned, turns_in_row, stuck = None, 0, 0, 0, 0, 0
        self.last_turn = 0
        recorded_turn = 0
        door_tried_at = float("-inf")
        seen_path, searched, scan_first, scan_looks, last_side = False, 0, None, 0, 1
        scan_offset, scan_phase = 0, 0
        scanning = True                                 # until the first dashes are found, look all round for them
        last_report = started
        try:
            while True:
                self.checkpoint()
                now = self.clock()
                if now - started > MAX_SECONDS:
                    raise Interrupted("Nav-Ray: the walk took longer than 10 minutes. Stopped.")
                got = self.evaluate(track, lost, quick=scanning)
                if got is not None and scanning:
                    got = self.evaluate(track, lost)               # something showed while sweeping: confirm it standing still
                frame = got[1] if got else self.frame()
                self.vitals(reader, frame, state)
                if got is None:
                    lost += 1
                    if not scanning and self.last_turn and seen_path:
                        back = -self.last_turn//2
                        self.last_turn = 0
                        self.emit("status", f"Nav-Ray: the turn lost the dashes; coming back {back:+d} counts.")
                        self.backend.move_relative(back, 0)
                        self.wait(.15)
                        continue
                    if not scanning:
                        # The dashes went out of view (a corner, a pillar): look all the way round before
                        # deciding the route is over.
                        scanning, scan_first, scan_looks, searched = True, None, 0, 0
                        scan_offset, scan_phase = 0, 0
                        self.emit("status", f"Nav-Ray: no dashes in view; searching nearby from a stop ({'right' if last_side > 0 else 'left'} first).")
                    if scanning:
                        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), (96, 54), interpolation=cv2.INTER_AREA).astype(np.int16)
                        scan_looks += 1
                        if scan_first is None:
                            scan_first = small
                        back_where_it_began = scan_looks > 15 and float(np.abs(small - scan_first).mean()) < SAME_VIEW
                        if not seen_path and (back_where_it_began or searched >= SEARCH_COUNTS):
                            raise Interrupted("No Nav-Ray path found after turning all the way round. Check that a route is active.")
                        look = max(20, round(SCAN_PX/abs(self.px_per_count))) if self.px_per_count else SEARCH_STEP
                        if seen_path:
                            limit = max(look, round(LOCAL_SCAN_WIDTH*frame.shape[1]/abs(self.px_per_count))) if self.px_per_count else 5*look
                            target = (last_side if scan_phase == 0 else -last_side)*limit
                            if scan_offset == target:
                                if scan_phase == 0:
                                    scan_phase = 1
                                    target = -last_side*limit
                                else:
                                    self.save_failure(Interrupted("Path lost or ended."))
                                    self.finish_route(started)
                                    self.emit("done", "Nav-Ray: path lost or ended. Arrived, or the route was lost.")
                                    return
                            delta = target - scan_offset
                            move = max(-look, min(look, delta))
                            scan_offset += move
                        else:
                            move = look*(self.route_hint or 1)
                        self.backend.move_relative(move, 0)
                        track = None                         # sweeping: look at the whole picture every time
                        searched += abs(move)
                        if self.clock() - last_report >= REPORT_EVERY:
                            last_report = self.clock()
                            self.emit("status", f"Nav-Ray: looking for the path, turned {searched}.")
                    continue
                scanning = False
                view, frame = got
                self.last_turn = 0 if abs(self.aim_error(view, frame)) <= TURN_FIRST else self.last_turn
                track, lost = view, 0
                seen_path = True
                state["last_path"] = self.clock()
                error = self.aim_error(view, frame)
                last_side = 1 if error >= 0 else -1
                if abs(error) > TURN_FIRST:
                    turns_in_row += 1
                    first = view.points[0] if view.points else view.aim
                    self.emit("status", f"Nav-Ray: turn {turns_in_row}, aim {error:+.3f}, {len(view.points)} marks, "
                              f"nearest ({first[0]:.0f}, {first[1]:.0f}).")
                    if turns_in_row > MAX_TURNS:
                        raise Interrupted("Nav-Ray: turning does not line the dashes up. Check the mouse look and try again.")
                    turned += self.turn(error, frame.shape[1])
                    track, lost = None, 0                    # the camera moved: the old path line no longer applies to the new picture
                    continue
                turns_in_row = 0
                legs += 1
                ahead = len(self.next_dashes(view, frame.shape[0]))
                self.emit("status", f"Nav-Ray: leg {legs}, {ahead} dashes ahead, aim {error:+.2f}, turned {turned:+d} so far.")
                leg_started = self.clock()
                track, passed, reason = self.walk_leg(view, track, reader, state, tether=bool(self.px_per_count))
                self.emit("status", f"Nav-Ray: leg {legs} ended after {self.clock() - leg_started:.0f}s: {reason}.")
                self.route_legs.append({"turn": int(turned - recorded_turn), "seconds": round(self.clock() - leg_started, 1),
                                        "dashes": passed, "reason": reason})
                recorded_turn = turned
                if reason == "stuck against something":
                    if self.clock() - door_tried_at >= DOOR_RETRY_SECONDS and self.try_open_door(reader):
                        door_tried_at = self.clock()
                        track, lost, scanning, self.last_turn = None, 0, False, 0
                        continue
                    stuck += 1
                    if stuck > MAX_STUCK:
                        raise Interrupted("Not moving (the view has not changed) after several tries round it. Something blocks the way. Stopped.")
                    # Look for the route from a stop; do not run away while searching.
                    last_side = -last_side
                    track, lost, scanning, scan_first, scan_looks, searched = None, 0, True, None, 0, 0
                    scan_offset, scan_phase = 0, 0
                    self.emit("status", f"Nav-Ray: stuck ({stuck}); stopped, searching nearby for the way round.")
        finally:
            for key in ("shift", "w", "s"):
                if key in self.backend.held_keys:
                    self.backend.key(key, False)

    # ---- sequence ----
    def execute(self):
        if self.profile["navray"].get("scan"):
            return self.scan()
        category, destination = navray.parse_destination(self.profile["navray"]["destination"])
        self.route_destination = f"{category} > {destination}"
        reader = self.detector.text_reader()
        self.open_navray(reader)
        self.emit("status", f"Nav-Ray: choosing {category}.")
        self.choose("select", category, reader)
        known = {navray._norm(k): v for k, v in navray.load_catalog(self.profile).items()}
        self.entries = known.get(navray._norm(category))
        self.emit("status", f"Nav-Ray: choosing {destination}.")
        self.choose("destination", destination, reader)
        window = self.find_window(reader)
        self.click(window.start_point())
        self.move((24, 80))
        self.emit("status", "Nav-Ray: waiting for the route.")
        self.wait_for_path(window)
        # Leave the interactive UI so the mouse turns the camera. Checked on screen: a blind Tab would
        # switch it ON if the game was already out of it.
        if not self.set_ui(reader, False):
            raise Interrupted("Nav-Ray: could not leave the interactive UI (Tab). Click the game view and try again.")
        self.wait(.3)
        self.emit("status", "Nav-Ray: walking the path.")
        self.walk()

    def run(self):
        try:
            if self.record_dir is None:
                self.start_recording(Path(__file__).parent / "diagnostics" / "last_run")
            self.guard()
            self.execute()
        except Exception as exc:
            diagnostic = self.save_failure(exc)
            if diagnostic is not None:
                self.emit("status", f"Last game frame saved locally: {diagnostic}")
            self.emit("error", f"{exc}")
        finally:
            self.backend.release_all()
