"""Live position, heading and sector from NeocronSharp's read-only `--telemetry` feed (one JSON line per sample).

Nav-Ray uses it to know where the character really is: stuck = the position stops changing, a zone change = the
sector changes, and the map planner (mapplan) gives the way to an exit from here. Without NeocronSharp, or with a
game build it does not support, latest() stays None and Nav-Ray walks by sight alone."""

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

EXECUTABLE = Path(__file__).resolve().parent / "NeocronSharp" / "dist" / "NeocronSharp.exe"
FRESH = 1.0                  # a sample older than this (seconds) is not trusted for steering


@dataclass(frozen=True)
class Sample:
    when: float              # time.monotonic() when the line arrived
    sector: int
    rotation: float | None   # map rotation in degrees (None until the HUD has loaded)
    x: float                 # ground X
    y: float                 # height
    z: float                 # ground Z
    heading: float           # degrees, 0 = -Z, 90 = +X (NeocronSharp's convention)


def parse(line, now=None):
    """A Sample from one feed line, or None for an error line or anything unreadable."""
    try:
        data = json.loads(line)
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        return Sample(time.monotonic() if now is None else now, int(data["sector"]),
                      None if data.get("rotation") is None else float(data["rotation"]),
                      float(data["x"]), float(data["y"]), float(data["z"]), float(data["heading"]))
    except (ValueError, KeyError, TypeError):
        return None


class Feed:
    """NeocronSharp's feed running in the background; latest() is the newest good sample."""

    def __init__(self, interval_ms=100, popen=subprocess.Popen, executable=EXECUTABLE):
        self.sample, self.error, self.process = None, None, None
        self.lock = threading.Lock()
        if not Path(executable).exists():
            self.error = "NeocronSharp is not built."
            return
        try:
            self.process = popen([str(executable), "--telemetry", str(int(interval_ms))], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.error = f"NeocronSharp telemetry could not start: {exc}"
            return
        threading.Thread(target=self._read, args=(self.process,), name="neocronsharp-telemetry", daemon=True).start()

    def _read(self, process):
        try:
            for line in process.stdout:
                sample = parse(line)
                with self.lock:
                    if sample is not None:
                        self.sample, self.error = sample, None
                    else:
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict):
                                self.error = data.get("error") or self.error
                        except ValueError:
                            pass
        except (OSError, ValueError, UnicodeDecodeError):  # the feed closed or sent something unreadable
            pass

    def latest(self, max_age=FRESH, now=None):
        """The newest sample if it is at most `max_age` seconds old, else None."""
        with self.lock:
            sample = self.sample
        now = time.monotonic() if now is None else now
        return sample if sample is not None and now - sample.when <= max_age else None

    def close(self):
        """Closing stdin ends the feed cleanly."""
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
            process.wait(2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
