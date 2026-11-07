"""Hunt: one enemy at a time. Hurt badly, it runs to cover out of every mob's sight and carries on once healed. Go in range of the nearest ticked NPC anywhere in the zone, back away if it is too close,
kill it, run to its body, take the T, E, A and L parts, and only then pick the next.

traversal.exe does the walking, the fighting and the running (one short run at a time); this file decides what comes
next and works the game's windows. NPCs only: a player is never picked, whatever the list says.
"""
import ctypes
import re
import subprocess
import threading

import traversal_tab as tt
from macro_core import Interrupted
from navray_runner import NavRayRunner
from vision import NotFound
from vision_runner import VisualRunner

REACH = 4000                 # units: how close to go before attacking: kills started from 4,000 to 5,000 live (1 Nov)
SAFE = 2500                  # units: a nearer mob is backed away from before the first shot, this far and no further
REACH_MOST = 6000            # units: about where the game stops letting you target (seen live, 1 Nov)
CLOSE = 200                  # units: the closest a target that takes no damage is walked to
LOOT_WALK = 300              # units: a body further than this gets Follow's routes, not a straight run
BODY_NEAR = 110              # units: where that walk ends, inside the run's own stopping distance
TARGET_MARGIN = 100          # units: walks stop this far inside the measured target limit
HEALTH_FLOOR = .35           # run to cover below this share of your health
RECOVERED = .7               # and go back to hunting at this share
RECOVER_SECONDS = 180        # the hunt ends if that takes longer: no healer is reaching you
FLEE_TRIES = 3               # runs to cover before giving up
FELL = .02                   # health falling by this share of the maximum in cover: they caught up, so run again
HEALTH_EVERY = 1.0           # seconds between readings during a fight
GIVE_UP = 20                 # seconds of no damage before going closer
IDLE_LIMIT = 600             # seconds with nothing to fight before the hunt ends: time for them to respawn
START_TRIES = 3              # readings of your health before the hunt refuses to start without one
# How a run ends when the trouble is that one target. Any other ending (Stop, focus, a zone change, mouse-look) stops the hunt.
ONE_TARGET = ("Reached ", "Right-clicked", " died.", "No damage to", "No walkable way", "Blocked ", " is gone", "crossed the zone line",
              "Nobody with id", " is dead", " is still alive", "The door did not open", "Kept leaving the route", "Could not face the route",
              "Could not reach the body", "Could not aim at the body", "No line of sight", "Switching to ")
SWITCH = re.compile(r"^Switching to (\S+) (.+): it is on you\.$")
MOST_SWITCHES = 8            # mobs on you fought first, per target, before it stops turning to them
MOST = 99                    # typed into the amount box: the game keeps it to the size of the stack
AWAY = (24, 80)              # where the pointer waits, off every window


class LowHealth(Interrupted):
    """Time to run. Still an Interrupted, so it ends a hunt that has not begun."""


PREY = {16, 17, 18}          # pak_factions: Robot, Mutant, Wildlife. Every other faction is human, and never hunted.


def hunted(actor, spare=()):
    """A robot, mutant or animal not named in spare, where a spare name may be part of one ("parasite" spares Genotoxic
    Parasite). Never a player, never a human NPC (City Mercs, LowSL, ...)."""
    name = " ".join(actor["name"].lower().split())
    return (actor["kind"] == "npc" and actor.get("faction") in PREY
            and not any(part and part in name for part in (" ".join(s.lower().split()) for s in spare)))


def pick_target(actors, spare=(), within=float("inf"), skip=()):
    """The nearest living robot, mutant or animal not spared, anywhere in the zone unless limited."""
    found = [a for a in actors if hunted(a, spare) and not a["dead"] and a["distance"] <= within and a["id"] not in skip]
    return min(found, key=lambda a: a["distance"], default=None)


class Engine:
    """traversal.exe, one run at a time, ended early when asked."""

    def __init__(self, log, control):
        self.log, self.control = log, control
        self.gains = None
        self.calibration = None
        self.limit = None
        self.pin = False             # set the camera's angles in the game's memory instead of moving the mouse
        self.pushers = False         # a mob on you is fought first
        self.kite = False            # walk backwards from a mob too close to see
        self.avoid = ()              # names, or parts of names, never to fight

    def tool(self, args):
        return tt.run_tool(args)

    def nearby(self):
        data = self.tool(["nearby"])
        if not data.get("live"):
            raise Interrupted(f"Cannot read the game: {data.get('why')}")
        return [{"id": str(e["id"]), "name": e["name"], "kind": e["kind"], "distance": float(e["distance"]),
                 "dead": bool(e.get("dead")), "faction": e.get("factionId")} for e in data.get("entities", [])]

    def live(self, args, tick):
        """Run one live command to its end and return what it printed. tick() runs while it does, and may raise."""
        tt.clear_stop()
        process = subprocess.Popen([str(tt.EXE), *args], cwd=tt.PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", creationflags=tt.NO_WINDOW)
        lines = []

        def pump():
            for line in process.stdout:
                if line.strip() and not line.lstrip().startswith("{"):
                    lines.append(line.strip())
        reader = threading.Thread(target=pump, daemon=True, name="loot-engine")
        reader.start()
        try:
            while process.poll() is None:
                if self.control.stopped.is_set():
                    raise Interrupted("Stopped.")
                tick()
                try:
                    process.wait(.1)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            tt.stop_walk(process)
            raise
        reader.join(2)
        return "\n".join(lines)

    pulse = "24"                 # pixels: the most the mouse moves the view in one step of a walk or an aim

    def run(self, args, tick=lambda: None):
        """A camera run, with the mouse gains the first one measured."""
        args = ["camera", *args, "--pulse", self.pulse, "--now"]
        if self.gains:
            args += ["--gains", self.gains]
        return self.keep_gains(self.live(args, tick))

    def keep_gains(self, text):
        found = re.search(r"^gains (\S+) (\S+)$", text, re.M)
        if found:
            self.gains = f"{found.group(1)},{found.group(2)}"
        return text

    def walk(self, actor, reach, tick):
        """Follow's routes to an NPC or its body, running while it is far, ending within reach."""
        args = ["follow", actor["id"], "--arrive", "--distance", str(reach), "--pulse", self.pulse, "--run"]
        if actor["dead"]:
            args.append("--body")
        if self.calibration:
            args += ["--calibration", self.calibration]
        text = self.live(args, tick)
        found = re.search(r"^calibration (\S+) (\S+)$", text, re.M)
        if found:
            self.calibration = f"{found.group(1)},{found.group(2)}"
        return text

    def fight(self, actor, tick, back=False):
        """Only shoots with a clear line to it, and first backs away from it when asked."""
        extra = (["--pin"] if self.pin else []) + (["--pushers"] if self.pushers else []) + (["--kite"] if self.kite else [])
        if self.pushers and self.avoid:
            extra += ["--avoid", ",".join(name.replace(",", " ") for name in self.avoid)]
        text = self.run([actor["id"], "--hold-left", "--give-up", str(GIVE_UP), "--sight", *(["--back-off", str(SAFE)] if back else []), *extra], tick)
        found = re.search(r"^Target limit (\d+) units", text, re.M)
        if found:
            self.limit = int(found.group(1))
        return text

    def box(self, actor, tick):
        return self.run([actor["id"], "--box"], tick)

    def flee(self, tick):
        args = ["flee", "--pulse", self.pulse]
        if self.calibration:
            args += ["--calibration", self.calibration]
        return self.live(args, tick)


class LootRunner(VisualRunner):
    needs_ready = False
    menu_words, ui_visible, set_ui, press, health = (NavRayRunner.menu_words, NavRayRunner.ui_visible, NavRayRunner.set_ui,
                                                     NavRayRunner.press, NavRayRunner.health)

    def __init__(self, *args, spare=(), reach=REACH, engine=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.spare = list(spare)       # names ticked "leave alone"
        self.reach = reach
        self.engine = engine or Engine(lambda text: self.emit("log", text), self.control)
        self.next_health = 0.
        self.kills = 0
        self.back = True             # until the weapon proves shorter than the target limit
        self.fleeing = False

    def guard(self):
        super().guard()
        if ctypes.windll.user32.GetAsyncKeyState(0x77) & 0x8000:
            raise Interrupted("F8 pressed.")

    def reader(self):
        return self.detector.text_reader()

    def hide_pointer(self):
        if not self.set_ui(self.reader(), False):
            raise Interrupted("Could not hide the pointer for mouse-look.")

    def ended(self, text):
        """The last line of a run, or Interrupted when it did not end over one target."""
        last = text.splitlines()[-1] if text else "The engine said nothing."
        if not any(word in last for word in ONE_TARGET):
            raise Interrupted(last)
        return last

    def my_health(self):
        return self.judge(self.health(self.reader(), self.frame()))

    def judge(self, reading):
        if reading and reading[0] < reading[1]*HEALTH_FLOOR and not self.fleeing:
            raise LowHealth(f"Your health is down to {reading[0]} of {reading[1]}.")
        return reading

    def watch_health(self):
        if self.clock() >= self.next_health:
            self.next_health = self.clock()+HEALTH_EVERY
            self.my_health()

    def walk_to(self, actor, reach):
        """True on arrival."""
        self.emit("log", f"Walking to {actor['name']}, {actor['distance']:.0f} units away.")
        last = self.ended(self.engine.walk(actor, reach, self.watch_health))
        self.emit("log", last)
        return last.startswith("Reached ")

    def fight(self, actor, back):
        """How it ended. A target limit met while backing away is as far as later walks need to stop."""
        self.emit("log", f"Attacking {actor['name']}.")
        last = self.ended(self.engine.fight(actor, self.watch_health, back))
        self.emit("log", last)
        if self.engine.limit:
            self.reach = min(self.reach, max(CLOSE, self.engine.limit-TARGET_MARGIN))
        return last

    def attack(self, actor, depth=0):
        """True when it died. A mob that gets on you meanwhile is fought first, then this one again. No clear shot, or hurting nothing, means going closer and trying again, as far as CLOSE,
        instead of leaving for the next enemy. A weapon shorter than the target limit shows by hurting nothing: the range
        that worked then is kept for the rest of the hunt, and it stops backing away."""
        reach, close, closer, unhurt, switches = self.reach, min(CLOSE, self.reach), False, False, 0
        pushers = getattr(self.engine, "pushers", False)
        while True:
            here = next((a for a in self.engine.nearby() if a["id"] == actor["id"]), None)
            if here is None:
                return False
            if here["dead"]:
                return True
            if (closer or here["distance"] > reach) and not self.walk_to(here, reach):
                return False
            self.engine.pushers = pushers and depth == 0 and switches < MOST_SWITCHES
            try:
                last = self.fight(here, self.back and not closer)
            finally:
                self.engine.pushers = pushers
            found = SWITCH.search(last)
            if found:
                switches += 1
                other = {"id": found.group(1), "name": found.group(2), "kind": "npc", "distance": 0., "dead": False}
                self.emit("log", f"{other['name']} is on you: fighting it first.")
                if self.attack(other, depth+1):
                    self.kills += 1
                    self.emit("log", f"{other['name']} killed ({self.kills} so far).")
                continue
            if " died." in last:
                if unhurt:
                    self.reach, self.back = reach, False
                return True
            unhurt = unhurt or "No damage to" in last
            if not any(word in last for word in ("No damage to", "No line of sight")) or (closer and reach <= close):
                return False
            reach, closer = max(close, min(reach, int(here["distance"]))//2), True

    def answer_amount(self, dialog):
        self.click(dialog["field"])
        self.type_number(MOST)
        self.move(AWAY)
        self.wait(self.settings["settle_seconds"])
        dialog = self.detector.quantity(self.frame(), checkpoint=self.guard)
        if dialog is None:
            raise Interrupted("The amount box closed before it was confirmed.")
        self.click(dialog["ok"])
        self.move(AWAY)
        self.wait(self.settings["settle_seconds"])
        if self.detector.quantity(self.frame(), checkpoint=self.guard) is not None:
            raise Interrupted("The amount box did not close.")

    def take_stack(self, window, count):
        """Answer the game's amount box, when it asks: all of them. A single part never asks, and just leaves the box."""
        ends = self.clock()+self.settings["dialog_timeout"]
        while self.clock() < ends:
            self.watch_health()
            frame = self.frame()
            dialog = self.detector.quantity(frame, checkpoint=self.guard)
            if dialog is not None:
                return self.answer_amount(dialog)
            if len(self.detector.loot_parts(frame, window)) < count:
                return
            self.wait(.1)
        dialog = self.detector.quantity(self.frame(), checkpoint=self.guard, expected=True)
        if dialog is not None:
            self.answer_amount(dialog)

    def take_parts(self, window):
        """Drag every T, E, A and L part into Inventory. Each move shifts the box, so read it again each time."""
        taken = 0
        for _ in range(16):
            self.watch_health()
            frame = self.frame()
            parts = self.detector.loot_parts(frame, window)
            if not parts:
                return taken
            part = parts[0]
            inventory = self.detector.inventory(frame, checkpoint=self.guard)
            drop = self.detector.inventory_drop(frame, inventory, part["letter"], checkpoint=self.guard)
            if drop is None:
                raise Interrupted("Inventory has no room in view.")
            self.emit("log", f"Taking a {part['letter']} part.")
            self.drag(part["point"], drop)
            self.move(AWAY)
            self.take_stack(window, len(parts))
            after = self.detector.loot_parts(self.frame(), window)
            if len(after) >= len(parts):
                raise Interrupted(f"The {part['letter']} part did not leave the loot box.")
            taken += 1
        return taken

    def loot(self, actor):
        """Run to a body, open it, take the parts, close it. A body that can't be opened is left behind."""
        actors = {a["id"]: a for a in self.engine.nearby()}
        if actor["id"] not in actors or not actors[actor["id"]]["dead"]:
            self.emit("log", f"The body of {actor['name']} is gone.")
            return
        self.hide_pointer()
        body = actors[actor["id"]]
        if body["distance"] > LOOT_WALK and not self.walk_to(body, BODY_NEAR):
            return
        last = self.ended(self.engine.box(actor, self.watch_health))
        self.emit("log", last)
        if not last.startswith("Right-clicked"):
            return
        window = None
        for attempt in range(6):
            self.watch_health()
            self.wait(.5)
            window = self.detector.loot_window(self.frame())
            if window:
                break
        if window is None:
            self.emit("log", f"No loot window opened for {actor['name']}.")
            return
        if not self.set_ui(self.reader(), True):
            raise Interrupted("Could not free the pointer to use the loot window.")
        taken = self.take_parts(window)
        self.emit("log", f"Took {taken} part stack{'' if taken == 1 else 's'} from {actor['name']}.")
        self.close_box(window)

    def close_box(self, window):
        for attempt in range(3):
            self.click(window["close"])
            self.move(AWAY)
            self.wait(self.settings["settle_seconds"])
            window = self.detector.loot_window(self.frame())
            if window is None:
                return
        raise Interrupted("The loot box did not close.")

    def check_health(self):
        """Every stop for your own safety rests on this reading, so no hunt starts without one."""
        for attempt in range(START_TRIES):
            if self.my_health():
                return
            self.wait(.5)
        raise Interrupted("Could not read your health from the screen. Stopped.")

    def recovered(self):
        """True once healed. False if health keeps falling, as they have caught up, or it never comes back."""
        ends, lowest = self.clock()+RECOVER_SECONDS, None
        while self.clock() < ends:
            reading = self.my_health()
            if reading:
                if reading[0] >= reading[1]*RECOVERED:
                    return True
                if lowest is not None and reading[0] < lowest-reading[1]*FELL:
                    return False
                lowest = reading[0] if lowest is None else min(lowest, reading[0])
            self.wait(1)
        return False

    def retreat(self, why):
        """Run to cover, out of every mob's sight, and wait there to be healed."""
        self.fleeing = True
        try:
            self.emit("log", f"{why} Running to cover.")
            for attempt in range(FLEE_TRIES):
                window = self.detector.loot_window(self.frame())
                if window:
                    self.close_box(window)
                self.hide_pointer()
                text = self.engine.flee(lambda: None)
                last = text.splitlines()[-1] if text else "The engine said nothing."
                self.emit("log", last)
                if "Stop pressed" in last or "lost focus" in last:
                    raise Interrupted(last)
                if self.recovered():
                    self.emit("log", "Healed. Back to the hunt.")
                    return
            raise Interrupted(f"{why} Running to cover did not help. Stopped.")
        finally:
            self.fleeing = False

    def execute(self):
        skip, waiting = set(), None
        self.hide_pointer()
        self.check_health()
        while True:
            try:
                self.checkpoint()
                self.hide_pointer()
                target = pick_target(self.engine.nearby(), self.spare, skip=skip)
                if target is None:
                    waiting = self.clock() if waiting is None else waiting
                    if self.clock()-waiting >= IDLE_LIMIT:
                        self.emit("done", f"Nothing left to hunt: {len(skip)} left alone. {self.kills} killed.")
                        return
                    self.emit("status", "No robot, mutant or animal to fight here: waiting for one to appear.")
                    self.my_health()
                    self.wait(3)
                    continue
                waiting = None
                if not self.attack(target):
                    self.emit("log", f"Leaving {target['name']} alone: it can't be reached or hurt.")
                    skip.add(target["id"])
                    continue
                self.kills += 1
                self.loot(target)
                self.hide_pointer()
            except LowHealth as low:
                self.retreat(str(low))

    def run(self):
        try:
            self.guard()
            self.execute()
        except Exception as exc:
            diagnostic = self.save_failure(exc)
            if diagnostic is not None:
                self.emit("log", f"Last game frame saved locally: {diagnostic}")
            self.emit("done", f"{exc} {self.kills} killed.")
        finally:
            self.backend.release_all()
