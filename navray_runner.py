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

GAIN = .30               # mouse counts per pixel of steering error at 2560 wide
MAX_STEP = 80            # largest single mouse move
DEADZONE = .015          # steering error (fraction of width) treated as straight ahead
SEARCH_STEP = 30         # turn while the path is momentarily out of view
FIND_SECONDS = 8.0       # how long to look for a path before giving up
END_SECONDS = 4.0        # no path for this long after seeing one = arrived (or the route ended)
STUCK_SECONDS = 3.0
MAX_SECONDS = 600.0
HEALTH_EVERY = 1.0
HEALTH_BOX = (.85, .84, .95, .875)      # "HLT 972 / 972" (fractions of the frame)
PAGES = 30


def steer_step(error):
    """Mouse counts to turn for a steering error (fraction of the view width)."""
    if abs(error) < DEADZONE:
        return 0
    return max(-MAX_STEP, min(MAX_STEP, round(error*2560*GAIN)))


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

    def choose(self, which, wanted, reader):
        window = self.find_window(reader)
        self.move(window.wheel_point(which))
        self.backend.scroll(10)                      # to the top of the list
        self.wait(.2)
        previous = None
        for _ in range(PAGES):
            rows = navray.read_rows(reader, self.detector.gray(self.frame()), window, which)
            row = navray.find_row(rows, wanted)
            if row is not None:
                self.click(window.row_point(which, row))
                self.wait(.4)
                return
            if rows == previous:
                break
            previous = rows
            self.move(window.wheel_point(which))
            self.backend.scroll(-2)
            self.wait(.25)
        raise Interrupted(f"Nav-Ray: '{wanted}' was not found in the {which} list.")

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
        try:
            started = self.clock()
            seen_path, last_path = False, started
            last_health_check, baseline = started, None
            previous_thumb, still_since = None, None
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
                    step = steer_step(view.error)
                    if step:
                        self.backend.move_relative(step, 0)
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
                    if not seen_path and now - started > FIND_SECONDS:
                        raise Interrupted("No Nav-Ray path found. Check that a route is active and visible.")
                    if seen_path and now - last_path > END_SECONDS:
                        self.emit("done", "Nav-Ray: the path ended. Arrived, or the route was lost.")
                        return
                    if seen_path:
                        self.backend.move_relative(SEARCH_STEP, 0)
                self.sleep(.005)
        finally:
            self.backend.key("w", False)

    # ---- sequence ----
    def execute(self):
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
