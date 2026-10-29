"""Render mapplan's walkable mask, exits and planned paths for visual checking (dev tool).

    runtime\\python.exe tools\\mapplan_render.py OUT_DIR [WORLD_ID ...]
    runtime\\python.exe tools\\mapplan_render.py --fixtures tests\\fixtures   (rewrites the test crops)

Writes OUT_DIR/plan_<id>.png (map, 4x): floor tinted green, opened separators blue, soft dots orange,
exits red (arrow + target), landmarks purple, and the A* path + waypoints from a few starts to every exit.
Reads the game install read-only; game art stays local (never commit the output).
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapplan  # noqa: E402

ZOOM = 4
COLORS = [(0, 0, 255), (0, 160, 0), (255, 0, 0), (0, 140, 255), (200, 0, 200), (0, 200, 200)]


def render(planner, starts, path):
    g = planner.gray
    img = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR).astype(np.float32)
    tint = np.zeros_like(img)
    tint[planner.walk & ~planner.bridges & ~planner.soft] = (0, 255, 0)
    tint[planner.bridges] = (255, 120, 0)
    tint[planner.soft] = (0, 140, 255)
    m = planner.walk[..., None]
    img = np.where(m, img * .65 + tint * .35, img)
    img = cv2.resize(img.astype(np.uint8), None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)

    def P(u, v):
        return int(round((u + .5) * ZOOM)), int(round((v + .5) * ZOOM))

    proj = planner.projection
    times = []
    for si, start in enumerate(starts):
        for ei, ex in enumerate(planner.exits):
            t = time.perf_counter()
            px = planner.plan_pixels(start, ex.world)
            times.append((time.perf_counter() - t) * 1000)
            if px is None:
                print("  no path", start, "->", ex.label)
                continue
            col = COLORS[(si * len(planner.exits) + ei) % len(COLORS)]
            pts = np.array([P(u, v) for u, v in px], np.int32)
            cv2.polylines(img, [pts], False, col, 1, cv2.LINE_AA)
            for x, z in planner.to_waypoints(px):
                cv2.circle(img, P(*proj.to_pixel(x, z)), 3, col, 1, cv2.LINE_AA)
        su, sv = proj.to_pixel(*start)
        cv2.drawMarker(img, P(su, sv), (0, 0, 0), cv2.MARKER_TILTED_CROSS, 14, 2)
    for ex in planner.exits:
        x, y, w, h = ex.box
        cv2.rectangle(img, P(x - .5, y - .5), P(x + w - .5, y + h - .5), (0, 0, 255), 2)
        cv2.circle(img, P(*ex.pixel), 6, (0, 0, 255), 2)
        a = P(x + w / 2 - .5, y + h / 2 - .5)
        cv2.arrowedLine(img, a, (a[0] + int(ex.direction[0] * 40), a[1] + int(ex.direction[1] * 40)), (0, 0, 255), 2)
        cv2.putText(img, f"{ex.label} {ex.bearing:.0f}", (P(x, y)[0], P(x, y)[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 200), 1)
    for lm in planner.landmarks:
        x, y, w, h = lm.box
        cv2.rectangle(img, P(x - .5, y - .5), P(x + w - .5, y + h - .5), (200, 0, 200), 2)
    cv2.imwrite(path, img)
    return times


def write_fixtures(folder, ids=(1, 5)):
    """tests/fixtures/mapplan_<id>.png crops (floor + labels, 3 px margin) and mapplan_maps.json."""
    import json
    catalog = mapplan.SectorMapCatalog()
    meta = {}
    for wid in ids:
        sector = catalog.find(wid)
        gray = catalog.image(sector)
        walk, _, _ = mapplan.walkable_mask(gray)
        keep = walk | (gray <= mapplan.BLACK_MAX)
        ys, xs = np.nonzero(keep)
        x0, y0 = max(0, xs.min() - 3), max(0, ys.min() - 3)
        x1, y1 = min(gray.shape[1], xs.max() + 4), min(gray.shape[0], ys.max() + 4)
        name = f"mapplan_{wid}.png"
        cv2.imwrite(os.path.join(folder, name), gray[y0:y1, x0:x1])
        meta[str(wid)] = {"name": sector.name, "image": name, "crop_origin": [int(x0), int(y0)],
                          "bitmap_ref": list(sector.bitmap_ref), "world_ref": list(sector.world_ref),
                          "scale": sector.scale}
    with open(os.path.join(folder, "mapplan_maps.json"), "w") as f:
        json.dump(meta, f, indent=1)


def main():
    if sys.argv[1] == "--fixtures":
        write_fixtures(sys.argv[2])
        return
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ids = [int(a) for a in sys.argv[2:]] or [1, 2, 101, 5]
    catalog = mapplan.SectorMapCatalog()
    for wid in ids:
        planner = mapplan.SectorPlanner.from_catalog(catalog, wid, 270)
        # starts: each landmark (on floor) plus the floor cell with the most clearance
        starts = [lm.world for lm in planner.landmarks if planner.snap(*lm.world)]
        v, u = np.unravel_index(np.argmax(planner.wall_distance), planner.wall_distance.shape)
        starts.append(planner.projection.to_world(u, v))
        if wid == 1:
            starts.append((-1023.0, 3072.05))     # live position read in Plaza 1
        times = render(planner, starts[:4], os.path.join(out, f"plan_{wid}.png"))
        print(catalog.name(wid), "exits", [e.label for e in planner.exits],
              "plans", len(times), "max %.1f ms, mean %.1f ms" % (max(times), sum(times) / len(times)))


if __name__ == "__main__":
    main()
