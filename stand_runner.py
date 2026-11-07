"""Stand and hunt: stay where you are and kill every robot, mutant and animal that comes within Attack from, nearest
first, one at a time, over and over until Stop or F8. Never a human NPC, a player, or a name typed in Don't attack.

It never takes a step: the fight turns the camera and holds the left button (traversal.exe's camera run with --stay), a
mob on you is fought first, and one that can't be hit from here (no line of sight, no damage) is left for a while and
tried again later, as mobs move. Badly hurt, it runs to cover as the other hunts do, and hunts on from there once healed.
"""
from loot_runner import Engine, LootRunner, LowHealth, MOST_SWITCHES, SWITCH, pick_target

RETRY_AFTER = 30             # seconds a mob that could not be hit from here is left before it is tried again
LOOK_EVERY = 1               # seconds between looks round while nothing is in range
SHOW_IDLE_EVERY = 30         # seconds between "nothing in range" lines


class StandRunner(LootRunner):
    def __init__(self, *args, engine=None, **kwargs):
        super().__init__(*args, engine=engine, **kwargs)
        self.engine.stay = True                  # the whole point: stand here
        self.engine.kite = False
        self.engine.pushers = True               # whatever is on you dies first
        self.engine.avoid = [name.replace(",", " ") for name in self.spare]
        self.back = False
        self.later = {}                          # id -> clock time it may be tried again

    def shot(self, actor, depth=0):
        """Fight it from here. True when it died."""
        switches = 0
        while True:
            self.engine.pushers = depth == 0 and switches < MOST_SWITCHES
            try:
                last = self.fight(actor, False)
            finally:
                self.engine.pushers = True
            found = SWITCH.search(last)
            if found:
                switches += 1
                other = {"id": found.group(1), "name": found.group(2), "kind": "npc", "distance": 0., "dead": False}
                self.emit("log", f"{other['name']} is on you: fighting it first.")
                if self.shot(other, depth+1):
                    self.killed(other)
                if not self.alive(actor):
                    return False
                continue
            return " died." in last

    def alive(self, actor):
        here = next((a for a in self.engine.nearby() if a["id"] == actor["id"]), None)
        return here is not None and not here["dead"]

    def killed(self, actor):
        self.kills += 1
        self.emit("log", f"{actor['name']} killed ({self.kills} so far).")

    def execute(self):
        self.hide_pointer()
        self.check_health()
        self.emit("log", f"Standing here: anything within {self.reach} units gets shot. Stop or F8 ends it.")
        idle_shown = None
        while True:
            try:
                self.checkpoint()
                now = self.clock()
                self.later = {k: t for k, t in self.later.items() if t > now}
                target = pick_target(self.engine.nearby(), self.spare, within=self.reach, skip=self.later)
                if target is None:
                    if idle_shown is None or now-idle_shown >= SHOW_IDLE_EVERY:
                        idle_shown = now
                        self.emit("status", f"Standing and hunting: nothing within {self.reach} units. {self.kills} killed.")
                    self.my_health()
                    self.wait(LOOK_EVERY)
                    continue
                idle_shown = None
                self.hide_pointer()
                self.emit("status", f"Standing and hunting: {target['name']}, {target['distance']:.0f} units away. {self.kills} killed.")
                if self.shot(target):
                    self.killed(target)
                elif self.alive(target):
                    self.emit("log", f"Can't hit {target['name']} from here: trying others for {RETRY_AFTER} s.")
                    self.later[target["id"]] = self.clock()+RETRY_AFTER
            except LowHealth as low:
                self.retreat(str(low))
