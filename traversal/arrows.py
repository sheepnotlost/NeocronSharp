"""Export each sector's zone-line arrows from its in-game sector map (mapplan.SectorPlanner).

The world files' WorldChange records name where an exit leads, but their position is
the arrival spot, not the zone line. The sector map's exit arrows mark the line itself
and the way to push through it; Nav-Ray crossed zone lines with them live. This writes
traversal/arrows.json: {"<worldId>": [{"label", "x", "z", "bx", "bz", "bearing"}]}.

Usage: runtime/python.exe traversal/arrows.py [worldId ...]   (default: every zone reachable on foot)
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import mapplan  # noqa: E402

EXE = HERE / "bin" / "Release" / "net9.0" / "traversal.exe"


def one(world_id, rotation):
    """Arrows for one sector at the live map rotation (from the HUD compass), as a list."""
    catalog = mapplan.SectorMapCatalog()
    sector = catalog.find(world_id)
    if sector is None:
        return []
    planner = mapplan.SectorPlanner(catalog.image(sector), sector.projection(rotation))
    return [{"label": e.label, "x": round(e.world[0], 1), "z": round(e.world[1], 1),
             "bx": round(e.beyond[0], 1), "bz": round(e.beyond[1], 1), "bearing": round(e.bearing, 1)}
            for e in planner.exits]


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--one":
        world_id, rotation = sys.argv[2].split(":")
        print(json.dumps(one(int(world_id), float(rotation))))
        return
    ids = [int(a) for a in sys.argv[1:]]
    if not ids:
        zones = json.loads(subprocess.run([str(EXE), "zones"], cwd=HERE, capture_output=True, text=True).stdout)
        ids = sorted(z["id"] for z in zones)
    catalog = mapplan.SectorMapCatalog()
    out, missing = {}, []
    for wid in ids:
        sector = catalog.find(wid)
        if sector is None:
            missing.append(wid)
            continue
        try:
            planner = mapplan.SectorPlanner(catalog.image(sector), sector.projection())
        except Exception as exc:  # a map style the planner refuses: report, carry on
            missing.append(wid)
            print(f"{wid}: {exc}")
            continue
        out[str(wid)] = [{"label": e.label, "x": round(e.world[0], 1), "z": round(e.world[1], 1),
                          "bx": round(e.beyond[0], 1), "bz": round(e.beyond[1], 1), "bearing": round(e.bearing, 1)}
                         for e in planner.exits]
    (HERE / "arrows.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(out)} sectors with arrows ({sum(len(v) for v in out.values())} arrows); no map: {missing}")


if __name__ == "__main__":
    main()
