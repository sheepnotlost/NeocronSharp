"""Regant's Legacy hunt: walk the Main Detention Area a room at a time and kill every NPC, one at a time, as each comes
within a short walk; once all of it has been walked, leave by its exit, wait outside for it to fill up again, go back in
and walk it again, until Stop or F8.

traversal.exe does the walking: "sweep" walks the place's planned points (Sweep.cs) and stops the moment an NPC is near,
the zone hunt's camera run does the fighting (loot_runner.py), and "travel" goes out and back in. Nothing is looted.
Badly hurt, it runs to cover and carries on once healed, as the zone hunt does.
"""
import re

from loot_runner import Engine, LootRunner, LowHealth
from macro_core import Interrupted

INSIDE = 1913                # MAIN DETENTION AREA, where the entrance leads
OUTSIDE = 2083               # E 03 - SWAMP, where the exit comes out and the entrance stands
PLACE = "Regant's Legacy"
ENGAGE = 1500                # units' walk: an NPC this near stops the sweep to be fought
RESPAWN_WAIT = 300           # seconds outside between sweeps, for the place to fill up again
SHOW_WAIT_EVERY = 30         # seconds between "back in ..." lines while waiting
NEXT = re.compile(r"^sweep next (\d+) left (\d+) of (\d+)$", re.M)
ENEMY = re.compile(r"^enemy (\S+) (\d+) (.+)$", re.M)


class DungeonEngine(Engine):
    def where(self):
        """The sector you are in, read from the game."""
        data = self.tool(["nearby"])
        if not data.get("live"):
            raise Interrupted(f"Cannot read the game: {data.get('why')}")
        return data.get("sector")

    def sweep(self, at, skip, tick):
        """Walk on from point at = (point, points left), or from the nearest point; skip: NPCs it can't kill."""
        args = ["sweep", "--world", str(INSIDE), "--engage", str(ENGAGE), "--pulse", self.pulse]
        if at is not None:
            args += ["--from", str(at[0]), "--left", str(at[1])]
        if skip:
            args += ["--skip", ",".join(sorted(skip))]
        if self.calibration:
            args += ["--calibration", self.calibration]
        return self.live(args, tick)

    def travel(self, sector, tick):
        return self.live(["travel", str(sector), "--pulse", self.pulse], tick)


class DungeonRunner(LootRunner):
    def __init__(self, *args, engine=None, wait_outside=RESPAWN_WAIT, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = engine or DungeonEngine(lambda text: self.emit("log", text), self.control)
        self.wait_outside = wait_outside
        self.back = False            # indoors, backing away walks into the next room's mobs
        self.phase = "sweep"
        self.at = None               # (point, points left) of the sweep under way
        self.skip = set()            # NPCs this sweep could not reach or hurt
        self.back_in_at = None
        self.sweeps = 0

    def last_line(self, text):
        return text.splitlines()[-1] if text else "The engine said nothing."

    def sweep(self):
        """Walk on until an NPC is near, then fight it; or, with all of it walked, go out."""
        self.hide_pointer()
        self.emit("status", f"Sweeping {PLACE}: {self.kills} killed.")
        text = self.engine.sweep(self.at, self.skip, self.watch_health)
        for found in NEXT.finditer(text):
            self.at = (int(found.group(1)), int(found.group(2)))
        last = self.last_line(text)
        if last == "swept":
            self.sweeps += 1
            self.emit("log", f"Walked all of {PLACE}'s main area (sweep {self.sweeps}): {self.kills} killed so far. Going out.")
            self.phase, self.at, self.skip = "leave", None, set()
            return
        found = ENEMY.search(text)
        if found is None:
            raise Interrupted(last)
        target = {"id": found.group(1), "name": found.group(3).strip(), "kind": "npc", "distance": float(found.group(2)), "dead": False}
        self.emit("log", f"{target['name']} ahead, {target['distance']:.0f} units away.")
        if self.attack(target):
            self.kills += 1
            self.emit("log", f"{target['name']} killed ({self.kills} so far).")
        else:
            self.emit("log", f"Leaving {target['name']} alone: it can't be reached or hurt.")
            self.skip.add(target["id"])

    def go(self, sector, name):
        self.hide_pointer()
        text = self.engine.travel(sector, self.watch_health)
        if self.engine.where() != sector:
            raise Interrupted(f"Could not get to {name}: {self.last_line(text)}")

    def leave(self):
        self.emit("status", f"Leaving {PLACE}.")
        self.go(OUTSIDE, "the swamp outside")
        self.back_in_at = self.clock()+self.wait_outside
        self.emit("log", f"Outside. Going back in {self.wait_outside//60} min from now, once it has filled up again.")
        self.phase = "wait"

    def wait_out(self):
        shown = None
        while self.clock() < self.back_in_at:
            self.checkpoint()
            self.my_health()
            left = int(self.back_in_at-self.clock())
            if shown is None or shown-left >= SHOW_WAIT_EVERY:
                shown = left
                self.emit("status", f"Waiting outside {PLACE}: back in {left//60}:{left % 60:02d}. {self.kills} killed.")
            self.wait(1)
        self.phase = "enter"

    def enter(self):
        self.emit("status", f"Going back into {PLACE}.")
        self.go(INSIDE, PLACE)
        self.emit("log", f"In {PLACE} again.")
        self.phase, self.at, self.skip = "sweep", None, set()

    def execute(self):
        self.hide_pointer()
        self.check_health()
        here = self.engine.where()
        if here == INSIDE:
            self.phase = "sweep"
        elif here == OUTSIDE:
            self.emit("log", f"Outside {PLACE}: going in first.")
            self.phase = "enter"
        else:
            raise Interrupted(f"Start inside {PLACE}'s main area, or outside it in E 03 - Swamp.")
        steps = {"sweep": self.sweep, "leave": self.leave, "wait": self.wait_out, "enter": self.enter}
        while True:
            try:
                self.checkpoint()
                steps[self.phase]()
            except LowHealth as low:
                self.retreat(str(low))
