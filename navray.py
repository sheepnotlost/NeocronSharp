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
