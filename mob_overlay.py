"""Mobs on map: the sector you are in, with every NPC the game reports around you drawn where it stands right now.
Wasteland sectors are drawn from their own heightfield, lined up like the game's map (x across, z down, the sector
32768 units wide and centred on 0: checked against the game's player mark in K 11, 8 Nov). Elsewhere it is a plain
grid fitted around you and them. The game only reports what is within about 10,000 units of you."""
import cv2
import numpy as np

SIZE = 820                   # pixels: the map square
LEGEND = 26                  # pixels per legend line
PREY = {16, 17, 18}          # pak_factions: Robot, Mutant, Wildlife
# Distinct, readable on green and on dark grey (BGR).
COLORS = [(255, 0, 255), (0, 0, 255), (0, 140, 255), (255, 255, 0), (0, 255, 255), (255, 80, 80), (180, 0, 120),
          (0, 200, 0), (255, 255, 255), (60, 60, 200), (200, 120, 0), (120, 255, 180)]


def shade(heights, samples, size=SIZE):
    """The heightfield as the game's map shows it: green, lit from the north-west."""
    h = heights.reshape(samples, samples).astype(np.float32)
    dz, dx = np.gradient(h)
    light = np.clip(.75 - (dx - dz) / 160., .25, 1.)
    img = np.zeros((samples, samples, 3), np.float32)
    img[..., 0], img[..., 1], img[..., 2] = 120 * light, 230 * light, 90 * light
    return cv2.resize(img.astype(np.uint8), (size, size), interpolation=cv2.INTER_CUBIC)


def frame(data, half=None):
    """(to_pixel, base image): the sector square when its size is known, else a square around you and the mobs."""
    if half:
        lo, span = (-half, -half), 2. * half
    else:
        xs = [data["player"]["x"]] + [e["x"] for e in data["entities"] if "x" in e]
        zs = [data["player"]["z"]] + [e["z"] for e in data["entities"] if "z" in e]
        span = max(max(xs) - min(xs), max(zs) - min(zs), 2000.) * 1.15
        lo = ((max(xs) + min(xs) - span) / 2, (max(zs) + min(zs) - span) / 2)
    return lambda x, z: (int((x - lo[0]) / span * SIZE), int((z - lo[1]) / span * SIZE))


def render(data, heights=None, samples=512, half=None):
    """The picture: map, mobs (one colour per kind of mob, numbered in the legend), you, and the legend below."""
    to_px = frame(data, half if heights is not None else None)
    base = shade(heights, samples) if heights is not None else np.full((SIZE, SIZE, 3), 45, np.uint8)
    if heights is None:
        for i in range(0, SIZE, SIZE // 8):
            base[i, :] = base[:, i] = 70
    mobs = [e for e in data["entities"] if e.get("kind") == "npc" and not e.get("dead") and "x" in e]
    kinds = sorted({" ".join(e["name"].split()) for e in mobs if e.get("factionId") in PREY},
                   key=lambda n: -sum(1 for e in mobs if " ".join(e["name"].split()) == n))
    color = {name: COLORS[i % len(COLORS)] for i, name in enumerate(kinds)}
    img = base.copy()
    for e in mobs:
        p = to_px(e["x"], e["z"])
        name = " ".join(e["name"].split())
        if name in color:
            cv2.circle(img, p, 9, (0, 0, 0), -1)
            cv2.circle(img, p, 7, color[name], -1)
        else:                                        # people: traders, guards, Pathfinders...
            cv2.circle(img, p, 5, (0, 0, 0), -1)
            cv2.circle(img, p, 3, (150, 150, 150), -1)
    you = to_px(data["player"]["x"], data["player"]["z"])
    cv2.drawMarker(img, you, (0, 0, 0), cv2.MARKER_STAR, 30, 6)
    cv2.drawMarker(img, you, (255, 255, 255), cv2.MARKER_STAR, 26, 2)
    lines = [(color[n], f"{n} ({sum(1 for e in mobs if ' '.join(e['name'].split()) == n)})") for n in kinds]
    lines += [((150, 150, 150), "People"), ((255, 255, 255), "* You"),
              ((200, 200, 200), "Only what the game reports: about 10,000 units around you.")]
    title = f"{data.get('sectorName') or 'This sector'}  -  mobs right now"
    out = np.full((SIZE + 50 + LEGEND * len(lines) + 10, SIZE, 3), 25, np.uint8)
    out[40:40 + SIZE] = img
    cv2.putText(out, title, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, .8, (230, 230, 230), 2, cv2.LINE_AA)
    y = 40 + SIZE + 30
    for c, text in lines:
        cv2.circle(out, (18, y - 7), 7, c, -1)
        cv2.putText(out, text, (34, y), cv2.FONT_HERSHEY_SIMPLEX, .6, (230, 230, 230), 1, cv2.LINE_AA)
        y += LEGEND
    return out
