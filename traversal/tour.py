"""Live acceptance tour: travel to each city sector in turn and record what happened.

Usage: runtime/python.exe traversal/tour.py [sectorId ...]
Writes traversal/logs/tour-<time>.md and prints one line per destination.
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXE = HERE / "bin" / "Release" / "net9.0" / "traversal.exe"
NAMES = {1: "Plaza 1", 2: "Plaza 2", 101: "Plaza 3", 102: "Plaza 4", 3: "Via Rosso 1", 4: "Via Rosso 2",
         401: "Via Rosso 3", 5: "Pepper Park 1", 6: "Pepper Park 2", 7: "Pepper Park 3",
         8: "Industrial 1", 801: "Industrial 2"}
DEFAULT = [2, 101, 5, 6, 7, 102, 3, 4, 401, 1, 8, 801]


def in_world():
    out = subprocess.run([str(EXE), "plan", "0,0,0"], cwd=HERE, capture_output=True, text=True, timeout=120).stdout
    return "verified in-world player is unavailable" not in out and "Open exactly one" not in out


def main():
    targets = [int(a) for a in sys.argv[1:]] or DEFAULT
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report = HERE / "logs" / f"tour-{stamp}.md"
    report.parent.mkdir(exist_ok=True)
    rows = []
    for target in targets:
        if not in_world():
            rows.append((target, "SKIPPED", 0, "character not in-world (logged out, loading or dead?)"))
            print(f"{NAMES.get(target, target)}: not in-world, tour stopped", flush=True)
            break
        start = time.time()
        proc = subprocess.run([str(EXE), "travel", str(target), "--pulse", "12", "--run"], cwd=HERE,
                              capture_output=True, text=True, timeout=1800)
        took = time.time() - start
        lines = [l for l in proc.stdout.splitlines() if l.strip() and not l.lstrip()[:1] in "-0123456789"]
        ok = proc.returncode == 0 and any(l.startswith("Arrived in") for l in lines)
        detail = lines[-1] if lines else "(no output)"
        legs = [l for l in lines if l.startswith("Leg ") or l.startswith("Avoiding") or "failed" in l or l.startswith("Landed")]
        rows.append((target, "PASS" if ok else "FAIL", took, detail, legs))
        print(f"{NAMES.get(target, target)}: {'PASS' if ok else 'FAIL'} in {took:.0f}s - {detail}", flush=True)
        (HERE / "logs" / f"tour-{stamp}-{target}.txt").write_text(proc.stdout, encoding="utf-8")
        if not ok and "F8" in detail:
            break
    with report.open("w", encoding="utf-8") as f:
        f.write(f"# Traversal tour {stamp}\n\n| Destination | Result | Seconds | Last line |\n|---|---|---|---|\n")
        for row in rows:
            f.write(f"| {NAMES.get(row[0], row[0])} | {row[1]} | {row[2]:.0f} | {row[3]} |\n")
        for row in rows:
            if len(row) > 4 and row[4]:
                f.write(f"\n## {NAMES.get(row[0], row[0])}\n\n" + "\n".join(f"- {l}" for l in row[4]) + "\n")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
