"""Reading the slots of a detected window: which are filled, and each stack number (SPEC 14.3).

Everything here works for any HUD color: text is found by the black drop shadow every theme draws under it, and
a slot counts as a candidate if it shows letter-shaped blobs in its label corner or is visually busy. The hover
(tooltip) then confirms each candidate, because an empty slot shows no tooltip.
"""
import re
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract

LABEL_ROI = (3, 3, 64, 30)     # where every item shows its short label (COMP, HULL, ATP...), slot-relative
QTY_ROI = (2, 38, 44, 32)      # bottom-left stack number "x14"; tall enough for a few px of misalignment
QTY_ROI_NARROW = (2, 38, 28, 32)   # one-digit counts only: keeps clear of an icon that reaches toward the text
TECH_LABELS = ("COMP", "HULL", "ATP", "CORE", "FRAM", "TECH")    # the short labels of tech parts
NOT_TECH_DISTANCE = 3          # a label this far (edit distance) from every tech label is not a tech
KNOWN_NON_TECH = ("ULT",)      # labels seen on items that are no tech (too close to HULL for the distance rule)
ACTIVITY_MIN = 0.18
TEXT_FRAC = 0.35               # a pixel is text if it is this close (relative to text-bg distance) to the text color


@dataclass
class SlotInfo:
    row: int
    col: int
    rect: tuple            # x, y, w, h on screen
    letters: int
    activity: float
    candidate: bool

    @property
    def center(self):
        x, y, w, h = self.rect
        return x + w // 2, y + h // 2


def _crop(img, rect, roi):
    x, y, w, h = rect
    rx, ry, rw, rh = roi
    return img[y + ry:y + ry + rh, x + rx:x + rx + rw]


def count_letters(img, rect):
    """Letter-shaped blobs in the label corner (6-22 px tall, not touching the edges, so wall stripes don't count)."""
    g = cv2.cvtColor(_crop(img, rect, LABEL_ROI), cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.GaussianBlur(g, (0, 0), 5)
    mask = ((g - b) > np.maximum(10, 0.15 * b)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(mask)
    h_roi = g.shape[0]
    cnt = 0
    for i in range(1, n):
        cx, cy, cw, ch, a = st[i]
        if 6 <= ch <= 22 and 2 <= cw <= 18 and a >= 8 and cy > 0 and cy + ch < h_roi:
            cnt += 1
    return cnt


def activity(img, rect, inset=6):
    x, y, w, h = rect
    g = cv2.cvtColor(img[y + inset:y + h - inset, x + inset:x + w - inset], cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 1.5)
    return float(g.std() / max(g.mean(), 8))


def analyze(img, win):
    """All slots of a window with their candidate flag."""
    out = []
    for r in range(win.rows):
        for c in range(win.cols):
            rect = win.slot_rect(r, c)
            if rect[0] < 0 or rect[1] < 0 or rect[0] + rect[2] > img.shape[1] or rect[1] + rect[3] > img.shape[0]:
                continue
            letters, act = count_letters(img, rect), activity(img, rect)
            out.append(SlotInfo(r, c, rect, letters, act, letters >= 1 or act >= ACTIVITY_MIN))
    return out


def text_color(slot):
    """Text is drawn with a black drop shadow: the pixels just up-left of shadow pixels are the text."""
    x, y, w, h = LABEL_ROI
    crop = slot[y:y + h, x:x + w].astype(np.float32)
    lum = crop.mean(axis=2)
    bg = np.median(crop.reshape(-1, 3), axis=0)
    shadow = lum < 18
    cand = np.zeros_like(shadow)
    cand[:-1, :-1] = shadow[1:, 1:] & ~shadow[:-1, :-1]
    cand &= np.linalg.norm(crop - bg, axis=2) > 45
    if cand.sum() >= 8:
        return np.median(crop[cand], axis=0)
    flat = crop.reshape(-1, 3)
    k = max(int(len(flat) * 0.04), 6)
    return np.median(flat[np.argsort(flat.mean(axis=1))[-k:]], axis=0)


def _ocr_qty(slot, roi):
    x, y, w, h = roi
    crop = slot[y:y + h, x:x + w].astype(np.float32)
    col = text_color(slot)
    bg = np.median(crop.reshape(-1, 3), axis=0)
    contrast = float(np.linalg.norm(col - bg))
    if contrast < 25:
        return ""
    d = np.linalg.norm(crop - col, axis=2)
    mask = (d < TEXT_FRAC * contrast).astype(np.uint8) * 255      # closer to the text color than to the background
    if mask.sum() / 255 < 12:
        return ""
    mask = cv2.dilate(mask, np.ones((2, 2), np.uint8))
    big = cv2.resize(255 - mask, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 14, 14, 14, 14, cv2.BORDER_CONSTANT, value=255)
    return pytesseract.image_to_string(big, config="--psm 7 -c tessedit_char_whitelist=x0123456789").strip()


def parse_qty(text):
    m = re.search(r"x\s*(\d{1,3})(?!\d)", text)
    return int(m[1]) if m else None


def read_qty(img, rect):
    """Stack number of a slot as (qty, flags). No visible number means a single item."""
    x, y, w, h = rect
    slot = img[y:y + h, x:x + w]
    for roi in (QTY_ROI, QTY_ROI_NARROW):
        q = parse_qty(_ocr_qty(slot, roi))
        if q is not None:
            return q, []
    return 1, []


def read_label(img, rect):
    """The short label of a slot (COMP, HULL, ULT...) as letters, "" if there is none or it cannot be read."""
    x, y, w, h = rect
    slot = img[y:y + h, x:x + w]
    rx, ry, rw, rh = LABEL_ROI
    crop = slot[ry:ry + rh, rx:rx + rw].astype(np.float32)
    col = text_color(slot)
    bg = np.median(crop.reshape(-1, 3), axis=0)
    contrast = float(np.linalg.norm(col - bg))
    if contrast < 25:
        return ""
    mask = (np.linalg.norm(crop - col, axis=2) < TEXT_FRAC * contrast).astype(np.uint8) * 255
    big = cv2.resize(255 - mask, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    return pytesseract.image_to_string(
        big, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ").strip()


def _distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def tech_distance(text):
    return min(_distance(text.upper(), t) for t in TECH_LABELS)


def label_is_not_tech(text):
    """True only when the label is clearly not a tech: a known non-tech label, or at least 3 letters and far from every tech label. Short, empty or near-miss reads (AIP, LUMP,
    HRAM...) return False, so the slot is hovered after all."""
    text = (text or "").strip().upper()
    if not text.isalpha():                       # empty, or letters split by gaps ("L C"): a garbled read
        return False
    if text in KNOWN_NON_TECH:
        return True
    return len(text) >= 3 and tech_distance(text) >= NOT_TECH_DISTANCE
