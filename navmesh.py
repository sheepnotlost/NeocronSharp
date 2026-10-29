"""Navmesh paths from NeocronSharp's read-only `--navplan` mode (one JSON request per line in, one answer per line out).

NeocronSharp reads the live position itself, bakes a Recast navmesh of the current sector from the game's level
geometry (about 5 s the first time; cached on disk under NeocronSharp/settings/navmesh, then well under a second)
and answers with Detour corner paths. Paths here are in ground coordinates (x, z); heights are kept alongside.
Every call returns None when NeocronSharp is missing, the game is not readable, or no path exists; `error` then
says why. Nothing here sends game input."""

import itertools
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

EXECUTABLE = Path(__file__).resolve().parent / "NeocronSharp" / "dist" / "NeocronSharp.exe"
TIMEOUT = 30.0               # seconds; a sector seen for the first time is baked (~5 s, more for big sectors)


@dataclass(frozen=True)
class Exit:
    name: str                # e.g. "WorldChange3"
    x: float
    y: float
    z: float
    index: int | None        # the record's own Index
    next_level: int | None   # destination world id
    next_level_name: str | None
    start_index: int | None  # arrival point in the destination; 0 = none (lift/placeholder records)
    destination_known: bool  # next_level > 0 and an arrival point is set
    bearing: float           # straight-line direction from the player, 0 = -Z, 90 = +X (telemetry heading)
    distance: float          # straight-line ground distance from the player
    path_length: float | None = None   # walked length on the navmesh (exits() only; None = unroutable)
    complete: bool | None = None       # exits() only: the exit itself is reachable


@dataclass(frozen=True)
class Plan:
    world: int
    world_name: str
    start: tuple             # the live position (x, z) the plan was made from
    path: list               # [(x, z), ...] Detour corners; the first is the player's snapped position
    heights: list            # Y of each corner
    complete: bool           # False: the target is not reachable; the path ends at the nearest reachable point
    length: float
    exit: Exit | None = None


def _exit(data):
    x, y, z = data["position"]
    return Exit(str(data["name"]), float(x), float(y), float(z), data.get("index"), data.get("nextLevel"),
                data.get("nextLevelName"), data.get("nextLevelStartIndex"), bool(data.get("destinationKnown")),
                float(data["bearing"]), float(data["distance"]),
                None if data.get("pathLength") is None else float(data["pathLength"]),
                None if "complete" not in data else bool(data["complete"]))


def parse_plan(data):
    """A Plan from a successful path answer, or None."""
    try:
        if not isinstance(data, dict) or not data.get("ok") or "path" not in data:
            return None
        path = [(float(c[0]), float(c[2])) for c in data["path"]]
        heights = [float(c[1]) for c in data["path"]]
        start = data["from"]
        return Plan(int(data["world"]), str(data.get("worldName") or ""), (float(start[0]), float(start[2])), path, heights,
                    bool(data.get("complete")), float(data.get("length", 0.0)),
                    _exit(data["exit"]) if isinstance(data.get("exit"), dict) else None)
    except (ValueError, KeyError, TypeError, IndexError):
        return None


class NavPlanner:
    """One NeocronSharp --navplan process, started on first use and restarted if it dies."""

    def __init__(self, popen=subprocess.Popen, executable=EXECUTABLE, timeout=TIMEOUT):
        self.popen, self.executable, self.timeout = popen, Path(executable), timeout
        self.process, self.answers, self.error = None, None, None
        self.ids = itertools.count(1)
        self.lock = threading.Lock()

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return True
        if not self.executable.exists():
            self.error = "NeocronSharp is not built."
            return False
        try:
            self.process = self.popen([str(self.executable), "--navplan"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.process, self.error = None, f"NeocronSharp navplan could not start: {exc}"
            return False
        self.answers = queue.Queue()
        threading.Thread(target=self._read, args=(self.process, self.answers), name="neocronsharp-navplan", daemon=True).start()
        return True

    @staticmethod
    def _read(process, answers):
        try:
            for line in process.stdout:
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    answers.put(data)
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        answers.put(None)    # the process closed its output

    def request(self, payload, timeout=None):
        """Send one request (a dict) and return the successful answer dict, or None (see `error`)."""
        with self.lock:
            if not self._start():
                return None
            request_id = next(self.ids)
            try:
                self.process.stdin.write(json.dumps({**payload, "id": request_id}) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                self.error = f"NeocronSharp navplan closed: {exc}"
                self._stop()
                return None
            deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
            while True:
                remaining = deadline - time.monotonic()
                try:
                    data = self.answers.get(timeout=max(remaining, 0)) if remaining > 0 else self.answers.get_nowait()
                except queue.Empty:
                    self.error = "NeocronSharp navplan did not answer in time."
                    return None
                if data is None:
                    self.error = "NeocronSharp navplan closed."
                    self._stop()
                    return None
                if data.get("id") != request_id:
                    continue     # a late answer to an earlier request that timed out
                if not data.get("ok"):
                    self.error = data.get("error") or "NeocronSharp navplan failed."
                    return None
                self.error = None
                return data

    def exits(self, timeout=None):
        """Every WorldChange in the current sector with its route from here, or None."""
        data = self.request({"to": "exits"}, timeout)
        try:
            return None if data is None else [_exit(e) for e in data["exits"]]
        except (ValueError, KeyError, TypeError):
            self.error = "Unreadable exits answer."
            return None

    def plan_to_exit(self, name=None, bearing=None, timeout=None):
        """Path to the exit called `name`, or else to the reachable zone exit nearest `bearing` (degrees, 0 = -Z,
        90 = +X). Real zone exits (known destination, another sector) win over lifts and placeholders."""
        if name is not None:
            payload = {"to": "exit", "name": str(name)}
        elif bearing is not None:
            payload = {"to": "exit", "bearing": float(bearing)}
        else:
            raise ValueError("Give an exit name or a bearing.")
        return self._plan(payload, timeout)

    def plan_to(self, x, z, y=None, timeout=None):
        """Path to ground point (x, z); without `y` the floor nearest the player's height is used."""
        payload = {"to": "point", "x": float(x), "z": float(z)}
        if y is not None:
            payload["y"] = float(y)
        return self._plan(payload, timeout)

    def _plan(self, payload, timeout):
        data = self.request(payload, timeout)
        if data is None:
            return None
        plan = parse_plan(data)
        if plan is None:
            self.error = "Unreadable plan answer."
        return plan

    def _stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.wait(2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    def close(self):
        """Closing stdin ends the planner cleanly."""
        with self.lock:
            self._stop()
