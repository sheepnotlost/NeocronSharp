"""The in-game Nav-Ray window: locate it from its Small / Sector / World map buttons, read the
two lists with the local OCR, and give click points. All geometry scales with the UI scale, which
is taken from the spacing of the three buttons, so any window position and resolution works.

Offsets are measured on real captures (scale 1) from the top-left of the word "Small".
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

SPAN = 353.0                      # "Small" -> "World" word spacing
SECTOR_DX = 174.0                 # "Small" -> "Sector"
ROW_PITCH, ROW_H = 22.0, 15.0
LIST_ROWS = {"select": 8, "destination": 7}       # the Start/Stop buttons cover the Destination list's 8th row
LIST_WIDTH = {"select": 270.0, "destination": 440.0}
SELECT_DX, SELECT_DY = -133.0, -204.0       # first Select row's text top-left
DEST_DX, DEST_DY = 176.0, -209.0            # first Destination row's text top-left
START_DX, STOP_DX, BUTTON_DY = 312.0, 455.0, -54.0
WINDOW_LEFT, WINDOW_TOP, WINDOW_RIGHT, WINDOW_BOTTOM = -215.0, -305.0, 670.0, 55.0


CATALOG_PATH = Path(__file__).parent / "data" / "navray_destinations.json"


def load_catalog(profile=None):
    """{category: [destination, ...]}: the user's own scan (saved in the profile) first, else the shipped list."""
    mine = ((profile or {}).get("navray") or {}).get("catalog")
    if isinstance(mine, dict) and mine:
        return mine
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["categories"]
    except (OSError, ValueError, KeyError):
        return {}


def numbered(entries):
    """Entries with " #n" added to every label that occurs more than once, so each choice is unique.
    The game cuts long names short, so different destinations can look identical."""
    totals = {}
    for entry in entries:
        totals[entry] = totals.get(entry, 0) + 1
    seen, result = {}, []
    for entry in entries:
        if totals[entry] > 1:
            seen[entry] = seen.get(entry, 0) + 1
            result.append(f"{entry} #{seen[entry]}")
        else:
            result.append(entry)
    return result


def split_label(text):
    """"Plaza / Daton Hale ... #2" -> ("Plaza / Daton Hale ...", 2); no suffix = occurrence 1."""
    match = re.fullmatch(r"(.*\S) #(\d+)", text or "")
    return (match.group(1), int(match.group(2))) if match else (text, 1)


def row_shift(before, after, minimum_overlap=3):
    """How many rows a list moved between two reads (lists of row texts), or None when it cannot be told."""
    for shift in range(1, len(before)):
        overlap = len(before) - shift
        if overlap >= minimum_overlap and len(after) >= overlap and after[:overlap] == before[shift:]:
            return shift
    return None


def parse_destination(text):
    """"Faction HQs > Black Dragon" -> ("Faction HQs", "Black Dragon"). Raises ValueError."""
    parts = [part.strip() for part in (text or "").split(">")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("Nav-Ray: choose a category and a destination (or tick Read lists to fill them from the game).")
    return parts[0], parts[1]


def clean_label(text):
    """List text as shown: collapsed spaces, and the game's cut-off marker ("..." read as "." or ". .") as an ellipsis."""
    text = " ".join((text or "").split())
    return re.sub(r"\s*[.…]+(\s*[.…]+)*$", "…", text)


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def find_row(rows, wanted):
    """Row number whose text is `wanted` (a trailing "..." means the game cut the label short).

    Letters and digits only are compared. No near-match is allowed: names such as "Enter A" and
    "Enter C" differ by one character and mean different places.
    """
    target = _norm(wanted)
    for row, text in rows:
        seen = _norm(text)
        if not seen:
            continue
        # The game cuts long labels with "..."; the OCR may read that as a single dot.
        if seen == target or (len(seen) >= 8 and re.search(r"[.…]\s*$", text) and target.startswith(seen)):
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
        right, bottom = self._at(dx + LIST_WIDTH[which], dy + ROW_PITCH*LIST_ROWS[which] + 5)
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


def tidy(text):
    """Tesseract's reading of a row without its typical edge junk (highlight bar read as a letter, trailing marks)."""
    text = " ".join((text or "").split())
    text = re.sub(r"^[|!\[\]l]+(?=[A-Z])", "", text)
    if ")" in text:
        text = text[:text.rindex(")") + 1]
    return re.sub(r"[\s|=~_,;:!¦]+$", "", text)


def read_row(row_gray):
    """Text of one list row, or "" for an empty row. The selected row is dark text on a bright bar."""
    bright = float((row_gray > 120).mean())
    if bright < .04:
        return ""
    import cv2
    import pytesseract
    from ntc import ocr
    ocr.configure("")
    image = row_gray if bright > .5 else 255 - row_gray      # Tesseract wants dark text on light
    big = cv2.resize(image, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=int(big.max()))
    return tidy(pytesseract.image_to_string(big, config="--psm 7"))


def read_rows(gray, window, which):
    """[(row, text)] of the non-empty visible entries of the "select" or "destination" list."""
    left, top, right, bottom = window.list_box(which)
    scale = window.scale
    rows = []
    for row in range(LIST_ROWS[which]):
        y0 = top + round((5 + ROW_PITCH*row - 1)*scale)
        y1 = min(bottom, top + round((5 + ROW_PITCH*row + ROW_H + 1)*scale))
        crop = gray[max(0, y0):y1, left:right]
        text = read_row(crop) if crop.size else ""
        if text:
            rows.append((row, text))
    return rows
