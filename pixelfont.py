"""The game's pixel font: what it draws at 1024x768 with UI scale 1.0 (the user's VM, 7 Nov).

Windows text recognition can't read it (GAM came out as GRM, x45 as garbage), but it is a bitmap font: every
letter is the same few pixels every time, light on dark with a one-pixel shadow down and right. So letters are
cut apart at their empty columns and looked up in GLYPHS, learned from the user's own screenshots."""
import cv2
import numpy as np

BRIGHT = 150             # letter pixels are lighter than this; their shadow and the panels behind are darker
WORD_GAP = 3             # empty columns between words; letters have one

# letter -> its pixels, row by row ('#' lit), each row as wide as the letter. Two sizes: the labels and counts
# on stacks (5 rows: GAM, x15) and tooltips (6 rows, bold: BLUEPRINT- 30 TO CAPACITY: TANGENT WEAPONPART 9).
# O and 0 are drawn alike in both, and in tooltips O, B and 0 can be too: names are compared with that in mind.
LABEL = {
    '0': [('#####', '#...#', '#...#', '#...#', '#####')],
    '1': [('##', '.#', '.#', '.#', '.#')],
    '2': [('#####', '....#', '#####', '#....', '#####')],
    '3': [('#####', '....#', '..###', '....#', '#####')],
    '4': [('#...#', '#...#', '#####', '....#', '....#')],
    '5': [('#####', '#....', '#####', '....#', '#####')],
    '6': [('#####', '#....', '#####', '#...#', '#####')],
    '7': [('#####', '....#', '....#', '....#', '....#')],
    '8': [('#####', '#...#', '#####', '#...#', '#####')],
    '9': [('#####', '#...#', '#####', '....#', '....#')],
    'A': [('#####', '#...#', '#####', '#...#', '#...#')],
    'B': [('####.', '#...#', '#####', '#...#', '####.')],
    'C': [('#####', '#....', '#....', '#....', '#####')],
    'E': [('#####', '#....', '###..', '#....', '#####')],
    'G': [('#####', '#....', '#.###', '#...#', '#####')],
    'I': [('#####', '..#..', '..#..', '..#..', '#####')],
    'L': [('#....', '#....', '#....', '#....', '#####')],
    'M': [('#...#', '##.##', '#.#.#', '#...#', '#...#')],
    'O': [('#####', '#...#', '#...#', '#...#', '#####')],
    'P': [('####.', '#...#', '#####', '#....', '#....')],
    'S': [('#####', '#....', '#####', '....#', '#####')],
    'T': [('#####', '..#..', '..#..', '..#..', '..#..')],
    'U': [('#...#', '#...#', '#...#', '#...#', '#####')],
    'W': [('#...#', '#...#', '#.#.#', '##.##', '#...#')],
    'X': [('#...#', '.#.#.', '..#..', '.#.#.', '#...#')],
}
TOOLTIP = {
    '-': [('....', '....', '....', '####', '....', '....')],
    '0': [('######', '######', '#...##', '#...##', '#...##', '######')],
    '3': [('######', '######', '..####', '..####', '######', '######')],
    '9': [('######', '######', '######', '######', '....##', '....##')],
    ':': [('#', '.', '.', '.', '.', '#')],
    'A': [('######', '######', '######', '######', '#...##', '#...##')],
    'B': [('#####.', '######', '######', '######', '######', '#####.')],
    'C': [('######', '#####.', '#.....', '#.....', '#####.', '######')],
    'E': [('######', '#####.', '###...', '###...', '#####.', '######')],
    'G': [('######', '#####.', '#.###.', '#.####', '######', '######')],
    'I': [('######', '#####.', '..##..', '..##..', '#####.', '######'), ('#', '#', '#', '#', '#', '#')],
    'L': [('#.....', '#.....', '#.....', '#.....', '#####.', '######')],
    'N': [('#...##', '##..##', '###.##', '#.####', '#..###', '#...##'), ('######', '######', '#...##', '#...##', '#...##', '#...##')],
    'O': [('#####.', '######', '######', '######', '######', '#####.'), ('######', '######', '#...##', '#...##', '#...##', '######')],
    'P': [('#####.', '######', '######', '#####.', '#.....', '#.....'), ('######', '######', '######', '#####.', '#.....', '#.....')],
    'R': [('#####.', '######', '######', '#####.', '#..##.', '#...##'), ('######', '######', '######', '#####.', '#..##.', '#...##')],
    'T': [('######', '#####.', '..##..', '..##..', '..##..', '..##..')],
    'U': [('#...##', '#...##', '#...##', '#...##', '######', '######')],
    'W': [('#...##', '#...##', '#.#.##', '######', '##.###', '#...##')],
    'Y': [('#...##', '##.#..', '.####.', '..##..', '..##..', '..##..')],
}
FONTS = {"label": (5, LABEL), "tooltip": (6, TOOLTIP)}


def _key(bits):
    return tuple("".join("#" if v else "." for v in row) for row in bits)


def segment(gray, height=5):
    """[(x, y, glyph pixels bool height x w)] for letter-sized marks in `gray`, top to bottom, left to right."""
    bright = gray >= BRIGHT
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bright.astype(np.uint8), connectivity=8)
    parts = []
    rows, width = gray.shape[:2]
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if w > 7 or h > height:
            continue
        ys, xs = np.nonzero(labels[y:y+h, x:x+w] == i)
        shade = [(yy+y+1, xx+x+1) for yy, xx in zip(ys, xs)
                 if yy+y+1 < rows and xx+x+1 < width and not bright[yy+y+1, xx+x+1]]
        if shade and np.mean([gray[p] < 70 for p in shade]) < .5:
            continue                       # no dark shadow: a speck of item art, not a letter
        parts.append((x, y, w, h))
    # Lines: a letter's band is HEIGHT rows from the top of the tallest mark around it.
    parts.sort(key=lambda p: -p[3])
    lines = []
    for x, y, w, h in parts:
        middle = y + h/2
        line = next((l for l in lines if l["top"] <= middle < l["top"] + height), None)
        if line is None:
            if h < 3:
                continue                   # a dot or dash on its own is not a line
            line = {"top": y, "parts": []}
            lines.append(line)
        line["parts"].append((x, x + w))
    found = []
    for line in sorted(lines, key=lambda l: l["top"]):
        spans = []
        for a, b in sorted(line["parts"]):
            if spans and a <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], b)
            else:
                spans.append([a, b])
        top = line["top"]
        for a, b in spans:
            found.append((a, top, bright[top:top+height, a:b]))
    return found


def classify(bits, glyphs):
    """The letter these pixels are: an exact match, else the nearest of the same size within two pixels, else ?."""
    key = _key(bits)
    for char, patterns in glyphs.items():
        if key in patterns:
            return char
    best, misses = "?", 3
    for char, patterns in glyphs.items():
        for pattern in patterns:
            if len(pattern[0]) != bits.shape[1] or len(pattern) != bits.shape[0]:
                continue
            wrong = sum(a != b for row_a, row_b in zip(pattern, key) for a, b in zip(row_a, row_b))
            if wrong < misses:
                best, misses = char, wrong
    return best


def read_words(gray, font="label"):
    """[(text, x, y, w, h)] like the Windows text reader's, from the pixel font."""
    height, glyphs = FONTS[font]
    words = []
    current = None
    for x, y, bits in segment(gray, height):
        w = bits.shape[1]
        if current and current["y"] == y and x - current["end"] <= WORD_GAP:
            current["text"] += classify(bits, glyphs)
            current["end"] = x + w
        else:
            if current:
                words.append(current)
            current = {"text": classify(bits, glyphs), "x": x, "y": y, "end": x + w}
    if current:
        words.append(current)
    return [(_settle(word["text"]), word["x"], word["y"], word["end"] - word["x"], height) for word in words]


def _settle(text):
    """S/5 and O/0 are one glyph: x15 and 150 keep digits, STS and SOL take letters."""
    import re
    if re.fullmatch(r"X?[0-9?]+", text):
        return text
    return text.translate(str.maketrans("50", "SO"))


def read(gray, font="label"):
    """All the text, line by line, words spaced: like the Windows reader's read()."""
    lines = {}
    for text, x, y, w, h in read_words(gray, font):
        lines.setdefault(y, []).append((x, text))
    return "\n".join(" ".join(text for _, text in sorted(words)) for _, words in sorted(lines.items()))


def text_mask(rgb):
    """The pale green label letters alone, white on black: item art (grey, teal, white) drops out."""
    c = rgb.astype(np.int16)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    return (((g - r > 35) & (g - b > 20) & (g > 170) & (r > 100)) * 255).astype(np.uint8)


def same_name(read, name):
    """True when a tooltip's words are this item name, allowing for the letters the font draws alike (O, B, 0)
    and one unread letter in five; every digit must agree."""
    import re
    def canon(text):
        text = re.sub(r"[^A-Z0-9?]+", " ", text.upper()).strip()
        return text.translate(str.maketrans("B0", "OO"))
    a, b = canon(read), canon(name)
    if re.findall(r"[1-9]", a) != re.findall(r"[1-9]", b) or abs(len(a) - len(b)) > 2:
        return False
    if len(a) != len(b):
        return False
    wrong = sum(x != y and x != "?" for x, y in zip(a, b)) + sum(x == "?" for x in a)
    return wrong <= len(b) // 5


class PixelReader:
    """Stands in for text_reader.TextReader when the game draws its pixel font."""
    pixel = True

    def read_words(self, gray, up=None):
        return read_words(gray)

    def read(self, gray):
        return read(gray, "tooltip") or read(gray)


# GoGuardian's Take All / Sort / Stack strip in the pixel font: the window's cells from where TAKE ALL's picture is.
GOGO_SCALE = .855                # its cell grid in the user's screenshot (columns .845, rows .864)
GOGO_TAKE = (7.6, -1.4)          # the GoGo take point (see gogo.GoGo) from TAKE ALL's picture
GOGO_STACK_DX = (100, 120)       # STACK's picture starts this far right of TAKE ALL's
_pictures = {}


def _picture(name):
    if name not in _pictures:
        from pathlib import Path
        path = Path(__file__).resolve().parent / "assets" / f"{name}.png"
        _pictures[name] = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return _pictures[name]


def find_strip(gray, threshold=.9):
    """(take_x, take_y, scale) of the GoGuardian window from its button words, or None."""
    take, stack = _picture("pixel_take_all"), _picture("pixel_stack")
    if take is None or stack is None or gray.shape[0] < take.shape[0] or gray.shape[1] < take.shape[1]:
        return None
    scores = cv2.matchTemplate(gray, take, cv2.TM_CCOEFF_NORMED)
    for _ in range(3):
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < threshold:
            return None
        scores[max(0, y-10):y+10, max(0, x-40):x+40] = -1
        area = gray[max(0, y-4):y+stack.shape[0]+4, x+GOGO_STACK_DX[0]:x+GOGO_STACK_DX[1]+stack.shape[1]]
        if area.shape[0] >= stack.shape[0] and area.shape[1] >= stack.shape[1] \
                and cv2.matchTemplate(area, stack, cv2.TM_CCOEFF_NORMED).max() >= threshold:
            return (x + GOGO_TAKE[0], y + GOGO_TAKE[1], GOGO_SCALE)
    return None
