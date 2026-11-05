"""Where the game's own pointer is, by sight, so a click lands where it was meant to (the user's ask, 5 Nov).

Neocron draws its own pointer: a small, solid, bright green arrow with a dark edge, its tip at the top left. On one PC the
pointer did not follow Windows' cursor and the moves went elsewhere. So before a click the job loop looks for the arrow,
steers it onto the target, and clicks only once it is there.
"""
import numpy as np

from vision import cv2

GREEN, GREEN_OVER_RED, GREEN_OVER_BLUE = 165, 70, 40     # the arrow: (70-90, 180-230, 100-130). Speech is near white, the panels dim
TALLEST, SHORTEST = 48, 8          # pixels: the arrow is 17 high in a 1080 recording of 2560x1440 at UI scale 1.7
SOLID = (.3, .75)                  # of its box: a triangle fills half of it; a lit button all of it, a line next to none
TALL = (1.0, 2.4)                  # its height over its width
STILL = 2                          # pixels: a shape that moved less than this between two looks is part of the screen


def green_mask(frame):
    """The arrow's green, fast: Windows' screenshots are big, and the pointer is looked for every few hundredths of a second."""
    red, green, blue = frame[..., 0], frame[..., 1], frame[..., 2]
    return ((green > GREEN) & (cv2.subtract(green, red) > GREEN_OVER_RED) & (cv2.subtract(green, blue) > GREEN_OVER_BLUE)).astype(np.uint8)


def candidates(frame, region=None):
    """[(tip_x, tip_y, high)] of every arrow-shaped green shape, in the frame's pixels. region (left, top, right, bottom)
    looks only there."""
    left0, top0 = 0, 0
    if region is not None:
        height, width = frame.shape[:2]
        left0, top0 = max(0, int(region[0])), max(0, int(region[1]))
        frame = frame[top0:min(height, int(region[3])), left0:min(width, int(region[2]))]
        if frame.size == 0:
            return []
    full = green_mask(frame)
    mask = cv2.morphologyEx(full, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))        # one-pixel lines go
    count, parts, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for i in range(1, count):
        left, top, wide, high, area = (int(v) for v in stats[i])
        if not (SHORTEST <= high <= TALLEST and wide >= 4 and TALL[0] <= high/wide <= TALL[1]):
            continue
        if not SOLID[0] <= area/(wide*high) <= SOLID[1]:
            continue
        # A pointer is widest low down and comes to a point at its top left: its first row is a pixel or two at the left.
        first = (parts[top, left:left+wide] == i).nonzero()[0]
        if first.size == 0 or first.size > max(3, wide//3) or first[0] > wide//3:
            continue
        # The tip itself, a pixel wide, went with the lines: it is the top of the green just above and left of the shape.
        x0, y0 = max(0, left-2), max(0, top-6)
        above = full[y0:top+1, x0:left+max(3, wide//3)+1]
        rows, columns = above.nonzero()
        tip = (x0+int(columns[rows == rows.min()].min()), y0+int(rows.min())) if rows.size else (left+int(first[0]), top)
        found.append((left0+tip[0], top0+tip[1], high))
    return found


def find(frame, near=None, before=None):
    """The pointer's tip (x, y), or None when none shows: mouse-look hides it. With before (a look from before the pointer
    was moved), a shape still where it was is the screen's, not the pointer. Of several, the one nearest near."""
    found = candidates(frame)
    if before is not None and found:
        old = candidates(before)
        moved = [c for c in found if all(abs(c[0]-o[0]) >= STILL or abs(c[1]-o[1]) >= STILL for o in old)]
        found = moved or found
    if not found:
        return None
    if near is not None:
        found.sort(key=lambda c: (c[0]-near[0])**2+(c[1]-near[1])**2)
    return found[0][:2]


def close(one, other, within=STILL):
    return abs(one[0]-other[0]) < within and abs(one[1]-other[1]) < within


def moves(before, after, start=None, region=None):
    """[(from, to)] of arrow shapes that left one place and showed up at another, at the same size: the pointer, when it moved.
    With start, only a shape that left there. region: look only there."""
    old, new = candidates(before, region), candidates(after, region)
    gone = [c for c in old if not any(close(c, o) for o in new)]
    came = [c for c in new if not any(close(c, o) for o in old)]
    if start is not None:
        gone = [c for c in gone if close(c, start, 4)] or ([(start[0], start[1], None)] if came else [])
    return [(g[:2], c[:2]) for g in gone for c in came if g[2] is None or abs(g[2]-c[2]) <= 2]
