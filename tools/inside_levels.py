"""Draw a cave or dungeon level by level, as a stack of tilted plates: the highest floor on top, stairs and ramps
joining the plates, doors, arrivals and supply boxes on their own level.

    runtime\\python.exe tools\\inside_levels.py WORLD [WORLD ...]

Reads traversal\\out\\inside-<world>.json, which `traversal.exe insidemap <world>` writes, and writes
traversal\\out\\inside-<world>-levels.png. Game data stays local (never commit the output).
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "traversal", "out")
BIN = 25              # units of height per histogram step
LEVEL_SHARE = .025    # of the floor's area: a height with less than this is not a level of its own
LEVEL_APART = 150     # units: two floors closer than this are one level
STAIR_SPAN = 20       # units: a floor piece rising more than this across is a stair or ramp
WIDE = 2200           # pixels: a plate's width before the tilt
SQUASH = .5           # how much a plate is flattened, seen at a slant
SHEAR = .35           # of the plate's height: how far its far edge leans right
GAP = 110             # pixels between plates
MARGIN = 60
TITLE = 130


def area(pts):
    x, z = pts[:, 0], pts[:, 2]
    return .5*abs(np.dot(x, np.roll(z, 1))-np.dot(z, np.roll(x, 1)))


def levels(polys):
    """The heights of the floors: peaks of the floor area by height, the small and the close ones merged away."""
    ys = np.array([p["y"] for p in polys])
    weights = np.array([p["area"] for p in polys])
    edges = np.arange(np.floor(ys.min()/BIN)*BIN, ys.max()+2*BIN, BIN)
    hist, _ = np.histogram(ys, bins=edges, weights=weights)
    smooth = np.convolve(hist, [1, 2, 3, 2, 1], "same")/9
    total = weights.sum()
    peaks = [i for i in range(len(smooth)) if smooth[i] > 0 and smooth[i] >= smooth[max(0, i-1)] and smooth[i] >= smooth[min(len(smooth)-1, i+1)]]
    found = []
    for i in sorted(peaks, key=lambda i: -smooth[i]):
        height = edges[i]+BIN/2
        near = abs(ys-height) < LEVEL_APART/2
        if weights[near].sum()/total < LEVEL_SHARE or any(abs(height-h) < LEVEL_APART for h in found):
            continue
        found.append(height)
    return sorted(found, reverse=True)


def load(world):
    with open(os.path.join(OUT, f"inside-{world}.json"), encoding="utf-8") as f:
        data = json.load(f)
    polys = []
    for p in data["polys"]:
        pts = np.array(p["pts"], dtype=float)
        polys.append({"pts": pts, "on": p["on"], "y": pts[:, 1].mean(), "span": np.ptp(pts[:, 1]), "area": area(pts)})
    return data, polys


def font(size):
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw(world):
    data, polys = load(world)
    heights = levels(polys)
    nearest = lambda y: int(np.argmin([abs(y-h) for h in heights]))
    for p in polys:
        p["level"] = nearest(p["y"])
        p["stair"] = p["span"] > STAIR_SPAN
    allpts = np.concatenate([p["pts"] for p in polys]+[np.array([m["at"] for m in data["marks"]])])
    x0, x1 = allpts[:, 0].min(), allpts[:, 0].max()
    z0, z1 = allpts[:, 2].min(), allpts[:, 2].max()
    scale = WIDE/(x1-x0)
    plate_high = (z1-z0)*scale*SQUASH
    lean = plate_high*SHEAR/SQUASH*SQUASH
    width = int(WIDE+lean+2*MARGIN+600)
    height = int(TITLE+len(heights)*(plate_high+GAP)+MARGIN)
    y_low, y_high = min(p["y"] for p in polys), max(p["y"] for p in polys)

    def project(x, z, level):
        """Ground point to the image, on a level's plate: north at the back, leaning right."""
        depth = (z1-z)*scale*SQUASH                     # 0 at the far (north) edge
        top = TITLE+level*(plate_high+GAP)
        u = MARGIN+(x-x0)*scale+(plate_high-depth)*SHEAR/SQUASH*SQUASH
        return u, top+depth

    def ring(pts, level):
        return np.array([project(x, z, level) for x, _, z in pts], dtype=np.float32)

    sup = 3           # drawn three times bigger, then shrunk: smooth edges
    canvas = np.full((height*sup, width*sup, 3), 17, np.uint8)

    def poly(points, colour, thickness=0, closed=True):
        pts = np.round(points*sup).astype(np.int32)
        if thickness == 0:
            cv2.fillPoly(canvas, [pts], colour, cv2.LINE_AA)
        else:
            cv2.polylines(canvas, [pts], closed, colour, thickness*sup, cv2.LINE_AA)

    # The plates, bottom first, each with the whole place's outline faint for reference.
    for level in reversed(range(len(heights))):
        corners = ring(np.array([[x0, 0, z1], [x1, 0, z1], [x1, 0, z0], [x0, 0, z0]]), level)
        poly(corners, (28, 30, 30))
        poly(corners, (60, 70, 66), 2)
        for p in polys:
            if p["level"] != level:
                pts = ring(p["pts"], level)
                poly(pts, (34, 38, 38))
        for p in sorted((p for p in polys if p["level"] == level), key=lambda p: p["y"]):
            t = (p["y"]-y_low)/max(1, y_high-y_low)
            g = int(90+140*t)
            if p["stair"]:
                colour = (40, 150, 235) if p["on"] else (70, 95, 120)       # orange (BGR) stairs and ramps
            else:
                colour = (g//2+40, g, 30) if p["on"] else (g//3+40, g//3+40, g//3+40)
            poly(ring(p["pts"], level), colour)
    # Stairs that rise toward the next level up: a dotted line between the plates, where they meet.
    for p in polys:
        if not p["stair"] or not p["on"]:
            continue
        level = p["level"]
        above = level-1 if level > 0 and p["pts"][:, 1].max() > heights[level]+40 else None
        below = level+1 if level+1 < len(heights) and p["pts"][:, 1].min() < heights[level]-40 else None
        cx, cz = p["pts"][:, 0].mean(), p["pts"][:, 2].mean()
        for other in (above, below):
            if other is None:
                continue
            a, b = project(cx, cz, level), project(cx, cz, other)
            poly(np.array([a, b], dtype=np.float32), (40, 150, 235), 1, closed=False)
    # Routes from the arrival, each stretch on the plate of its height.
    for route in data["routes"]:
        pts = np.array(route["pts"], dtype=float)
        for a, b in zip(pts[:-1], pts[1:]):
            la, lb = nearest(a[1]), nearest(b[1])
            colour = (51, 204, 255)
            if la == lb:
                poly(np.array([project(a[0], a[2], la), project(b[0], b[2], lb)], dtype=np.float32), colour, 3, closed=False)
            else:
                mid = (a+b)/2
                poly(np.array([project(a[0], a[2], la), project(mid[0], mid[2], la)], dtype=np.float32), colour, 3, closed=False)
                poly(np.array([project(mid[0], mid[2], la), project(mid[0], mid[2], lb)], dtype=np.float32), colour, 2, closed=False)
                poly(np.array([project(mid[0], mid[2], lb), project(b[0], b[2], lb)], dtype=np.float32), colour, 3, closed=False)
    # The dungeon sweep (traversal.exe sweepplan <world>), when planned: its points in walking order, cyan, each leg on its level.
    sweep_file = os.path.join(OUT, f"sweep-{world}.json")
    sweep = None
    if os.path.exists(sweep_file):
        with open(sweep_file, encoding="utf-8") as f:
            sweep = np.array(json.load(f), dtype=float)
        for a, b in zip(sweep[:-1], sweep[1:]):
            la, lb = nearest(a[1]), nearest(b[1])
            poly(np.array([project(a[0], a[2], la), project(b[0], b[2], lb)], dtype=np.float32), (230, 210, 60), 2, closed=False)
    image = Image.fromarray(cv2.cvtColor(cv2.resize(canvas, (width, height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
    pen = ImageDraw.Draw(image)
    big, small, tiny = font(44), font(26), font(22)
    pen.text((MARGIN, 24), f"{data['name']} (world {world}): {len(heights)} levels", fill=(225, 225, 225), font=big)
    pen.text((MARGIN, 80), "green: walkable from the arrival (lighter = higher) · grey: not reached · orange: stairs and ramps, dotted to the level they lead to · "
                           "yellow: routes from the arrival · red: doors · white: arrivals · gold: supply boxes", fill=(170, 170, 170), font=tiny)
    for level, h in enumerate(heights):
        u, v = project(x1, z1, level)
        mine = [p for p in polys if p["level"] == level]
        share = sum(p["area"] for p in mine)/sum(p["area"] for p in polys)
        reached = sum(p["area"] for p in mine if p["on"])/max(1, sum(p["area"] for p in mine))
        pen.text((u+24, v+plate_high*.35), f"Level {level+1}", fill=(230, 230, 230), font=font(34))
        pen.text((u+24, v+plate_high*.35+44), f"height {h:.0f}", fill=(160, 160, 160), font=small)
        pen.text((u+24, v+plate_high*.35+76), f"{100*share:.0f}% of the floor", fill=(160, 160, 160), font=small)
        pen.text((u+24, v+plate_high*.35+108), f"{100*reached:.0f}% of it walkable" if reached >= .01 else "not reachable on foot",
                 fill=(120, 200, 150) if reached >= .01 else (200, 120, 120), font=small)
    colours = {"door": (255, 70, 70), "arrival": (255, 255, 255), "box": (255, 200, 50)}
    placed = []
    for m in sorted(data["marks"], key=lambda m: {"door": 0, "arrival": 1, "box": 2}[m["kind"]]):
        x, y, z = m["at"]
        u, v = project(x, z, nearest(y))
        r = 9 if m["kind"] == "box" else 12
        pen.ellipse((u-r, v-r, u+r, v+r), fill=colours[m["kind"]], outline=(0, 0, 0), width=3)
        if m["kind"] == "box" and any(k == "box" and abs(u-pu) < 120 and abs(v-pv) < 60 for k, pu, pv in placed):
            continue          # one label for a row of boxes
        placed.append((m["kind"], u, v))
        label = m["name"] if m["kind"] != "box" else "Supply Boxes"
        dy = -34 if m["kind"] == "arrival" else 4
        pen.text((u+16, v+dy), label, fill=colours[m["kind"]], font=small, stroke_width=4, stroke_fill=(0, 0, 0))
    if sweep is not None:
        for i, (x, y, z) in enumerate(sweep):
            u, v = project(x, z, nearest(y))
            r = 9 if i == 0 else 5
            pen.ellipse((u-r, v-r, u+r, v+r), fill=(60, 210, 230), outline=(0, 0, 0), width=2)
            if i == 0 or (i+1) % 20 == 0 or i == len(sweep)-1:
                pen.text((u+10, v-14), str(i+1), fill=(60, 210, 230), font=tiny, stroke_width=3, stroke_fill=(0, 0, 0))
        pen.text((MARGIN, 108), f"cyan: the hunt's sweep, {len(sweep)} points in walking order (every 20th numbered)", fill=(60, 210, 230), font=tiny)
    target = os.path.join(OUT, f"inside-{world}-levels.png")
    image.save(target)
    print(f"{data['name']}: levels at {', '.join(f'{h:.0f}' for h in heights)}. Wrote {target}")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        draw(int(arg))
