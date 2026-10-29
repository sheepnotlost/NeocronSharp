"""Path planning on Neocron's own sector maps (read-only port of the C# map code).

Layers:
  * catalog  -- pak_maps.csv + pak_worldinfo.csv + gfx/pak_gfx.ini (NeocronSharp.Core/SectorMaps.cs)
  * assets   -- gfx.pak reader and local pak_ overrides (GamePakArchive.cs / GameMapFiles.cs)
  * Projection -- the RPOSMAPWINDOW world<->bitmap transform (MAP-SPEC.md)
  * SectorPlanner -- walkable mask, exit arrows, A* planning, steering helpers

Nothing here writes to the game install or sends game input.
"""
from __future__ import annotations

import csv
import heapq
import io
import math
import os
import re
import struct
import zlib
from dataclasses import dataclass, field

import cv2
import numpy as np

DEFAULT_INSTALL = r"C:\Games\Neocron Client\Neocron Evolution 2.5"
_ENVELOPE = bytes([0x0A, 0xF7, 0x3D, 0x88, 0x84, 0x75, 0x84, 0x93, 0xBD, 0xEF, 0xFD, 0xAB])
_PAK_MAGIC = 0x3D458CDE
_LIMIT = 16 * 1024 * 1024


# --------------------------------------------------------------------------- files

def decode_envelope(data: bytes) -> bytes:
    """Decode the game's compressed 'pak_' envelope (12-byte magic, int32 size, zlib)."""
    if len(data) < 18 or data[:12] != _ENVELOPE:
        raise ValueError("Unrecognized definition header.")
    expected = struct.unpack_from("<i", data, 12)[0]
    if expected <= 0 or expected > _LIMIT * 4:
        raise ValueError("Definition size exceeds the read limit.")
    out = zlib.decompress(data[16:])
    if len(out) != expected:
        raise ValueError("Definition length does not match its header.")
    return out


def parse_definitions(data: bytes) -> dict[int, dict[str, str]]:
    """Enabled rows of a game definition CSV, keyed by EntryId."""
    text = decode_envelope(data).decode("utf-8")
    rows: dict[int, dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("Enabled") != "1":
            continue
        rows[int(row["EntryId"])] = row
    return rows


class PakArchive:
    """Bounded read-only access to gfx.pak (index format in MAP-SPEC.md)."""

    def __init__(self, path: str):
        self.path = path
        self._entries: dict[str, tuple[int, int, int]] = {}
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            magic, count = struct.unpack("<II", f.read(8))
            if magic != _PAK_MAGIC or count > 100000:
                raise ValueError("Unsupported game archive header.")
            first_payload = size
            for _ in range(count):
                start = f.tell()
                rec, offset, comp, usize, nlen = struct.unpack("<iIiii", f.read(20))
                if not (2 <= nlen <= 1024) or rec != nlen + 20 or comp <= 0 or usize <= 0 \
                        or offset < 8 or offset > size - comp or f.tell() + nlen > first_payload:
                    raise ValueError("Invalid game archive entry.")
                name = f.read(nlen)
                if len(name) != nlen or name[-1] != 0 or 0 in name[:-1]:
                    raise ValueError("Invalid archive asset name.")
                key = name[:-1].decode("latin-1").replace("\\", "/").lower()
                self._entries[key] = (offset, comp, usize)
                first_payload = min(first_payload, offset)
                if f.tell() != start + rec:
                    raise ValueError("Archive index overlaps its content.")

    def read(self, asset: str) -> bytes:
        name = asset.replace("\\", "/").lower()
        if name.startswith("gfx/"):
            name = name[4:]
        if name not in self._entries:
            raise FileNotFoundError(f"Asset '{name}' is not in {os.path.basename(self.path)}.")
        offset, comp, usize = self._entries[name]
        if usize > _LIMIT or comp > _LIMIT:
            raise ValueError("Archive asset exceeds the read limit.")
        with open(self.path, "rb") as f:
            f.seek(offset)
            raw = f.read(comp)
        out = zlib.decompress(raw)
        if len(out) != usize:
            raise ValueError("Archive asset size does not match its index.")
        return out


def read_map_file(install: str, asset: str, archive: PakArchive | None = None) -> bytes:
    """Local 'pak_' override, then a plain local file, then gfx.pak (as GameMapFiles.Read)."""
    root = os.path.normcase(os.path.abspath(install)).rstrip("\\/") + os.sep
    path = os.path.abspath(os.path.join(install, asset.replace("/", os.sep).replace("\\", os.sep)))
    if not os.path.normcase(path).startswith(root):
        raise ValueError("Map asset escapes the installation directory.")
    packed = os.path.join(os.path.dirname(path), "pak_" + os.path.basename(path))
    local = packed if os.path.isfile(packed) else path if os.path.isfile(path) else None
    if local is None:
        archive = archive or PakArchive(os.path.join(install, "gfx.pak"))
        data = archive.read(asset)
    else:
        if os.path.getsize(local) > _LIMIT:
            raise ValueError("Local map asset exceeds the read limit.")
        with open(local, "rb") as f:
            data = f.read()
        if data[:2] != b"BM":
            data = decode_envelope(data)
    if len(data) < 26 or data[:2] != b"BM":
        raise ValueError("The map asset is not a supported bitmap.")
    return data


def decode_bmp_gray(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or not (16 <= img.shape[0] <= 4096 and 16 <= img.shape[1] <= 4096):
        raise ValueError("Invalid sector-map image.")
    return img


# --------------------------------------------------------------------------- projection

@dataclass(frozen=True)
class SectorMap:
    world_id: int
    name: str
    bitmap_id: int
    asset_path: str
    bitmap_ref: tuple[float, float]   # BitmapRefX, BitmapRefY
    world_ref: tuple[float, float]    # WorldRefX, WorldRefZ
    scale: float                      # pixels per world unit

    def projection(self, rotation_deg: float = 270.0) -> "Projection":
        return Projection(self.bitmap_ref, self.world_ref, self.scale, rotation_deg)


@dataclass(frozen=True)
class Projection:
    """World (X, Z) <-> map pixel (u, v); same transform as RPOSMAPWINDOW RVA 0x134bfd."""
    bitmap_ref: tuple[float, float]
    world_ref: tuple[float, float]
    scale: float
    rotation_deg: float = 270.0

    def __post_init__(self):
        vals = (*self.bitmap_ref, *self.world_ref, self.scale, self.rotation_deg)
        if not all(math.isfinite(v) for v in vals) or self.scale <= 0:
            raise ValueError("Invalid sector-map coordinates.")

    @property
    def _cs(self) -> tuple[float, float]:
        t = (self.rotation_deg - 90.0) * math.pi / 180.0
        return math.cos(t), math.sin(t)

    def to_pixel(self, x: float, z: float) -> tuple[float, float]:
        if not (math.isfinite(x) and math.isfinite(z)):
            raise ValueError("Invalid world coordinates.")
        c, s = self._cs
        dx, dz = x - self.world_ref[0], z - self.world_ref[1]
        return (self.bitmap_ref[0] + self.scale * (c * dx - s * dz),
                self.bitmap_ref[1] + self.scale * (s * dx + c * dz))

    def to_world(self, u: float, v: float) -> tuple[float, float]:
        c, s = self._cs
        a, b = (u - self.bitmap_ref[0]) / self.scale, (v - self.bitmap_ref[1]) / self.scale
        # inverse of the rotation [[c,-s],[s,c]] is its transpose
        return (self.world_ref[0] + c * a + s * b, self.world_ref[1] - s * a + c * b)

    def world_bearing_to_pixel_angle(self, bearing_deg: float) -> float:
        """Map a world bearing (see bearing_of) to an image angle atan2(dv, du) in degrees."""
        b = math.radians(bearing_deg)
        dx, dz = math.sin(b), math.cos(b)
        c, s = self._cs
        return math.degrees(math.atan2(s * dx + c * dz, c * dx - s * dz))


def bearing_of(dx: float, dz: float) -> float:
    """World bearing in degrees: 0 = +Z, 90 = +X (compass-style, clockwise in X/Z)."""
    return math.degrees(math.atan2(dx, dz)) % 360.0


def bearing_from_forward(fx: float, fz: float) -> float:
    """Bearing of the game's heading forward vector (X, Z components)."""
    return bearing_of(fx, fz)


# --------------------------------------------------------------------------- catalog

_BITMAP_RE = re.compile(r'(?im)^\s*set\s+(\d+)\s+"(gfx[\\/]maps[\\/][^"]+)"[^\r\n]*$')


class SectorMapCatalog:
    """Join of pak_maps.csv, pak_worldinfo.csv and the map resources of gfx/pak_gfx.ini."""

    def __init__(self, install: str = DEFAULT_INSTALL):
        self.install = install
        self.names: dict[int, str] = {}
        self.maps: dict[int, SectorMap] = {}
        with open(os.path.join(install, "definitions", "pak_worldinfo.csv"), "rb") as f:
            for key, row in parse_definitions(f.read()).items():
                self.names[key] = row["Name"]
        with open(os.path.join(install, "gfx", "pak_gfx.ini"), "rb") as f:
            resources = decode_envelope(f.read()).decode("utf-8")
        bitmaps = {int(m.group(1)): m.group(2).replace("\\", "/") for m in _BITMAP_RE.finditer(resources)}
        with open(os.path.join(install, "definitions", "pak_maps.csv"), "rb") as f:
            rows = parse_definitions(f.read())
        for row in rows.values():
            try:
                world, bitmap = int(row["WorldId"]), int(row["BitmapId"])
                scale = float(row["Scale"])
                rx, rz = float(row["WorldRefX"]), float(row["WorldRefZ"])
                bx, by = int(row["BitmapRefX"]), int(row["BitmapRefY"])
            except (KeyError, ValueError):
                continue
            if not (math.isfinite(scale) and 0 < scale <= 100 and math.isfinite(rx) and math.isfinite(rz)):
                continue
            if bitmap not in bitmaps or world in self.maps:
                continue
            self.maps[world] = SectorMap(world, self.name(world), bitmap, bitmaps[bitmap],
                                         (float(bx), float(by)), (rx, rz), scale)
        self._archive: PakArchive | None = None
        self._images: dict[int, np.ndarray] = {}

    def name(self, world_id: int) -> str:
        return self.names.get(world_id, f"Sector {world_id}")

    def find(self, world_id: int) -> SectorMap | None:
        return self.maps.get(world_id)

    def find_by_name(self, name: str) -> SectorMap | None:
        key = name.strip().upper()
        for m in self.maps.values():   # first (lowest catalog row) wins, as in C# TryAdd order
            if m.name.upper() == key:
                return m
        return None

    def image(self, sector: SectorMap) -> np.ndarray:
        if sector.bitmap_id not in self._images:
            if self._archive is None:
                self._archive = PakArchive(os.path.join(self.install, "gfx.pak"))
            self._images[sector.bitmap_id] = decode_bmp_gray(
                read_map_file(self.install, sector.asset_path, self._archive))
        return self._images[sector.bitmap_id]


# --------------------------------------------------------------------------- map art

# The sector map BMPs (Plaza 1-4, Pepper Park 1-3 checked) use a small fixed palette:
#   247 background, 231 outlines of off-route buildings, 39 black icons/labels,
#   71 / 135 / 199 walkable areas (shade = area/level), 1 px 247 separators between areas.
FLOOR_MIN, FLOOR_MAX = 50, 220      # 71, 135, 199 (and stray 87/103/151 pixels) are floor
BLACK_MAX = 60                      # 39: labels, arrows, dots

# 9x9 glyph interiors of the 11x11 label boxes (white strokes on black), as they occur in all 161 maps.
_GLYPHS = {
    "1": (".........", ".........", "...##....", "....#....", "....#....", "....#....", "....#....", ".........", "........."),
    "2": (".........", ".........", "..####...", "......#..", "...###...", "..#......", "..#####..", ".........", "........."),
    "3": (".........", ".........", "..####...", "......#..", "...###...", "......#..", "..####...", ".........", "........."),
    "4": (".........", ".........", "..#...#..", "..#...#..", "..#####..", "......#..", "......#..", ".........", "........."),
    "A": (".........", ".........", "...###...", "..#...#..", "..#####..", "..#...#..", "..#...#..", ".........", "........."),
    "B": (".........", ".........", "..####...", "..#...#..", "..####...", "..#...#..", "..####...", ".........", "........."),
    "C": (".........", ".........", "...###...", "..#...#..", "..#......", "..#...#..", "...###...", ".........", "........."),
    "D": (".........", ".........", "..####...", "..#...#..", "..#...#..", "..#...#..", "..####...", ".........", "........."),
    "E": (".........", ".........", "..#####..", "..#......", "..####...", "..#......", "..#####..", ".........", "........."),
    "F": (".........", ".........", "..#####..", "..#......", "..####...", "..#......", "..#......", ".........", "........."),
}
_GLYPH_ARRAYS = {label: np.array([[ch == "#" for ch in row] for row in rows], bool)
                 for label, rows in _GLYPHS.items()}


def read_glyph(gray: np.ndarray, x: int, y: int) -> str:
    """Label of the 11x11 box whose top-left is (x, y); '?' if the glyph is unknown (1 stray pixel tolerated)."""
    inner = gray[y + 1:y + 10, x + 1:x + 10] > 128
    if inner.shape != (9, 9):
        return "?"
    diffs = {label: int(np.count_nonzero(g != inner)) for label, g in _GLYPH_ARRAYS.items()}
    best = min(diffs, key=diffs.get)
    return best if diffs[best] <= 1 else "?"


@dataclass
class Exit:
    label: str                         # sector digit read from the box ('?' if unreadable)
    box: tuple[int, int, int, int]     # x, y, w, h of the label box on the map
    direction: tuple[float, float]     # unit pixel vector the arrow points (out of the sector)
    pixel: tuple[float, float]         # floor pixel to walk to (next to the box)
    world: tuple[float, float]         # same point in world X, Z
    beyond: tuple[float, float]        # world point a little past the arrow (where to push through)
    bearing: float                     # world bearing of the arrow (bearing_of convention)


@dataclass
class Landmark:
    label: str                         # A-F boxes without an arrow
    box: tuple[int, int, int, int]
    pixel: tuple[float, float]
    world: tuple[float, float]


def _arrow_direction(comp: np.ndarray) -> tuple[float, float] | None:
    """Unit pixel vector from the base to the tip of a black triangle (6x11 or 11x6 component)."""
    h, w = comp.shape
    if (w, h) not in ((6, 11), (11, 6)):
        return None
    if w < h:
        counts = comp.sum(axis=0)
        return (1.0, 0.0) if counts[0] > counts[-1] else (-1.0, 0.0)
    counts = comp.sum(axis=1)
    return (0.0, 1.0) if counts[0] > counts[-1] else (0.0, -1.0)


def walkable_mask(gray: np.ndarray, *, bridge_same_shade: bool = False):
    """(walkable, bridges, soft) boolean masks from the map art.

    walkable -- floor shades, plus 1 px separators between floor areas, plus black dots drawn on floor
    bridges  -- the separator pixels that were opened (crossing them costs extra)
    soft     -- black dot icons on the floor (walkable at a high cost: usually a terminal or vendor)
    The map art has no anti-aliasing; the gaps to close are the 1 px separator lines the artist drew
    between differently shaded areas (levels / zones). A 1 px line between two areas of the SAME shade
    is kept as a wall unless bridge_same_shade=True.
    """
    floor = (gray >= FLOOR_MIN) & (gray <= FLOOR_MAX)
    black = gray <= BLACK_MAX
    shade = np.where(floor, gray.astype(np.int16), -1)
    pad = np.pad(shade, 1, constant_values=-1)
    h, w = gray.shape
    bridges = np.zeros_like(floor)
    for (dy1, dx1), (dy2, dx2) in (((0, -1), (0, 1)), ((-1, 0), (1, 0)), ((-1, -1), (1, 1)), ((-1, 1), (1, -1))):
        a = pad[1 + dy1:1 + dy1 + h, 1 + dx1:1 + dx1 + w]
        b = pad[1 + dy2:1 + dy2 + h, 1 + dx2:1 + dx2 + w]
        ok = (a >= 0) & (b >= 0)
        if not bridge_same_shade:
            ok &= a != b
        bridges |= ok
    bridges &= ~floor & ~black
    # black dots (7x7 discs) whose surroundings are mostly floor sit on the floor
    soft = np.zeros_like(floor)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(black.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw <= 8 and bh <= 8 and area >= 25:
            ring = floor[max(0, y - 1):y + bh + 1, max(0, x - 1):x + bw + 1]
            if ring.mean() > .45:
                soft |= lab == i
    walk = floor | bridges | soft
    return walk, bridges, soft


def find_labels(gray: np.ndarray):
    """[(label, box, arrow_direction_or_None)] for every 11x11 label box on the map."""
    black = (gray <= BLACK_MAX).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(black, connectivity=8)
    boxes, arrows = [], []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w == 11 and h == 11 and area >= 60:
            boxes.append((int(x), int(y), 11, 11))
        elif 25 <= area <= 45:
            d = _arrow_direction(lab[y:y + h, x:x + w] == i)
            if d is not None:
                arrows.append(((x + w / 2, y + h / 2), d))
    out = []
    for box in boxes:
        bx, by = box[0] + 5.5, box[1] + 5.5
        best = None
        for (ax, ay), d in arrows:
            dist = math.hypot(ax - bx, ay - by)
            along = (ax - bx) * d[0] + (ay - by) * d[1]   # the arrow sits on the side it points to
            if dist <= 11 and along > 5 and (best is None or dist < best[0]):
                best = (dist, d)
        out.append((read_glyph(gray, box[0], box[1]), box, best[1] if best else None))
    return out


# --------------------------------------------------------------------------- planner

_SQRT2 = math.sqrt(2.0)


def supported_style(gray: np.ndarray) -> bool:
    """The Plaza / Viarosso / Pepper Park map style: a light background (247) and a handful of flat grey levels. The
    Industrial, Outzone, Canyon, Military Base and Secret Passage maps (and Dome of York) are drawn on black with a
    hundred and more levels and outline-only floors; read as floor plans they give wrong floor and no exits (checked
    by eye on all 24 city sector maps, 29 Oct)."""
    counts = np.bincount(gray.ravel(), minlength=256)
    return int(counts.argmax()) >= 200 and int((counts > gray.size*.002).sum()) <= 8


class SectorPlanner:
    """A* planning on one sector map, in world coordinates (X, Z).

    Build once per sector (catalog image + live map rotation): ~150-300 ms including prepare().
    Distances are world units. UNIT ASSUMPTION (unverified): about 40 world units per metre, so the
    default waypoint spacing of 80-160 units is roughly 2-4 m and the wall clearance of 120 units ~3 m.
    """

    def __init__(self, gray: np.ndarray, projection: Projection, *, clearance: float = 120.0,
                 wall_weight: float = 4.0, bridge_cost: float = 40.0, soft_cost: float = 25.0,
                 bridge_same_shade: bool = False, prepare: bool = True):
        self.gray = gray
        self.projection = projection
        self.h, self.w = gray.shape
        self.walk, self.bridges, self.soft = walkable_mask(gray, bridge_same_shade=bridge_same_shade)
        labels = find_labels(gray)
        for _, (x, y, bw, bh), _ in labels:          # label boxes are drawn over the floor edge
            self.walk[max(0, y - 1):y + bh + 1, max(0, x - 1):x + bw + 1] = False
        self.wall_distance = cv2.distanceTransform(self.walk.astype(np.uint8), cv2.DIST_L2, 5)
        c_px = max(1.5, clearance * projection.scale)
        near = np.clip((c_px - self.wall_distance) / c_px, 0, 1)
        cost = 1.0 + wall_weight * near * near
        cost += np.where(self.bridges, bridge_cost, 0.0) + np.where(self.soft, soft_cost, 0.0)
        self.cost = np.where(self.walk, cost, np.inf)
        _, self.component = cv2.connectedComponents(self.walk.astype(np.uint8), connectivity=4)
        self._g = self._parent = None
        self._fields: dict = {}
        self._dists: dict = {}
        self._alt = None
        self._rows, self._cols = np.indices(gray.shape)
        self._build_graph()
        self.exits: list[Exit] = []
        self.landmarks: list[Landmark] = []
        for label, box, d in labels:
            self._add_label(label, box, d)
        if prepare:
            self.prepare()

    @classmethod
    def from_catalog(cls, catalog: SectorMapCatalog, world_id: int, rotation_deg: float, **kw) -> "SectorPlanner":
        sector = catalog.find(world_id)
        if sector is None:
            raise KeyError(f"No client map for world {world_id}.")
        gray = catalog.image(sector)
        if not supported_style(gray):
            raise ValueError(f"The map of {catalog.name(world_id) or world_id} is drawn in a style the planner cannot read.")
        return cls(gray, sector.projection(rotation_deg), **kw)

    # -- helpers
    def _nearest_walkable(self, u: float, v: float, radius: float = 8.0):
        x0, y0 = max(0, int(u - radius)), max(0, int(v - radius))
        ys, xs = np.nonzero(self.walk[y0:int(v + radius) + 1, x0:int(u + radius) + 1])
        if len(xs) == 0:
            return None
        xs, ys = xs + x0, ys + y0
        d2 = (xs - u) ** 2 + (ys - v) ** 2
        score = d2 - 0.5 * np.minimum(self.wall_distance[ys, xs], 2.0)   # prefer a little clearance
        i = int(np.argmin(score))
        if d2[i] > radius * radius:
            return None
        return int(xs[i]), int(ys[i])

    def _add_label(self, label, box, d):
        x, y, bw, bh = box
        cu, cv = x + bw / 2, y + bh / 2
        if d is None:
            p = self._nearest_walkable(cu, cv, 10) or (cu, cv)
            self.landmarks.append(Landmark(label, box, (float(p[0]), float(p[1])), self.projection.to_world(*p)))
            return
        p = self._nearest_walkable(cu, cv, 12)
        if p is None:
            return
        # Some arrows point across the corridor rather than along it (Viarosso 1 '1', Plaza 4 '1' and '2'): past
        # such an exit, push on the way the corridor leads into the box, not the way the arrow points.
        push = d
        into = (cu - p[0], cv - p[1])
        norm = (into[0]**2 + into[1]**2) ** .5
        if norm > 1e-6 and (into[0]*d[0] + into[1]*d[1])/norm < math.cos(math.radians(45)):
            push = (into[0]/norm, into[1]/norm)
        beyond = (cu + push[0] * 12, cv + push[1] * 12)
        wb = self.projection.to_world(*beyond)
        wp = self.projection.to_world(*p)
        o, t = self.projection.to_world(0, 0), self.projection.to_world(*d)
        self.exits.append(Exit(label, box, d, (float(p[0]), float(p[1])), wp, wb,
                               bearing_of(t[0] - o[0], t[1] - o[1])))

    # -- queries
    def is_floor(self, x: float, z: float) -> bool:
        u, v = self.projection.to_pixel(x, z)
        iu, iv = int(round(u)), int(round(v))
        return 0 <= iu < self.w and 0 <= iv < self.h and bool(self.walk[iv, iu])

    def snap(self, x: float, z: float, radius_px: float = 6.0):
        """Nearest walkable pixel to a world point (None when off the floor by more than radius_px)."""
        u, v = self.projection.to_pixel(x, z)
        if not (-radius_px <= u < self.w + radius_px and -radius_px <= v < self.h + radius_px):
            return None
        iu, iv = int(round(u)), int(round(v))
        if 0 <= iu < self.w and 0 <= iv < self.h and self.walk[iv, iu]:
            return iu, iv
        return self._nearest_walkable(u, v, radius_px)

    def _build_graph(self):
        """Neighbour lists [(cell, step cost), ...] for every walkable cell (8-connected, no corner cutting).
        A step costs its length times the mean cost of the two cells."""
        w, h = self.w, self.h
        cost = self.cost
        walk = self.walk
        pad = np.pad(cost, 1, constant_values=np.inf)
        steps = []
        for dy, dx, length in ((0, -1, 1.0), (0, 1, 1.0), (-1, 0, 1.0), (1, 0, 1.0),
                               (-1, -1, _SQRT2), (-1, 1, _SQRT2), (1, -1, _SQRT2), (1, 1, _SQRT2)):
            nb = pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
            ok = walk & np.isfinite(nb)
            if dx and dy:   # diagonal: both orthogonal cells must be open too
                ok &= np.isfinite(pad[1 + dy:1 + dy + h, 1:1 + w]) & np.isfinite(pad[1:1 + h, 1 + dx:1 + dx + w])
            step = np.where(ok, (cost + nb) * .5 * length, 0.0)
            steps.append((dy * w + dx, ok.ravel(), step.ravel()))
        graph: list = [None] * (w * h)
        for i in np.flatnonzero(walk.ravel()).tolist():
            graph[i] = [(i + off, float(st[i])) for off, ok, st in steps if ok[i]]
        self._graph = graph

    def astar(self, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]] | None:
        """8-connected A* over the cost grid, no corner cutting. Pixel path [(u, v), ...] or None."""
        w = self.w
        s, g = start[1] * w + start[0], goal[1] * w + goal[0]
        graph = self._graph
        if graph[s] is None or graph[g] is None:
            return None
        if self.component[start[1], start[0]] != self.component[goal[1], goal[0]]:
            return None
        if self._g is None:
            self._g = [math.inf] * (w * self.h)
            self._parent = [-1] * (w * self.h)
        best, parent = self._g, self._parent
        touched = [s]
        dx = np.abs(self._cols - goal[0])
        dy = np.abs(self._rows - goal[1])
        h = ((dx + dy) + (_SQRT2 - 2) * np.minimum(dx, dy)).ravel()   # octile; every step cost >= its length
        if self._alt is not None:   # ALT: triangle inequality on the exit distance fields (all consistent)
            h = np.maximum(h, np.abs(self._alt - self._alt[:, g:g + 1]).max(axis=0))
        hval = h.tolist()
        best[s] = 0.0
        parent[s] = -1
        heap = [(0.0, 0.0, s)]
        push, pop = heapq.heappush, heapq.heappop
        found = False
        try:
            while heap:
                _, ngc, cur = pop(heap)
                gc = -ngc
                if cur == g:
                    found = True
                    break
                if gc > best[cur]:
                    continue
                for nb, step in graph[cur]:
                    ng = gc + step
                    if ng < best[nb]:
                        if best[nb] == math.inf:
                            touched.append(nb)
                        best[nb] = ng
                        parent[nb] = cur
                        push(heap, (ng + hval[nb], -ng, nb))   # ties: deepest first
            out = []
            if found:
                cur = g
                while cur != -1:
                    out.append((cur % w, cur // w))
                    cur = parent[cur]
                out.reverse()
            return out or None
        finally:
            for i in touched:
                best[i] = math.inf
                parent[i] = -1

    def exit_field(self, ex: "Exit") -> list[int]:
        """Cached Dijkstra tree towards an exit: next cell on the cheapest path for every reachable cell
        (-1 at the exit, -2 unreachable). One full expansion (~50-100 ms), then any plan to it is O(path)."""
        key = (round(ex.pixel[0]), round(ex.pixel[1]))
        field = self._fields.get(key)
        if field is not None:
            return field
        w = self.w
        n = w * self.h
        g = key[1] * w + key[0]
        graph = self._graph
        dist = [math.inf] * n
        nxt = [-2] * n
        dist[g] = 0.0
        nxt[g] = -1
        heap = [(0.0, g)]
        push, pop = heapq.heappush, heapq.heappop
        while heap:
            d, cur = pop(heap)
            if d > dist[cur]:
                continue
            for nb, step in graph[cur]:   # steps are symmetric, so this is also the cost towards g
                nd = d + step
                if nd < dist[nb]:
                    dist[nb] = nd
                    nxt[nb] = cur
                    push(heap, (nd, nb))
        self._fields[key] = nxt
        d = np.array(dist)
        self._dists[key] = np.where(np.isfinite(d), d, 0.0)
        self._alt = np.stack(list(self._dists.values()))
        return nxt

    def prepare(self):
        """Precompute every exit field (~50-200 ms per sector; the constructor does it unless prepare=False).
        The fields also serve as ALT landmarks that keep astar() well under 50 ms."""
        for ex in self.exits:
            self.exit_field(ex)
        return self

    def path_to_exit_pixels(self, world_from, ex: "Exit"):
        s = self.snap(*world_from)
        if s is None:
            return None
        nxt = self.exit_field(ex)
        cur = s[1] * self.w + s[0]
        if nxt[cur] == -2:
            return None
        out = []
        while cur >= 0:
            out.append((cur % self.w, cur // self.w))
            cur = nxt[cur]
        return out

    def _segment_clear(self, a, b) -> bool:
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 2) + 1
        for i in range(n + 1):
            t = i / n
            iu = int(round(a[0] + (b[0] - a[0]) * t))
            iv = int(round(a[1] + (b[1] - a[1]) * t))
            if not self.walk[iv, iu]:
                return False
        return True

    def simplify(self, pixels, epsilon: float = 0.8):
        """Douglas-Peucker on the pixel path; a chord is only accepted if it stays on the floor."""
        pts = [(float(x), float(y)) for x, y in pixels]
        if len(pts) <= 2:
            return pts
        keep = [False] * len(pts)
        keep[0] = keep[-1] = True
        stack = [(0, len(pts) - 1)]
        while stack:
            i, j = stack.pop()
            if j <= i + 1:
                continue
            ax, ay = pts[i]
            bx, by = pts[j]
            L = math.hypot(bx - ax, by - ay) or 1e-9
            dmax, k = -1.0, i + 1
            for m in range(i + 1, j):
                px, py = pts[m]
                d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / L
                if d > dmax:
                    dmax, k = d, m
            if dmax > epsilon or not self._segment_clear(pts[i], pts[j]):
                keep[k] = True
                stack.append((i, k))
                stack.append((k, j))
        return [p for p, kp in zip(pts, keep) if kp]

    def to_waypoints(self, pixels, *, max_spacing: float = 160.0, min_spacing: float = 80.0):
        """World waypoints: the path's turning points, thinned where a turn comes less than min_spacing
        after the previous one (only if the shortcut stays on the floor), then filled in so that no leg is
        longer than max_spacing. World units; the first point is the start, the last the goal."""
        corners = self.simplify(pixels)
        scale = self.projection.scale
        kept = [corners[0]]
        for i in range(1, len(corners) - 1):
            last, cur, nxt = kept[-1], corners[i], corners[i + 1]
            short = math.dist(last, cur) / scale < min_spacing or math.dist(cur, nxt) / scale < min_spacing
            if short and self._segment_clear(last, nxt):
                continue
            kept.append(cur)
        kept.append(corners[-1])
        world = [self.projection.to_world(u, v) for u, v in kept]
        out = [world[0]]
        for a, b in zip(world, world[1:]):
            k = max(1, math.ceil(math.dist(a, b) / max_spacing - 1e-9))
            for i in range(1, k + 1):
                out.append((a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k))
        return out

    def plan_pixels(self, world_from, target) -> list[tuple[int, int]] | None:
        s = self.snap(*world_from)
        g = self.snap(*target, radius_px=10.0)
        if s is None or g is None:
            return None
        return self.astar(s, g)

    def plan(self, world_from, target, **spacing) -> list[tuple[float, float]] | None:
        """World waypoints [(X, Z), ...] from world_from to target ((X, Z) or an Exit); None if unreachable
        or either end is more than a few pixels off the floor."""
        if isinstance(target, Exit):
            pixels = self.path_to_exit_pixels(world_from, target)
        else:
            pixels = self.plan_pixels(world_from, target)
        return None if pixels is None else self.to_waypoints(pixels, **spacing)

    def plan_to_exit(self, world_from, bearing_hint: float | None = None, *, lead: float = 300.0,
                     labels=None, **spacing):
        """(Exit, waypoints) for the reachable exit whose path leaves world_from closest to bearing_hint
        (degrees, bearing_of convention), judged over the first `lead` world units of the path. Exits
        within 15 degrees of each other tie and the shorter path wins; with no hint, the shortest path.
        labels restricts the candidates (e.g. {'2'}). None if no exit is reachable.
        Follows the cached exit fields (built by prepare(), which the constructor runs by default), so a
        call takes a few ms."""
        best = None
        for ex in self.exits:
            if labels is not None and ex.label not in labels:
                continue
            pixels = self.path_to_exit_pixels(world_from, ex)
            if pixels is None:
                continue
            wps = self.to_waypoints(pixels, **spacing)
            length = path_length(wps)
            score = 0.0
            if bearing_hint is not None and length > 0:
                first = point_along(wps, min(lead, length))
                score = angle_diff(bearing_of(first[0] - wps[0][0], first[1] - wps[0][1]), bearing_hint)
            key = (int(score // 15.0), length)
            if best is None or key < best[0]:
                best = (key, ex, wps)
        return None if best is None else (best[1], best[2])


# --------------------------------------------------------------------------- steering helpers

def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, degrees."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def path_length(path) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))


def point_along(path, distance: float):
    """The point `distance` world units along the polyline (clamped to its ends)."""
    for a, b in zip(path, path[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if distance <= seg and seg > 0:
            t = distance / seg
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        distance -= seg
    return path[-1]


def _project_on_path(position, path):
    """(segment index, t, signed offset, distance along the path) of the nearest polyline point."""
    px, pz = position
    best = None
    along = 0.0
    for i, (a, b) in enumerate(zip(path, path[1:])):
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz)
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (pz - a[1]) * dz) / (L * L)))
        d = math.hypot(px - (a[0] + dx * t), pz - (a[1] + dz * t))
        side = ((px - a[0]) * dz - (pz - a[1]) * dx) if L else 0.0   # > 0 on the bearing+90 side
        if best is None or d < best[0] - 1e-9:
            best = (d, i, t, -d if side < 0 else d, along + L * t)
        along += L
    return best[1:]


def cross_track_error(position, path) -> float:
    """Signed distance (world units) from the path polyline: positive on the side that bearing + 90
    points to (the +X side while walking towards +Z), negative on the other."""
    if len(path) < 2:
        return 0.0 if not path else math.hypot(position[0] - path[0][0], position[1] - path[0][1])
    return _project_on_path(position, path)[2]


def next_waypoint(position, path, *, reach: float = 60.0, lookahead: float = 0.0):
    """(index, (X, Z)) to steer for. Default: the first waypoint after the position's projection onto the
    path that is farther than `reach`. With lookahead > 0: the point that far along the path past the
    projection (index = the waypoint ending that leg). (len-1, last) once the end is within reach."""
    if not path:
        return None
    if len(path) == 1:
        return 0, path[0]
    i, _, _, along = _project_on_path(position, path)
    if lookahead > 0:
        remaining = along + lookahead
        for j, (a, b) in enumerate(zip(path, path[1:])):
            seg = math.dist(a, b)
            if remaining <= seg and seg > 0:
                t = remaining / seg
                return j + 1, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            remaining -= seg
        return len(path) - 1, path[-1]
    for j in range(i + 1, len(path)):
        if math.hypot(path[j][0] - position[0], path[j][1] - position[1]) > reach:
            return j, path[j]
    return len(path) - 1, path[-1]
