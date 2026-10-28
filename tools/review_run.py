"""Summarise the last recorded Nav-Ray run (diagnostics/last_run) and build a contact sheet of its failures.

    runtime/python.exe tools/review_run.py [folder]

Prints how the run went (legs by outcome, turns, calibration, dash colour) and saves failures.png: the
game frames at every "stuck", "lost" and "lost the dashes" moment, numbered, so the exact scenes the macro
fails in can be seen and added to the tests.
"""
import collections
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FAILURE = re.compile(r"stuck|lost the dashes|lost the dashes|turn lost|no dashes in view|did not|not found|could not", re.I)


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "diagnostics" / "last_run"
    path = folder / "events.jsonl"
    if not path.exists():
        raise SystemExit(f"No recording in {folder}. Run Nav-Ray once first.")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    outcomes = collections.Counter()
    for event in events:
        text = event.get("text") or ""
        match = re.search(r"leg \d+ ended after (\d+)s: (.*)\.", text)
        if match:
            outcomes[match.group(2)] += 1
    print(f"{len(events)} events over {events[-1]['t']:.0f}s; colour {events[-1].get('dash_color')}, "
          f"calibration {events[-1].get('px_per_count')} px per count")
    for reason, count in outcomes.most_common():
        print(f"  {count:3d} legs ended: {reason}")
    failures = [e for e in events if e.get("frame") and FAILURE.search(e.get("text") or "")]
    print(f"{len(failures)} failure moments")
    tiles = []
    for event in failures[:12]:
        image = cv2.imread(str(folder / event["frame"]))
        if image is None:
            continue
        image = cv2.resize(image, (640, 360))
        cv2.putText(image, f"{event['n']} {event['t']:.0f}s", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, .9, (0, 255, 255), 2)
        cv2.putText(image, (event["text"] or "")[:60], (10, 350), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
        tiles.append(image)
    if tiles:
        while len(tiles) % 3:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
        cv2.imwrite(str(folder / "failures.png"), sheet)
        print("saved", folder / "failures.png")


if __name__ == "__main__":
    main()
