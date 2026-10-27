"""Run one Nav-Ray walk from the command line (same code path as the Nav-Ray tab).

    runtime/python.exe tools/run_navray.py "FACTION HQS > BLACK DRAGON"

Focus Neocron (Nav-Ray open, Tab pressed so the cursor is free) within the countdown.
"""
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
    destination = sys.argv[1] if len(sys.argv) > 1 else "FACTION HQS > BLACK DRAGON"
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
    profile["navray"] = {"destination": destination}
    profile["client_size"] = size
    started = time.monotonic()

    def emit(kind, payload=None):
        print(f"[{time.monotonic() - started:6.1f}s] {kind}: {payload}", flush=True)

    NavRayRunner(profile, backend, Control(), emit).run()


if __name__ == "__main__":
    main()
