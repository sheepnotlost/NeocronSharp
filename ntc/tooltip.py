"""Tooltip location, validation, stabilisation and OCR (SPEC 6.4)."""
import time

import cv2
import numpy as np

from . import ocr


BORDER = 221   # the tooltip box has a 1px border of exactly this gray (measured on the real game)


def find_tooltip(img, cx, cy):
    """Return (x, y, w, h) of the tooltip box whose horizontal span contains cx, or None.

    The tooltip is a black rectangle framed by a 1px gray border. Find long horizontal border
    lines, then pair a top line with a bottom line of the same span, 18-45 px apart.
    """
    x0, y0, x1, y1 = search_region(cx, cy, img.shape[1], img.shape[0])
    return find_in_crop(img[y0:y1, x0:x1], x0, y0, cx)


def search_region(cx, cy, screen_w, screen_h):
    return max(0, cx - 450), cy, min(screen_w, cx + 450), min(screen_h, cy + 100)


def find_in_crop(crop, x0, y0, cx):
    crop = crop.astype(np.int16)
    mask = (np.abs(crop - BORDER) <= 4).all(axis=2).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((1, 60), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    lines = [tuple(int(v) for v in stats[i][:4]) for i in range(1, n) if stats[i][3] <= 2]
    best = None
    for (lx, ly, lw, _lh) in lines:
        for (bx, by, bw, _bh) in lines:
            if abs(lx - bx) <= 2 and abs(lw - bw) <= 2 and 18 <= by - ly + 1 <= 45 \
                    and x0 + lx <= cx <= x0 + lx + lw:
                cand = (x0 + lx, y0 + ly, lw, by - ly + 1)
                if best is None or cand[2] * cand[3] > best[2] * best[3]:
                    best = cand
    return best


def box_crop(img, box, inset=2):
    """The text area of a tooltip box. Only the 1px border is removed at the bottom: letters with descenders
    (g, y, comma) reach right down to it, and trimming more turns "Dog Tag" into "Doa Taa"."""
    x, y, w, h = box
    return img[y + inset:y + h - 1, x + inset:x + w - inset]


def read_from_image(img, cx, cy):
    """Offline helper: tooltip text from one screenshot, or None."""
    box = find_tooltip(img, cx, cy)
    return ocr.read_tooltip_text(box_crop(img, box)) if box else None


def capture_live(cfg, grab_region, get_cursor, aborted=lambda: False, screen=(2560, 1440), timeout_ms=None):
    """Wait for a valid, stable tooltip under the current cursor. Returns the box crop (BGR) or None.

    The game hides the old tooltip as soon as the cursor moves, and the new one appears after
    ~120-190 ms, so a tooltip whose span contains the cursor x is the current one.
    """
    time.sleep(cfg["hover_settle_ms"] / 1000)
    deadline = time.time() + (timeout_ms or cfg["tooltip_timeout_ms"]) / 1000
    last, stable = None, 0
    while time.time() < deadline and not aborted():
        cx, cy = get_cursor()
        x0, y0, x1, y1 = search_region(cx, cy, *screen)
        region = grab_region(x0, y0, x1 - x0, y1 - y0)
        box = find_in_crop(region, x0, y0, cx)
        if box:
            crop = box_crop(region, (box[0] - x0, box[1] - y0, box[2], box[3]))
            if last is not None and last.shape == crop.shape and np.array_equal(last, crop):
                stable += 1
            else:
                stable = 1
            last = crop
            if stable >= cfg["tooltip_stable_frames"]:
                return crop
        else:
            last, stable = None, 0
        time.sleep(0.02)
    return None


def read_live(cfg, grab_region, get_cursor, aborted=lambda: False, screen=(2560, 1440)):
    crop = capture_live(cfg, grab_region, get_cursor, aborted, screen)
    return ocr.read_tooltip_text(crop) if crop is not None else None
