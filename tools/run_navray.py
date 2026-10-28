"""Run one Nav-Ray walk from the command line (same code path as the Nav-Ray tab) and record it.

    runtime/python.exe tools/run_navray.py "TRADER DIRECTORY > WEAPONS" [recording-folder]

Focus Neocron (Nav-Ray open, Tab pressed so the cursor is free) within the countdown. Every status
message of the run is printed with its time and the game frame at that moment is saved as a
full-size JPEG in the recording folder, so a run can be reviewed afterwards.
"""
import subprocess
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from macro_core import Control, default_profile  # noqa: E402
from navray_runner import NavRayRunner  # noqa: E402
from windows_backend import WindowsBackend  # noqa: E402


def main():
    destination = sys.argv[1] if len(sys.argv) > 1 else "FACTION HQS > BLACK DRAGON"
    folder = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "diagnostics" / "recording"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.jpg"):
        old.unlink()
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
    holder = {}
    count = {"n": 0}

    def emit(kind, payload=None):
        count["n"] += 1
        print(f"[{time.monotonic() - started:6.1f}s] {count['n']:03d} {kind}: {payload}", flush=True)
        frame = getattr(holder.get("runner"), "last_frame", None)
        if frame is not None:
            cv2.imwrite(str(folder / f"{count['n']:03d}.jpg"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 93])

    runner = holder["runner"] = NavRayRunner(profile, backend, Control(), emit)
    # Open Nav-Ray ourselves if it is not showing: Tab for the interactive UI, then click NAV-RAY in the top menu.
    import navray
    reader = runner.detector.text_reader()

    def menu_item():
        gray = runner.detector.gray(runner.frame())
        strip = gray[:int(.06*gray.shape[0])]
        for text, x, y, w, h in reader.read_words(strip):
            if text.upper().startswith("NAV"):
                return (x + w//2, y + h//2)
        return None
    if navray.find_navray(reader, runner.detector.gray(runner.frame())) is None:
        point = menu_item()
        if point is None:
            emit("status", "Nav-Ray window not showing: pressing Tab for the interactive UI.")
            backend.key("tab", True)
            time.sleep(.08)
            backend.key("tab", False)
            time.sleep(.8)
            point = menu_item()
        if point is not None:
            emit("status", f"Clicking NAV-RAY in the top menu at {point}.")
            runner.click(point)
            time.sleep(1.0)
    runner.run()


if __name__ == "__main__":
    main()
