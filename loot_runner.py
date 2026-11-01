"""Hunt: walk to the nearest ticked NPC anywhere in the zone, kill it, kill whatever is still hurting you, run to the
bodies and take T, E, A and L parts.

traversal.exe does the walking, the fighting and the running (one short run at a time); this file decides what comes
next and works the game's windows. NPCs only: a player is never picked, whatever the list says.
"""
import re
import subprocess
import threading

import traversal_tab as tt
from macro_core import Interrupted
from navray_runner import NavRayRunner
from vision import NotFound
from vision_runner import VisualRunner

REACH = 200                  # units: how close to walk before attacking
THREAT_RADIUS = 200          # units: how far away something still hurting you is looked for
HEALTH_FLOOR = .35           # stop for good below this share of your health
HEALTH_DROP = .01            # a smaller fall than this share of the maximum is rounding, not an attack
HEALTH_EVERY = 1.0           # seconds between readings during a fight
ATTACK_CHECK = 2.0           # seconds your health is watched after a kill
GIVE_UP = 20                 # seconds of no damage before a target is left alone
IDLE_LIMIT = 600             # seconds with nothing to fight before the hunt ends: time for them to respawn
ENDS_THE_HUNT = ("Stop pressed", "changed zone")   # a walk that ends with these is not one target's problem
MOST = 99                    # typed into the amount box: the game keeps it to the size of the stack
AWAY = (24, 80)              # where the pointer waits, off every window


def pick_target(actors, names, within=float("inf"), skip=()):
    """The nearest living NPC with a ticked name, anywhere in the zone unless limited. Never a player."""
    wanted = {name.lower() for name in names}
    found = [a for a in actors if a["kind"] == "npc" and not a["dead"] and a["name"].lower() in wanted
             and a["distance"] <= within and a["id"] not in skip]
    return min(found, key=lambda a: a["distance"], default=None)


def dropped(before, after):
    """Did your health fall between two (current, maximum) readings? False when either could not be read."""
    return bool(before and after) and after[0] < before[0] - after[1]*HEALTH_DROP


class Engine:
    """traversal.exe, one run at a time, ended early when asked."""

    def __init__(self, log, control):
        self.log, self.control = log, control
        self.gains = None
        self.calibration = None

    def nearby(self):
        data = tt.run_tool(["nearby"])
        if not data.get("live"):
            raise Interrupted(f"Cannot read the game: {data.get('why')}")
        return [{"id": str(e["id"]), "name": e["name"], "kind": e["kind"], "distance": float(e["distance"]),
                 "dead": bool(e.get("dead"))} for e in data.get("entities", [])]

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

    def run(self, args, tick=lambda: None):
        """A camera run, with the mouse gains the first one measured."""
        args = ["camera", *args, "--pulse", "24", "--now"]
        if self.gains:
            args += ["--gains", self.gains]
        text = self.live(args, tick)
        found = re.search(r"^gains (\S+) (\S+)$", text, re.M)
        if found:
            self.gains = f"{found.group(1)},{found.group(2)}"
        return text

    def walk(self, actor, reach, tick):
        """Follow's routes to an NPC, ending within reach. Walked, not sprinted: Shift runs out of stamina on a long way."""
        args = ["follow", actor["id"], "--arrive", "--distance", str(reach), "--pulse", "24"]
        if self.calibration:
            args += ["--calibration", self.calibration]
        text = self.live(args, tick)
        found = re.search(r"^calibration (\S+) (\S+)$", text, re.M)
        if found:
            self.calibration = f"{found.group(1)},{found.group(2)}"
        return text

    def fight(self, actor, tick):
        return self.run([actor["id"], "--hold-left", "--give-up", str(GIVE_UP)], tick)

    def box(self, actor, tick):
        return self.run([actor["id"], "--box"], tick)


class LootRunner(VisualRunner):
    needs_ready = False
    menu_words, ui_visible, set_ui, press, health = (NavRayRunner.menu_words, NavRayRunner.ui_visible, NavRayRunner.set_ui,
                                                     NavRayRunner.press, NavRayRunner.health)

    def __init__(self, *args, names=(), reach=REACH, engine=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.names = list(names)
        self.reach = reach
        self.engine = engine or Engine(lambda text: self.emit("log", text), self.control)
        self.next_health = 0.
        self.kills = 0

    def reader(self):
        return self.detector.text_reader()

    def my_health(self):
        reading = self.health(self.reader(), self.frame())
        if reading and reading[0] < reading[1]*HEALTH_FLOOR:
            raise Interrupted(f"Your health is down to {reading[0]} of {reading[1]}. Stopped.")
        return reading

    def watch_health(self):
        if self.clock() >= self.next_health:
            self.next_health = self.clock()+HEALTH_EVERY
            self.my_health()

    def approach(self, actor):
        """True once within reach. A target with no way to it is one target's problem, unless the walk says otherwise."""
        if actor["distance"] <= self.reach:
            return True
        self.emit("log", f"Walking to {actor['name']}, {actor['distance']:.0f} units away.")
        result = self.engine.walk(actor, self.reach, self.watch_health)
        last = result.splitlines()[-1] if result else "The engine said nothing."
        if any(reason in result for reason in ENDS_THE_HUNT):
            raise Interrupted(last)
        self.guard()
        self.emit("log", last)
        return last.startswith("Reached ")

    def fight(self, actor):
        """True when it died."""
        self.emit("log", f"Attacking {actor['name']}.")
        result = self.engine.fight(actor, self.watch_health)
        self.emit("log", result.splitlines()[-1] if result else "The engine said nothing.")
        return " died." in result

    def under_attack(self):
        before = self.my_health()
        self.wait(ATTACK_CHECK)
        return dropped(before, self.my_health())

    def take_stack(self):
        """Answer the game's amount box, when it asks: all of them."""
        elapsed = 0.
        while elapsed < self.settings["dialog_timeout"]:
            dialog = self.detector.quantity(self.frame(), checkpoint=self.guard, expected=True)
            if dialog is not None:
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
                return
            self.wait(.1)
            elapsed += .1

    def take_parts(self, window):
        """Drag every T, E, A and L part into Inventory. Each move shifts the box, so read it again each time."""
        taken = 0
        for _ in range(16):
            frame = self.frame()
            parts = self.detector.loot_parts(frame, window)
            if not parts:
                return taken
            part = parts[0]
            inventory = self.detector.inventory(frame, checkpoint=self.guard)
            drop = self.detector.inventory_drop(frame, inventory, part["letter"], checkpoint=self.guard)
            if drop is None:
                raise Interrupted("Inventory is full.")
            self.emit("log", f"Taking a {part['letter']} part.")
            self.drag(part["point"], drop)
            self.move(AWAY)
            self.take_stack()
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
        try:
            self.emit("log", self.engine.box(actor, self.watch_health).splitlines()[-1])
        except (RuntimeError, IndexError) as exc:
            if isinstance(exc, Interrupted):
                raise
            self.emit("log", f"Could not open the body of {actor['name']}: {exc}")
            return
        window = None
        for attempt in range(6):
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
        self.click(window["close"])
        self.move(AWAY)
        self.wait(self.settings["settle_seconds"])

    def execute(self):
        skip, idle = set(), 0.
        while True:
            self.checkpoint()
            if not self.set_ui(self.reader(), False):
                raise Interrupted("Could not hide the pointer for mouse-look.")
            target = pick_target(self.engine.nearby(), self.names, skip=skip)
            if target is None:
                if idle >= IDLE_LIMIT:
                    self.emit("done", f"No ticked NPCs left in this zone. {self.kills} killed.")
                    return
                if idle == 0:
                    self.emit("status", "No ticked NPCs alive here: waiting for one to appear.")
                self.wait(3)
                idle += 3
                continue
            idle = 0.
            if not self.approach(target) or not self.fight(target):
                skip.add(target["id"])
                continue
            self.kills += 1
            bodies = [target]
            while self.under_attack():
                threat = pick_target(self.engine.nearby(), self.names, THREAT_RADIUS, skip)
                if threat is None:
                    raise Interrupted("Your health is dropping and no ticked NPC is near. Stopped.")
                self.emit("log", "Still under attack.")
                if self.fight(threat):
                    self.kills += 1
                    bodies.append(threat)
                else:
                    skip.add(threat["id"])
            for body in bodies:
                self.loot(body)
                if not self.set_ui(self.reader(), False):
                    raise Interrupted("Could not hide the pointer for mouse-look.")

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
