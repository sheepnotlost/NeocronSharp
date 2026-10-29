"""navray_debug: marked frames, the black box and the overlay. No game input; the overlay is only ever shown at
alpha 0, click-through and without activation."""

import json
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest

import cv2
import numpy as np

import navray_debug as nd

W, H = 2560, 1440


def busy_info(hue=71, width=W, height=H):
    """Marks everywhere, including inside every protected area, so clipping is exercised."""
    grid = [(x*width/16, y*height/12) for x in range(17) for y in range(13)]
    return {"candidates": [(x, y, 40.0, 0.3) for x, y in grid], "points": grid[::3], "route": grid[::5],
            "aim": (width*.5, height*.535), "corner": (width*.1, height*.1), "error": -.042,
            "state": "pushing to zone line", "hue": hue, "time": 12.5}


def scene(width=W, height=H, seed=1, grain=12):
    """A game-like frame: smooth gradients with mild noise (compresses like the game, unlike pure noise)."""
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    base = np.stack(np.broadcast_arrays(x, y, (x + y)/4 + 64), -1)
    noise = rng.integers(-grain, grain + 1, (height, width, 3), dtype=np.int16)
    return np.clip(base + noise, 0, 255).astype(np.uint8)


class AnnotateTests(unittest.TestCase):
    def test_protected_hud_areas_are_untouched_and_the_input_is_not_changed(self):
        frame = np.random.default_rng(3).integers(0, 255, (H, W, 3), dtype=np.uint8)
        before = frame.copy()
        out = nd.annotate(frame, busy_info())
        self.assertTrue(np.array_equal(frame, before))
        changed = np.any(out != frame, axis=2)
        self.assertGreater(changed.sum(), 1000)
        for x0, y0, x1, y1 in nd.protected_boxes(W, H):
            self.assertFalse(changed[y0:y1, x0:x1].any(), (x0, y0, x1, y1))
        x0, y0, x1, y1 = (round(v*s) for v, s in zip(nd.BANNER, (W, H, W, H)))
        self.assertTrue(changed[y0:y1, x0:x1].any())             # the state line is drawn near the top centre
        self.assertGreaterEqual(nd.BANNER[1], .06)

    def test_no_drawn_colour_lies_near_the_dash_hue(self):
        frame = np.full((720, 1280, 3), 128, np.uint8)
        for hue in (0, 15, 30, 60, 71, 90, 115, 135, 151, 170, 179, "green", "red", None):
            with self.subTest(hue=hue):
                out = nd.annotate(frame, busy_info(hue, W, H) | {"size": (W, H)})
                hsv = cv2.cvtColor(out, cv2.COLOR_RGB2HSV)
                drawn = np.any(out != frame, axis=2) & (hsv[..., 1] >= 40)   # coloured pixels (white/black have no hue)
                self.assertGreater(drawn.sum(), 100)
                dash = nd._hue(hue)
                d = np.abs(hsv[..., 0][drawn].astype(int) - dash) % 180
                self.assertGreaterEqual(int(np.minimum(d, 180 - d).min()), 25)

    def test_coordinates_follow_the_frame_size(self):
        small = np.zeros((720, 1280, 3), np.uint8)
        out = nd.annotate(small, {"aim": (1600, 600), "size": (W, H), "hue": 71})
        self.assertTrue(out[300, 800].any())                     # the crosshair centre at half scale

    def test_view_info_reads_a_path_view(self):
        class View:
            points = ((1280, 1000), (1290, 900))
            route = ((1280, 1000), (1290, 900), (1500, 850), (1700, 840))
            aim = (1290, 900)
            corner = 1
        info = nd.view_info(View(), (H, W, 3), "walking", 71, candidates=[(1, 2, 3, 4)], error=.01)
        self.assertEqual(info["corner"], (1290, 900))
        self.assertEqual(info["candidates"], [(1, 2)])
        self.assertEqual(info["size"], (W, H))
        self.assertEqual(nd.view_info(None, (H, W, 3), "searching left", 71)["state"], "searching left")


class BlackBoxTests(unittest.TestCase):
    def test_frame_rate_is_held_to_three_a_second(self):
        box = nd.BlackBox(seconds=60, fps=3)
        frame = np.zeros((360, 640, 3), np.uint8)
        kept = [t/60 for t in range(600) if box.add(frame, {"state": "walking"}, now=t/60)]   # 60 fps for 10 s
        self.assertLessEqual(len(kept), 31)
        self.assertGreaterEqual(len(kept), 29)
        self.assertGreaterEqual(min(b - a for a, b in zip(kept, kept[1:])), 1/3 - 1e-5)

    def test_memory_and_length_stay_bounded(self):
        rng = np.random.default_rng(5)
        noisy = [rng.integers(0, 255, (H, W, 3), dtype=np.uint8) for _ in range(2)]   # worst case for JPEG
        box = nd.BlackBox(seconds=60, fps=3, max_bytes=8 << 20, max_keys=4, max_events=100)
        for n in range(40):                                      # a new state every frame
            box.add(noisy[n % 2], {"state": f"s{n}"}, now=n/3)
        for n in range(300):
            box.event("status", f"line {n}", now=n/3)
        self.assertLessEqual(len(box), 60*3 + 1)
        self.assertLessEqual(box.jpeg_bytes, 8 << 20)
        self.assertLessEqual(box.nbytes, (8 << 20) + 4*noisy[0].nbytes)
        self.assertEqual(len(box.events), 100)
        gentle = nd.BlackBox(seconds=60, fps=3)
        frame = scene(640, 360)                                  # the time window does not depend on the size
        for n in range(400):
            gentle.add(frame, {"state": "walking"}, now=n/3)
        self.assertEqual(len(gentle), 181)                       # the time window, not the byte cap, decides here
        self.assertTrue(all(399/3 - t <= 60.0 + 1e-6 for t, *_ in gentle.frames))

    def test_add_is_cheap_for_a_2560_frame(self):
        box = nd.BlackBox()
        frames = [scene(seed=s) for s in range(3)]
        box.add(frames[0], {"state": "walking"}, now=0)
        spent = []
        for n in range(1, 25):
            info = busy_info() | {"state": "walking" if n % 8 else "turning"}
            start = time.perf_counter()
            self.assertTrue(box.add(frames[n % 3], info, now=n))
            spent.append(time.perf_counter() - start)
        median = statistics.median(spent)
        print(f"\nBlackBox.add 2560x1440: median {median*1000:.1f} ms, max {max(spent)*1000:.1f} ms", file=sys.stderr)
        self.assertLess(median, .040)                            # aim ~15 ms; generous for a loaded test machine

    def test_save_writes_a_readable_video_events_and_key_frames(self):
        box = nd.BlackBox()
        frame = scene(grain=2)                                   # heavy grain makes each key PNG take seconds
        states = ["walking"]*4 + ["turning"]*3 + ["walking"]*5
        for n, state in enumerate(states):
            box.add(frame, busy_info() | {"state": state, "time": None}, now=10 + n/3)
            box.add(frame, {"state": state}, now=10 + n/3 + .1)         # dropped: too soon
        for n in range(7):
            box.event("status", f"Nav-Ray: line {n}", now=10 + n)
        with tempfile.TemporaryDirectory() as temp:
            folder = box.save(Path(temp) / "run")
            self.assertTrue(folder.is_dir())
            video = cv2.VideoCapture(str(folder / "video.mp4"))
            self.assertTrue(video.isOpened())
            count = 0
            while True:
                ok, picture = video.read()
                if not ok:
                    break
                count += 1
                self.assertEqual(picture.shape[:2], (720, 1280))
            video.release()
            self.assertEqual(count, len(states))
            lines = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["text"] for e in lines], [f"Nav-Ray: line {n}" for n in range(7)])
            self.assertEqual(lines[0]["t"], 0.0)
            self.assertEqual(len((folder / "frames.jsonl").read_text(encoding="utf-8").splitlines()), len(states))
            keys = sorted(p.name for p in folder.glob("key_*.png") if "_marked" not in p.name)
            # first, turning, walking (two state changes), last
            self.assertEqual(keys, ["key_01_first.png", "key_02_turning.png", "key_03_walking.png", "key_04_last.png"])
            full = cv2.imread(str(folder / keys[0]))
            self.assertEqual(full.shape[:2], (H, W))
            self.assertTrue(np.array_equal(cv2.cvtColor(full, cv2.COLOR_BGR2RGB), frame))
            self.assertEqual(cv2.imread(str(folder / "key_02_turning_marked.jpg")).shape[:2], (H, W))


@unittest.skipUnless(sys.platform == "win32", "Windows overlay")
class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()                                     # never shown; the overlay is its own toplevel
        self.user = nd.user32()
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetActiveWindow.restype = wintypes.HWND
        self.overlays = []

    def tearDown(self):
        for overlay in self.overlays:
            overlay.close()
        self.root.destroy()

    def overlay(self, **kwargs):
        overlay = nd.Overlay(self.root, rect=(0, 0, 640, 360), alpha=0.0, **kwargs)   # alpha 0: never visible
        self.overlays.append(overlay)
        return overlay

    def test_style_is_click_through_never_activating_and_excluded_from_capture(self):
        calls, notes = [], []

        def affinity(hwnd, mode):
            calls.append((hwnd, mode))
            return nd.set_affinity(hwnd, mode)
        foreground = self.user.GetForegroundWindow()
        overlay = self.overlay(affinity=affinity, report=notes.append)
        overlay.show()
        self.root.update()
        self.assertTrue(overlay.hwnd)
        style = self.user.GetWindowLongW(overlay.hwnd, nd.GWL_EXSTYLE)
        for bit in (nd.WS_EX_LAYERED, nd.WS_EX_TRANSPARENT, nd.WS_EX_NOACTIVATE, nd.WS_EX_TOOLWINDOW, nd.WS_EX_TOPMOST):
            self.assertTrue(style & bit, hex(bit))
        self.assertEqual(calls, [(overlay.hwnd, nd.WDA_EXCLUDEFROMCAPTURE)])
        self.assertEqual(self.user.GetForegroundWindow(), foreground)
        self.assertNotEqual(self.user.GetActiveWindow(), overlay.hwnd)
        self.assertEqual(overlay.top.attributes("-transparentcolor"), nd.KEY_COLOR)
        self.assertTrue(overlay.top.overrideredirect())
        if sys.getwindowsversion().build >= 19041:               # WDA_EXCLUDEFROMCAPTURE: Windows 10 2004+
            got = self.wintypes.DWORD()
            self.assertTrue(self.user.GetWindowDisplayAffinity(overlay.hwnd, self.ctypes.byref(got)))
            self.assertEqual(got.value, nd.WDA_EXCLUDEFROMCAPTURE)
            self.assertTrue(overlay.excluded)
            self.assertEqual(notes, [])

    def test_a_refused_affinity_is_reported_and_only_the_state_line_is_drawn(self):
        notes = []
        overlay = self.overlay(affinity=lambda hwnd, mode: False, report=notes.append)
        self.assertFalse(overlay.excluded)
        self.assertEqual(len(notes), 1)
        overlay.post(busy_info(width=640, height=360) | {"size": (640, 360)})
        self.assertTrue(overlay.pump())
        self.assertEqual(overlay.canvas.find_withtag("mark"), ())
        self.assertTrue(overlay.canvas.find_withtag("state"))

    def test_post_from_another_thread_and_pump_on_the_tk_thread(self):
        overlay = self.overlay(affinity=lambda hwnd, mode: True)
        self.assertFalse(overlay.pump())                         # nothing posted yet

        def worker():
            for n in range(100):
                overlay.post(busy_info(width=640, height=360) | {"size": (640, 360), "state": f"step {n}"},
                             rect=(10, 20, 640, 360) if n == 99 else None)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertTrue(overlay.pump())
        self.assertFalse(overlay.pump())                         # drained: only the newest drawing was made
        canvas = overlay.canvas
        self.assertIn("step 99", canvas.itemcget(canvas.find_withtag("state")[0], "text"))
        self.assertTrue(canvas.find_withtag("mark"))
        self.assertEqual(overlay.rect, (10, 20, 640, 360))
        # The protected areas are covered in the transparent colour, on top of everything.
        masks = canvas.find_withtag("mask")
        self.assertEqual(len(masks), len(nd.PROTECTED))
        self.assertEqual(canvas.find_all()[-len(masks):], masks)
        self.assertTrue(all(canvas.itemcget(m, "fill") == nd.KEY_COLOR for m in masks))


if __name__ == "__main__":
    unittest.main()
