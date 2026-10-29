"""Tracking orbs: the Nav-Ray dashes as fixed points on the floor, kept in world coordinates.

Each dash seen on screen is a measurement of one point on the floor. With the live position and heading
(telemetry) and a fitted camera model, every dash becomes a world point; repeated sightings merge into one
"orb" (count = confidence). A smoothed route through the orbs ahead is steered by the live position and
heading, so dashes hidden behind the character or off screen still count.

Conventions (verified on the 28 Oct cal1 recording, 285 frames): heading 0 = -Z, 90 = +X; forward =
(sin h, -cos h) in (x, z): the direction of motion matched the heading to within 0.5 deg on straight runs
(frames 125-130, 265.2 vs 265.2). The character's right is (cos h, sin h): the mirrored model's best grid cost
was 11% worse and its refinement collapsed to a 5-unit-high camera. Floor = the ground plane X/Z (telemetry y
-255.9 on flat floor, not needed). Running speed 255-290 units/s.

Limits measured on cal1: dashes of one steady frame land 35 units (40-200 ahead), 48 (200-400), 57 (400-700)
and 79 (700-1300) from the nearest dash of the next frame or two (median); dashes are ~70 apart. In a turn
the telemetry heading trails the screen (~0.1-0.2 s), so turning frames are not placed.
"""
from dataclasses import dataclass, field

import numpy as np

REF_W, REF_H = 1920, 1080          # the camera model is fitted in these pixels; other sizes are scaled (same aspect)


def forward(heading):
    """Unit (dx, dz) the character faces, heading in degrees."""
    h = np.radians(heading)
    return np.array([np.sin(h), -np.cos(h)])


def right(heading):
    """Unit (dx, dz) to the character's right."""
    h = np.radians(heading)
    return np.array([np.cos(h), np.sin(h)])


def heading_to(dx, dz):
    """Heading in degrees (0..360) of the direction (dx, dz)."""
    return float(np.degrees(np.arctan2(dx, -dz)) % 360)


def wrap(angle):
    """Degrees into -180..180."""
    return (angle + 180.0) % 360.0 - 180.0


def pose(sample):
    """(sector, x, z, heading) from a telemetry.Sample or a dict with the same fields."""
    get = (lambda k: sample[k]) if isinstance(sample, dict) else (lambda k: getattr(sample, k))
    return int(get("sector")), float(get("x")), float(get("z")), float(get("heading"))


def _field(sample, name):
    """A sample's optional field, or None."""
    return sample.get(name) if isinstance(sample, dict) else getattr(sample, name, None)


@dataclass(frozen=True)
class Camera:
    """Pinhole camera behind the character, looking along its heading, pitched down.
    Pixels are REF_W x REF_H; the principal point is the image centre plus `rise` px down."""
    pitch: float = 0.0              # radians below the horizontal
    height: float = 60.0            # units above the floor
    back: float = 150.0             # units behind the character (along -forward)
    focal: float = 900.0            # px at REF_W
    side: float = 0.0               # units to the character's right
    yaw: float = 0.0                # degrees added to the heading
    rise: float = 0.0               # principal point offset, px down from the centre

    def to_floor(self, points, size=(REF_W, REF_H)):
        """(N, 2) floor offsets (forward, right) from the character, in units, for pixel points (N, 2).
        NaN for points at or above the horizon."""
        pts = np.asarray(points, float).reshape(-1, 2) * (REF_W/size[0])
        a = (pts[:, 1] - (REF_H/2 + self.rise))/self.focal
        b = (pts[:, 0] - REF_W/2)/self.focal
        cp, sp = np.cos(self.pitch), np.sin(self.pitch)
        down = sp + a*cp                                  # the ray's downward component
        t = np.where(down > 1e-4, self.height/np.where(down > 1e-4, down, 1.0), np.nan)
        return np.stack([-self.back + t*(cp - a*sp), self.side + t*b], 1)

    def from_floor(self, offsets, size=(REF_W, REF_H)):
        """Pixels (N, 2) for floor offsets (forward, right); NaN behind the camera."""
        off = np.asarray(offsets, float).reshape(-1, 2)
        fw, lat = off[:, 0] + self.back, off[:, 1] - self.side
        cp, sp = np.cos(self.pitch), np.sin(self.pitch)
        depth = fw*cp + self.height*sp                    # along the optical axis
        down = -fw*sp + self.height*cp                    # along the image's down axis
        ok = depth > 1.0
        depth = np.where(ok, depth, np.nan)
        u = REF_W/2 + self.focal*lat/depth
        v = REF_H/2 + self.rise + self.focal*down/depth
        return np.stack([u, v], 1) * (size[0]/REF_W)

    def to_world(self, points, x, z, heading, size=(REF_W, REF_H)):
        """World (x, z) of pixel points seen with the character at (x, z) facing `heading`."""
        off = self.to_floor(points, size)
        h = heading + self.yaw
        return np.array([x, z]) + off[:, :1]*forward(h) + off[:, 1:]*right(h)

    def to_image(self, world, x, z, heading, size=(REF_W, REF_H)):
        """Pixels of world (x, z) points; NaN for points behind the camera."""
        d = np.asarray(world, float).reshape(-1, 2) - np.array([x, z])
        h = heading + self.yaw
        return self.from_floor(np.stack([d @ forward(h), d @ right(h)], 1), size)


# Fitted on cal1 (141 frames with dashes, sectors 101 and 1) by Nelder-Mead: the same dashes seen from different
# positions (frame pairs < 3 s apart, nearest-neighbour distance truncated at 60 units) must land together, and
# near the walked track; feet held at v = 870 px (6 frames) and the horizon at v = 345 px (vanishing point of
# evenly spaced dashes, 6 frames: 322-364). Focal profile (cost): 650 3267, 800 3284, 950 3277, 1100 3320 - flat,
# so the focal is weakly determined (lateral scale +-15%); 800 px = 100 deg across. The screen showed the
# character ~0.12 s AHEAD of the telemetry sample taken just after it (LAG < 0: positions are extrapolated).
CAMERA = Camera(pitch=0.240, height=71.0, back=97.2, focal=800.0, side=-3.0, yaw=-1.1)
LAG = -0.116


@dataclass
class Orb:
    x: float
    z: float
    count: int = 1                  # sightings merged into it
    born: int = 0                   # tracker frame of the first sighting
    seen: int = 0                   # tracker frame of the latest sighting
    visited: bool = False           # the character has been at it: never part of the route again
    weight: float = 1.0             # summed trust of the sightings (near ones count more)
    misses: int = 0                 # frames that should have shown it but did not


@dataclass(frozen=True)
class Steer:
    error: float                    # degrees to turn, + = right (clockwise seen from above)
    point: tuple                    # the look-ahead point (x, z)
    confidence: float               # 0..1, from the sightings behind the route near the character


@dataclass
class PathTracker:
    camera: Camera = CAMERA
    merge: float = 30.0             # a sighting this close to an orb is that orb (units, near the character)
    spread: float = 500.0           # ... and the radius grows (1 + distance/spread): far sightings are coarser
    confirm_after: int = 6          # frames an orb seen once may wait for a second sighting
    max_range: float = 1300.0       # sightings farther ahead are too coarse (1 px of v = 20+ units there)
    near: float = 40.0              # sightings closer ahead than this are at the feet: never added
    reach: float = 60.0             # the character this close to an orb has passed it
    link: float = 360.0             # the longest gap the route bridges between orbs
    min_count: int = 2              # sightings an orb needs to be on the route
    steady: float = 30.0            # deg: a frame whose heading moved more since the last one is not placed
    frame: int = 0
    sectors: dict = field(default_factory=dict)
    last_heading: float | None = None   # heading of the previous update, for `steady`
    lag: float = LAG                # s the screen trails the sample (negative: it leads; positions are extrapolated)
    last_seen: tuple | None = None  # (when, x, z, sector) of the previous sample, for the velocity behind `lag`
    align: float = 15.0             # deg: search this far for the yaw that puts a frame's dashes on the orbs (0 = off)
    correction: float = 0.0         # the yaw correction applied to the last frame, degrees
    placed: tuple | None = None     # (sector, x, z, heading) of the last frame whose dashes were placed

    def update(self, sample, points, size=(REF_W, REF_H), before=None):
        """Add one frame's dash points (pixels) seen with the character at `sample` (telemetry taken just after
        the screenshot; `before`, optional, the one taken just before it). Returns how many sightings were used:
        none while the heading turns (cal1: the screen leads the telemetry heading by ~0.1-0.2 s in a turn)."""
        self.frame += 1
        sector, x, z, heading = pose(sample)
        orbs = self.sectors.setdefault(sector, [])
        here = np.array([x, z])
        turning = self.last_heading is not None and abs(wrap(heading - self.last_heading)) > self.steady
        if before is not None:
            turning = turning or abs(wrap(heading - pose(before)[3])) > 1.0
        self.last_heading = heading
        when = _field(sample, "when")
        at = here
        if (when is not None and self.last_seen is not None and self.last_seen[3] == sector
                and 0 < when - self.last_seen[0] < 1.0):
            velocity = (here - self.last_seen[1:3])/(when - self.last_seen[0])
            at = here - velocity*self.lag                  # where the character was when the screen was drawn
        self.last_seen = None if when is None else (when, x, z, sector)
        for orb in orbs:
            if not orb.visited and np.hypot(orb.x - x, orb.z - z) <= self.reach:
                orb.visited = True
        used = 0
        pts = np.asarray(points, float).reshape(-1, 2)
        if (self.placed is not None and self.placed[0] == sector and np.hypot(x - self.placed[1], z - self.placed[2]) < 10
                and abs(wrap(heading - self.placed[3])) < 1.0):
            turning = True                                 # the same view again: no new evidence, counts would inflate
        if len(pts) and not turning:    # mid-turn the screen and the telemetry heading disagree (cal1: up to ~13 deg)
            off = self.camera.to_floor(pts, size)
            self.correction = self._align(orbs, pts, at, heading, size, off) if self.align else 0.0
            world = self.camera.to_world(pts, at[0], at[1], heading + self.correction, size)
            self.placed = (sector, x, z, heading)
            hit = set()
            for (fw, _), w in zip(off, world):
                if not np.isfinite(fw) or fw < self.near or fw > self.max_range:
                    continue                              # behind, at the feet, or too far to place
                if np.hypot(*(w - here)) <= self.reach:
                    continue
                trust = 1.0/(1.0 + (fw/self.spread)**2)  # 1 px of v covers ~(distance)^2 more floor far away
                radius = self.merge*(1.0 + fw/self.spread)
                best, gap = None, np.inf
                for orb in orbs:
                    d = np.hypot(orb.x - w[0], orb.z - w[1])
                    if d <= radius and d < gap:
                        best, gap = orb, d
                if best is None:
                    orbs.append(Orb(float(w[0]), float(w[1]), 1, self.frame, self.frame, weight=trust))
                    hit.add(id(orbs[-1]))
                else:
                    if not best.visited:              # a passed orb stays where it was confirmed
                        k = best.weight
                        best.x, best.z = (best.x*k + w[0]*trust)/(k + trust), (best.z*k + w[1]*trust)/(k + trust)
                        best.weight = k + trust
                    best.count += 1
                    best.seen = self.frame
                    hit.add(id(best))
                used += 1
            if used >= 2:
                self._misses(orbs, hit, at, heading + self.correction, size)
        self.sectors[sector] = [o for o in orbs if (o.count > 1 or self.frame - o.born <= self.confirm_after)
                                and not (o.misses >= 2 and o.misses >= o.count)]
        return used

    def _misses(self, orbs, hit, at, heading, size):
        """An orb that should be in plain view this frame (on screen, 60-600 ahead, clear of the HUD and the
        character) but was not seen gets a miss; one missed as often as seen is dropped. A misplaced orb (a frame
        whose heading was off) is not seen again where it was put, so it goes; a real dash is seen again."""
        live = [o for o in orbs if not o.visited and id(o) not in hit]
        if not live:
            return
        w, h = size
        world = np.array([[o.x, o.z] for o in live])
        d = world - at
        fw = d @ forward(heading + self.camera.yaw)
        px = self.camera.to_image(world, at[0], at[1], heading, size)
        for orb, ahead, (u, v) in zip(live, fw, px):
            if not (60 <= ahead <= 600) or not np.isfinite(u):
                continue
            fx, fy = u/w, v/h
            if not (.03 < fx < .88 and .3 < fy < .97) or (fx < .47 and fy > .76) or (fx > .84 and fy > .78):
                continue                                   # off screen or under the HUD panels
            if abs(fx - .5) < .07 and fy > .45:
                continue                                   # behind the character's body
            orb.misses += 1

    def _align(self, orbs, pts, at, heading, size, off):
        """Degrees to add to the heading so that this frame's sightings land on the confirmed orbs, or 0.
        The telemetry heading trails the screen in turns (cal1: best match with the heading ~0.15 s later), so
        each frame's yaw is checked against what is already known. One degree of freedom (a rotation about the
        character) cannot slide the dashes along their line by a whole dash."""
        known = np.array([[o.x, o.z] for o in orbs if o.count >= self.min_count])
        use = np.isfinite(off[:, 0]) & (off[:, 0] >= self.near) & (off[:, 0] <= self.max_range)
        if len(known) < 3 or use.sum() < 3:
            return 0.0
        pts = pts[use]

        def score(turn):
            w = self.camera.to_world(pts, at[0], at[1], heading + turn, size)
            d = np.hypot(*(w[:, None] - known[None]).transpose(2, 0, 1)).min(1)
            return float(np.clip(1 - (d/self.merge)**2, 0, None).sum())

        turns = np.arange(-self.align, self.align + .5, 1.0)
        scores = np.array([score(t) for t in turns])
        best = int(np.argmax(scores))
        if scores[best] < score(0.0) + 1.0 or scores[best] < 2.0:
            return 0.0                                     # not clearly better than the telemetry
        return float(turns[best])

    def orbs(self, sector=None):
        """Copies of the orbs, of one sector or all."""
        keys = self.sectors if sector is None else [sector]
        return [Orb(**vars(o)) for k in keys for o in self.sectors.get(k, [])]

    def route(self, sample):
        """(M, 2) world polyline ahead of the character through the confirmed orbs, nearest first; empty if none.
        Greedy chain from the character: each step takes the closest orb within `link` that does not turn
        back (turns cost extra); orbs off the chain are outliers. Then kinks (a stray orb the chain stepped
        to and back from) are dropped and the chain is smoothed, weighted by sightings."""
        sector, x, z, heading = pose(sample)
        pool = [o for o in self.sectors.get(sector, []) if o.count >= self.min_count and not o.visited
                and np.hypot(o.x - x, o.z - z) <= self.max_range + self.camera.back]
        if not pool:
            return np.zeros((0, 2))
        pts = np.array([[o.x, o.z] for o in pool])
        weight = np.array([min(o.count, 8) for o in pool], float)
        cur, way = np.array([x, z]), forward(heading)
        free = np.ones(len(pts), bool)
        chain = []
        while free.any():
            d = pts - cur
            dist = np.hypot(d[:, 0], d[:, 1])
            cos = (d @ way)/np.maximum(dist, 1e-9)
            limit = .0 if not chain else -.2              # the first orb must be ahead; later ones may bend ~100 deg
            ok = free & (dist <= self.link) & (cos > limit)
            if not ok.any():
                break
            score = np.where(ok, dist*(1 + 1.5*(1 - cos)), np.inf)
            k = int(np.argmin(score))
            chain.append(k)
            free[k] = False
            step = pts[k] - cur
            way = step/np.hypot(*step) if np.hypot(*step) > 1e-6 else way
            cur = pts[k]
        if not chain:
            return np.zeros((0, 2))
        line, w = _drop_kinks(np.vstack([[x, z], pts[chain]]), np.concatenate([[1e9], weight[chain]]))
        return _smooth(line, w)[1:]

    def steer(self, sample, lookahead=180.0):
        """Steer(error, point, confidence) towards the route point `lookahead` units on, or None without a route."""
        sector, x, z, heading = pose(sample)
        line = self.route(sample)
        if not len(line):
            return None
        poly = np.vstack([[x, z], line])
        seg = np.hypot(*np.diff(poly, axis=0).T)
        run = np.concatenate([[0], np.cumsum(seg)])
        if run[-1] <= lookahead:
            point = poly[-1]
        else:
            i = int(np.searchsorted(run, lookahead)) - 1
            t = (lookahead - run[i])/max(seg[i], 1e-9)
            point = poly[i] + t*(poly[i + 1] - poly[i])
        near = [o for o in self.sectors.get(sector, []) if o.count >= self.min_count and not o.visited
                and np.hypot(o.x - x, o.z - z) <= 2*lookahead + self.camera.back]
        support = sum(min(o.count, 6) for o in near)
        confidence = float(1 - np.exp(-support/8.0)) * min(1.0, run[-1]/lookahead)
        error = wrap(heading_to(point[0] - x, point[1] - z) - heading)
        return Steer(float(error), (float(point[0]), float(point[1])), confidence)


def _drop_kinks(line, weight, turn=100.0):
    """Drop interior points where the line turns back on itself (a stray orb); the first point is kept."""
    keep = list(range(len(line)))
    changed = True
    while changed and len(keep) > 2:
        changed = False
        for j in range(1, len(keep) - 1):
            a, b, c = line[keep[j - 1]], line[keep[j]], line[keep[j + 1]]
            u, v = b - a, c - b
            if (u @ v)/max(np.hypot(*u)*np.hypot(*v), 1e-9) < np.cos(np.radians(turn)):
                del keep[j]
                changed = True
                break
    return line[keep], weight[keep]


def _smooth(line, weight, passes=2):
    """Each interior point moves towards the sighting-weighted mean of itself and its neighbours; ends stay."""
    line = line.copy()
    for _ in range(passes):
        if len(line) < 3:
            break
        new = line.copy()
        for i in range(1, len(line) - 1):
            w = np.minimum([weight[i - 1], 2*weight[i], weight[i + 1]], 2*weight[i])   # the character does not pull
            new[i] = (w[:, None]*line[i - 1:i + 2]).sum(0)/w.sum()
        line = new
    return line
