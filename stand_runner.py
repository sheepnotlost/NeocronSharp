"""Stand and hunt: stay where you are and kill the nearest robot, mutant or animal within Attack from, and only that one
until it dies; then the next nearest, over and over until Stop or F8. Never a human NPC, a player, or a name typed in
Don't attack.

It never takes a step and never drops a mob for another (traversal.exe's camera run with --stay): once it has shot at
one, it keeps the aim on it until it dies, holding fire while it is out of sight or behind something; only after 8 s
out of view is it let go for the nearest one in view, and looked at again later. Dropping them
for the next left four mobs on you with none dead (7 Nov). What is in view is the game's say, not the map's: it turns to
each mob, nearest first, and one whose label the game doesn't draw within about a second is behind something, so the
next is looked at; that one is looked at again in a few seconds, as mobs move. The map's props were wrong both ways. Badly hurt, it runs to cover as the other hunts do, and hunts on
from there once healed.
"""
from loot_runner import LootRunner, LowHealth, pick_target

BLOCKED_AGAIN = 10           # seconds before a mob not on screen (behind something) is looked at again
LOST_AGAIN = 15              # seconds before one that went out of view mid-fight is looked at again
UNHURT_AGAIN = 30            # seconds before one that took no damage (out of the weapon's reach) is tried again
LOOK_EVERY = 1               # seconds between looks round while nothing is in range
SHOW_IDLE_EVERY = 30         # seconds between "nothing in range" lines


class StandRunner(LootRunner):
    def __init__(self, *args, engine=None, **kwargs):
        super().__init__(*args, engine=engine, **kwargs)
        self.engine.stay = True                  # stand here, and fight each one until it dies
        self.engine.kite = False
        self.engine.pushers = False              # never drop the target for one that gets on you
        self.back = False
        self.later = {}                          # id -> clock time it may be looked at again

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
                last = self.fight(target, False)
                if " died." in last:
                    self.killed(target)
                elif self.alive(target):
                    if "went out of view" in last:
                        wait, text = LOST_AGAIN, f"{target['name']} went out of view: on to the nearest in view"
                    elif "No damage to" in last:
                        wait, text = UNHURT_AGAIN, f"Not starting on {target['name']}: it takes no damage from here"
                    else:
                        wait, text = BLOCKED_AGAIN, f"Not starting on {target['name']}: not on screen from here"
                    self.emit("log", f"{text}. Looking at it again in {wait} s.")
                    self.later[target["id"]] = self.clock()+wait
            except LowHealth as low:
                self.retreat(str(low))
