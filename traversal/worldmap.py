"""The wasteland world map, built from the game's own files.

Base: every cell's own ground texture, as the game lays it on the terrain (the 16 x 16 JPEG tiles in
terrain/pak_<cell>.tfl, roads and tracks included), with water where the heightfield is below the sea
(height 150; the sea floor is about 96). Every point on it comes from the world data:
  - doors (traversal.exe worlddata): city gates, dungeon, cave, bunker and tunnel entrances, and where each leads;
  - outposts (pak_outposts, at their gate or main building), with their kind;
  - GenReps, GoGuardians, vehicle depots, CityComs and the traders and medics standing in the wasteland
    (the cells' spawn files, terrain/pak_<cell>.dat).
Villages, oases and camps have no name in the files: their names and rough spots are read off the EMS.ru and
NEMA world maps (techhaven.org), then each is pinned to the GenRep, GoGuardian or trader the files place nearest.
Creature spawns are not in the client's files (the server places them).

Rows A (south, beside Neocron) to L, columns 01 (west) to 16. Cell space: x east, z south, 32768 units a cell.
Writes out/World map.png. Run "World map.cmd" (double-click).
"""
import csv, glob, io, json, os, struct, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mapplan  # noqa: E402

INSTALL = r"C:\Games\Neocron Client\Neocron Evolution 2.5"
HALF = 16384.0
CELL = 200                 # px a cell on the world map
ZONE = 1800                # px the one cell of a zone map
MARGIN = 70
TITLE = 96
LEGEND = 260

OCEAN = (16, 30, 46)
OCEAN_WATER = (22, 44, 78)

# Named places the files do not name, read off the EMS.ru map: (name, gx, gy) in cells from the south-west corner.
REFERENCE = [
    ("El Farid Oasis", 9.34, 10.10), ("El Farid Village", 9.15, 9.64), ("Ancient Yucida Village", 12.56, 10.30),
    ("Escador Oasis", 14.25, 10.19), ("Ancient Loba Village", 12.33, 9.60), ("DoY Outpost", 7.26, 9.62),
    ("Encampment", 6.37, 6.39), ("Old Greycore Outpost", 5.45, 5.69), ("Blakkmist Garbage Dump", 8.34, 5.48),
    ("Canyon Reloading Point", 11.44, 5.57), ("Catlock Bay", 11.22, 4.58), ("Tawkeen Village", 5.70, 2.56),
    ("Crest Village", 7.28, 2.47), ("Calida Village", 8.64, 3.22), ("Point Red", 6.50, 1.59), ("Sherman Bay", 9.39, 1.43),
    ("Desert Racetrack", 10.49, 6.38),
]
SNAP = 0.3                 # cells: how far a reference spot may be pinned to a placed object

CITIES = [("TECH HAVEN", "Tech Haven"), ("MILITARY", "Military Base"), ("CANYON FACILITY", "Canyon Facility (Twilight Guardian)"),
          ("DOY", "Dome of York"), ("DOME OF YORK", "Dome of York"), ("OUTZONE", "Neocron (Outzone gates)")]
OUTPOST_LETTER = {"Mine": "M", "Factory": "F", "Lab": "L", "Fortress": "T", "Uplink": "U", "Outpost": "O"}
COLOURS = {"city": (255, 214, 64), "door": (255, 80, 72), "outpost": (40, 90, 230), "genrep": (60, 230, 230),
           "goguardian": (70, 110, 255), "vehicle": (90, 230, 90), "citycom": (230, 140, 255), "trader": (255, 160, 60),
           "place": (255, 255, 255)}


def table(name):
    rows = list(csv.reader(io.StringIO(mapplan.decode_envelope(open(os.path.join(INSTALL, "definitions", f"pak_{name}.csv"), "rb").read()).decode("latin1"))))
    head = rows[0]
    return {int(r[0]): dict(zip(head, r)) for r in rows[1:] if r and r[0].lstrip("-").isdigit()}


def decode(data):
    try:
        return mapplan.decode_envelope(data)
    except ValueError:
        return data


def elements(b):
    """Section 2 of a spawn file: (record type, bytes), as traversal's WorldObjects.Elements."""
    if len(b) < 4:
        return
    p = 4 + struct.unpack_from("<I", b, 0)[0]
    while p + 16 <= len(b):
        h, _, sec, size = struct.unpack_from("<IIII", b, p)
        if h < 12:
            return
        p += 4 + h
        if p + size > len(b):
            return
        if sec == 2:
            q, end = p, p + size
            while q + 16 <= end:
                hh, _, typ, ln = struct.unpack_from("<IIII", b, q)
                if hh < 12:
                    break
                q += 4 + hh
                if q + ln > end:
                    break
                yield typ, b[q:q + ln]
                q += ln
        p += size


def clean(name):
    return " ".join(name.replace("\\n", " ").replace("\n", " ").replace("---", " ").split())


def world_data():
    exe = os.path.join(HERE, "bin", "Release", "net9.0", "traversal.exe")
    out = subprocess.run([exe, "worlddata"], capture_output=True, text=True, timeout=600, cwd=HERE).stdout
    return json.loads(out[out.index("{"):])


SEA = 150                  # heightfield value under which a cell is water
TEXTURE = 32               # px each of a cell's 16 x 16 texture tiles is decoded at (JPEG draft scaling)


def terrain_file(code):
    """A cell's .tfl: its directory of named parts (map.dat heights, 0000-0255.jpg ground textures)."""
    f = decode(open(os.path.join(INSTALL, "terrain", f"pak_{code}.tfl"), "rb").read())
    at, parts, p = struct.unpack_from("<I", f, 12)[0], {}, 0
    p = at + 8
    while p + 4 < len(f):
        n = struct.unpack_from("<i", f, p)[0]
        if 2 <= n <= 64 and p + 4 + n + 20 <= len(f) and f[p + 3 + n] == 0 and all(32 < c < 127 for c in f[p + 4:p + 3 + n]):
            q = p + 4 + n + 12
            parts[f[p + 4:p + 3 + n].decode("latin1").lower()] = (struct.unpack_from("<i", f, q + 4)[0], struct.unpack_from("<i", f, q)[0])
            p = q + 20
            continue
        p += 1
    return f, parts


def ground(code, size, texture=TEXTURE):
    """The cell's ground texture (north at the top), water where it lies below the sea, at size x size px."""
    import numpy as np
    f, parts = terrain_file(code)
    canvas = Image.new("RGB", (16 * texture, 16 * texture))
    for k in range(256):
        off, length = parts[f"{k:04d}.jpg"]
        piece = Image.open(io.BytesIO(f[off:off + length]))
        piece.draft("RGB", (texture, texture))
        canvas.paste(piece.convert("RGB").resize((texture, texture)), ((k % 16) * texture, (k // 16) * texture))
    off, _ = parts["map.dat"]
    heights = np.frombuffer(f, "<u2", 512 * 512, off + 4).reshape(512, 512) / 4
    side = canvas.size[0]
    pixels = np.array(canvas, dtype=np.float32)
    water = np.array(Image.fromarray((heights < SEA).astype(np.uint8) * 255).resize((side, side))) > 127
    pixels[water] = pixels[water] * 0.25 + np.array(OCEAN_WATER) * 0.75
    return Image.fromarray(pixels.astype(np.uint8)).resize((size, size), Image.LANCZOS)


def main(zone=None):
    """The whole wasteland, or with zone = "j_01" one cell at full detail with every object named and a coordinate grid."""
    info, models, npcs, chars = table("worldinfo"), table("worldmodels"), table("npcs"), table("characters")
    cells = {}
    for path in glob.glob(os.path.join(INSTALL, "terrain", "pak_*.tfl")):
        code = os.path.basename(path)[4:-4]
        if zone is None or code == zone:
            cells[(ord(code[0]) - 97, int(code[2:]))] = code
    if not cells:
        raise SystemExit(f"No wasteland cell {zone}.")
    CELL = ZONE if zone else globals()["CELL"]
    k = 1.7 if zone else 1.0                       # text and marks scale with the zone map
    row0, row1 = min(r for r, _ in cells), max(r for r, _ in cells)
    col0, col1 = min(c for _, c in cells), max(c for _, c in cells)
    rows, cols = row1 - row0 + 1, col1 - col0 + 1
    W, H = MARGIN * 2 + cols * CELL, int(TITLE + MARGIN * 2 + rows * CELL + LEGEND * k)
    img = Image.new("RGB", (W, H), OCEAN)
    draw = ImageDraw.Draw(img)
    font = lambda s, bold=False: ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", int(s * k))
    top = TITLE + MARGIN

    def cell_box(row, col):
        return MARGIN + (col - col0) * CELL, top + (row1 - row) * CELL

    def at(world, x, z):
        """Map pixel of a cell-space point (None outside the cells drawn)."""
        row, col = (world - 2000) // 20, (world - 2000) % 20
        if (row, col) not in cells:
            return None
        x0, y0 = cell_box(row, col)
        return x0 + (x + HALF) / (2 * HALF) * CELL, y0 + (z + HALF) / (2 * HALF) * CELL

    def grid(gx, gy):
        return MARGIN + (gx - col0 + 1) * CELL, top + (row1 + 1 - gy) * CELL

    # Cells: their ground textures.
    for (row, col), code in cells.items():
        try:
            img.paste(ground(code, CELL, 128 if zone else TEXTURE), cell_box(row, col))
        except (KeyError, OSError, ValueError, struct.error):
            continue
    # Grid and cell names.
    for (row, col), code in cells.items():
        x0, y0 = cell_box(row, col)
        draw.rectangle((x0, y0, x0 + CELL, y0 + CELL), outline=(20, 20, 20))
        world = 2000 + 20 * row + col
        kind = info.get(world, {}).get("Name", "").split(" - ", 1)[-1].title()
        draw.text((x0 + 5, y0 + 3), f"{chr(65 + row)} {col:02d}", fill=(255, 255, 255), font=font(17, True), stroke_width=3, stroke_fill=(0, 0, 0))
        draw.text((x0 + 5, y0 + 23), kind, fill=(225, 225, 225), font=font(12), stroke_width=2, stroke_fill=(0, 0, 0))
    for c in range(col0, col1 + 1):
        for y in (top - 26 * k, top + rows * CELL + 6):
            draw.text((MARGIN + (c - col0) * CELL + CELL // 2 - 10, y), f"{c:02d}", fill=(220, 220, 220), font=font(18, True))
    for r in range(row0, row1 + 1):
        for x in (MARGIN // 2 - 8 * k, MARGIN + cols * CELL + MARGIN // 2 - 8 * k):
            draw.text((x, top + (row1 - r) * CELL + CELL // 2 - 10), chr(65 + r), fill=(220, 220, 220), font=font(20, True))
    if zone:
        # Game coordinates (cell space: x east, z south) every 4096 units, to tell spots apart.
        x0, y0 = cell_box(row0, col0)
        for i in range(9):
            v = -HALF + i * 4096
            px, py = x0 + i * CELL / 8, y0 + i * CELL / 8
            draw.line((px, y0, px, y0 + CELL), fill=(255, 255, 255), width=1)
            draw.line((x0, py, x0 + CELL, py), fill=(255, 255, 255), width=1)
            draw.text((px + 4, y0 + CELL - 22 * k), f"x {v:+.0f}", fill=(255, 255, 255), font=font(11), stroke_width=2, stroke_fill=(0, 0, 0))
            draw.text((x0 + CELL - 70 * k, py + 4), f"z {v:+.0f}", fill=(255, 255, 255), font=font(11), stroke_width=2, stroke_fill=(0, 0, 0))

    marks = []   # (kind, x, y, label, priority)

    # Doors and cities.
    data = world_data()
    seen_city = set()
    for d in data["doors"]:
        to = d["toName"].upper()
        if to[:1].isalpha() and " - " in to and to.split(" - ")[0].replace(" ", "")[1:].isdigit():
            continue   # a hut whose door leads back out into the wasteland
        if at(d["cell"], d["x"], d["z"]) is None:
            continue
        x, y = at(d["cell"], d["x"], d["z"])
        city = next((label for key, label in CITIES if key in to), None)
        if city:
            # Every gate is marked; the city is named once.
            marks.append(("city", x, y, "" if city in seen_city else city, 0))
            seen_city.add(city)
            continue
        name = d["name"].split("@")[0]
        if name.lower().startswith("worldchange"):
            name = d["toName"].title()
        name = (name.replace("Underground entrance", "Underground").replace(" Entrance", "").replace(" ENTRANCE", "")
                .replace("Entrance", "").strip(" -"))
        if "DANGEROUS CANYON CAVE" in to and "Outdoor Cave" not in name:
            name = "Dangerous Canyon Cave"
        marks.append(("door", x, y, name, 2))
    # Outposts.
    for o in data["outposts"]:
        if at(o["cell"], o["x"], o["z"]) is None:
            continue
        x, y = at(o["cell"], o["x"], o["z"])
        marks.append(("outpost", x, y, f"{o['name']}|{OUTPOST_LETTER.get(o['kind'], 'O')}", 1))

    # Placed objects and NPCs in the cells' spawn files.
    anchors = []   # spots a reference name may be pinned to
    trade = ("pawn shop", "trader", "medic", "barkeeper", "dealer", "hawker")
    for (row, col), code in cells.items():
        world = 2000 + 20 * row + col
        path = os.path.join(INSTALL, "terrain", f"pak_{code}.dat")
        if not os.path.exists(path):
            continue
        traders = []
        for typ, e in elements(decode(open(path, "rb").read())):
            if typ == 1000003 and len(e) >= 46:
                r = models.get(struct.unpack_from("<H", e, 44)[0])
                kind = {"6": "genrep", "7": "goguardian", "28": "vehicle", "2": "citycom"}.get(r["Type"]) if r else None
                if kind:
                    px, _, pz = struct.unpack_from("<fff", e, 0)
                    x, y = at(world, px, pz)
                    marks.append((kind, x, y, clean(r["Name"]).title() if zone else "", 3))
                    anchors.append((x, y))
            elif typ == 1000006 and len(e) >= 20:
                n = npcs.get(struct.unpack_from("<I", e, 16)[0])
                if not n or n.get("ModelTargetType") != "1":
                    continue
                name = clean(chars.get(int(n.get("ModelTargetValue") or 0), {}).get("Name", ""))
                if any(t in name.lower() for t in trade):
                    px, _, pz = struct.unpack_from("<fff", e, 0)
                    traders.append((*at(world, px, pz), name))
        # One trader mark per group standing together.
        groups = []
        for p in traders:
            g = next((g for g in groups if abs(g[0][0] - p[0]) < 12 and abs(g[0][1] - p[1]) < 12), None)
            (g.append(p) if g else groups.append([p]))
        for g in groups:
            x, y = sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g)
            names = sorted({p[2].split(" Selling")[0] for p in g})
            marks.append(("trader", x, y, ", ".join(names) if zone else "", 3))
            anchors.append((x, y))
    # Reference names, pinned to the nearest placed object.
    for name, gx, gy in REFERENCE:
        if (int(gy), int(gx) + 1) not in cells:
            continue
        x, y = grid(gx, gy)
        near = min(anchors, key=lambda a: (a[0] - x) ** 2 + (a[1] - y) ** 2, default=None)
        if near and ((near[0] - x) ** 2 + (near[1] - y) ** 2) ** 0.5 <= SNAP * CELL:
            x, y = near
        marks.append(("place", x, y, name, 1))

    # Draw: small dots first, then labelled marks, labels placed where they do not overlap.
    taken = []

    def free(box):
        return all(box[2] < t[0] or box[0] > t[2] or box[3] < t[1] or box[1] > t[3] for t in taken)

    for kind, x, y, label, _ in sorted(marks, key=lambda m: -m[4]):
        c = COLOURS[kind]
        if kind in ("genrep", "goguardian", "vehicle", "citycom", "trader"):
            r = (4 if kind != "goguardian" else 3) * k
            (draw.rectangle if kind == "trader" else draw.ellipse)((x - r, y - r, x + r, y + r), fill=c, outline=(0, 0, 0))
        elif kind == "door":
            r = 6 * k
            draw.ellipse((x - r, y - r, x + r, y + r), fill=c, outline=(0, 0, 0), width=2)
        elif kind == "outpost":
            draw.rectangle((x - 10, y - 10, x + 10, y + 10), fill=c, outline=(255, 255, 255), width=2)
            draw.text((x, y), label.split("|")[1], fill=(255, 255, 255), font=font(14, True), anchor="mm")
        elif kind == "place":
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline=(255, 255, 255), width=3)
        elif kind == "city":
            r = 11 * k
            draw.ellipse((x - r, y - r, x + r, y + r), fill=c, outline=(0, 0, 0), width=3)
        taken.append((x - 6, y - 6, x + 6, y + 6))
    for kind, x, y, label, _ in sorted(marks, key=lambda m: m[4]):
        if not label:
            continue
        text = label.split("|")[0]
        size, bold, colour = {"city": (24, True, COLOURS["city"]), "outpost": (16, True, (190, 215, 255)),
                              "place": (16, False, (255, 255, 255)), "door": (13, False, (255, 175, 165))}.get(kind, (12, False, COLOURS[kind]))
        f = font(size, bold)
        w, h = draw.textbbox((0, 0), text, font=f)[2:]
        gap = (14 if kind != "city" else 18) * k
        for dx, dy in ((gap, -h / 2), (-gap - w, -h / 2), (-w / 2, -gap - h), (-w / 2, gap), (gap, -h - 4), (gap, 4), (-gap - w, -h - 4), (-gap - w, 4)):
            box = (x + dx, y + dy, x + dx + w, y + dy + h)
            if free(box) or kind == "city":
                break
        draw.text((box[0], box[1]), text, fill=colour, font=f, stroke_width=3, stroke_fill=(0, 0, 0))
        taken.append(box)

    # Title and legend.
    world_name = info.get(2000 + 20 * row0 + col0, {}).get("Name", "")
    draw.text((MARGIN, 22), f"{world_name} (world {2000 + 20 * row0 + col0})" if zone else "Neocron wasteland", fill=(255, 255, 255), font=font(30 if zone else 40, True))
    subtitle = ("From the game's own files: the ground texture and every object placed in this zone. Grid lines every 4096 units. North at the top."
                if zone else "From the game's own files: the ground textures, doors, outposts, GenReps, GoGuardians, vehicle depots and traders. "
                "Village and oasis names from the EMS.ru / NEMA maps, pinned to the nearest placed object. North at the top.")
    draw.text((MARGIN, 70 if not zone else 76), subtitle, fill=(200, 200, 200), font=font(16 if not zone else 11))
    ly = top + rows * CELL + 46 * k
    items = [("city", "City or city gate"), ("outpost", "Outpost (M mine, F factory, L lab, T fortress, U uplink)"),
             ("door", "Dungeon, cave, bunker or tunnel entrance"), ("place", "Village, oasis or camp"),
             ("genrep", "GenRep"), ("goguardian", "GoGuardian"), ("vehicle", "Vehicle depot"), ("citycom", "CityCom"),
             ("trader", "Trader or medic")]
    for i, (kind, text) in enumerate(items):
        x, y = MARGIN + (i % 3) * (W - 2 * MARGIN) // 3, ly + (i // 3) * 46 * k
        c = COLOURS[kind]
        if kind == "outpost":
            draw.rectangle((x - 10, y - 10, x + 10, y + 10), fill=c, outline=(255, 255, 255), width=2)
        elif kind == "place":
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline=c, width=3)
        elif kind == "trader":
            draw.rectangle((x - 6, y - 6, x + 6, y + 6), fill=c, outline=(0, 0, 0))
        else:
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=c, outline=(0, 0, 0), width=2)
        draw.text((x + 20 * k, y - 11 * k), text, fill=(230, 230, 230), font=font(18 if not zone else 12))
    draw.text((MARGIN, ly + 150 * k), "Rows A (south, beside Neocron) to L; columns 01 (west) to 16. Creature spawns are placed by the server and are not in the client's files.",
              fill=(170, 170, 170), font=font(16 if not zone else 11))
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    target = os.path.join(out, f"Zone {zone[0].upper()} {zone[2:]} map.png" if zone else "World map.png")
    img.save(target)
    print(f"Wrote {target} ({img.size[0]} x {img.size[1]}, {len(marks)} marks)")
    return target


if __name__ == "__main__":
    # worldmap.py            the whole wasteland
    # worldmap.py J01        one zone (cell) at full detail
    # --open                 then show it (the double-click launchers)
    args = [a for a in sys.argv[1:] if a != "--open"]
    arg = "".join(args).strip().lower().replace(" ", "").replace("_", "")
    if arg and not (arg[0].isalpha() and arg[1:].isdigit()):
        raise SystemExit(f"'{' '.join(args)}' is not a zone: give its cell, for example J01.")
    picture = main(f"{arg[0]}_{int(arg[1:]):02d}" if arg else None)
    if "--open" in sys.argv:
        os.startfile(picture)
