"""Read every Nav-Ray category and destination from the open in-game window and save them to
data/navray_destinations.json. Focus Neocron (Nav-Ray open, Tab pressed so the cursor is free)
within the countdown. Sends mouse clicks and wheel events to the game; no keyboard input.

    runtime/python.exe tools/scan_navray.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from macro_core import Control, default_profile  # noqa: E402
from navray_runner import NavRayRunner  # noqa: E402
from windows_backend import WindowsBackend  # noqa: E402


def main():
    backend = WindowsBackend()
    for left in range(5, 0, -1):
        print(f"Focus Neocron... {left}", flush=True)
        time.sleep(1)
    # Bring the game forward ourselves right before binding (another window may have taken the focus).
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "(New-Object -ComObject WScript.Shell).AppActivate('Neocron Evolution')"],
                   capture_output=True, timeout=20)
    time.sleep(1.0)
    title, size = backend.bind_foreground()
    if "neocron" not in title.lower():
        raise SystemExit(f"The foreground window is '{title}', not Neocron.")
    profile = default_profile()
    profile["operation"] = "navray"
    profile["navray"] = {"destination": "", "scan": True}
    profile["client_size"] = size
    result = {}

    def emit(kind, payload=None):
        print(kind, payload if kind != "navray_catalog" else f"{len(payload)} categories", flush=True)
        if kind == "navray_catalog":
            result.update(payload)

    runner = NavRayRunner(profile, backend, Control(), emit)
    runner.run()
    if result:
        out = ROOT / "data" / "navray_destinations.json"
        out.write_text(json.dumps({"categories": result}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("saved", out, flush=True)


if __name__ == "__main__":
    main()
