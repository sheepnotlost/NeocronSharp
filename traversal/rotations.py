"""Work out each street sector's map rotation offline.

The sector map's zone-line arrows only land in the right world place with the map's
rotation, which the game shows on the HUD compass (Plaza 270, Pepper Park 0). Without
being there, the rotation can be found from the world files: each exit to a neighbouring
street sector has a zone line close by, so the right rotation is the one that puts an
arrow near every such exit. This scores 0/90/180/270 and writes traversal/rotations.json:
{"<worldId>": {"rotation": deg, "score": mean distance, "runnerUp": deg, "margin": units}}.
Usage: runtime/python.exe traversal/rotations.py
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import mapplan  # noqa: E402
from arrows import one  # noqa: E402

INDEX = HERE.parent / "NeocronSharp" / "logs" / "environment-index.json"
# Seen live on the compass, to check the method against.
KNOWN = {1: 270, 2: 270, 101: 270, 5: 0, 6: 0}


def street_exits(summary, streets):
    """Real exits (an arrival point is set) that lead to another street sector."""
    out = []
    for f in summary["Features"]:
        p = f["Properties"]
        if f["Kind"] != "WorldChange" or p.get("NextLevelStartIndex", "0") in ("", "0"):
            continue
        try:
            to = int(p["NextLevel"])
        except (KeyError, ValueError):
            continue
        if to != summary["WorldId"] and to in streets:
            out.append((f["Position"]["X"], f["Position"]["Z"]))
    return out


def main():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    by = {s["WorldId"]: s for s in index["summaries"]}
    streets = {int(k) for k in json.loads((HERE / "arrows.json").read_text(encoding="utf-8"))}
    result = {}
    for wid in sorted(streets):
        exits = street_exits(by[wid], streets) if wid in by else []
        scores = {}
        for rot in (0, 90, 180, 270):
            arrows = one(wid, rot)
            if not arrows or not exits:
                continue
            # Mean distance from each street exit to its nearest arrow (capped, so one odd exit cannot dominate).
            scores[rot] = sum(min(2500.0, min(math.hypot(a["x"] - x, a["z"] - z) for a in arrows)) for x, z in exits) / len(exits)
        if not scores:
            continue
        ranked = sorted(scores, key=scores.get)
        best, second = ranked[0], ranked[1] if len(ranked) > 1 else None
        result[str(wid)] = {"rotation": best, "score": round(scores[best]), "runnerUp": second,
                            "margin": round(scores[second] - scores[best]) if second is not None else None,
                            "exits": len(exits), "name": by[wid]["Name"]}
        check = "" if wid not in KNOWN else ("  (matches compass)" if KNOWN[wid] == best else f"  (COMPASS SAYS {KNOWN[wid]})")
        print(f"{wid:5} {by[wid]['Name']:24} rotation {best:3}  mean {scores[best]:5.0f}  next {second} by {result[str(wid)]['margin']}{check}")
    (HERE / "rotations.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
