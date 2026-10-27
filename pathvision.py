"""Find the game's dashed Nav-Ray path in a screenshot and say where to steer.

The path is a chain of short, thin, green dashes lying on one line on the floor. Colour alone is
not enough (green signs and tiles exist), so candidate dashes are filtered by size and shape and
the longest chain of candidates on one straight line is taken as the path.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PathView:
    points: tuple      # (x, y) dash centres, nearest to the camera first
    aim: tuple         # the point to turn towards
    error: float       # look-ahead aim x relative to the view centre, as a fraction of the width (-.5 .. .5)
    lateral: float = 0.0   # how far the line passes from the character, same units, measured near the character


def _excluded(fx, fy):
    """HUD areas that are always on screen and green (fractions of the frame)."""
    return (fy < .06 or (fx < .20 and fy < .20) or (fx > .84 and fy > .78)
            or fx > .92 or (fx < .47 and fy > .76))


def dash_candidates(frame, ignore=()):
    """[(cx, cy, area)] of small, dash-shaped green blobs. `ignore` = pixel boxes (x0,y0,x1,y1)."""
    height, width = frame.shape[:2]
    unit = width/2000
    hue, sat, val = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
    mask = ((hue >= 55) & (hue <= 85) & (sat >= 55) & (val >= 95)).astype(np.uint8)
    count, labels, stats, centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        cx, cy = centres[i]
        if not 6*unit*unit <= area <= 1500*unit*unit:
            continue
        if _excluded(cx/width, cy/height):
            continue
        if abs(cx - width/2) < 28*unit and abs(cy - .504*height) < 28*unit:
            continue                                   # the reticle
        if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in ignore):
            continue
        long_side, short_side = max(w, h), max(1, min(w, h))
        if long_side > 10*unit and long_side/short_side < 1.5 and area/(w*h) > .5:
            continue                                   # a filled blob, not a dash
        found.append((float(cx), float(cy), int(area), _orientation(labels, i, x, y, w, h, unit)))
    return found


def _orientation(labels, index, x, y, w, h, unit):
    """Direction (radians, image axes) a dash-shaped blob points in; nan for small or roundish blobs."""
    if max(w, h) < 9*unit:
        return float("nan")
    moments = cv2.moments((labels[y:y+h, x:x+w] == index).astype(np.uint8), binaryImage=True)
    a, b, c = moments["mu20"], moments["mu02"], moments["mu11"]
    spread = float(np.hypot(a - b, 2*c))
    major, minor = (a + b + spread)/2, (a + b - spread)/2
    if minor <= 0 or major/minor < 3.0:
        return float("nan")
    return float(.5*np.arctan2(2*c, a - b))


def _plausible(points, areas, angles, height):
    """Is this chain shaped like dashes on the floor receding into the distance?

    It must span some depth (a flat row of marks is text), and where the dashes have a measurable
    direction their size must shrink with height on screen (far dashes are small). Text on a sign
    fails both: rows of equal-height lines of random width.
    """
    ys = points[:, 1]
    if ys.max() - ys.min() < .08*height:
        return False
    measured = ~np.isnan(angles)
    if measured.sum() >= 4:
        sizes = np.sqrt(areas[measured])
        if np.ptp(ys[measured]) > 0 and np.ptp(sizes) > 0:
            if np.corrcoef(ys[measured], sizes)[0, 1] < .7:
                return False
    return True


def best_chain(candidates, tolerance=7.0, minimum=4, samples=3000, max_turn=np.radians(30), height=1440, tries=25):
    """Largest plausible set of candidates on one line, nearest (lowest on screen) first; [] if none.

    Every pair is tried for small inputs; busy scenes (hundreds of candidates) try a fixed random
    sample of pairs so the cost stays bounded. Chains are examined best first and the first one
    that looks like a floor path wins.
    """
    points = np.array([(c[0], c[1]) for c in candidates], dtype=float)
    areas = np.array([c[2] for c in candidates], dtype=float)
    angles = np.array([c[3] if len(c) > 3 else float("nan") for c in candidates], dtype=float)
    count = len(points)
    if count < minimum:
        return []
    first, second = np.triu_indices(count, 1)
    if len(first) > samples:
        pick = np.random.default_rng(0).choice(len(first), samples, replace=False)
        first, second = first[pick], second[pick]
    delta = points[second] - points[first]
    length = np.hypot(delta[:, 0], delta[:, 1])
    usable = length >= 15
    if not usable.any():
        return []
    first, delta, length = first[usable], delta[usable], length[usable]
    normal = np.stack([-delta[:, 1], delta[:, 0]], axis=1)/length[:, None]
    offsets = points[None, :, :] - points[first][:, None, :]
    inside = np.abs(np.einsum("pnk,pk->pn", offsets, normal)) <= tolerance
    # A dash lies along the path: elongated blobs must point the way the line runs. Text lines on a
    # sign, which are elongated across it, therefore never join a chain. Small blobs carry no direction.
    line = np.arctan2(delta[:, 1], delta[:, 0])
    turn = np.abs((angles[None, :] - line[:, None] + np.pi/2) % np.pi - np.pi/2)
    inside &= np.isnan(angles)[None, :] | (turn <= max_turn)
    seen = set()
    for pair in np.argsort(-inside.sum(axis=1), kind="stable")[:tries*4]:
        members = tuple(np.where(inside[pair])[0])
        if len(members) < minimum:
            break
        if members in seen:
            continue
        seen.add(members)
        index = list(members)
        if _plausible(points[index], areas[index], angles[index], height):
            chosen = points[index]
            return [tuple(p) for p in chosen[np.argsort(-chosen[:, 1])]]
        if len(seen) >= tries:
            break
    return []


def find_path(frame, ignore=()):
    """PathView for a BGR frame, or None when no path is visible.

    The steering point comes from a straight-line fit through the whole chain, evaluated at a
    look-ahead height, so one stray or flickering dash cannot jerk the aim around.
    """
    chain = best_chain(dash_candidates(frame, ignore), height=frame.shape[0])
    if not chain:
        return None
    height, width = frame.shape[:2]
    ys = np.array([p[1] for p in chain])
    xs = np.array([p[0] for p in chain])
    slope, intercept = np.polyfit(ys, xs, 1)
    look_y = min(max(.5*height, float(ys.min())), float(ys.max()))
    look_x = min(max(float(slope*look_y + intercept), 0.0), float(width))
    near_x = min(max(float(slope*.75*height + intercept), 0.0), float(width))
    return PathView(tuple(chain), (look_x, look_y), (look_x - width/2)/width, (near_x - width/2)/width)
