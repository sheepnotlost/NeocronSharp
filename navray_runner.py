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

GAIN = .16               # mouse counts per pixel of steering error at 2560 wide (only until the turn is calibrated)
MAX_STEP = 45            # largest single mouse move (before the turn is calibrated)
CAL_NUDGES = (40, 20, 80, 10)    # mouse counts tried, in turn, to measure how far the view slides per count
SCENE_BOX = (.22, .10, .82, .52)   # the part of the screen that is only scene: no HUD, not the character
CAL_DAMP = .85           # share of a measured correction applied in one turn
CAL_MAX_PX = 260         # largest single mouse move, in screen pixels
LOST_FRAMES = 10         # looks without the followed path before the macro searches the whole screen again
DASHES_PER_LEG = 4       # dashes read in front of the character, then walked, before reading the next four
LINED_UP = .03           # steering error (fraction of width) below which the character walks
AGREE = .05              # the three looks before a move must agree on the heading to within this
VEER = .22               # while walking, an error this big stops the leg and re-reads the path (a corner)
LEG_SECONDS = 8.0        # longest a leg may last
MAX_TURNS = 6            # turns in a row that do not line the dashes up before giving up
SEARCH_STEP = 60         # mouse counts per look while turning to find the path (until calibrated)
SEARCH_COUNTS = 7000     # most turning allowed to find the first path (a safety stop)
SCAN_PX = 220            # how far the view sweeps per look while scanning all round for the path
SAME_VIEW = 9            # mean picture difference below which the view is back where the scan began
END_SECONDS = 4.0        # no path for this long after seeing one = arrived (or the route ended)
STUCK_SECONDS = 3.0
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


def slide_pixels(first_gray, second_gray):
    """How far (in pixels of the inputs) the picture slid horizontally between two frames, and how sure we are."""
    first, second = np.float32(first_gray), np.float32(second_gray)
    window = cv2.createHanningWindow((first.shape[1], first.shape[0]), cv2.CV_32F)
    (dx, _), response = cv2.phaseCorrelate(first, second, window)
    return float(dx), float(response)


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

    px_per_count = None

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

    def turn(self, error, width):
        """Turn the camera by `error` of the screen width in one go, in moves the game can follow, then let it settle."""
        remaining = self.counts(error, width)
        limit = max(10, round(CAL_MAX_PX/abs(self.px_per_count))) if self.px_per_count else MAX_STEP*3
        total = remaining
        while remaining:
            chunk = max(-limit, min(limit, remaining))
            self.backend.move_relative(chunk, 0)
            remaining -= chunk
            self.wait(.02)
        self.wait(.12)
        return total

    def evaluate(self, track, lost):
        """Stand still and take three quick looks at the dashes. The heading is only trusted when they agree
        (a stray mark or a moving picture makes them differ), otherwise look again. Returns the middle
        reading as (view, frame), or None if no dashes were seen."""
        readings, errors = [], []
        for _ in range(3):
            readings = []
            for _ in range(3):
                frame = self.frame()
                view = pathvision.find_path(_bgr(frame), prior=track if lost < LOST_FRAMES else None,
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

    def aim_error(self, view, frame):
        """Where the next dashes lie sideways of straight ahead, as a fraction of the width: the first two
        dashes together, so that one odd mark cannot decide the heading."""
        height, width = frame.shape[:2]
        ahead = self.next_dashes(view, height)[:2] or [view.aim]
        return (sum(p[0] for p in ahead)/len(ahead) - width/2)/width

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

    def walk_leg(self, view, track, reader, state):
        """Walk towards the next dashes with W held; stop after DASHES_PER_LEG of them have been passed, or when
        the path bends away, is lost, or the character is stuck. Returns the last path seen."""
        started = self.clock()
        self.backend.key("w", True)
        passed, last_y, lost, still_since, previous_thumb, reason = 0, None, 0, None, None, "time"
        try:
            while self.clock() - started < LEG_SECONDS:
                self.checkpoint()
                frame = self.frame()
                self.vitals(reader, frame, state)
                now = self.clock()
                seen = pathvision.find_path(_bgr(frame), prior=track, tube=.25)
                if seen is None:
                    lost += 1
                    if lost >= 3:
                        reason = "lost the dashes"
                        break
                else:
                    lost, track = 0, seen
                    state["last_path"] = now
                    if last_y is not None and seen.aim[1] < last_y - .12*frame.shape[0]:
                        passed += 1                          # the dash we were heading for was reached: on to the next
                    last_y = seen.aim[1]
                    if passed >= DASHES_PER_LEG:
                        reason = f"passed {passed} dashes"
                        break
                    if abs(self.aim_error(seen, frame)) > VEER:
                        reason = "the path bends away"
                        break
                thumb = self.thumbnail(frame)
                if previous_thumb is not None and float(np.abs(thumb - previous_thumb).mean()) < 1.5:
                    still_since = still_since if still_since is not None else now
                    if now - still_since >= STUCK_SECONDS:
                        raise Interrupted("Not moving (the view has not changed). Something may be blocking the way. Stopped.")
                else:
                    still_since = None
                previous_thumb = thumb
                self.sleep(.005)
        finally:
            self.backend.key("w", False)
        self.wait(.05)
        return track, passed, reason

    def walk(self):
        reader = self.detector.text_reader()
        self.px_per_count = self.calibrate_turn()
        if self.px_per_count:
            self.emit("status", f"Nav-Ray: turning calibrated, the view slides {self.px_per_count:+.2f} px per mouse count.")
        else:
            self.emit("status", "Nav-Ray: turning could not be calibrated; using the default gain.")
        self.backend.key("shift", True)                  # run: Shift only acts while the character moves
        started = self.clock()
        state = {"health": None, "health_checked": started, "last_path": started}
        track, lost, legs, turned, turns_in_row = None, 0, 0, 0, 0
        seen_path, searched, scan_first, scan_looks, last_side = False, 0, None, 0, 1
        scanning = True                                 # until the first dashes are found, look all round for them
        last_report = started
        try:
            while True:
                self.checkpoint()
                now = self.clock()
                if now - started > MAX_SECONDS:
                    raise Interrupted("Nav-Ray: the walk took longer than 10 minutes. Stopped.")
                got = self.evaluate(track, lost)
                frame = got[1] if got else self.frame()
                self.vitals(reader, frame, state)
                if got is None:
                    lost += 1
                    if seen_path and not scanning and lost >= 3:
                        # The dashes went out of view (a corner, a pillar): look all the way round before
                        # deciding the route is over.
                        scanning, scan_first, scan_looks, searched = True, None, 0, 0
                        self.emit("status", "Nav-Ray: dashes out of view, looking all the way round.")
                    if scanning:
                        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), (96, 54), interpolation=cv2.INTER_AREA).astype(np.int16)
                        scan_looks += 1
                        if scan_first is None:
                            scan_first = small
                        back_where_it_began = scan_looks > 15 and float(np.abs(small - scan_first).mean()) < SAME_VIEW
                        if back_where_it_began or searched >= SEARCH_COUNTS:
                            if seen_path:
                                self.save_failure(Interrupted("The walk ended here."))
                                self.emit("done", "Nav-Ray: no more dashes all the way round. Arrived, or the route was lost.")
                                return
                            raise Interrupted("No Nav-Ray path found after turning all the way round. Check that a route is active.")
                        look = max(20, round(SCAN_PX/abs(self.px_per_count))) if self.px_per_count else SEARCH_STEP
                        self.backend.move_relative(look, 0)
                        searched += look
                        if self.clock() - last_report >= REPORT_EVERY:
                            last_report = self.clock()
                            self.emit("status", f"Nav-Ray: looking for the path, turned {searched}.")
                    continue
                scanning = False
                view, frame = got
                track, lost = view, 0
                seen_path = True
                state["last_path"] = self.clock()
                error = self.aim_error(view, frame)
                last_side = 1 if error >= 0 else -1
                if abs(error) > LINED_UP:
                    turns_in_row += 1
                    if turns_in_row > MAX_TURNS:
                        raise Interrupted("Nav-Ray: turning does not line the dashes up. Check the mouse look and try again.")
                    turned += self.turn(error, frame.shape[1])
                    continue
                turns_in_row = 0
                legs += 1
                ahead = len(self.next_dashes(view, frame.shape[0]))
                self.emit("status", f"Nav-Ray: leg {legs}, {ahead} dashes ahead, aim {error:+.2f}, turned {turned:+d} so far.")
                leg_started = self.clock()
                track, passed, reason = self.walk_leg(view, track, reader, state)
                self.emit("status", f"Nav-Ray: leg {legs} ended after {self.clock() - leg_started:.0f}s: {reason}.")
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
