"""GoGuardian (GoGo) window: find it, read its stacks, plan 15-at-a-time refills.

The window is recognised from its bottom button strip ("Take All  Sort  Stack"), read
with the local Windows OCR. Cell labels (three-letter ingredient codes and xN counts) are
read the same way, so no GoGo artwork has to be captured and any UI scale works: the
scale comes from the spacing of the button words, and every other position follows from it.
"""

import re
from dataclasses import dataclass

import cv2
import numpy as np

# Measured on a real capture at its own scale (taken as 1.0): the "Take" word's left edge,
# the "Stack" word's left edge, cell pitch, and the first cell's offset from "Take".
STACK_DX = 128.0
CELL_W, CELL_H = 93.5, 46.3
FIRST_CELL_FROM_TAKE = (-37.0, -472.0)
COLUMNS, ROWS = 5, 9
BATCH = 15
MAX_HOVERS = 20

# Ingredient label codes shown on stacks, per built-in recipe (exactly as the game prints them).
INGREDIENT_CODES = {
    "weaponpart_7": {"Trisol": "TRS", "Metal D": "MET", "Arillium": "ARI", "Solantium": "SOL"},
    "weaponpart_9": {"Gamonin": "GAM", "Metal D": "MET", "Solantium": "SOL", "Strastin": "STS", "Tiberal": "TIB"},
    # Finished parts are labelled W<number> (W6, W7, W9, W10 seen on real stacks).
    "holy_heal": {f"Tangent Weaponpart {n}": f"W{n}" for n in (9, 7, 6, 5, 4, 1)},
}


def default_code(name):
    """Best guess at the label the game prints on an ingredient's stack.

    Known ingredients first; finished Weaponparts show as W<number>; otherwise the first
    three letters (right for most). Wrong guesses are fixed in the Materials row.
    """
    for codes in INGREDIENT_CODES.values():
        if name in codes:
            return codes[name]
    match = re.fullmatch(r"Tangent Weaponpart (\d+)", name.strip())
    if match:
        return "W" + match.group(1)
    letters = re.sub(r"[^A-Za-z]", "", name).upper()
    return letters[:3] if len(letters) >= 2 else "XXX"


def materials_from_parts(parts):
    """[{quantity, name}] from the catalog -> {name: default label}."""
    return {part["name"]: default_code(part["name"]) for part in parts or []}


@dataclass(frozen=True)
class GoGo:
    take_x: int
    take_y: int
    scale: float

    def cell_origin(self, col, row):
        return (self.take_x + FIRST_CELL_FROM_TAKE[0]*self.scale + col*CELL_W*self.scale,
                self.take_y + FIRST_CELL_FROM_TAKE[1]*self.scale + row*CELL_H*self.scale)

    def cell_center(self, col, row):
        x, y = self.cell_origin(col, row)
        return (round(x + CELL_W*self.scale/2), round(y + CELL_H*self.scale/2))

    def box(self):
        """The whole window in game-view pixels, title bar to button strip, for resting the pointer clear of it."""
        left, top = self.cell_origin(0, 0)
        right, _ = self.cell_origin(COLUMNS, 0)
        s = self.scale
        return (round(left - 20*s), round(top - 40*s), round(right + 56*s), round(self.take_y + 30*s))

    def grid_box(self, frame_shape):
        left, top = self.cell_origin(0, 0)
        right, bottom = self.cell_origin(COLUMNS, ROWS)
        return (max(0, int(left)-2), max(0, int(top)-2), min(frame_shape[1], int(right)+2), min(frame_shape[0], int(bottom)+2))


def ingredients_for(recipe_key, profile=None):
    """{ingredient: label code} for the recipe: the user's own list (saved in the profile)
    first, then the built-in table. None when neither knows the recipe."""
    mine = ((profile or {}).get("materials") or {}).get(recipe_key)
    return dict(mine) if mine else INGREDIENT_CODES.get(recipe_key)


def parse_materials(text):
    """"Gamonin=GAM, Metal D=MET" -> {"Gamonin": "GAM", "Metal D": "MET"}. Raises ValueError."""
    result = {}
    for part in re.split(r"[,;\n]", text or ""):
        part = part.strip()
        if not part:
            continue
        name, sep, code = part.partition("=")
        name, code = name.strip(), code.strip().upper()
        if not sep or not name or len(name) > 60 or not re.fullmatch(r"[A-Z0-9]{2,4}", code):
            raise ValueError(f"Materials: use Name=LABEL (2-4 letters/digits), separated by commas. Problem with '{part}'.")
        result[name] = code
    if len(result) > 12:
        raise ValueError("Materials: at most 12 ingredients per recipe.")
    return result


def format_materials(materials):
    return ", ".join(f"{name}={code}" for name, code in (materials or {}).items())


def find_gogo(reader, gray, tiles=((0, 0), (1, 0), (0, 1), (1, 1)), checkpoint=lambda: None):
    """Locate the button strip anywhere in a grayscale frame. Returns GoGo or None."""
    height, width = gray.shape[:2]
    tile_w, tile_h = width//2 + width//8, height//2 + height//8
    for tx, ty in tiles:
        checkpoint()
        left = 0 if tx == 0 else width - tile_w
        top = 0 if ty == 0 else height - tile_h
        words = reader.read_words(gray[top:top+tile_h, left:left+tile_w])
        found = _strip_in(words)
        if found:
            return GoGo(found[0]+left, found[1]+top, found[2])
    return None


def _strip_in(words):
    """Take / All / Sort / Stack on one line, spaced like the reference strip."""
    by_text = {}
    for text, x, y, w, h in words:
        by_text.setdefault(text.lower(), []).append((x, y, w, h))
    for tx, ty, tw, th in by_text.get("take", ()):
        for sx, sy, sw, sh in by_text.get("stack", ()):
            scale = (sx - tx) / STACK_DX
            if not .35 <= scale <= 3.5 or abs(sy - ty) > 4*scale:
                continue
            if any(abs(ax - (tx + 38*scale)) < 8*scale and abs(ay - ty) < 4*scale for ax, ay, _, _ in by_text.get("all", ())) \
                    and any(abs(ox - (tx + 79*scale)) < 8*scale and abs(oy - ty) < 4*scale for ox, oy, _, _ in by_text.get("sort", ())):
                return (tx, ty, scale)
    return None


def _close(word, code):
    """Same three letters, allowing one misread character (OCR on small game text)."""
    word = word.upper()
    if len(word) != len(code) or len(code) < 2:
        return False
    return word == code or (len(code) >= 3 and sum(a != b for a, b in zip(word, code)) <= 1)


def read_cells(reader, gray, gogo, wanted=None):
    """{(col,row): {"code","count","point"}} for stacks whose label could be read.

    `wanted` (label codes the recipe needs): any still missing after the whole-grid read
    are looked for cell by cell at a larger upscale, which reads small labels better.
    """
    left, top, right, bottom = gogo.grid_box(gray.shape)
    words = reader.read_words(gray[top:bottom, left:right])
    cells = {}
    for text, x, y, w, h in words:
        gx, gy = x + left, y + top
        ox, oy = gogo.cell_origin(0, 0)
        col = int((gx - ox) // (CELL_W*gogo.scale))
        row = int((gy - oy) // (CELL_H*gogo.scale))
        if not (0 <= col < COLUMNS and 0 <= row < ROWS):
            continue
        cell = cells.setdefault((col, row), {"code": None, "count": None, "point": gogo.cell_center(col, row), "words": []})
        cell["words"].append((text, gx, gy))
    result = {}
    for key, cell in cells.items():
        code = count = None
        # Reading order: rows of text by height, left to right within a row.
        words_in = sorted(cell["words"], key=lambda item: (round(item[2]/8), item[1]))
        for text, _, _ in words_in:
            clean = text.strip()
            if (re.fullmatch(r"[A-Za-z0-9]{2,4}", clean) and code is None and not re.fullmatch(r"x\d*", clean, re.I)
                    and not clean.isdigit()):
                code = clean.upper()
        match = re.search(r"x\s*(\d+)", " ".join(item[0] for item in words_in), re.I)
        if match:
            count = int(match.group(1))
        if code:
            result[key] = {"code": code, "count": count, "point": cell["point"]}
    missing = set(wanted or ()) - {info["code"] for info in result.values()}
    if missing:
        for col in range(COLUMNS):
            for row in range(ROWS):
                if (col, row) in result or not missing:
                    continue
                ox, oy = gogo.cell_origin(col, row)
                crop = gray[max(0, int(oy)):int(oy + CELL_H*gogo.scale), max(0, int(ox)):int(ox + CELL_W*gogo.scale)]
                if crop.size == 0:
                    continue
                for text, _, _, _, _ in reader.read_words(crop, up=4):
                    hit = next((code for code in missing if _close(text.strip(), code)), None)
                    if hit:
                        result[(col, row)] = {"code": hit, "count": None, "point": gogo.cell_center(col, row)}
                        missing.discard(hit)
                        break
    return result


def plan_refill(recipe_key, cells, codes=None):
    """[(ingredient, code, cell_point, amount)] moving at most BATCH of each needed ingredient.

    Ingredients the GoGo does not hold are skipped; raises LookupError when it holds none.
    """
    codes = codes if codes is not None else ingredients_for(recipe_key)
    if codes is None:
        raise LookupError("This recipe's material labels are not known, so GoGuardian refills are unavailable for it.")
    by_code = {}
    for info in cells.values():
        by_code.setdefault(info["code"], info)
    plan = []
    absent = [name for name, code in codes.items() if code not in by_code]
    if absent:
        seen = ", ".join(sorted(by_code)) or "none"
        raise LookupError("GoGuardian: could not find " + ", ".join(f"{name} ({codes[name]})" for name in absent)
                          + f". Labels seen: {seen}. Nothing was moved.")
    for name, code in codes.items():
        info = by_code[code]
        # Stack counts are often too small for the OCR to read. The quantity dialog
        # opens at the full stack, so the runner caps the amount there; here BATCH
        # is only the upper limit.
        amount = min(BATCH, info["count"]) if info["count"] else BATCH
        plan.append((name, code, info["point"], amount))
    return plan


# Inventory grid, in its window's units (as construction_runner places drops).
INVENTORY_CELL = (39, 63, 44.6, 45.5)
INVENTORY_COLUMNS, INVENTORY_ROWS = 8, 6
EMPTY_CONTRAST = 18      # a cell's grey spread: empty 5-14 (another window showing through), items 23 and up


def text_mask(rgb):
    """The UI's light-green label text alone, white on black: item art (grey, teal, red, yellow) drops out."""
    c = rgb.astype(np.int16)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    return (((g - r > 40) & (g - b > 30) & (g > 140)) * 255).astype(np.uint8)


def inventory_cell(frame, inventory, col, row):
    """The RGB pixels of one Inventory cell."""
    ox, oy, cw, ch = INVENTORY_CELL
    x, y = inventory.point(ox + col*cw, oy + row*ch)
    return frame[max(0, y):y + round(ch*inventory.scale), max(0, x):x + round(cw*inventory.scale)]


def inventory_point(inventory, col, row):
    ox, oy, cw, ch = INVENTORY_CELL
    return inventory.point(ox + (col+.5)*cw, oy + (row+.5)*ch)


def inventory_labels(reader, frame, inventory):
    """{(col, row): (label mask, [words])} for each Inventory cell with a label at its top.

    A label is the green text at a stack's top left (TIB, W9, II); words are what the text reader makes of the
    row's labels, one line per row. Two-character labels (W9) are often not read at all; the mask still is."""
    labels = {}
    for row in range(INVENTORY_ROWS):
        strips, spans, x = [], [], 0
        for col in range(INVENTORY_COLUMNS):
            mask = text_mask(inventory_cell(frame, inventory, col, row))
            top = mask[:max(1, round(mask.shape[0]*.42))]
            if (top > 0).sum() >= 10:
                labels[(col, row)] = (top, [])
            strips.append(top)
            spans.append((x, x + top.shape[1], col))
            x += top.shape[1]
        if not any((col, row) in labels for col in range(INVENTORY_COLUMNS)):
            continue
        height = max(strip.shape[0] for strip in strips)
        line = np.hstack([np.pad(strip, ((0, height-strip.shape[0]), (0, 0))) for strip in strips])
        for text, wx, _, ww, _ in reader.read_words(line):
            middle = wx + ww/2
            col = next((c for a, b, c in spans if a <= middle < b), None)
            if (col, row) in labels:
                labels[(col, row)][1].append(text.strip())
    return labels


def same_label(a, b):
    """The same label picture (same size, near the same pixels)."""
    if a is None or b is None or a.shape != b.shape:
        return False
    on_a, on_b = a > 0, b > 0
    union = np.logical_or(on_a, on_b).sum()
    return union > 0 and np.logical_and(on_a, on_b).sum() / union >= .8


def read_count(reader, cells):
    """A stack's xN count from its cells (the label cell, then the one below for tall items): the reading at
    least two ways agree on, None when none does. Counts under 10 (x2) often don't read; they never matter."""
    for rgb in cells:
        if rgb is None or not rgb.size:
            continue
        found = []
        mask = text_mask(rgb)
        for part in (mask[mask.shape[0]//2:], mask):
            for up in (3, 4):
                for blur in (0, .7):
                    image = cv2.GaussianBlur(part, (0, 0), blur) if blur else part
                    count = _count(" ".join(word[0] for word in reader.read_words(image, up=up)))
                    if count is not None:
                        found.append(count)
        best = max(set(found), key=found.count) if found else None
        if best is not None and found.count(best) >= 2:      # two ways agree, or it isn't trusted
            return best
    return None


def _count(text):
    """15 from "x15"; l, I and | read as 1 and O as 0 inside the number."""
    match = re.search(r"[xX]\s*([0-9lI|Oo]+)", text or "")
    if not match:
        return None
    digits = match.group(1).translate(str.maketrans("lI|Oo", "11100"))
    return int(digits) if digits.isdigit() else None


def occupied_cells(gray, window):
    """[(col, row)] of GoGuardian cells holding something, in reading order: not a flat background inside."""
    s = window.scale
    found = []
    for row in range(ROWS):
        for col in range(COLUMNS):
            x, y = window.cell_origin(col, row)
            crop = gray[int(y + 7*s):int(y + (CELL_H-7)*s), int(x + 7*s):int(x + (CELL_W-7)*s)]
            if crop.size and float(crop.std()) >= EMPTY_CONTRAST:
                found.append((col, row))
    return found


def drop_cell(reader, gray, window, code, cells=None):
    """Where a stack labelled `code` goes in GoGuardian: onto its own stack there, else the first empty cell
    (reading order); None when neither is visible. A cell is empty only with a flat background inside."""
    cells = read_cells(reader, gray, window) if cells is None else cells
    for key in sorted(cells, key=lambda k: (k[1], k[0])):
        if cells[key]["code"] == code:
            return cells[key]["point"]
    full = set(occupied_cells(gray, window)) | set(cells)
    for row in range(ROWS):
        for col in range(COLUMNS):
            if (col, row) not in full:
                return window.cell_center(col, row)
    return None


def _alnum(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def is_abbreviation(label, name):
    """True when the label starts a word of the name and its characters follow in order
    (GAM / Gamonin, W4 / Tangent Weaponpart 4). One-character labels prove nothing."""
    label = _alnum(label)
    initials = {word[0] for word in re.findall(r"[a-z0-9]+", (name or "").lower())}
    rest = iter(_alnum(name))
    return len(label) >= 2 and label[0] in initials and all(char in rest for char in label)


def hover_order(cells, names):
    """[(key, info)] worth hovering: labels that abbreviate a wanted name first, the rest after."""
    items = sorted(cells.items(), key=lambda item: (item[0][1], item[0][0]))
    likely = [item for item in items if any(is_abbreviation(item[1]["code"], name) for name in names)]
    return likely + [item for item in items if item not in likely]


def match_name(texts, names):
    """The wanted ingredient whose whole name a tooltip's text contains, else None."""
    best = None
    for text in texts:
        words = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        for name in names:
            wanted = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
            if wanted and re.search(r"(?<![a-z0-9])" + re.escape(wanted) + r"(?![a-z0-9])", words):
                if best is None or len(wanted) > len(re.sub(r"[^a-z0-9]+", " ", best.lower()).strip()):
                    best = name
    return best


def tooltip_texts(reader, gray, point, scale):
    """Text of each tooltip panel (black box with a light border) near `point`, nearest first.

    The panel is found from its pixels, not from where the game happens to draw it, so any
    window position and UI scale works.
    """
    height, width = gray.shape[:2]
    scale = max(scale, .5)
    left, top = max(0, round(point[0] - 500*scale)), max(0, round(point[1] - 140*scale))
    right, bottom = min(width, round(point[0] + 900*scale)), min(height, round(point[1] + 200*scale))
    patch = gray[top:bottom, left:right]
    if patch.size == 0:
        return []
    _, _, stats, _ = cv2.connectedComponentsWithStats((patch < 42).astype(np.uint8))
    found = []
    for x, y, w, h, area in stats[1:].tolist():
        if w < 40*scale*.6 or not 7 <= h <= 90*scale or area/(w*h) < .45 or y == 0 or y + h >= patch.shape[0]:
            continue
        if (patch[y-1, x:x+w] > 90).mean() > .8 and (patch[y+h, x:x+w] > 90).mean() > .8:
            found.append((abs(top + y + h/2 - point[1]) + abs(left + x + w/2 - point[0])/4, x, y, w, h))
    return [reader.read(patch[y:y+h, x:x+w]) for _, x, y, w, h in sorted(found)[:3]]
