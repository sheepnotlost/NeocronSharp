"""Make a copy of the suite for a PC or VM with no .NET: the tracked files, plus traversal.exe with .NET inside it.

Run with Make VM Copy.cmd. It needs the .NET 9 SDK on this PC only. The tracker tabs stay empty in the copy; Target
Acquisition, Traversal, Research and Construction work. Sends no game input.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT.parent / "NeocronSharp VM"
ENGINE = TARGET / "traversal" / "bin" / "Release" / "net9.0"    # where traversal_tab.py looks for it
LEFT_OUT = ("Research/", "tests/", "styling/", "NeocronSharp/tests/")


def wanted(path):
    return not path.startswith(LEFT_OUT)


def main():
    listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    files = [path for path in listed.splitlines() if wanted(path)]
    print(f"Copying {len(files)} files to {TARGET} ...")
    for path in files:
        to = TARGET / path
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, to)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    (TARGET / "VERSION").write_text(head + "\n", encoding="utf-8")       # shown in the Research log
    print("Building traversal.exe with .NET inside it ...")
    done = subprocess.run(["dotnet", "publish", str(ROOT / "traversal" / "Traversal.csproj"), "-c", "Release", "-r", "win-x64",
                           "--self-contained", "true", "-o", str(ENGINE), "-nologo", "-v", "q"])
    if done.returncode or not (ENGINE / "traversal.exe").exists():
        print("The engine did not build, so the copy is not ready.")
        return 1
    print(f"\nReady: {TARGET}\nCopy that whole folder into the VM and double-click Launch.cmd there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
