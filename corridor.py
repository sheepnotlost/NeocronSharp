"""Follow the natural path of a corridor when the Nav-Ray dashes are gone (near a zone change).

Zone-line corridors have a light grey tiled floor with a faint lilac tint: Lab a*-b* about -2.5..+1.5,
against -7..-3.5 for the beige concrete walls and about -3 for the plain grey ones (measured on the four
2026-10-28 clips). The floor is masked by that tint relative to the floor right in front of the character,
and for each column the unbroken floor running up the screen is the free space that way; the column where
it reaches highest is the corridor's far end. With no floor ahead (a wall), the side with floor in view
is the open side, else the lines of the wall itself say which way it recedes.

corridor_heading(frame_bgr) -> (error, confidence, debug) is the entry point.
"""
import cv2
import numpy as np


W, H = 320, 180          # working resolution: 15 ms per 2560x1440 frame, 9-12 ms per 1920x1080
BASE_Y = .78             # the bottom 22% is HUD (chat, status) and the character's legs
CUT = 1.5                # floor: a*-b* within this of the floor beside the character (tiles spread about 1)
MIN_REACH = .12          # free floor reaching less than this (fraction of the height) is a wall in front
MIN_AHEAD = .07          # ... and the middle 30% of the view must have at least this much
TURN_REACH = .20         # floor ending lower than this with floor running off a side: the corridor turns


def _hud_mask(h, w):
    """True where the HUD is (fractions of the frame)."""
    ys = (np.arange(h) + .5)[:, None] / h
    xs = (np.arange(w) + .5)[None, :] / w
    return (ys < .06) | ((xs < .20) & (ys < .20)) | (ys > BASE_Y) | (xs > .92)


_HUD = _hud_mask(H, W)


def floor_mask(small_bgr):
    """Boolean floor mask at the working resolution, plus (pinker class median, other class median)."""
    lab = cv2.cvtColor(small_bgr.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)   # L 0-100, a/b signed
    lum = cv2.blur(lab[..., 0], (3, 3))
    red = cv2.blur(lab[..., 1], (5, 5))
    pink = cv2.blur(lab[..., 1] - lab[..., 2], (5, 5))
    hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
    loud = (hsv[..., 1] > 90) & (hsv[..., 2] > 60)          # HUD green, Nav-Ray dashes, skin
    usable = ~_HUD & ~loud & (lum > 12) & (red > -1.0)      # copbot blue-grey paint: a* about -2
    usable[:int(.28 * H)] = False                            # the horizon sits at about .3h: no floor above
    # The clips differ by about 3 in overall a*-b*, so no fixed cut works: Otsu splits the view in two
    # by tint, the pinker class must be clearly apart from the rest and show up beside the character.
    vals = pink[usable]
    if vals.size < 500:
        return np.zeros((H, W), bool), (None, None)
    u8 = np.clip((vals + 10) * 17, 0, 255).astype(np.uint8)
    t, _ = cv2.threshold(u8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = t / 17 - 10
    hi, lo = vals[vals > t], vals[vals <= t]
    if hi.size < 150 or lo.size < 150:
        return np.zeros((H, W), bool), (None, None)
    m_hi, m_lo = float(np.median(hi)), float(np.median(lo))
    y0, y1, x0, x1 = int(.50 * H), int(BASE_Y * H), int(.10 * W), int(.90 * W)
    near = usable[y0:y1, x0:x1] & (pink[y0:y1, x0:x1] > t)
    # class medians 1.6 apart on the faintest real floor seen (C 30.5 s); a blank wall splits about 1 apart
    if m_hi - m_lo < 1.5 or m_hi < -3.0 or near.sum() < 150:
        return np.zeros((H, W), bool), (m_hi, m_lo)
    ref_lum = float(np.median(lum[y0:y1, x0:x1][near]))
    # upper quartile: the near band also catches the foot of the walls, which only pulls the median down
    ref_pink = float(np.percentile(pink[y0:y1, x0:x1][near], 75))
    cut = max(t, ref_pink - CUT)
    mask = usable & (pink > cut) & (lum > max(22.0, ref_lum - 10)) & (lum < ref_lum + 20)
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask[_HUD] = 0
    return mask.astype(bool), (m_hi, m_lo)


def free_profile(mask):
    """Per column: how far up from BASE_Y (fraction of the height) the floor around the character runs."""
    h, w = mask.shape
    base = int(BASE_Y * h)
    count, labels, _, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=4)
    # floor pieces that reach the band just above the HUD: the ground the character stands on
    band = labels[int(.62 * h):base]
    keep = np.zeros(count, bool)
    ids, hits = np.unique(band[band > 0], return_counts=True)
    keep[ids[hits >= 40]] = True
    kept = keep[labels][:base]
    # the unbroken run up from each column's lowest floor pixel (the character hides the floor at the
    # bottom centre, so the run starts wherever the floor does); grout and dashes are closed first
    kept = cv2.morphologyEx(kept.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 1), np.uint8)).astype(bool)
    rows = np.arange(base)[:, None]
    low = np.where(kept.any(0), base - 1 - kept[::-1].argmax(0), -1)
    gap = np.where(~kept & (rows < low), rows, -1).max(0)
    top = np.where(low >= 0, gap + 1, base)
    return (base - top) / h


def _segments(edges, min_len, votes, used, sign):
    """Hough segments of a binary edge map; adds sign * (how far each falls left to right) to votes."""
    lines = cv2.HoughLinesP(edges.astype(np.uint8), 1, np.pi / 180, 20, minLineLength=min_len, maxLineGap=4)
    for x1, y1, x2, y2 in ([] if lines is None else lines.reshape(-1, 4).astype(float)):
        dx, dy = abs(x2 - x1), (y2 - y1) * (1 if x2 > x1 else -1)
        if dx < 1 or abs(dy) > .6 * dx:           # wall corners and outlines of people stand upright
            continue
        votes.append(sign * dy * np.hypot(dx, dy) / dx)
        if used is not None:
            used.append((x1 / W, y1 / H, x2 / W, y2 / H))


def wall_lean(small_bgr, used=None):
    """Which side a blank wall ahead opens towards (-1 left, +1 right, 0 unknown), from its lines.
    A wall that comes closer runs down the screen below the horizon (the dark trim line at waist height)
    and up the screen above it (the stepped cornice under the ceiling). Lines falling to the right below,
    or rising to the right above, say the right side is closed in. On the wall frames of A 28.5-40.5 s and
    B 27.5-33.5 s: 13 of 19 right, 2 unknown, 4 wrong (inside corners, a copbot at arm's length).
    Floor in view decides first, so this only breaks ties on blank walls."""
    gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
    lab = cv2.cvtColor(small_bgr.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)
    # copbot armour: light and colourless, with dark plates whose edges look like wall lines
    armour = (lab[..., 0] > 62) & (np.abs(lab[..., 1]) + np.abs(lab[..., 2]) < 12)
    armour[:int(.35 * H)] = False
    armour = cv2.dilate(armour.astype(np.uint8), np.ones((9, 15), np.uint8)).astype(bool)
    votes = []
    trim = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, np.ones((5, 5), np.uint8)) > 10
    trim &= ~_HUD & ~armour
    trim[:int(.40 * H)] = False
    _segments(trim, W * .15, votes, used, 1)
    cornice = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 100) > 0
    cornice &= ~_HUD
    cornice[int(.38 * H):] = False
    _segments(cornice, W * .15, votes, used, -1)
    vote = float(sum(votes))
    return 0 if abs(vote) < 6 else (-1 if vote > 0 else 1)


def corridor_heading(frame_bgr):
    """Where the corridor leads, for a third-person frame of any size.

    Returns (error, confidence, debug). error is the heading to steer towards as a fraction of the width
    relative to the screen centre (-.5..+.5, negative = left), or None when no open way is visible (a wall
    or a copbot in front); debug["side"] then says which side looks more open (-1 left, +1 right, 0 unknown).
    confidence is 0..1 (free floor reaching .3 of the height or more is 1). debug also holds "reach" (the
    smoothed free-floor profile per working column, fractions of the height above BASE_Y), "mask",
    "best" (the chosen column), "ahead" (most free floor in the middle 30%) and "lines" when the wall's
    lines were read."""
    small = cv2.resize(frame_bgr, (W, H), interpolation=cv2.INTER_AREA)
    mask, ref = floor_mask(small)
    reach = free_profile(mask)
    k = max(3, W // 20) | 1
    smooth = np.convolve(np.pad(reach, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
    xs = (np.arange(W) + .5) / W
    score = smooth - .05 * np.abs(xs - .5)          # ties go to the current heading
    best = int(score.argmax())
    ahead = float(smooth[np.abs(xs - .5) <= .15].max())
    debug = {"reach": smooth, "mask": mask, "best": best, "ahead": ahead, "ref": ref, "side": 0}
    if smooth[best] >= MIN_REACH and ahead >= MIN_AHEAD:
        # floor running off a side of the view at over half the height it reaches anywhere, with the floor
        # ending close in front: the corridor turns out of view that way (D 159-166 s)
        left, right = smooth[:int(.10 * W)], smooth[int(.78 * W):int(.90 * W)]
        reach_edge, col = max((float(left.max()), int(left.argmax())),
                              (float(right.max()), int(.78 * W) + int(right.argmax())))
        if smooth[best] < TURN_REACH and reach_edge >= .55 * smooth[best]:
            best = col
            debug["best"] = col
        error = float(xs[best] - .5)
        debug["side"] = -1 if error < 0 else 1
        return error, float(min(1.0, smooth[best] / .3)), debug
    # a wall in front: turn towards floor seen off to one side, else read the wall's own lines
    if smooth[best] >= .06:
        debug["side"] = -1 if xs[best] < .5 else 1
    else:
        debug["lines"] = []
        debug["side"] = wall_lean(small, debug["lines"])
    return None, 0.0, debug
