"""Nav-Ray auto-walk: pick a destination in the Nav-Ray window, press Start, then follow the
dashed path by steering the camera (relative mouse motion) while holding W.

All constants below are starting values to be tuned against live runs (mouse sensitivity, speed).
"""
import re

import cv2
import numpy as np

import navray
import pathvision
from macro_core import Interrupted
from vision_runner import VisualRunner

GAIN = .16               # mouse counts per pixel of steering error at 2560 wide
MAX_STEP = 45            # largest single mouse move
DEADZONE = .02           # steering error (fraction of width) treated as straight ahead
SMOOTH = .5              # share of each new reading blended into the smoothed error
LEAD = .12               # seconds of error trend added, so the turn eases off before the aim is reached
SEARCH_STEP = 30         # turn while the path is momentarily out of view
FIND_SECONDS = 8.0       # how long to look for a path before giving up
END_SECONDS = 4.0        # no path for this long after seeing one = arrived (or the route ended)
STUCK_SECONDS = 3.0
MAX_SECONDS = 600.0
HEALTH_EVERY = 1.0
ALIGNED = .12           # steering error below which the character moves forward again
TURN_IN_PLACE = .20      # above this the character stops and turns first (running into walls while turning)
REPORT_EVERY = 2.0       # progress line in the log
HEALTH_BOX = (.85, .84, .95, .875)      # "HLT 972 / 972" (fractions of the frame)
PAGES = 30
LIST_PAGES = 250


def steer_step(error):
    """Mouse counts to turn for a steering error (fraction of the view width)."""
    if abs(error) < DEADZONE:
        return 0
    return max(-MAX_STEP, min(MAX_STEP, round(error*2560*GAIN)))


class Steering:
    """Smoothed, damped steering: blends readings and adds the error's trend so the camera does not overshoot."""

    def __init__(self):
        self.smooth = self.last = self.time = None

    def step(self, error, now):
        self.smooth = error if self.smooth is None else self.smooth + SMOOTH*(error - self.smooth)
        rate = 0.0 if self.last is None or now <= self.time else (self.smooth - self.last)/(now - self.time)
        self.last, self.time = self.smooth, now
        return steer_step(self.smooth + LEAD*rate)

    def reset(self):
        self.smooth = self.last = self.time = None


def _bgr(frame):
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


class NavRayRunner(VisualRunner):
    # ---- setup: choose the destination in the open Nav-Ray window ----
    def find_window(self, reader):
        # The OCR occasionally misses the button row on one capture, so look a few times.
        for attempt in range(3):
            window = navray.find_navray(reader, self.detector.gray(self.frame()), checkpoint=self.guard)
            if window is not None:
                return window
            self.wait(.3)
        raise Interrupted("Nav-Ray window not found. Press Tab, open Nav-Ray (F9) with its Small / Sector / World Map buttons visible, then Start.")

    rows_per_notch = None

    def calibrate_scroll(self, window):
        """Rows moved per wheel notch, measured on the Select list (all its entries differ)."""
        def page():
            self.clear_pointer()
            return [t for _, t in navray.read_rows(self.detector.gray(self.frame()), window, "select")]
        self.move(window.wheel_point("select"))
        self.backend.scroll(10)
        self.wait(.25)
        before = page()
        self.move(window.wheel_point("select"))
        self.backend.scroll(-2)
        self.wait(.25)
        shift = navray.row_shift(before, page())
        if not shift:
            raise Interrupted("Nav-Ray: could not measure how far the lists scroll.")
        self.rows_per_notch = shift/2

    def step_to_occurrence(self, which, window, label, row, occurrence):
        """Row of the n-th of several identical-looking entries that follow each other, scrolling if needed."""
        target = row + occurrence - 1
        visible = navray.LIST_ROWS[which]
        while target >= visible:
            if self.rows_per_notch is None:
                self.calibrate_scroll(window)
            shift = round(self.rows_per_notch*self.notches)
            if shift < 1:
                raise Interrupted("Nav-Ray: could not work out how far the list scrolls.")
            self.move(window.wheel_point(which))
            self.backend.scroll(-self.notches)
            self.wait(.25)
            target -= shift
        self.clear_pointer()
        shown = dict(navray.read_rows(self.detector.gray(self.frame()), window, which))
        if target < 0 or navray.find_row([(0, shown.get(target, ""))], label) is None:
            raise Interrupted(f"Nav-Ray: could not locate '{label}' number {occurrence}. Nothing was clicked.")
        return target

    def choose(self, which, wanted, reader):
        label, occurrence = navray.split_label(wanted)
        window = self.find_window(reader)
        self.move(window.wheel_point(which))
        self.backend.scroll(10)                      # to the top of the list
        self.wait(.2)
        previous, empty, saw = None, 0, []
        for _ in range(PAGES):
            self.clear_pointer()
            rows = navray.read_rows(self.detector.gray(self.frame()), window, which)
            if not rows and empty < 8:
                empty += 1                       # the list may not have redrawn after the last click yet
                self.wait(.3)
                continue
            saw = [text for _, text in rows] or saw
            row = navray.find_row(rows, label)
            if row is not None:
                if occurrence > 1:
                    row = self.step_to_occurrence(which, window, label, row, occurrence)
                self.click(window.row_point(which, row))
                self.wait(.4)
                return
            if rows == previous:
                break
            previous = rows
            self.move(window.wheel_point(which))
            self.backend.scroll(-self.notches)
            self.wait(.25)
        shown = "; ".join(saw[:8]) if saw else "nothing readable"
        raise Interrupted(f"Nav-Ray: '{label}' was not found in the {which} list. Last rows read: {shown}.")

    notches = 2

    def clear_pointer(self):
        """The game's cursor would cover list text, so park it away from the window before reading."""
        self.move((24, 80))
        self.wait(.12)

    def read_list(self, which, window, reader):
        """Every entry of a list, top to bottom, plus how many rows could not be read (a highlighted row reads blank)."""
        self.move(window.wheel_point(which))
        self.backend.scroll(10)
        self.wait(.25)
        names, gaps, previous = [], 0, None
        for _ in range(LIST_PAGES):
            self.clear_pointer()
            rows = navray.read_rows(self.detector.gray(self.frame()), window, which)
            numbers = [row for row, _ in rows]
            if numbers:
                gaps += max(numbers) - min(numbers) + 1 - len(numbers)
            for _, text in rows:
                label = navray.clean_label(text)
                if label and label not in names:
                    names.append(label)
            if rows == previous:
                break
            if previous is not None:
                self.learn_scroll_step([t for _, t in previous], [t for _, t in rows], window, which)
            previous = rows
            self.move(window.wheel_point(which))
            self.backend.scroll(-self.notches)
            self.wait(.25)
        return names, gaps

    def learn_scroll_step(self, before, after, window, which):
        """Rows moved by one page of wheel notches -> notches per page that still overlap by two rows."""
        if self.notches != 2 or not before or not after:
            return
        shift = navray.row_shift(before, after)
        if shift:
            self.rows_per_notch = shift/self.notches
            visible = navray.LIST_ROWS[which]
            if 0 < shift < visible - 2:
                self.notches = max(1, min(40, (self.notches*(visible - 2))//shift))

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

    def wait_for_path(self, window):
        started = self.clock()
        while self.clock() - started < 10:
            view = pathvision.find_path(_bgr(self.frame()), ignore=[window.window_box()])
            if view is not None:
                return
            self.wait(.25)
        raise Interrupted("Nav-Ray: no path appeared after Start. Check the route in the Nav-Ray window.")

    def press(self, name):
        self.backend.key(name, True)
        try:
            self.wait(.05)
        finally:
            self.backend.key(name, False)

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

    def walk(self):
        reader = self.detector.text_reader()
        self.backend.key("w", True)
        self.backend.key("shift", True)                  # run
        steering = Steering()
        forward = True

        def go(on):
            nonlocal forward
            if on != forward:
                self.backend.key("w", on)
                forward = on
        try:
            started = self.clock()
            seen_path, last_path = False, started
            last_health_check, baseline = started, None
            previous_thumb, still_since = None, None
            last_report, turned = started, 0
            while True:
                self.checkpoint()
                now = self.clock()
                if now - started > MAX_SECONDS:
                    raise Interrupted("Nav-Ray: the walk took longer than 10 minutes. Stopped.")
                frame = self.frame()
                if frame.mean() < 6:
                    raise Interrupted("Loading screen or black frame. Stopped; walking across zones is not supported yet.")
                if now - last_health_check >= HEALTH_EVERY:
                    last_health_check = now
                    reading = self.health(reader, frame)
                    if reading:
                        if baseline is None:
                            baseline = reading[0]
                        elif reading[0] < baseline - max(1, reading[1]*.02):
                            raise Interrupted(f"Health dropped ({baseline} to {reading[0]}). Stopped.")
                view = pathvision.find_path(_bgr(frame))
                if view is not None:
                    seen_path, last_path = True, now
                    step = steering.step(view.error, now)
                    go(abs(steering.smooth) < (TURN_IN_PLACE if forward else ALIGNED))
                    if step:
                        self.backend.move_relative(step, 0)
                        turned += step
                    if now - last_report >= REPORT_EVERY:
                        last_report = now
                        self.emit("status", f"Nav-Ray: walking {now - started:.0f}s, aim {view.error:+.2f}, "
                                  f"{len(view.points)} dashes, turned {turned:+d}.")
                    thumb = self.thumbnail(frame)
                    if previous_thumb is not None and float(np.abs(thumb - previous_thumb).mean()) < 1.5:
                        still_since = still_since if still_since is not None else now
                        if now - still_since >= STUCK_SECONDS:
                            raise Interrupted("Not moving (the view has not changed). Something may be blocking the way. Stopped.")
                    else:
                        still_since = None
                    previous_thumb = thumb
                else:
                    still_since, previous_thumb = None, None
                    steering.reset()
                    if seen_path:
                        go(False)                        # path out of view: stand and look for it
                    if not seen_path and now - started > FIND_SECONDS:
                        raise Interrupted("No Nav-Ray path found. Check that a route is active and visible.")
                    if seen_path and now - last_path > END_SECONDS:
                        self.emit("done", "Nav-Ray: the path ended. Arrived, or the route was lost.")
                        return
                    if seen_path:
                        self.backend.move_relative(SEARCH_STEP, 0)
                self.sleep(.005)
        finally:
            self.backend.key("shift", False)
            self.backend.key("w", False)

    # ---- sequence ----
    def execute(self):
        if self.profile["navray"].get("scan"):
            return self.scan()
        category, destination = navray.parse_destination(self.profile["navray"]["destination"])
        reader = self.detector.text_reader()
        self.emit("status", f"Nav-Ray: choosing {category}.")
        self.choose("select", category, reader)
        self.emit("status", f"Nav-Ray: choosing {destination}.")
        self.choose("destination", destination, reader)
        window = self.find_window(reader)
        self.click(window.start_point())
        self.move((24, 80))
        self.emit("status", "Nav-Ray: waiting for the route.")
        self.wait_for_path(window)
        self.press("tab")                    # leave the interactive UI; the mouse now turns the camera
        self.wait(.3)
        self.emit("status", "Nav-Ray: walking the path.")
        self.walk()

    def run(self):
        try:
            self.guard()
            self.execute()
        except Exception as exc:
            diagnostic = self.save_failure(exc)
            if diagnostic is not None:
                self.emit("status", f"Last game frame saved locally: {diagnostic}")
            self.emit("error", f"{exc}")
        finally:
            self.backend.release_all()
