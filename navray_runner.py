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
SEARCH_STEP = 60         # mouse counts per look while turning to find the path
SEARCH_COUNTS = 7000     # total turning allowed to find the first path (a bit more than a full circle)
LATERAL_W = .35          # share of the steering that pulls the character back onto the line itself
JUMP = .25               # a reading this far from the smoothed one is held back for a moment (stray dashes)
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
        self.held = 0

    def step(self, error, now):
        if self.smooth is not None and abs(error - self.smooth) > JUMP and self.held < 2:
            self.held += 1                    # probably a stray detection: ignore it for up to two readings
            error = self.smooth
        else:
            self.held = 0
        self.smooth = error if self.smooth is None else self.smooth + SMOOTH*(error - self.smooth)
        rate = 0.0 if self.last is None or now <= self.time else (self.smooth - self.last)/(now - self.time)
        self.last, self.time = self.smooth, now
        return steer_step(self.smooth + LEAD*rate)

    def reset(self):
        self.smooth = self.last = self.time = None
        self.held = 0


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

    # ---- scrolling: drag the list's own scroll thumb (the wheel jumps too far in this small window) ----
    def clear_pointer(self):
        """The game's cursor would cover list text and the scroll thumb, so park it away before reading."""
        self.move((24, 80))
        self.wait(.12)

    def read_page(self, which, window):
        self.clear_pointer()
        return navray.read_rows(self.detector.gray(self.frame()), window, which)

    def drag_thumb(self, which, window, rows):
        """Drag the scroll thumb so the list moves `rows` rows (negative = up).

        Returns how many rows it actually moved, measured from where the thumb ended up (so it is
        right even when the list hit its end and the page cannot tell), or None if there is no thumb.
        """
        found = navray.find_thumb(self.detector.gray(self.frame()), window, which)
        if found is None:
            return None
        x, top, bottom = found
        middle = (top + bottom)//2
        # The thumb moves the list in proportion to its size: d pixels = d * visible rows / thumb length.
        distance = rows*(bottom - top)/navray.LIST_ROWS[which]
        self.drag((x, middle), (x, round(middle + distance)))
        self.move((24, 80))
        self.wait(.3)
        after = navray.find_thumb(self.detector.gray(self.frame()), window, which)
        if after is None:
            return 0.0
        return (after[1] - top)*navray.LIST_ROWS[which]/(bottom - top)

    def to_top(self, which, window):
        self.clear_pointer()
        self.drag_thumb(which, window, -10000)
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
            if rows == previous or step(which, window) is None:
                return None
            previous = rows
        return None

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
        self.backend.key("shift", True)                  # run (only acts while moving)
        steering = Steering()
        forward = False                                  # stand still until a path is in view and lined up

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
            last_report, turned, searched, last_side = started, 0, 0, 1
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
                    # Aim along the line ahead and also pull back onto the line itself, so the character
                    # follows the dashes instead of running parallel to them.
                    step = steering.step((1 - LATERAL_W)*view.error + LATERAL_W*view.lateral, now)
                    last_side = 1 if steering.smooth >= 0 else -1
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
                    go(False)                            # path out of view: stand and look for it
                    if not seen_path:
                        # Just after Start the route begins at the character, but it may lead out of view:
                        # turn all the way round looking for it.
                        if searched >= SEARCH_COUNTS:
                            raise Interrupted("No Nav-Ray path found after turning all the way round. Check that a route is active.")
                        self.backend.move_relative(SEARCH_STEP, 0)
                        searched += SEARCH_STEP
                        if now - last_report >= REPORT_EVERY:
                            last_report = now
                            self.emit("status", f"Nav-Ray: looking for the path, turned {searched}.")
                    else:
                        if now - last_path > END_SECONDS:
                            self.emit("done", "Nav-Ray: the path ended. Arrived, or the route was lost.")
                            return
                        self.backend.move_relative(last_side*SEARCH_STEP//2, 0)   # lost it: look back towards where it was
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
