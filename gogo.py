"""GoGuardian (GoGo) window: find it, read its stacks, plan 15-at-a-time refills.

The window is recognised from its bottom button strip ("Take All  Sort  Stack"), read
with the local Windows OCR. Cell labels (three-letter ingredient codes and xN counts) are
read the same way, so no GoGo artwork has to be captured and any UI scale works: the
scale comes from the spacing of the button words, and every other position follows from it.
"""

import re
from dataclasses import dataclass

# Measured on a real capture at its own scale (taken as 1.0): the "Take" word's left edge,
# the "Stack" word's left edge, cell pitch, and the first cell's offset from "Take".
STACK_DX = 128.0
CELL_W, CELL_H = 93.5, 46.3
FIRST_CELL_FROM_TAKE = (-37.0, -472.0)
COLUMNS, ROWS = 5, 9
BATCH = 15

# Ingredient label codes shown on stacks, per built-in recipe (exactly as the game prints them).
INGREDIENT_CODES = {
    "weaponpart_7": {"Trisol": "TRS", "Metal D": "MET", "Arillium": "ARI", "Solantium": "SOL"},
    "weaponpart_9": {"Gamonin": "GAM", "Metal D": "MET", "Solantium": "SOL", "Strastin": "STS", "Tiberal": "TIB"},
}


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
        if not sep or not name or len(name) > 40 or not re.fullmatch(r"[A-Z0-9]{2,4}", code):
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
        raise LookupError("GoGuardian: could not find " + ", ".join(absent) + ". Nothing was moved.")
    for name, code in codes.items():
        info = by_code[code]
        # Stack counts are often too small for the OCR to read. The quantity dialog
        # opens at the full stack, so the runner caps the amount there; here BATCH
        # is only the upper limit.
        amount = min(BATCH, info["count"]) if info["count"] else BATCH
        plan.append((name, code, info["point"], amount))
    return plan
