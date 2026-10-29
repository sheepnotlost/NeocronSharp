"""Pair video banners and Location-panel changes with the walk logs' positions.

Video time 0 = 2026-10-29 13:49:43 UTC. Prints one line per banner and per zone change.
"""
import json, sys
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOGS = Path(sys.argv[1])
T0 = datetime(2026, 10, 29, 13, 49, 43, tzinfo=timezone.utc)

samples = []
for f in sorted(LOGS.glob("steer-*.jsonl")):
    for line in f.read_text().splitlines():
        e = json.loads(line)
        ts = e["timeUtc"]
        ts = ts[:26] + ts[-6:] if len(ts) > 32 else ts   # trim 7-digit fractions for fromisoformat
        t = (datetime.fromisoformat(ts) - T0).total_seconds()
        p, fw = e["position"], e["forward"]
        samples.append((t, p["X"], p["Y"], p["Z"], fw["X"], fw["Z"], e["kind"], f.name))
samples.sort()
times = [s[0] for s in samples]


def at(t, tol=1.0):
    i = bisect_left(times, t)
    best = min((j for j in (i - 1, i) if 0 <= j < len(samples)), key=lambda j: abs(times[j] - t), default=None)
    if best is None or abs(times[best] - t) > tol:
        return None
    return samples[best]


ev = json.loads((HERE / "events.json").read_text())
locs = ev["locations"]


def where(t):
    name = None
    for l in locs:
        if l["t"] <= t: name = l["text"]
    return name


rows = []
for b in ev["banners"]:
    s = at(b["start"])
    nxt = next((l for l in locs if b["start"] < l["t"] <= b["end"] + 25), None)
    rows.append({"kind": "banner", "t": b["start"], "end": b["end"], "in": where(b["start"]), "text": b["text"],
                 "zoned_to": nxt and nxt["text"], "zoned_t": nxt and nxt["t"],
                 "pos": s and [round(v) for v in s[1:4]], "fwd": s and [round(v, 3) for v in s[4:6]], "log": s and s[7]})
for l in locs:
    s = at(l["t"] - 1.5, tol=3)
    rows.append({"kind": "zone", "t": l["t"], "to": l["text"], "pos_before": s and [round(v) for v in s[1:4]],
                 "log": s and s[7]})
rows.sort(key=lambda r: r["t"])
for r in rows:
    utc = (T0 + timedelta(seconds=r["t"])).strftime("%H:%M:%S")
    if r["kind"] == "banner":
        print(f"{r['t']:7.1f}s {utc}  BANNER in {r['in']}: {r['text']}  pos={r['pos']} fwd={r['fwd']} -> zoned {r['zoned_to']} at {r['zoned_t']}  [{r['log']}]")
    else:
        print(f"{r['t']:7.1f}s {utc}  LOCATION now {r['to']}  last pos={r['pos_before']}  [{r['log']}]")
(HERE / "paired.json").write_text(json.dumps(rows, indent=1))
