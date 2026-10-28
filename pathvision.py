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


def _excluded(fx, fy, color="green"):
    """HUD areas that are always on screen in the dash colour (fractions of the frame).
    The character region needs shape checks instead: real floor dashes also cross it."""
    return (fy < .06 or (fx < .20 and fy < .20) or (fx > .84 and fy > .78)
            or fx > .92 or (fx > .89 and .30 < fy < .82) or (fx < .47 and fy > .76))


# The dashes follow the HUD colour scheme (/set gfx_hudcolor): green by default, any colour you pick.
# OpenCV hues run 0-179; red wraps round (170..179 and 0..10 are one colour). Ranges are (low, high) with
# low > high meaning "wraps". The scene is mostly grey, dark teal and warm yellow-orange lights, so red,
# magenta and blue stand out best.
COLOR_HUES = {"green": (55, 88), "red": (170, 10), "magenta": (135, 168), "blue": (100, 130)}
COLORS = tuple(COLOR_HUES)


HUD_BOX = (0.0, 0.0, .20, .20)      # the Location / Time panel: its frame is drawn in the HUD colour scheme


def hud_hue(frame):
    """The HUD colour scheme's hue (OpenCV 0-179), read from the frame of the Location panel in the top left,
    or None when it has no clear colour (the grey scheme). The Nav-Ray dashes are drawn in this colour, so it
    says which colour to look for and which green things in the scene to ignore."""
    height, width = frame.shape[:2]
    left, top, right, bottom = HUD_BOX
    hsv = cv2.cvtColor(frame[int(top*height):int(bottom*height), int(left*width):int(right*width)], cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    chosen = hue[(sat >= 120) & (val >= 140)]
    if chosen.size < 120:
        return None
    # Hue is circular (red wraps): vote on a circle shifted so that the commonest hue sits in the middle.
    counts = np.bincount(chosen, minlength=180).astype(float)
    smooth = sum(np.roll(counts, shift) for shift in range(-4, 5))
    return int(np.argmax(smooth))


def _hue_window(color):
    """(low, high, strict) for a colour name or a numeric hue. `strict` = a colour other than the default green,
    which gets the stricter saturation rule (red and the like are rarer in the scene, so easier to trust)."""
    if isinstance(color, str):
        low, high = COLOR_HUES[color]
        return low, high, color != "green"
    centre = int(color) % 180
    if 55 <= centre <= 88:
        return COLOR_HUES["green"][0], COLOR_HUES["green"][1], False
    return (centre - 12) % 180, (centre + 12) % 180, True


def dash_candidates(frame, ignore=(), color="green"):
    """[(cx, cy, area, angle)] of dash-shaped blobs of the dash colour (a name from COLOR_HUES or a numeric hue).
    `ignore` = pixel boxes (x0,y0,x1,y1)."""
    height, width = frame.shape[:2]
    unit = width/2000
    hue, sat, val = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    low, high, strict = _hue_window(color)
    centre = ((low + high + (180 if low > high else 0))/2) % 180
    # Shift the hue circle so the dash colour sits in one block at 90 (this also makes red, which wraps, simple).
    hue = ((hue.astype(np.int16) + 90 - int(round(centre))) % 180).astype(np.uint8)
    half = ((high - low) % 180)/2
    if not strict:
        mask = ((np.abs(hue.astype(np.int16) - 90) <= half) & (sat >= 35) & (val >= 62)).astype(np.uint8)
    else:
        mask = ((np.abs(hue.astype(np.int16) - 90) <= half) & (sat >= 90) & (val >= 70)).astype(np.uint8)
    count, labels, stats, centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        cx, cy = centres[i]
        if not 6*unit*unit <= area <= 40000*unit*unit:
            continue
        if _excluded(cx/width, cy/height, "red" if strict else "green"):
            continue
        if abs(cx - width/2) < 28*unit and abs(cy - .504*height) < 28*unit:
            continue                                   # the reticle
        if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in ignore):
            continue
        inside = labels[y:y + h, x:x + w] == i
        saturation = float(sat[y:y + h, x:x + w][inside].mean())
        direction = _orientation(labels, i, x, y, w, h, unit)
        if not strict and .43 < cx/width < .60 and cy/height > .50:
            if direction != direction or area < 100*unit*unit:
                continue                               # gear and tiny character markers, while retaining clear floor dashes
        if saturation < (90 if strict else MIN_SATURATION):
            # Translucent dashes on pale tiles measure saturation 43-58. Accept these only
            # on the floor with both a clear dash shape and contrast above the surrounding tiles.
            if (strict or cy < .35*height or direction != direction
                    or _contrast(gray, labels, i, x, y, w, h, unit) < FAINT_CONTRAST):
                continue                               # washed-out glass, walls and sign backing
        if area >= 60*unit*unit and float(hue[y:y + h, x:x + w][inside].std()) > MAX_HUE_SPREAD:
            continue                                   # blotchy colour: a picture or sign, not a flat overlay
        # A clear dash shape passes whatever the floor looks like (green-lit floors give little contrast);
        # anything else must stand out, which a flat green glow on a wall does not.
        if direction != direction and _contrast(gray, labels, i, x, y, w, h, unit) < MIN_CONTRAST:
            continue
        long_side, short_side = max(w, h), max(1, min(w, h))
        if long_side > 10*unit and long_side/short_side < 1.5 and area/(w*h) > .5:
            continue                                   # a filled blob, not a dash
        found.append((float(cx), float(cy), int(area), direction))
    return found


MIN_SATURATION = 62   # real dashes are a rich green (measured 70-120); signs and glass are washed out (43-55)
MAX_HUE_SPREAD = 4.0  # and a flat overlay: the hue barely varies across a dash (measured 1.4-3.1)
MIN_CONTRAST = 14    # a dash is this much brighter (grey levels) than the floor around it
FAINT_CONTRAST = 16  # low-saturation floor dashes measured 16.6-23.5; wall/gear clutter measured <=15.8


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


def _plausible(points, areas, angles, height, width=None):
    """Is this chain shaped like dashes on the floor receding into the distance?

    It must span some depth (a flat row of marks is text), and where the dashes have a measurable
    direction their size must shrink with height on screen (far dashes are small). Text on a sign
    fails both: rows of equal-height lines of random width.
    """
    ys = points[:, 1]
    # A path runs away from the camera, so it climbs the screen at a good rate. A near-flat row of marks
    # (the lettering of a shop sign, a row of lights) climbs hardly at all.
    flat = ys.max() - ys.min() < .25*(points[:, 0].max() - points[:, 0].min())
    big = 1200*(height/1440)**2
    if flat and int(np.sum((areas >= big) & ~np.isnan(angles))) < 2:
        return False                                       # a row of small marks is lettering, not a path
    tolerance = max(4.0, .006*height)
    for centre in ys:                                       # three or more marks on exactly one screen row: text, never a path
        on_row = np.abs(ys - centre) <= tolerance
        if on_row.sum() >= 3 and on_row.sum() >= .6*len(ys) and np.ptp(points[on_row, 0]) >= 60:
            return False
    # (A real path seen across the view is a gently sloping row, and its dashes grow steadily towards the near end.)
    if float(ys.max()) < .30*height:
        return False                                       # all of it high on the screen: on a wall or ceiling, not the floor
    if not flat and ys.max() - ys.min() < .04*height:
        return False
    measured = ~np.isnan(angles)
    # Dashes are spaced out. Text (lettering on a sign) puts many marks a few pixels apart.
    spacing = np.hypot(*np.diff(points[np.argsort(-ys)], axis=0).T)
    if len(spacing) >= 3 and float((spacing < 12*height/1440).mean()) > .30:
        return False
    if len(points) == 2:
        # two big dashes: they must lie well apart, on the floor part of the screen, the nearer one the bigger
        if float(np.hypot(*(points[0] - points[1]))) < 80 or float(ys.min()) < .35*height:
            return False
        return True
    if len(points) == 3:
        # The thin evidence of a three-mark chain must be clean: marks well apart, and the nearer
        # (lower) big dash larger than the farther one.
        order = np.argsort(-ys)
        gaps = np.hypot(*np.diff(points[order], axis=0).T)
        if gaps.min() < 40:
            return False
    if measured.sum() >= 4 and not flat:
        sizes = np.sqrt(areas[measured])
        if np.ptp(ys[measured]) > 0 and np.ptp(sizes) > 0:
            if np.corrcoef(ys[measured], sizes)[0, 1] < .7:
                return False
    return True


def best_chain(candidates, tolerance=7.0, minimum=2, samples=3000, max_turn=np.radians(30), height=1440, tries=25,
               anchor=None, width=None):
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
    # Two do only when both are big dashes, each pointing along the line joining them (a sparse path seen close up).
    def enough(members):
        index = list(members)
        if len(index) >= 4:
            return True
        oriented = int((~np.isnan(angles[index])).sum())
        if len(index) == 3:
            return oriented >= 2
        if len(index) == 2 and oriented == 2 and float(areas[index].min()) >= 1000*(height/1440)**2:
            joint = np.arctan2(points[index[1], 1] - points[index[0], 1], points[index[1], 0] - points[index[0], 0])
            off = np.abs((angles[index] - joint + np.pi/2) % np.pi - np.pi/2)
            return bool(off.max() <= np.radians(22))
        return False
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
        mass = float(np.sum(np.sqrt(areas[list(members)])))          # a few bold dashes outweigh a cluster of specks
        ranked.append((mass + bonus*5, members))
        if len(seen) >= tries*2:
            break
    for _, members in sorted(ranked, key=lambda item: -item[0])[:tries]:
        index = list(members)
        if _plausible(points[index], areas[index], angles[index], height, width):
            chosen = points[index]
            return [tuple(p) for p in chosen[np.argsort(-chosen[:, 1])]]
    return []


def _continuation(candidates, prior, height, width):
    """The next stretch of the path being followed when too few dashes show to make a chain (a corner, a
    pillar): marks on the prior line, pointing along it, with at least one clear dash among them.
    Never used to start following a path, only to carry on with one."""
    line = np.arctan2(1.0, prior.slope)                    # direction of the prior line in image axes
    picks = []
    big = 300*(width/2000)**2                              # a real dash, not a speck of lettering
    for x, y, area, angle in sorted(candidates, key=lambda c: -c[1]):
        if y > .90*height or y < .30*height or area < big:
            continue
        if angle == angle:
            if abs((angle - line + np.pi/2) % np.pi - np.pi/2) > np.radians(35):
                continue                                   # a dash, but pointing some other way
        if angle == angle:
            picks.append((x, y))                           # only clear dashes: loose small marks are mostly noise
    return picks[:3]


def _curved(candidates, width, height):
    """Big dashes of a path that bends (round a corner or into a doorway): they do not lie on one straight line, so
    best_chain finds nothing. Take the clear dashes (large, elongated, in the floor part of the screen) that are
    near the character, nearest first, as the next stretch of the path. At least two are needed, and they must
    be reasonably close together: scattered marks are not a path."""
    big = 560*(width/1920)**2
    anchor = (.5*width, .85*height)
    largest = 9000*(width/1920)**2                          # bigger than any real dash: a poster or a sign panel
    picks = [(float(np.hypot(x - anchor[0], y - anchor[1])), x, y, a) for x, y, a, angle in candidates
             if angle == angle and big <= a <= largest and .35*height <= y <= .97*height]
    picks.sort()
    picks = [p for p in picks if p[0] <= .75*width]
    chain, areas = [], []
    for distance, x, y, a in picks:
        if not chain or np.hypot(x - chain[-1][0], y - chain[-1][1]) <= .30*width:
            chain.append((x, y))
            areas.append(a)
        if len(chain) >= 4:
            break
    # A path close enough to bend round the character has a really big dash among its first few marks.
    return chain if len(chain) >= 2 and max(areas) >= 2.5*big else []


def _bend(candidates, width, height):
    """Follow nearby oriented dashes through a change of direction.

    Each step must be spaced like a dash, approach the horizon and point along
    the preceding dash. Allow the next dash to turn at the junction. A real
    change of orientation is required, so ordinary straight chains use best_chain.
    """
    unit = width/1920
    anchor = (.5*width, .85*height)
    picks = [(x, y, area, angle) for x, y, area, angle in candidates
             if angle == angle and 200*unit*unit <= area <= 9000*unit*unit
             and .35*height <= y <= .97*height]
    if not picks:
        return []
    picks.sort(key=lambda p: np.hypot(p[0] - anchor[0], p[1] - anchor[1]))
    if np.hypot(picks[0][0] - anchor[0], picks[0][1] - anchor[1]) > .35*width:
        return []
    chain = [picks.pop(0)]
    while picks and len(chain) < 6:
        x, y, _, angle = chain[-1]
        options = []
        for candidate in picks:
            x2, y2, _, angle2 = candidate
            distance = np.hypot(x2 - x, y2 - y)
            if not .018*width <= distance <= .18*width or y2 > y + .02*height:
                continue
            direction = np.arctan2(y2 - y, x2 - x)
            turn1 = abs((angle - direction + np.pi/2) % np.pi - np.pi/2)
            turn2 = abs((angle2 - direction + np.pi/2) % np.pi - np.pi/2)
            if turn1 <= .55 and turn2 <= 1.2:
                options.append((distance, candidate))
        if not options:
            break
        _, chosen = min(options, key=lambda item: item[0])
        chain.append(chosen)
        picks.remove(chosen)
    angles = [candidate[3] for candidate in chain]
    bent = any(abs((a - b + np.pi/2) % np.pi - np.pi/2) >= .5 for a in angles for b in angles)
    return [(x, y) for x, y, _, _ in chain] if len(chain) >= 3 and bent else []


def find_path(frame, ignore=(), prior=None, tube=.18, color="green"):
    """PathView for a BGR frame, or None when no path is visible in front of the character.

    The dashes ahead of the character are the way on. A chain lying wholly below the character's feet
    is behind it and is not followed. With `prior` (the view being followed) only marks within `tube`
    (a fraction of the width) of its line are considered, so the macro stays on the path it is
    following and ignores everything else.

    The character goes from one dash to the next: the target is the nearest dash ahead (above the
    character's feet), and as it is reached the next one becomes the target.
    """
    candidates = dash_candidates(frame, ignore, color)
    height, width = frame.shape[:2]
    if prior is not None:
        candidates = [c for c in candidates if abs(c[0] - (prior.slope*c[1] + prior.intercept)) <= tube*width]
    chain = best_chain(candidates, height=height, anchor=(.5*width, .72*height), width=width)
    bend = _bend(candidates, width, height)
    anchor = (.5*width, .85*height)
    if bend and (not chain or np.hypot(bend[0][0] - anchor[0], bend[0][1] - anchor[1]) + .06*width
                 < min(np.hypot(x - anchor[0], y - anchor[1]) for x, y in chain)):
        chain = bend  # do not skip the approach in favour of a long, distant leg beyond the corner
    if not chain:
        chain = _curved(candidates, width, height)           # a bending path: the next clear dashes, nearest first
        chain = sorted(chain, key=lambda point: -point[1]) if chain else chain    # nearest (lowest) first, like a straight chain
    if not chain and prior is not None:
        chain = _continuation(candidates, prior, height, width)    # one or two dashes of the path already being followed
    if not chain:
        return None
    ys = np.array([p[1] for p in chain])
    xs = np.array([p[0] for p in chain])
    if ys.min() > .80*height:
        return None                                        # all of it is at or behind the character's feet
    if ys.max() - ys.min() < .25*(xs.max() - xs.min()):
        # A path running across the view lies in a flat row: its near end is the one by the character, not the lowest.
        chain = sorted(chain, key=lambda p: np.hypot(p[0] - .5*width, p[1] - .80*height))
    if len(chain) >= 2 and np.ptp(ys) > 0:
        slope, intercept = np.polyfit(ys, xs, 1)           # kept for tracking: where the line runs
    elif prior is not None:
        slope, intercept = prior.slope, prior.intercept    # too few marks to fit: the path keeps its line
    else:
        slope, intercept = 0.0, float(xs.mean())           # a single mark: a vertical line through it
    centre = width/2
    ahead = [p for p in chain if p[1] <= REACH_Y*height]    # chain is nearest first
    target = ahead[0] if ahead else chain[-1]
    near_x = min(max(float(slope*.75*height + intercept), 0.0), float(width))
    return PathView(tuple(chain), (float(target[0]), float(target[1])), (target[0] - centre)/width,
                    (near_x - centre)/width, float(slope), float(intercept), chain[-1])
