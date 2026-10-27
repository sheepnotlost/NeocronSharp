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
    error: float       # aim x relative to the view centre, as a fraction of the width (-.5 .. .5)


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
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
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
        found.append((float(cx), float(cy), int(area)))
    return found


def best_chain(candidates, tolerance=7.0, minimum=4):
    """Largest set of candidates on one line, nearest (lowest on screen) first; [] if too few."""
    points = np.array([(c[0], c[1]) for c in candidates], dtype=float)
    best = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            delta = points[j] - points[i]
            length = float(np.hypot(*delta))
            if length < 15:
                continue
            normal = np.array([-delta[1], delta[0]])/length
            inliers = np.where(np.abs((points - points[i]) @ normal) <= tolerance)[0]
            if len(inliers) > len(best):
                best = inliers
    if len(best) < minimum:
        return []
    chosen = points[best]
    return [tuple(p) for p in chosen[np.argsort(-chosen[:, 1])]]


def find_path(frame, ignore=()):
    """PathView for a BGR frame, or None when no path is visible."""
    chain = best_chain(dash_candidates(frame, ignore))
    if not chain:
        return None
    height, width = frame.shape[:2]
    # Aim at the first dash at or above mid-screen: far enough to steer smoothly, near enough to follow bends.
    aim = next((p for p in chain if p[1] <= .5*height), chain[-1])
    return PathView(tuple(chain), aim, (aim[0] - width/2)/width)
