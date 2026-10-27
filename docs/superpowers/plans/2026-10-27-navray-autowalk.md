# Nav-Ray Auto-Walk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Nav-Ray tab: the user names "Category > Destination"; the macro selects it in the in-game Nav-Ray window, presses Start, then walks the dashed path in real time until it ends or something blocks it.

**Architecture:** Screenshot-only control, like the rest of the suite. `pathvision.py` finds the dashed path and returns where to steer; `navray.py` finds and reads the Nav-Ray window; `navray_runner.py` runs setup then a closed steering loop (hold W, relative mouse moves); `windows_backend.py` gains relative mouse motion and W/Tab keys. Spec: `docs/superpowers/specs/2026-10-27-navray-autowalk-design.md`.

**Tech Stack:** Python 3.12 (bundled `runtime\python.exe`), OpenCV, NumPy, Windows OCR via `text_reader.TextReader`, Tk, `unittest`.

**Run everything from the repo root with** `.\runtime\python.exe`. Never run tests while the user is testing in the game (Tk windows steal focus); ask first. Commit and push straight to `main` (`git push origin main`). Do not rebuild the portable ZIP.

**Honesty rules:** offline tests prove detection and logic only. Real steering, arrival, stuck and health detection are unverified until a live run shows them in `macro.log`. Say so in every status report.

## File structure

| File | Responsibility |
|---|---|
| `pathvision.py` (new) | Dash candidates, best straight chain, `find_path(frame_bgr) -> PathView or None`. Pure functions. |
| `navray.py` (new) | Nav-Ray window geometry, `find_navray`, `read_rows`, `find_row`, `parse_destination`. No game input. |
| `navray_runner.py` (new) | `NavRayRunner(VisualRunner)`: select, Start, wait for path, Tab, `walk()` loop, stop reasons. |
| `windows_backend.py` | Add `move_relative(dx, dy)`; add `w` and `tab` scan codes. |
| `macro_core.py` | Profile: `navray: {destination}`, operation `"navray"`, validation. |
| `app.py` | Nav-Ray tab, profile collect/apply, runner dispatch, `--check` line. |
| `tools/build_portable.py` | Add the three new modules to the manifest. |
| `tests/test_pathvision.py`, `tests/test_navray.py`, `tests/test_navray_runner.py`, `tests/test_backend_input.py`, `tests/test_navray_ui.py` (new) | Tests. |
| `tests/fixtures/navray_*.png` (new) | The user's real captures (see Task 1). |

Fixture source folder (user's screenshots, read-only):
`C:\Users\Kainen\AppData\Local\Temp\claude\C--Users-Kainen-Documents-Neocron-Macro-Suite\d86a2f24-e2ec-4bcb-9e75-e97cfb9537cc\images\`
(`14.webp` = hall with path, `15.webp` = stairs with path, `8.png` = Nav-Ray window at scale 1, `16.png` = window with destination list at scale 1, `18.webp` = 2000x1125 frame, window open, scale about .78.)

---

### Task 1: Path detection (`pathvision.py`)

**Files:**
- Create: `pathvision.py`, `tests/test_pathvision.py`
- Create fixtures: `tests/fixtures/navray_path_hall_2000.png`, `tests/fixtures/navray_path_stairs_2000.png`

- [ ] **Step 1: Copy the fixtures as PNG**

```powershell
$img="C:\Users\Kainen\AppData\Local\Temp\claude\C--Users-Kainen-Documents-Neocron-Macro-Suite\d86a2f24-e2ec-4bcb-9e75-e97cfb9537cc\images"
.\runtime\python.exe -c "import cv2,sys; img=sys.argv[1]; [cv2.imwrite('tests/fixtures/'+out, cv2.imread(img+'\\'+src)) for src,out in (('14.webp','navray_path_hall_2000.png'),('15.webp','navray_path_stairs_2000.png'),('8.png','navray_window_1082.png'),('16.png','navray_window_destinations_924.png'),('18.webp','navray_open_with_path_2000.png'))]" $img
Get-ChildItem tests\fixtures\navray_*.png | Select-Object Name,Length
```
Expected: five PNGs, each under 700 KB.

- [ ] **Step 2: Write the failing tests** — `tests/test_pathvision.py`

```python
"""Dashed Nav-Ray path detection on the user's real captures (2000x1125 stills)."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import pathvision

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return cv2.imread(str(FIXTURES / name))


class PathVisionTests(unittest.TestCase):
    def test_stairs_frame_finds_a_long_chain_and_aims_left(self):
        view = pathvision.find_path(load("navray_path_stairs_2000.png"))
        self.assertIsNotNone(view)
        self.assertGreaterEqual(len(view.points), 8)
        self.assertLess(view.error, -.2)            # the path leads well to the left of centre
        ys = [p[1] for p in view.points]
        self.assertEqual(ys, sorted(ys, reverse=True))   # nearest (lowest on screen) first
        self.assertTrue(310 <= min(ys) <= 330 and 520 <= max(ys) <= 620, (min(ys), max(ys)))

    def test_hall_frame_with_green_signs_still_aims_at_the_dashes(self):
        view = pathvision.find_path(load("navray_path_hall_2000.png"))
        self.assertIsNotNone(view)
        self.assertTrue(880 <= view.aim[0] <= 960, view.aim)   # dashes run down x ~ 900-940
        self.assertLess(abs(view.error), .1)

    def test_a_frame_without_a_path_returns_none(self):
        self.assertIsNone(pathvision.find_path(np.full((1125, 2000, 3), 40, np.uint8)))

    def test_ignored_boxes_hide_candidates(self):
        frame = load("navray_path_stairs_2000.png")
        everything = (0, 0, frame.shape[1], frame.shape[0])
        self.assertIsNone(pathvision.find_path(frame, ignore=[everything]))
```

- [ ] **Step 3: Run to verify failure**

Run: `.\runtime\python.exe -m unittest tests.test_pathvision -v`
Expected: ERROR `ModuleNotFoundError: No module named 'pathvision'`.

- [ ] **Step 4: Implement** — `pathvision.py`

```python
"""Find the game's dashed Nav-Ray path in a screenshot and say where to steer.

The path is a chain of short, thin, green dashes lying on one line on the floor. Colour alone is
not enough (green signs and tiles exist), so candidate dashes are filtered by size and shape and
the longest chain of candidates on one straight line is taken as the path.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PathView:
    points: tuple      # (x, y) dash centres, nearest to the camera first
    aim: tuple         # the point to turn towards
    error: float       # aim x relative to the view centre, as a fraction of the width (-.5 .. .5)


def _excluded(fx, fy):
    """HUD areas that are always on screen and green (fractions of the frame)."""
    return (fy < .06 or (fx < .20 and fy < .20) or (fx > .84 and fy > .78)
            or fx > .92 or (fx < .47 and fy > .76))


def dash_candidates(frame, ignore=()):
    """[(cx, cy, area)] of small, dash-shaped green blobs. `ignore` = pixel boxes (x0,y0,x1,y1)."""
    height, width = frame.shape[:2]
    unit = width/2000
    hue, sat, val = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
    mask = ((hue >= 55) & (hue <= 85) & (sat >= 55) & (val >= 95)).astype(np.uint8)
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        cx, cy = centres[i]
        if not 6*unit*unit <= area <= 1500*unit*unit:
            continue
        if _excluded(cx/width, cy/height):
            continue
        if abs(cx - width/2) < 28*unit and abs(cy - .504*height) < 28*unit:
            continue                                   # the reticle
        if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in ignore):
            continue
        long_side, short_side = max(w, h), max(1, min(w, h))
        if long_side > 10*unit and long_side/short_side < 1.5 and area/(w*h) > .5:
            continue                                   # a filled blob, not a dash
        found.append((float(cx), float(cy), int(area)))
    return found


def best_chain(candidates, tolerance=7.0, minimum=4):
    """Largest set of candidates on one line, nearest (lowest on screen) first; [] if too few."""
    points = np.array([(c[0], c[1]) for c in candidates], dtype=float)
    best = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            delta = points[j] - points[i]
            length = float(np.hypot(*delta))
            if length < 15:
                continue
            normal = np.array([-delta[1], delta[0]])/length
            inliers = np.where(np.abs((points - points[i]) @ normal) <= tolerance)[0]
            if len(inliers) > len(best):
                best = inliers
    if len(best) < minimum:
        return []
    chosen = points[best]
    return [tuple(p) for p in chosen[np.argsort(-chosen[:, 1])]]


def find_path(frame, ignore=()):
    """PathView for a BGR frame, or None when no path is visible."""
    chain = best_chain(dash_candidates(frame, ignore))
    if not chain:
        return None
    height, width = frame.shape[:2]
    # Aim at the first dash at or above mid-screen: far enough to steer smoothly, near enough to follow bends.
    aim = next((p for p in chain if p[1] <= .5*height), chain[-1])
    return PathView(tuple(chain), aim, (aim[0] - width/2)/width)
```

- [ ] **Step 5: Run to verify pass**

Run: `.\runtime\python.exe -m unittest tests.test_pathvision -v`
Expected: 4 tests OK. (This exact code was run on both frames: stairs gave 11 points, aim (358, 531), error -.32; hall gave 11 points, aim (900, 546), error -.05.) If a bound fails by a few pixels, adjust the test bound, not the thresholds, unless the chain is wrong.

- [ ] **Step 6: Commit**

```powershell
git add pathvision.py tests/test_pathvision.py tests/fixtures/navray_*.png
git commit -m "Add dashed Nav-Ray path detection"
git push origin main
```

---

### Task 2: Relative mouse motion and W/Tab keys

**Files:**
- Modify: `windows_backend.py` (`key()` scan table at ~line 225; add `move_relative` after `move()` at ~line 209)
- Test: `tests/test_backend_input.py`

- [ ] **Step 1: Write the failing test**

```python
"""New backend input: relative mouse motion and the W / Tab keys (SendInput is captured, not sent)."""
import os
import unittest

from windows_backend import WindowsBackend


@unittest.skipUnless(os.name == "nt", "Windows only")
class BackendInputTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowsBackend()
        self.sent = []
        self.backend.send = self.sent.append

    def test_relative_move_sends_a_move_event_with_the_deltas(self):
        self.backend.move_relative(-37, 5)
        event = self.sent[0]
        self.assertEqual(event.type, 0)
        self.assertEqual((event.mi.dx, event.mi.dy), (-37, 5))
        self.assertEqual(event.mi.dwFlags, 0x0001)        # MOUSEEVENTF_MOVE, not absolute

    def test_w_and_tab_are_scan_code_keys_and_tracked_for_release(self):
        self.backend.key("w", True)
        self.backend.key("tab", True)
        self.assertEqual([e.ki.wScan for e in self.sent], [0x11, 0x0F])
        self.assertEqual(self.backend.held_keys, {"w", "tab"})
        self.backend.key("w", False)
        self.assertEqual(self.sent[-1].ki.dwFlags, 0x0008 | 0x0002)   # scancode | keyup
        self.assertEqual(self.backend.held_keys, {"tab"})
```

- [ ] **Step 2: Run to verify failure**

Run: `.\runtime\python.exe -m unittest tests.test_backend_input -v`
Expected: FAIL/ERROR (`move_relative` missing, `KeyError: 'w'`).

- [ ] **Step 3: Implement**

In `windows_backend.py` add after `move()`:

```python
    def move_relative(self, dx, dy):
        """Raw mouse motion for mouse-look (the game holds the cursor, so absolute moves do not turn the camera)."""
        self.send(self.Input(type=0, mi=self.MouseInput(dx=int(dx), dy=int(dy), dwFlags=0x0001)))
```

In `key()`, extend the scan table: change

```python
        scan = {"ctrl": 0x1D, "shift": 0x2A, "a": 0x1E, "1": 0x02, ...
```
to include `"w": 0x11, "tab": 0x0F,` right after `"a": 0x1E,`.

- [ ] **Step 4: Run to verify pass**

Run: `.\runtime\python.exe -m unittest tests.test_backend_input -v`
Expected: 2 tests OK.

- [ ] **Step 5: Commit**

```powershell
git add windows_backend.py tests/test_backend_input.py
git commit -m "Backend: relative mouse motion and W/Tab keys"
git push origin main
```

---

### Task 3: Nav-Ray window reading (`navray.py`)

Geometry was measured on the real captures (scale 1 = the 1082x526 capture; verified against the .78-scale frame). All offsets are from the top-left of the OCR word "Small" (the left map button), multiplied by `scale`. `scale = (World.x - Small.x) / 353`.

**Files:**
- Create: `navray.py`, `tests/test_navray.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_navray.py`

```python
"""Nav-Ray window geometry and list reading on the user's real captures."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import navray
from text_reader import TextReader

FIXTURES = Path(__file__).parent / "fixtures"


def gray(name, size=None, at=(100, 100)):
    image = cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2GRAY)
    if size is None:
        return image
    frame = np.zeros(size, np.uint8)
    frame[at[1]:at[1]+image.shape[0], at[0]:at[0]+image.shape[1]] = image
    return frame


class DestinationTextTests(unittest.TestCase):
    def test_parse_destination_needs_category_and_destination(self):
        self.assertEqual(navray.parse_destination("Faction HQs > Black Dragon"), ("Faction HQs", "Black Dragon"))
        for bad in ("", "Faction HQs", "a > b > c", " > x"):
            with self.assertRaises(ValueError, msg=bad):
                navray.parse_destination(bad)

    def test_find_row_matches_names_and_truncated_labels(self):
        rows = [(0, "UTILITIES"), (3, "PEPPER PARK APARTMEN ..."), (7, "FACTION HQS")]
        self.assertEqual(navray.find_row(rows, "faction hqs"), 7)
        self.assertEqual(navray.find_row(rows, "Pepper Park Apartments"), 3)
        self.assertIsNone(navray.find_row(rows, "Plaza"))


class NavRayReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = TextReader()

    def test_window_and_buttons_at_scale_one(self):
        frame = gray("navray_window_1082.png", (1080, 1920))
        window = navray.find_navray(self.reader, frame)
        self.assertIsNotNone(window)
        self.assertAlmostEqual(window.scale, 1.0, delta=.05)
        sx, sy = window.start_point()
        self.assertLessEqual(abs(sx - (649 + 100 + 23)), 6)     # "Start" word centre in the capture
        self.assertLessEqual(abs(sy - (341 + 100 + 7)), 6)

    def test_window_at_a_smaller_ui_scale(self):
        frame = gray("navray_open_with_path_2000.png")
        window = navray.find_navray(self.reader, frame)
        self.assertIsNotNone(window)
        self.assertAlmostEqual(window.scale, .78, delta=.04)
        sx, sy = window.stop_point()
        self.assertLessEqual(abs(sx - 579), 8)                  # "Stop" word centre
        self.assertLessEqual(abs(sy - 514), 8)

    def test_category_rows_are_read_in_order(self):
        frame = gray("navray_window_1082.png", (1080, 1920))
        window = navray.find_navray(self.reader, frame)
        rows = navray.read_rows(self.reader, frame, window, "select")
        self.assertEqual(navray.find_row(rows, "Faction HQs"), 7)
        self.assertEqual(navray.find_row(rows, "Utilities"), 0)
        self.assertEqual(navray.find_row(rows, "Pepper Park Apartments"), 3)

    def test_destination_rows_are_read(self):
        frame = gray("navray_window_destinations_924.png", (1080, 1920))
        window = navray.find_navray(self.reader, frame)
        rows = navray.read_rows(self.reader, frame, window, "destination")
        self.assertEqual(navray.find_row(rows, "Protopharm"), 0)
        self.assertEqual(navray.find_row(rows, "Black Dragon"), 2)

    def test_a_frame_without_the_window_is_not_found(self):
        self.assertIsNone(navray.find_navray(self.reader, np.zeros((1080, 1920), np.uint8)))
```

- [ ] **Step 2: Run to verify failure**

Run: `.\runtime\python.exe -m unittest tests.test_navray -v`
Expected: ERROR `ModuleNotFoundError: No module named 'navray'`.

- [ ] **Step 3: Implement** — `navray.py`

```python
"""The in-game Nav-Ray window: locate it from its Small / Sector / World map buttons, read the
two lists with the local OCR, and give click points. All geometry scales with the UI scale, which
is taken from the spacing of the three buttons, so any window position and resolution works.

Offsets are measured on real captures (scale 1) from the top-left of the word "Small".
"""
import re
from dataclasses import dataclass

SPAN = 353.0                      # "Small" -> "World" word spacing
SECTOR_DX = 174.0                 # "Small" -> "Sector"
ROW_PITCH, ROWS, ROW_H = 22.0, 8, 15.0
LIST_W = 270.0
SELECT_DX, SELECT_DY = -133.0, -204.0       # first Select row's text top-left
DEST_DX, DEST_DY = 176.0, -209.0            # first Destination row's text top-left
START_DX, STOP_DX, BUTTON_DY = 312.0, 455.0, -54.0
WINDOW_LEFT, WINDOW_TOP, WINDOW_RIGHT, WINDOW_BOTTOM = -215.0, -305.0, 670.0, 55.0


def parse_destination(text):
    """"Faction HQs > Black Dragon" -> ("Faction HQs", "Black Dragon"). Raises ValueError."""
    parts = [part.strip() for part in (text or "").split(">")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("Nav-Ray destination: use Category > Destination (for example Faction HQs > Black Dragon).")
    return parts[0], parts[1]


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def find_row(rows, wanted):
    """Row number whose text is `wanted` (a trailing "..." means the game cut the label short)."""
    target = _norm(wanted)
    for row, text in rows:
        seen = _norm(text)
        if not seen:
            continue
        if seen == target or (len(seen) >= 8 and ("..." in text or "\u2026" in text) and target.startswith(seen)):
            return row
    return None


@dataclass(frozen=True)
class NavRay:
    x: float          # top-left of the word "Small"
    y: float
    scale: float

    def _at(self, dx, dy):
        return (round(self.x + dx*self.scale), round(self.y + dy*self.scale))

    def start_point(self):
        return self._at(START_DX + 23, BUTTON_DY + ROW_H/2)

    def stop_point(self):
        return self._at(STOP_DX + 21, BUTTON_DY + ROW_H/2)

    def _origin(self, which):
        return (SELECT_DX, SELECT_DY) if which == "select" else (DEST_DX, DEST_DY)

    def row_point(self, which, row):
        dx, dy = self._origin(which)
        return self._at(dx + 60, dy + ROW_PITCH*row + ROW_H/2)

    def wheel_point(self, which):
        return self.row_point(which, 3)

    def list_box(self, which):
        dx, dy = self._origin(which)
        left, top = self._at(dx - 4, dy - 5)
        right, bottom = self._at(dx + LIST_W, dy + ROW_PITCH*ROWS + 5)
        return (max(0, left), max(0, top), right, bottom)

    def window_box(self):
        left, top = self._at(WINDOW_LEFT, WINDOW_TOP)
        right, bottom = self._at(WINDOW_RIGHT, WINDOW_BOTTOM)
        return (max(0, left), max(0, top), right, bottom)


def _anchor_in(words):
    """Small / Sector / World on one line, spaced like the reference buttons -> (x, y, scale)."""
    by_text = {}
    for text, x, y, w, h in words:
        by_text.setdefault(text.lower(), []).append((x, y))
    for sx, sy in by_text.get("small", ()):
        for wx, wy in by_text.get("world", ()):
            scale = (wx - sx)/SPAN
            if not .35 <= scale <= 3.5 or abs(wy - sy) > 4*scale:
                continue
            if any(abs(ox - (sx + SECTOR_DX*scale)) < 8*scale and abs(oy - sy) < 4*scale
                   for ox, oy in by_text.get("sector", ())):
                return (sx, sy, scale)
    return None


def find_navray(reader, gray, checkpoint=lambda: None):
    """Locate the Nav-Ray window anywhere in a grayscale frame. Returns NavRay or None."""
    height, width = gray.shape[:2]
    tile_w, tile_h = width//2 + width//8, height//2 + height//8
    for tx, ty in ((0, 0), (1, 0), (0, 1), (1, 1)):
        checkpoint()
        left = 0 if tx == 0 else width - tile_w
        top = 0 if ty == 0 else height - tile_h
        found = _anchor_in(reader.read_words(gray[top:top+tile_h, left:left+tile_w]))
        if found:
            return NavRay(found[0] + left, found[1] + top, found[2])
    return None


def read_rows(reader, gray, window, which):
    """[(row, text)] of the visible entries of the "select" or "destination" list."""
    left, top, right, bottom = window.list_box(which)
    scale = window.scale
    lines = {}
    for text, x, y, w, h in reader.read_words(gray[top:bottom, left:right]):
        row = round((y + h/2 - (5 + ROW_H/2)*scale)/(ROW_PITCH*scale))
        if 0 <= row < ROWS:
            lines.setdefault(row, []).append((x, text))
    return [(row, " ".join(text for _, text in sorted(words))) for row, words in sorted(lines.items())]
```

- [ ] **Step 4: Run to verify pass**

Run: `.\runtime\python.exe -m unittest tests.test_navray -v`
Expected: 7 tests OK. If a position assertion misses by more than its tolerance, print `window` and the OCR words and correct the corresponding constant (they come from word boxes measured at scale 1: Start 649,341 / Stop 792,341 / Small 337,395 / Select row 204,191 / Destination row 400,137 in the 1082x526 and 924x438 captures). If `find_row(rows, "Black Dragon")` fails because OCR merged words, compare with `_norm`; do not loosen matching to substrings.

- [ ] **Step 5: Commit**

```powershell
git add navray.py tests/test_navray.py
git commit -m "Add Nav-Ray window finder and list reader"
git push origin main
```

---

### Task 4: The runner (`navray_runner.py`)

Behaviour: find the open Nav-Ray window, pick category then destination (scrolling lists), click Start, wait for the path (ignoring the window's own pixels), press Tab to return to mouse-look, then `walk()`.

`walk()` loop each iteration: capture, stop checks, `find_path`, steer. Stop reasons (each an `Interrupted` message except arrival): loading screen (frame nearly black), no path found within 8 s of starting to walk, not moving (view unchanged 3 s while a path is visible), health dropped (read about once a second), longer than 10 minutes, focus lost (`guard`). Arrival: a path was seen and none has been seen for 4 s, then emit `done`. W is always released.

**Files:**
- Create: `navray_runner.py`, `tests/test_navray_runner.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_navray_runner.py`

```python
"""Walk loop and setup sequence with a fake backend and the user's real path frames."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import navray_runner
from macro_core import Control, Interrupted
from navray_runner import NavRayRunner

FIXTURES = Path(__file__).parent / "fixtures"


def rgb(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)


HALL, STAIRS = rgb("navray_path_hall_2000.png"), rgb("navray_path_stairs_2000.png")
DARK = np.full((1125, 2000, 3), 40, np.uint8)


class FakeBackend:
    def __init__(self):
        self.events = []
    def key(self, name, down):self.events.append(("key", name, down))
    def move_relative(self, dx, dy):self.events.append(("rel", dx, dy))
    def scroll(self, notches):self.events.append(("scroll", notches))
    def release_all(self):self.events.append(("release",))
    def check_focus(self, size):pass


class Reader:
    """Pretends to be the OCR: the health region reads the next scripted value."""
    def __init__(self, health):
        self.health = list(health)
    def read_words(self, gray, up=3):
        if not self.health:
            return []
        value = self.health.pop(0) if len(self.health) > 1 else self.health[0]
        return [("HLT", 0, 0, 10, 10), (str(value), 20, 0, 10, 10), ("/", 40, 0, 5, 10), ("972", 50, 0, 10, 10)]


def make_runner(frames, health=(972,)):
    """frames: callable(index) -> RGB frame. Each frame() call advances the fake clock by .1 s."""
    clock = {"t": 0.0, "i": 0}
    runner = NavRayRunner.__new__(NavRayRunner)
    runner.backend = FakeBackend()
    runner.control = Control()
    runner.events = events = []
    runner.emit = lambda kind, payload=None: events.append((kind, payload))
    runner.clock = lambda: clock["t"]
    runner.sleep = lambda seconds: clock.__setitem__("t", clock["t"] + seconds)
    runner.profile = {"client_size": [2000, 1125], "navray": {"destination": "Faction HQs > Black Dragon"}}
    reader = Reader(health)
    class Detector:
        def text_reader(self):return reader
        def gray(self, frame):return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    runner.detector = Detector()
    def frame():
        clock["t"] += .1
        clock["i"] += 1
        return frames(clock["i"])
    runner.frame = frame
    return runner, events


class WalkTests(unittest.TestCase):
    def test_walks_steers_towards_the_path_and_reports_arrival_when_it_ends(self):
        runner, events = make_runner(lambda i: STAIRS if i <= 12 else DARK)
        runner.walk()
        kinds = [e for e in runner.backend.events]
        self.assertEqual(kinds[0], ("key", "w", True))
        self.assertEqual(kinds[-1], ("key", "w", False))
        turns = [e[1] for e in kinds if e[0] == "rel" and e[1] != 0]
        self.assertTrue(turns and all(t < 0 for t in turns[:5]), turns[:5])      # path is to the left
        self.assertTrue(all(abs(t) <= navray_runner.MAX_STEP for t in turns))
        done = [p for k, p in events if k == "done"]
        self.assertEqual(len(done), 1)
        self.assertIn("arrived", done[0].lower())

    def test_no_path_at_all_stops_with_a_clear_reason(self):
        runner, _ = make_runner(lambda i: DARK)
        with self.assertRaisesRegex(Interrupted, "No Nav-Ray path"):
            runner.walk()
        self.assertEqual(runner.backend.events[-1], ("key", "w", False))

    def test_a_black_frame_is_a_loading_screen(self):
        runner, _ = make_runner(lambda i: STAIRS if i < 4 else np.zeros((1125, 2000, 3), np.uint8))
        with self.assertRaisesRegex(Interrupted, "Loading screen"):
            runner.walk()

    def test_an_unchanging_view_with_a_path_is_stuck(self):
        runner, _ = make_runner(lambda i: STAIRS)
        with self.assertRaisesRegex(Interrupted, "Not moving"):
            runner.walk()

    def test_a_health_drop_stops_the_walk(self):
        runner, _ = make_runner(lambda i: STAIRS if i % 2 else HALL, health=(972, 972, 800))
        with self.assertRaisesRegex(Interrupted, "Health dropped"):
            runner.walk()
        self.assertEqual(runner.backend.events[-1], ("key", "w", False))

    def test_steering_step_is_proportional_and_clamped(self):
        self.assertEqual(navray_runner.steer_step(0.0), 0)
        self.assertEqual(navray_runner.steer_step(.01), 0)                       # inside the dead zone
        self.assertLess(navray_runner.steer_step(-.05), 0)
        self.assertEqual(navray_runner.steer_step(-.5), -navray_runner.MAX_STEP)
        self.assertEqual(navray_runner.steer_step(.5), navray_runner.MAX_STEP)
```

- [ ] **Step 2: Run to verify failure**

Run: `.\runtime\python.exe -m unittest tests.test_navray_runner -v`
Expected: ERROR `ModuleNotFoundError: No module named 'navray_runner'`.

- [ ] **Step 3: Implement** — `navray_runner.py`

```python
"""Nav-Ray auto-walk: pick a destination in the Nav-Ray window, press Start, then follow the
dashed path by steering the camera (relative mouse motion) while holding W.

All constants below are starting values to be tuned against live runs (mouse sensitivity, speed).
"""
import cv2
import re
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
        window = navray.find_navray(reader, self.detector.gray(self.frame()), checkpoint=self.guard)
        if window is None:
            raise Interrupted("Nav-Ray window not found. Press Tab, open Nav-Ray (F9) with its Small / Sector / World Map buttons visible, then Start.")
        return window

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
```

- [ ] **Step 4: Run to verify pass**

Run: `.\runtime\python.exe -m unittest tests.test_navray_runner -v`
Expected: 6 tests OK. Notes for debugging: the arrival test relies on 12 identical path frames (1.2 s) staying below the 3 s stuck limit; the health test alternates two different frames so "stuck" cannot fire first; `Reader` returns scripted health values once per `HEALTH_EVERY` seconds.

- [ ] **Step 5: Commit**

```powershell
git add navray_runner.py tests/test_navray_runner.py
git commit -m "Add Nav-Ray runner: select route, Start, steer along the path"
git push origin main
```

---

### Task 5: Profile, tab, dispatch, manifest

**Files:**
- Modify: `macro_core.py` (`default_profile` ~line 29; `validate_profile` ~lines 45-60 and ~143; `monitor_only_profile` ~line 189)
- Modify: `app.py` (tabs ~line 97-102 and ~193; profile apply ~line 595; `collect` ~line 621; runner dispatch ~line 750; `--check` ~line 866)
- Modify: `tools/build_portable.py:13` (manifest)
- Test: `tests/test_navray_ui.py`

- [ ] **Step 1: Write the failing test** — `tests/test_navray_ui.py`

```python
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from app import App
from macro_core import default_profile, load_profile, validate_profile


class NavRayProfileTests(unittest.TestCase):
    def test_default_profile_and_validation(self):
        profile = default_profile()
        self.assertEqual(profile["navray"], {"destination": ""})
        profile["operation"] = "navray"
        with self.assertRaises(ValueError):
            validate_profile(profile)                      # needs Category > Destination
        profile["navray"]["destination"] = "Faction HQs > Black Dragon"
        validate_profile(profile)
        profile["navray"]["destination"] = "x" * 200 + " > y"
        with self.assertRaises(ValueError):
            validate_profile(profile)

    def test_tab_collects_and_restores_the_destination(self):
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            root = tk.Tk();root.withdraw();app = App(root, profile_path=path, backend=NoInput())
            try:
                app.tabs.select(app.navray_tab)
                app.navray_destination.set("Faction HQs > Black Dragon")
                profile = app.collect()
                self.assertEqual(profile["operation"], "navray")
                self.assertEqual(profile["navray"]["destination"], "Faction HQs > Black Dragon")
            finally:
                app.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `.\runtime\python.exe -m unittest tests.test_navray_ui -v`
Expected: FAIL (`KeyError: 'navray'` / no `navray_tab`).

- [ ] **Step 3: Implement `macro_core.py`**

1. In `default_profile()`, after the `"recycling": {"recipe":None},` line add `"navray": {"destination": ""},`.
2. In `validate_profile`, change the operation tuple to `("tech_parts", "blueprints", "construction", "recycling", "navray")`, and right after the recycling-catalog check add:

```python
    navray_config = profile.get("navray", {"destination": ""})
    if (not isinstance(navray_config, dict) or not isinstance(navray_config.get("destination", ""), str)
            or len(navray_config.get("destination", "")) > 120):
        raise ValueError("Invalid Nav-Ray destination.")
```
3. In the `if require_ready:` block, before `if operation == "recycling":` add:

```python
        if operation == "navray":
            from navray import parse_destination
            parse_destination(navray_config.get("destination", ""))
            return profile
```
4. In `monitor_only_profile` add `profile.setdefault("navray", {"destination": ""})` next to the other `setdefault` lines.

- [ ] **Step 4: Implement `app.py`**

1. Tabs: after `self.recycling_tab = ttk.Frame(self.tabs)` add `self.navray_tab = ttk.Frame(self.tabs)`; after `self.tabs.add(self.recycling_tab, text="Recycling")` add `self.tabs.add(self.navray_tab, text="Nav-Ray")`; after `self.build_recycling_tab()` add `self.build_navray_tab()`.
2. New method (next to `build_recycling_tab`):

```python
    def build_navray_tab(self):
        host = ttk.Frame(self.navray_tab, padding=12);host.pack(fill="both", expand=True)
        host.columnconfigure(1, weight=1)
        ttk.Label(host, text="Destination").grid(row=0, column=0, sticky="w", pady=5)
        self.navray_destination = tk.StringVar()
        entry = ttk.Entry(host, textvariable=self.navray_destination, width=1)
        entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5);self.editable.append(entry)
        ttk.Label(host, text="Category > Destination. Open Nav-Ray first.").grid(row=1, column=1, sticky="w", padx=(10, 0))
```
3. Profile apply (the block that ends with `self.tabs.select(self.recycling_tab if operation=="recycling" ...`): before it add `self.navray_destination.set(self.profile.get("navray", {}).get("destination", ""))` and extend the select expression so `operation=="navray"` selects `self.navray_tab`.
4. `collect()`: add a branch before the recycling branch:

```python
            if self.tabs.select()==str(self.navray_tab):
                profile["operation"]="navray"
                profile["navray"]={"destination":self.navray_destination.get().strip()}
            elif self.tabs.select()==str(self.recycling_tab):
```
   (turn the existing `if self.tabs.select()==str(self.recycling_tab):` into the `elif`.)
5. Runner dispatch: add `from navray_runner import NavRayRunner` beside the other runner imports and `"navray":NavRayRunner` to the `runner_class` dict.
6. `--check`: add `elif profile["operation"]=="navray":` printing `Configuration valid: Nav-Ray walk to <destination>. No input sent.`

- [ ] **Step 5: Manifest** — in `tools/build_portable.py` line 13 add `"pathvision.py", "navray.py", "navray_runner.py",` after `"gogo.py",`.

- [ ] **Step 6: Run the new tests, then the whole suite**

Run: `.\runtime\python.exe -m unittest tests.test_navray_ui -v` — Expected: 2 tests OK.
Run: `.\runtime\python.exe -m unittest discover -s tests` — Expected: all pass (previously 221). Then `.\runtime\python.exe app.py --smoke-ui` — Expected: `UI smoke check passed. No game input sent.`

- [ ] **Step 7: Commit**

```powershell
git add macro_core.py app.py tools/build_portable.py tests/test_navray_ui.py
git commit -m "Add the Nav-Ray tab and profile"
git push origin main
```

---

### Task 6: Docs, and the live test the user must run

**Files:** Modify `TASKS.md`, `CLAUDE-HANDOFF.md`, `README.md` (one short paragraph each).

- [ ] **Step 1: Record status honestly** — in `TASKS.md` add a "Nav-Ray auto-walk — 27 Oct" section: items checked for pathvision/navray/runner/backend/tab (offline tests, count), and an unchecked item "Not verified live: Nav-Ray list selection (scroll step per wheel notch), Start, Tab to mouse-look, steering gain/direction, arrival, stuck and health detection." Mirror one paragraph in `CLAUDE-HANDOFF.md` ("Nav-Ray auto-walk") and README (usage: Tab, open Nav-Ray with F9, type `Category > Destination`, Start in 3 seconds; stop by switching away from the game).

- [ ] **Step 2: Commit and push**

```powershell
git add TASKS.md CLAUDE-HANDOFF.md README.md
git commit -m "Document the Nav-Ray auto-walk and what is unverified"
git push origin main
```

- [ ] **Step 3: Ask the user to run this live check, then read `macro.log` and `diagnostics\latest.png`**

1. In game: Tab, open Nav-Ray (F9), leave it visible. 2. Nav-Ray tab: `Faction HQs > Black Dragon`. Start in 3 seconds, hands off the mouse.
Expected log lines: choosing category, choosing destination, waiting for the route, walking the path, then either "path ended" or a named stop reason. Likely tuning needs, in order: mouse direction/gain (`GAIN`, `MAX_STEP`), list scroll step (`backend.scroll(-2)` in `choose`), whether Tab returns to mouse-look, false path detections in other areas (add exclusions in `pathvision._excluded` with a regression fixture from the real frame).

---

## Self-review

- **Spec coverage:** Nav-Ray selection (Tasks 3, 4), path detection (1), relative mouse + keys (2), walking loop and stop reasons (4: loading, no path, stuck, health, max duration, focus via `guard`, arrival), tab/profile (5), honesty/unverified list (6). Spec item "press Nav-Ray Stop on arrival" is deliberately not done (the default in the spec); "run/sprint key" is not implemented (unknown key), listed as a later tuning item.
- **Placeholders:** none; every code step contains code. Offsets and thresholds come from measured captures; tuning constants are named in `navray_runner.py`.
- **Consistency:** `PathView(points, aim, error)`, `find_path(frame_bgr, ignore)`, `NavRay.start_point/stop_point/row_point/wheel_point/list_box/window_box`, `read_rows(reader, gray, window, which)`, `find_row(rows, wanted)`, `parse_destination`, `steer_step`, `NavRayRunner.walk/choose/execute` are used with the same names in tests and code.
