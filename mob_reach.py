"""How far away each mob is when it hurts you: the one fact the game's files don't give for mobs that fight with their own
bodies (claws, bites, spit). The hunt calls record() when your health falls; with only one robot, mutant or animal alive
near you, that mob did it, and the distance goes into traversal/logs/mob-reach.json. `traversal.exe mobs` reads it back
into logs/mob-map.md ("Hit you from", and melee or ranged once three hits are seen)."""
import json

NEAR = 1000          # units: any mob closer than this could have done it (the longest NPC guns reach about 900)
KEEP = 20            # hits kept per mob, the newest


def culprit(actors, hunted, near=NEAR):
    """The only living prey within near, or None when it could have been any of several (or none)."""
    close = [a for a in actors if hunted(a) and not a["dead"] and a["distance"] <= near]
    return close[0] if len(close) == 1 else None


def record(path, actors, hunted, near=NEAR):
    """(name, distance) of the mob that hit you, written down; None when it can't be told."""
    mob = culprit(actors, hunted, near)
    if mob is None:
        return None
    try:
        seen = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(seen, dict):
            seen = {}
    except (OSError, ValueError):
        seen = {}
    name = " ".join(mob["name"].split())
    entry = seen.setdefault(name, {})
    entry["away"] = ([*entry.get("away", []), round(mob["distance"])])[-KEEP:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    except OSError:
        pass          # a note that can't be written must not stop a hunt
    return name, mob["distance"]
