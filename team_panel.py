"""The team panel on the left of the game view: one green bar per team member (name, health), and under it that member's
buff icons, each with its seconds left. Always on screen once Teamplates are on (Alt+T), so a healer reads who needs
what without aiming at anyone. Found by the bars, so it works wherever the panel sits and at any size (7 Nov, 2560x1440)."""
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

BAR = (60, 175, 112)         # the bar's green
BAR_HEIGHT = 26.             # at scale 1 (a 2000 px wide picture of the 1440p game)
ICON, PITCH = 35., 37.7      # tile and spacing, at scale 1
SLOTS = {1: "heal", 2: "pale", 3: "red", 4: "blue", 5: "anchor"}
MAX_ICONS = 8


@dataclass
class Member:
    name: str
    health: int | None
    bar: tuple                                   # x, y, w, h of the name bar
    buffs: dict = field(default_factory=dict)    # slot -> seconds left (None: shown, timer unread)


def bars(rgb):
    """[(x, y, w, h)] of the green name bars, top to bottom."""
    c = rgb.astype(int)
    mask = ((abs(c[..., 0]-BAR[0]) < 28) & (abs(c[..., 1]-BAR[1]) < 28) & (abs(c[..., 2]-BAR[2]) < 28)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    found = []
    for x, y, w, h, area in stats[1:].tolist():
        if w >= 100 and 12 <= h <= 90 and w/h >= 5 and area/(w*h) > .7:
            found.append((x, y, w, h))
    return sorted(found, key=lambda b: (b[1], b[0]))


def _ring(tile):
    """What kind of icon a tile holds, from its ring's colour: heal (vivid green cross), red, blue, else None."""
    c = tile.astype(int)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    area = r.size
    if ((r < 90) & (g > 200) & (b < 110)).sum() > .04*area:
        return "heal"
    if ((r > 45) & (r > g*1.8) & (r > b*2.5)).sum() > .02*area:
        return "red"
    if ((b > 110) & (r < 60) & (g < 70)).sum() > .02*area:
        return "blue"
    return None


def classify(tile, references):
    kind = _ring(tile)
    if kind:
        return {"heal": 1, "red": 3, "blue": 4}[kind]
    gray = cv2.cvtColor(tile, cv2.COLOR_RGB2GRAY)
    best, slot = .0, None
    for number, reference in references.items():
        k = gray.shape[0] / ICON
        inner = reference[5:30, 5:30]                      # the middle: a pixel's shift in the cut doesn't matter
        ref = cv2.resize(inner, None, fx=k, fy=k)
        score = float(cv2.matchTemplate(gray, ref, cv2.TM_CCOEFF_NORMED).max())
        if score > best:
            best, slot = score, number
    return slot if best > .5 else None


def references():
    """{slot: gray tile} for the two icons with no coloured ring, from assets (cut at scale 1)."""
    from pathlib import Path
    folder = Path(__file__).resolve().parent / "assets"
    return {slot: cv2.imread(str(folder / f"team_icon_{slot}.png"), cv2.IMREAD_GRAYSCALE) for slot in (2, 5)}


def read(rgb, reader, references, wanted=None):
    """[Member] for every bar found. `reader` is a text reader (read_words); `references` {slot: gray tile} for the
    icons that have no colour ring (slots 2 and 5)."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    members = []
    for x, y, w, h in bars(rgb):
        s = h / BAR_HEIGHT
        full = round(308*s)                              # the bar's fill shrinks with health; its number stays at the right end
        words = reader.read_words(gray[y:y+h, x:x+full], up=3)
        name = " ".join(t for t, wx, *_ in sorted(words, key=lambda t: t[1]) if wx < 210*s and not t.isdigit()).strip()
        digits = "".join(t for t, wx, *_ in sorted(words, key=lambda t: t[1]) if wx > 210*s and t.isdigit())
        member = Member(name, int(digits) if digits else None, (x, y, w, h))
        if wanted is None or name in wanted:
            top = y + h + round(2*s)
            dark = 0
            for i in range(MAX_ICONS):
                left = x + round(i*PITCH*s)
                tile = rgb[top:top+round(ICON*s), left:left+round(ICON*s)]
                if tile.shape[0] < 10 or tile.shape[1] < 10:
                    break
                if tile.reshape(-1, 3).mean() < 60:           # a dim icon or gap is skipped; two in a row: no more icons
                    dark += 1
                    if dark >= 2:
                        break
                    continue
                dark = 0
                slot = classify(tile, references)
                label = gray[top+round(ICON*s)-round(1*s):top+round(ICON*s)+round(19*s), left-round(1*s):left+round((ICON+1.5)*s)]
                seconds = None
                if label.size:
                    text = "".join(t for t, *_ in reader.read_words(cv2.resize(label, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC), up=1))
                    found = re.sub(r"\D", "", text)
                    seconds = int(found) if found else None
                if slot is not None:
                    member.buffs[slot] = seconds
        members.append(member)
    return members
