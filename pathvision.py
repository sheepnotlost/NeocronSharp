"""Find the game's dashed Nav-Ray path in a screenshot and say where to steer.

The path is a chain of short, thin, green dashes lying on one line on the floor. Colour alone is
not enough (green signs and tiles exist), so candidate dashes are filtered by size and shape and
the longest chain of candidates on one straight line is taken as the path.
"""
from dataclasses import dataclass

import cv2
import numpy as np


REACH_Y = .80    # a dash lower than this (fraction of the height) is at the character's feet: already reached


@dataclass(frozen=True)
class PathView:
    points: tuple      # (x, y) dash centres, nearest to the camera first
    aim: tuple         # the point to turn towards
    error: float       # look-ahead aim x relative to the view centre, as a fraction of the width (-.5 .. .5)
    lateral: float = 0.0   # how far the line passes from the character, same units, measured near the character
    slope: float = 0.0     # the fitted line: x = slope * y + intercept
    intercept: float = 0.0
    forward_point: tuple = (0.0, 0.0)   # the far end of the chain: the way on


def _excluded(fx, fy):
    """HUD areas that are always on screen and green, and the character itself (fractions of the frame)."""
    return (fy < .06 or (fx < .20 and fy < .20) or (fx > .84 and fy > .78)
            or fx > .92 or (fx < .47 and fy > .76)
            or (.43 < fx < .60 and fy > .50))


def dash_candidates(frame, ignore=()):
    """[(cx, cy, area)] of small, dash-shaped green blobs. `ignore` = pixel boxes (x0,y0,x1,y1)."""
    height, width = frame.shape[:2]
    unit = width/2000
    hue, sat, val = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask = ((hue >= 55) & (hue <= 85) & (sat >= 55) & (val >= 95)).astype(np.uint8)
    count, labels, stats, centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        cx, cy = centres[i]
        if not 6*unit*unit <= area <= 6000*unit*unit:
            continue
        if _excluded(cx/width, cy/height):
            continue
        if abs(cx - width/2) < 28*unit and abs(cy - .504*height) < 28*unit:
            continue                                   # the reticle
        if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in ignore):
            continue
        direction = _orientation(labels, i, x, y, w, h, unit)
        # A clear dash shape passes whatever the floor looks like (green-lit floors give little contrast);
        # anything else must stand out, which a flat green glow on a wall does not.
        if direction != direction and _contrast(gray, labels, i, x, y, w, h, unit) < MIN_CONTRAST:
            continue
        long_side, short_side = max(w, h), max(1, min(w, h))
        if long_side > 10*unit and long_side/short_side < 1.5 and area/(w*h) > .5:
            continue                                   # a filled blob, not a dash
        found.append((float(cx), float(cy), int(area), direction))
    return found


MIN_CONTRAST = 14    # a dash is this much brighter (grey levels) than the floor around it


def _contrast(gray, labels, index, x, y, w, h, unit):
    """How much brighter a mark is than the ring of picture just outside it. Dashes are bright overlays
    on a dark floor; the teal wall surfaces of the scene are almost as bright as their surroundings."""
    pad = max(4, round(6*unit))
    top, left = max(0, y - pad), max(0, x - pad)
    bottom, right = min(gray.shape[0], y + h + pad), min(gray.shape[1], x + w + pad)
    inside = labels[top:bottom, left:right] == index
    grown = cv2.dilate(inside.astype(np.uint8), np.ones((2*pad + 1, 2*pad + 1), np.uint8)) > 0
    ring = grown & ~cv2.dilate(inside.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    crop = gray[top:bottom, left:right]
    if not ring.any():
        return 255.0
    return float(crop[inside].mean() - crop[ring].mean())


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
    # Dashes are spaced out. Text (lettering on a sign) puts many marks a few pixels apart.
    spacing = np.hypot(*np.diff(points[np.argsort(-ys)], axis=0).T)
    if len(spacing) >= 3 and float((spacing < 12*height/1440).mean()) > .30:
        return False
    if len(points) == 3:
        # The thin evidence of a three-mark chain must be clean: marks well apart, and the nearer
        # (lower) big dash larger than the farther one.
        order = np.argsort(-ys)
        gaps = np.hypot(*np.diff(points[order], axis=0).T)
        if gaps.min() < 40:
            return False
        big = [i for i in order if measured[i]]
        if any(areas[a] <= areas[b] for a, b in zip(big, big[1:])):
            return False
    if measured.sum() >= 4:
        sizes = np.sqrt(areas[measured])
        if np.ptp(ys[measured]) > 0 and np.ptp(sizes) > 0:
            if np.corrcoef(ys[measured], sizes)[0, 1] < .7:
                return False
    return True


def best_chain(candidates, tolerance=7.0, minimum=3, samples=3000, max_turn=np.radians(30), height=1440, tries=25,
               anchor=None):
    """Largest plausible set of candidates on one line, nearest (lowest on screen) first; [] if none.

    Every pair is tried for small inputs; busy scenes (hundreds of candidates) try a fixed random
    sample of pairs so the cost stays bounded. Chains are examined best first and the first one
    that looks like a floor path wins. "Best" is the most marks, with a bonus for a chain that begins at
    `anchor` (the character): the route starts under the character, so that is the one to follow.
    """
    points = np.array([(c[0], c[1]) for c in candidates], dtype=float)
    areas = np.array([c[2] for c in candidates], dtype=float)
    angles = np.array([c[3] if len(c) > 3 else float("nan") for c in candidates], dtype=float)
    count = len(points)
    if count < minimum:
        return []
    # Four marks make a chain. Three do only when two of them are big dashes pointing along it (the
    # near stretch of a path whose far end is out of view); three small dots prove nothing.
    def enough(members):
        return len(members) >= 4 or (len(members) == 3 and int((~np.isnan(angles[list(members)])).sum()) >= 2)
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
    ranked, seen = [], set()
    for pair in np.argsort(-inside.sum(axis=1), kind="stable")[:tries*4]:
        members = tuple(np.where(inside[pair])[0])
        if len(members) < minimum:
            break
        if members in seen or not enough(members):
            continue
        seen.add(members)
        bonus = 0.0
        if anchor is not None:
            nearest = float(np.min(np.hypot(points[list(members)][:, 0] - anchor[0], points[list(members)][:, 1] - anchor[1])))
            bonus = 12*max(0.0, 1 - nearest/(.5*height*16/9))
        ranked.append((len(members) + bonus, members))
        if len(seen) >= tries*2:
            break
    for _, members in sorted(ranked, key=lambda item: -item[0])[:tries]:
        index = list(members)
        if _plausible(points[index], areas[index], angles[index], height):
            chosen = points[index]
            return [tuple(p) for p in chosen[np.argsort(-chosen[:, 1])]]
    return []


def find_path(frame, ignore=(), prior=None, tube=.18):
    """PathView for a BGR frame, or None when no path is visible in front of the character.

    The dashes ahead of the character are the way on. A chain lying wholly below the character's feet
    is behind it and is not followed. With `prior` (the view being followed) only marks within `tube`
    (a fraction of the width) of its line are considered, so the macro stays on the path it is
    following and ignores everything else.

    The character goes from one dash to the next: the target is the nearest dash ahead (above the
    character's feet), and as it is reached the next one becomes the target.
    """
    candidates = dash_candidates(frame, ignore)
    height, width = frame.shape[:2]
    if prior is not None:
        candidates = [c for c in candidates if abs(c[0] - (prior.slope*c[1] + prior.intercept)) <= tube*width]
    chain = best_chain(candidates, height=height, anchor=(.5*width, .72*height))
    if not chain:
        return None
    ys = np.array([p[1] for p in chain])
    xs = np.array([p[0] for p in chain])
    if ys.min() > .80*height:
        return None                                        # all of it is at or behind the character's feet
    slope, intercept = np.polyfit(ys, xs, 1)               # kept for tracking: where the line runs
    centre = width/2
    ahead = [p for p in chain if p[1] <= REACH_Y*height]    # chain is nearest first
    target = ahead[0] if ahead else chain[-1]
    near_x = min(max(float(slope*.75*height + intercept), 0.0), float(width))
    return PathView(tuple(chain), (float(target[0]), float(target[1])), (target[0] - centre)/width,
                    (near_x - centre)/width, float(slope), float(intercept), chain[-1])
