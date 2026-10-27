"""Scan orchestration: find windows, read every slot, scroll to the bottom, handle abort (SPEC 3, 7, 14)."""
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cv2
import numpy as np

from . import capture, detect, ocr, slots as slotmod, tooltip, winapi
from .models import CellRead, ScanResult

ABORT_DRIFT_PX = 20
TARGETS = {"all": None, "cabinet": "cabinet", "inventory": "inventory"}
SAME_VIEW = 2.0          # mean gray-level difference below which two screens of a window count as unchanged
MATCH_MAX = 14.0         # best row-shift match must be at least this good, or the scroll is "not understood"


def _row_sigs(img, win):
    """A small grayscale signature of every visible row of a window, for comparing two screenshots of it."""
    x0, qx, qy, R, C = int(round(win.x0)), win.qx, win.qy, win.rows, win.cols
    inset = 5
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    out = []
    for r in range(R):
        ya, yb = int(round(win.y0 + r * qy)) + inset, int(round(win.y0 + (r + 1) * qy)) - inset
        xa, xb = x0 + inset, int(round(win.x0 + C * qx)) - inset
        out.append(cv2.resize(g[ya:yb, xa:xb], (96, 8), interpolation=cv2.INTER_AREA).astype(np.float32))
    return out


def views_equal(prev, new, win):
    a, b = _row_sigs(prev, win), _row_sigs(new, win)
    return float(np.mean([np.abs(a[r] - b[r]).mean() for r in range(win.rows)])) < SAME_VIEW


def shift_rows(prev, new, win):
    """How many rows the content moved up between two screenshots of a window.
    0 = the view did not change (bottom reached, or nothing scrolled); -1 = could not match the two screens."""
    R = win.rows
    a, b = _row_sigs(prev, win), _row_sigs(new, win)
    if views_equal(prev, new, win):
        return 0
    best, best_k = None, -1
    for k in range(1, R):                       # prev rows k.. should equal new rows 0..R-k-1
        d = float(np.mean([np.abs(a[r + k] - b[r]).mean() for r in range(R - k)]))
        if best is None or d < best:
            best, best_k = d, k
    return best_k if best is not None and best <= MATCH_MAX else -1


class Scanner:
    def __init__(self, cfg, names, grab=capture.grab, move=winapi.move_to, get_cursor=winapi.get_cursor_pos,
                 foreground=winapi.foreground_title, focus=winapi.focus_window, grab_region=capture.grab_region,
                 wheel=winapi.wheel):
        self.cfg, self.names = cfg, names
        self.grab, self._move, self.get_cursor, self.foreground = grab, move, get_cursor, foreground
        self.focus, self.grab_region, self.wheel = focus, grab_region, wheel
        self.abort_event = threading.Event()
        self._placed = None

    # -- abort handling ----------------------------------------------------
    def request_abort(self):
        self.abort_event.set()

    def aborted(self):
        if self.abort_event.is_set():
            return True
        if self.cfg["game_window_title_contains"].lower() not in self.foreground().lower():
            self.abort_event.set()
        elif self._placed is not None:
            x, y = self.get_cursor()
            if math.hypot(x - self._placed[0], y - self._placed[1]) > ABORT_DRIFT_PX:
                self.abort_event.set()
        return self.abort_event.is_set()

    def move_to(self, x, y):
        self._move(x, y, self.cfg["mouse_mode"])
        self._placed = (x, y)

    # -- helpers -----------------------------------------------------------
    def _park_point(self, win, windows):
        """A spot on screen that is not over any item window, so no tooltip covers the slots."""
        H, W = self.grab_size
        cands = [(win.x0 - 70, win.y0 + win.rows * win.qy + 70), (W // 2, H - 60), (60, H - 60), (W - 60, H - 60)]
        for x, y in cands:
            x, y = int(min(max(x, 10), W - 10)), int(min(max(y, 10), H - 10))
            if not any(w.bounds[0] - 30 <= x <= w.bounds[0] + w.bounds[2] + 30 and
                       w.bounds[1] - 30 <= y <= w.bounds[1] + w.bounds[3] + 30 for w in windows):
                return x, y
        return 10, H - 10

    def _scroll(self, win, park, notches):
        """Wheel the window (negative = down, positive = up) and return a clean screenshot of the new view."""
        cx = int(win.x0 + (win.cols // 2) * win.qx + win.qx / 2)
        cy = int(win.y0 + (win.rows // 2) * win.qy + win.qy / 2)
        self.move_to(cx, cy)
        time.sleep(0.08)
        self.wheel(notches)
        time.sleep(self.cfg["scroll_settle_ms"] / 1000)
        self.move_to(*park)
        time.sleep(self.cfg["scroll_park_ms"] / 1000)
        return self.grab()

    # -- scan --------------------------------------------------------------
    def scan(self, targets="all", progress=lambda msg: None, items=None, *,
             activate_game=True, reset_abort=True, restore_cursor=True):
        """Scan the chosen windows (all of them by default). `items` is "all" or "techs" (default: config log_items).
        Returns one ScanResult per window found."""
        cfg = self.cfg
        self.techs_only = (items or cfg["log_items"]) == "techs"
        ocr.configure(cfg["tesseract_path"])
        ocr.require()
        if reset_abort:
            self.abort_event.clear()
        self._placed = None
        title = cfg["game_window_title_contains"]
        if activate_game:
            for _ in range(3):
                self.focus(title)
                time.sleep(0.4)
                if title.lower() in self.foreground().lower():
                    break
        if self.aborted():
            return [ScanResult(started_at=_now(), warnings=[
                "Game is not focused. Scan stopped; start again with Neocron focused."]) ]

        img = self.grab()
        self.grab_size = img.shape[:2]
        wanted = TARGETS.get(targets)
        windows = [w for w in detect.find_windows(img) if wanted is None or w.kind == wanted]
        if not windows:
            what = {"all": "No cabinet or inventory window", "cabinet": "No cabinet window",
                    "inventory": "No inventory window"}.get(targets, "No window")
            return [ScanResult(started_at=_now(), kind=wanted or "cabinet",
                               warnings=[f"{what} found - open it in the game first"])]
        windows.sort(key=lambda w: (w.kind != "cabinet", w.x0))        # cabinet first, then left to right

        start = self.get_cursor()
        results = []
        try:
            for win in windows:
                if self.aborted():
                    break
                results.append(self._scan_window(win, windows, progress))
        finally:
            if not restore_cursor:
                self.aborted()  # detect input/focus changes while pending OCR finished
            self._placed = None
            if restore_cursor:
                self._move(start[0], start[1], cfg["mouse_mode"])
            self.names.save()
        return results

    def _scan_window(self, win, windows, progress):
        cfg = self.cfg
        result = ScanResult(started_at=_now(), kind=win.kind)
        t0 = time.time()
        label = "cabinet" if win.kind == "cabinet" else "inventory"
        park = self._park_point(win, windows)
        self.move_to(*park)
        time.sleep(0.25)
        img = self.grab()
        for _ in range(cfg["max_scroll_frames"]):              # start from the top, whatever the scroll position was
            up = self._scroll(win, park, cfg["scroll_notches"] * 3)
            if views_equal(img, up, win) or self.aborted():
                img = up
                break
            img = up

        seen_rows, offset, prev = set(), 0, None
        pending = []                                  # (global row, col, qty future, name future) - OCR runs while the mouse moves on
        frames, warn, skipped = 0, None, 0
        with ThreadPoolExecutor(max_workers=2) as pool:
            while True:
                if prev is not None:
                    k = shift_rows(prev, img, win)
                    if k == 0:
                        break                         # the view did not change: bottom reached
                    if k < 0:
                        warn = "Lost track of the scrolling - the list may be incomplete"
                        break
                    offset += k
                frames += 1
                new_rows = [r for r in range(win.rows) if offset + r not in seen_rows]
                infos = [s for s in slotmod.analyze(img, win) if s.candidate and s.row in new_rows]
                if self.techs_only and infos:
                    # Read every label first (in the background pool): slots whose label is clearly not a tech
                    # part are never hovered.
                    labels = list(pool.map(lambda s: slotmod.read_label(img, s.rect), infos))
                    keep = [s for s, text in zip(infos, labels) if not slotmod.label_is_not_tech(text)]
                    skipped += len(infos) - len(keep)
                    infos = keep
                for i, s in enumerate(infos):
                    if self.aborted():
                        break
                    progress(f"{label}: screen {frames}, slot {i + 1} of {len(infos)}")
                    cx, cy = s.center
                    strong = s.letters >= 2          # one stray mark is not enough to call a slot an item
                    self.move_to(cx, cy)
                    crop = tooltip.capture_live(cfg, self.grab_region, self.get_cursor, self.aborted,
                                                screen=(self.grab_size[1], self.grab_size[0]),
                                                timeout_ms=None if strong else cfg["tooltip_probe_ms"])
                    if crop is None and strong and not self.aborted():
                        self.move_to(cx + 6, cy + 3)          # nudge once to retrigger the tooltip
                        crop = tooltip.capture_live(cfg, self.grab_region, self.get_cursor, self.aborted,
                                                    screen=(self.grab_size[1], self.grab_size[0]))
                    if self.abort_event.is_set():
                        break
                    if crop is None and not strong:
                        continue                              # no tooltip on a weak candidate: it was an empty slot
                    fut = pool.submit(ocr.read_tooltip_text, crop) if crop is not None else None
                    qfut = pool.submit(slotmod.read_qty, img, s.rect)      # the screenshot is never modified
                    pending.append((offset + s.row, s.col, qfut, fut))
                if self.abort_event.is_set():
                    break
                seen_rows.update(offset + r for r in range(win.rows))
                if frames >= cfg["max_scroll_frames"]:
                    warn = f"Stopped after {frames} screens - the list may be longer"
                    break
                self.move_to(*park)
                prev = img
                img = self._scroll(win, park, -cfg["scroll_notches"])
                if self.aborted():
                    break
            for grow, col, qfut, fut in pending:
                qty, qflags = qfut.result()
                raw = fut.result() if fut else None
                name, nflags = self.names.normalize(raw, techs_only=self.techs_only)
                if "SKIP" in nflags:
                    skipped += 1
                    continue
                result.cells.append(CellRead(grow, col, name, raw or "", qty, qflags + nflags))

        result.aborted = self.abort_event.is_set()
        result.duration_s = round(time.time() - t0, 1)
        result.recompute()
        if frames == 1 and not result.aborted:
            last_rows = [c for c in result.cells if c.row == win.rows - 1]
            if last_rows:
                result.warnings.append("This window did not scroll: items below the visible rows are not counted "
                                       "(or the mouse wheel is not supported here)")
        if warn:
            result.warnings.append(warn)
        if skipped:
            result.warnings.append(f"{skipped} other item(s) not logged (techs only)")
        if result.aborted:
            result.warnings.append("ABORTED - partial")
        uncertain = sum(1 for c in result.cells if {"QTY_UNCERTAIN", "NAME_UNREAD"} & set(c.flags))
        if uncertain:
            result.warnings.append(f"{uncertain} cells uncertain")
        new_names = len({c.name for c in result.cells if "NEW_NAME" in c.flags})
        if new_names:
            result.warnings.append(f"{new_names} new item names added to known_items.json")
        return result


def _now():
    return datetime.now().isoformat(timespec="seconds")
