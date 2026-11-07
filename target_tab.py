"""Target Acquisition tab: keep the camera on a player or NPC while you move yourself.

Follow's target list without the walk: the work is done by traversal.exe's "camera" command,
which sends mouse movement only (no movement keys, no clicks) and stops on Stop or F8.
The one option adds a click: on an NPC it can hold the left mouse button (--hold-left).
The hunt (loot_runner.py) repeats walk, fight, run and loot on every robot, mutant and animal in the zone, except names ticked
"leave alone" in the enemy list or typed (whole or in part) in Don't attack; never a human NPC or a player. In Regant's Legacy Start hunt is the dungeon sweep instead.
Hunt Regant's Legacy (dungeon_runner.py) walks that dungeon's main area a room at a time, kills every creature but Don't attack as it comes near,
then goes out, waits for the place to fill up again, and goes back in.
Stand and hunt (stand_runner.py) never takes a step: it shoots every creature but Don't attack that comes within Attack from, over and over.
Follow and heal runs on the healer's own PC (or VM), one Neocron client there, with the fighter played on another computer:
"follow --heal", real mouse input, Follow's routes to the fighter named here, then aiming and a cast every 30 s when in reach.
If that ends for any reason but Stop, it looks for the fighter again, so a healer left alone keeps going. Two clients on one
PC are not supported any more: the tab says to close one.
"""
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import clients
import traversal_tab as tt
from dungeon_runner import INSIDE, OUTSIDE
from loot_runner import REACH_MOST, hunted
from macro_core import Control


FIGHTER_FILE = tt.PROJECT / "fighter.txt"
AVOID_FILE = tt.PROJECT / "avoid.txt"      # the Don't attack box, kept for next time
PIN_FILE = tt.PROJECT / "pin.txt"          # the Pin camera tick, kept for next time
NOTES_FILE = tt.PROJECT / "logs" / "notes.md"   # the hunt's notes, written by the engine after every fight
HEAL_DISTANCE = 120          # units from the fighter the healer stops at
HEAL_RETRY = 10              # seconds before a healer alone looks for the fighter again
OTHER_LIVE = "A walk, follow or TL 60 Job Loop is running on another tab. Stop it first."
TWO_CLIENTS = ("{} Neocron clients are open on this PC. Close all but one: Follow and heal runs one client per PC, "
               "with the fighter on another computer.")
TICKED, UNTICKED = "\u2611", "\u2610"
log_box = tt.log_box


def typed_names(text):
    """The Don't attack box: names or parts of names, split at commas."""
    return [" ".join(part.split()) for part in text.split(",") if part.strip()]


def enemy_rows(actors, ticked=()):
    """One row per name the hunt would fight (no humans), living ones only, nearest first, then any ticked name with none alive here now."""
    rows = {}
    for actor in actors:
        if hunted(actor) and not actor["dead"]:
            row = rows.setdefault(actor["name"].lower(), {"name": actor["name"], "alive": 0, "nearest": actor["distance"]})
            row["alive"] += 1
            row["nearest"] = min(row["nearest"], actor["distance"])
    found = sorted(rows.values(), key=lambda row: row["nearest"])
    return found + [{"name": name, "alive": 0, "nearest": None} for name in ticked if name.lower() not in rows]


class TargetTab:
    def __init__(self, parent, root, autoload=True, other_live=lambda: False, loot_runner=None, hunt_parent=None, dungeon_runner=None,
                 stand_runner=None):
        """Track and Follow and heal in parent. With hunt_parent, the Hunt is its own tab there; without, it sits beside them."""
        self.root = root
        self.autoload = autoload            # read the game on first view; tests turn it off
        self.other_live = other_live        # a walk, follow or job loop is steering the same mouse
        self.loot_runner = loot_runner      # makes a LootRunner(names, reach, emit, control) bound to the game
        self.dungeon_runner = dungeon_runner    # makes a DungeonRunner(reach, emit, control, avoid) bound to the game
        self.stand_runner = stand_runner        # makes a StandRunner(reach, emit, control, avoid) bound to the game
        self.hunted = {}                    # names ticked "leave alone": lower-case name -> name (kept name for old callers)
        self.sector = None                  # the zone the last Refresh read
        self.heal_name = None               # the fighter a healer alone keeps going back to
        self.heal_retry = None              # its next look
        self.last_line = ""                 # the engine's latest words
        self.measured = {}                  # what the first follow measured, so a retry needs no test moves
        self.looting = None                 # the running hunt's Control
        self.loot_start = None              # its 5 s countdown
        self.queue = queue.Queue()
        self.process = None                 # the live camera follow
        self.busy = False                   # the actor list is being read
        self.offline = set()                # its process, ended on close
        self.closed = False
        self.actors, self.rows = [], {}
        self._loaded = False
        self._after = None

        host = ttk.Frame(parent, padding=12)
        host.pack(fill="both", expand=True)
        host.columnconfigure(0, weight=1)
        host.rowconfigure(2, weight=1)
        top = ttk.Frame(host)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Find:").pack(side="left")
        self.find = tk.StringVar()
        ttk.Entry(top, textvariable=self.find, width=22).pack(side="left", padx=6)
        self.find.trace_add("write", lambda *_: self.show_actors())
        self.hold_left = tk.BooleanVar(value=False)
        self.hold_check = ttk.Checkbutton(top, text="Hold left mouse button (NPCs only)", variable=self.hold_left)
        self.hold_check.pack(side="left", padx=(12, 0))
        self.status = tk.StringVar(value="Press Refresh to see who is around you.")
        ttk.Label(host, textvariable=self.status, font=("Segoe UI", 11, "bold"), wraplength=900).grid(
            row=1, column=0, sticky="ew", pady=(8, 4))
        holder = ttk.Frame(host)
        holder.grid(row=2, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(holder, columns=("name", "type", "distance"), show="headings", selectmode="browse", height=8)
        for column, text, width, anchor in (("name", "Name", 260, "w"), ("type", "Type", 70, "w"), ("distance", "Distance", 90, "e")):
            self.tree.heading(column, text=text, anchor=anchor)
            self.tree.column(column, width=width, anchor=anchor, stretch=column == "name")
        self.tree.tag_configure("grey", foreground=tt.GREY)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_buttons())
        self.tree.bind("<Double-1>", lambda e: self.track())
        hunt_host = None
        if hunt_parent is not None:
            hunt_host = ttk.Frame(hunt_parent, padding=12)
            hunt_host.pack(fill="both", expand=True)
            hunt_host.columnconfigure(0, weight=1)
            hunt_host.rowconfigure(1, weight=1)
            ttk.Label(hunt_host, textvariable=self.status, font=("Segoe UI", 11, "bold"), wraplength=900).grid(
                row=0, column=0, sticky="ew", pady=(0, 4))
            hunting = ttk.Frame(hunt_host)
            hunting.grid(row=1, column=0, sticky="nsew")
        else:
            hunting = ttk.Frame(holder)
            hunting.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        hunting.columnconfigure(0, weight=1)
        hunting.rowconfigure(1, weight=1)
        ttk.Label(hunting, text="Enemies here (no humans): tick any to leave alone").grid(row=0, column=0, sticky="w", pady=(0, 4))
        avoid_row = ttk.Frame(hunting)
        avoid_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        avoid_row.columnconfigure(1, weight=1)
        ttk.Label(avoid_row, text="Don't attack:").grid(row=0, column=0, sticky="w")
        try:
            kept = AVOID_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            kept = ""
        self.avoid = tk.StringVar(value=kept)
        self.avoid.trace_add("write", lambda *_: self.show_enemies() if getattr(self, "ready", False) else None)
        ttk.Entry(avoid_row, textvariable=self.avoid).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(avoid_row, text="e.g. parasite, slugger").grid(row=0, column=2, sticky="w")
        self.enemies = ttk.Treeview(hunting, columns=("hunt", "name", "alive", "nearest"), show="headings", selectmode="none", height=8)
        for column, text, width, anchor in (("hunt", "Spare", 54, "center"), ("name", "Enemy", 190, "w"), ("alive", "Alive", 50, "e"),
                                            ("nearest", "Nearest", 70, "e")):
            self.enemies.heading(column, text=text, anchor=anchor)
            self.enemies.column(column, width=width, anchor=anchor, stretch=column == "name")
        self.enemies.grid(row=1, column=0, sticky="nsew")
        enemy_scroll = ttk.Scrollbar(hunting, orient="vertical", command=self.enemies.yview)
        enemy_scroll.grid(row=1, column=1, sticky="ns")
        self.enemies.configure(yscrollcommand=enemy_scroll.set)
        self.enemies.bind("<Button-1>", self.toggle_enemy)
        self.enemy_names = {}
        buttons = ttk.Frame(host)
        buttons.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.track_button = ttk.Button(buttons, text="Track", command=self.track)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop)
        self.refresh_button = ttk.Button(buttons, text="Refresh", command=self.refresh)
        self.heal_button = ttk.Button(buttons, text="Follow and heal", command=self.heal)
        for button in (self.track_button, self.stop_button, self.refresh_button, self.heal_button):
            button.pack(side="left", padx=(0, 6))
        self.stop_buttons, self.refresh_buttons = [self.stop_button], [self.refresh_button]
        ttk.Label(buttons, text="Fighter:").pack(side="left", padx=(6, 0))
        try:
            saved = FIGHTER_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            saved = ""
        self.fighter = tk.StringVar(value=saved)
        self.fighter.trace_add("write", lambda *_: self.update_buttons())
        ttk.Entry(buttons, textvariable=self.fighter, width=16).pack(side="left", padx=6)
        hunt_buttons = buttons
        if hunt_host is not None:
            hunt_buttons = ttk.Frame(hunt_host)
            hunt_buttons.grid(row=2, column=0, sticky="ew", pady=(6, 0))
            for text, command, kept in (("Refresh", self.refresh, self.refresh_buttons), ("Stop", self.stop, self.stop_buttons)):
                button = ttk.Button(hunt_buttons, text=text, command=command)
                button.pack(side="left", padx=(0, 6))
                kept.append(button)
        try:
            pinned = PIN_FILE.read_text(encoding="utf-8").strip() == "1"
        except OSError:
            pinned = False
        self.pin = tk.BooleanVar(value=pinned)
        self.pin.trace_add("write", lambda *_: self.keep_pin())
        # Beside Don't attack: the button row below is full (the Regant's button was squeezed to "Hun", 7 Nov).
        ttk.Checkbutton(avoid_row, text="Pin camera (writes game memory)", variable=self.pin).grid(row=0, column=3, sticky="w", padx=(12, 0))
        ttk.Button(avoid_row, text="Hunt notes", command=self.open_notes).grid(row=0, column=4, sticky="e", padx=(12, 0))
        self.hunt_button = ttk.Button(hunt_buttons, text="Start hunt", command=self.start_hunt)
        self.hunt_button.pack(side="right")
        self.dungeon_button = ttk.Button(hunt_buttons, text="Hunt Regant's Legacy", command=self.start_dungeon)
        self.dungeon_button.pack(side="right", padx=(0, 12))
        self.stand_button = ttk.Button(hunt_buttons, text="Stand and hunt", command=self.start_stand)
        self.stand_button.pack(side="right", padx=(0, 6))
        ttk.Label(hunt_buttons, text="units").pack(side="right", padx=(0, 8))
        self.reach = tk.StringVar(value=str(REACH_MOST))   # 6,000: as far as the game lets you target (asked for, 7 Nov)
        self.reach.trace_add("write", lambda *_: self.update_buttons())
        ttk.Entry(hunt_buttons, textvariable=self.reach, width=6).pack(side="right", padx=4)
        ttk.Label(hunt_buttons, text="Attack from").pack(side="right")
        self.logs = [log_box(host, 4, 3)] + ([log_box(hunt_host, 3, 5)] if hunt_host is not None else [])
        self.log = self.logs[0]
        parent.bind("<Map>", self.first_view, add="+")
        self.ready = True
        self.update_buttons()
        self._after = self.root.after(100, self.poll)

    def first_view(self, _event=None):
        if self._loaded or not self.autoload:
            return
        self._loaded = True
        self.refresh()

    def selected(self):
        chosen = self.tree.selection()
        return self.rows.get(chosen[0]) if chosen else None

    def may_heal(self, actor):
        """A living player; heal() then checks it is the fighter named in the box, and says so if not."""
        return actor is not None and not actor["dead"] and actor["kind"] == "player"

    def named_fighter(self, actor):
        return " ".join(actor["name"].lower().split()) == " ".join(self.fighter.get().lower().split())

    def steering(self):
        return self.process is not None or self.looting is not None or self.heal_name is not None

    def reach_units(self):
        """The Attack from box, or None while it does not hold a usable distance."""
        text = self.reach.get().strip()
        return int(text) if text.isdigit() and 40 <= int(text) <= REACH_MOST else None

    def update_buttons(self):
        if not getattr(self, "ready", False):
            return
        idle = not self.busy and not self.steering()
        actor = self.selected()
        # Stays clickable so a hunt that cannot start says why: greyed out with nothing ticked looked like a dead button (1 Nov).
        self.hunt_button.configure(state="normal" if self.loot_runner and self.looting is None else "disabled")
        self.dungeon_button.configure(state="normal" if self.dungeon_runner and self.looting is None else "disabled")
        self.stand_button.configure(state="normal" if self.stand_runner and self.looting is None else "disabled")
        self.track_button.configure(state="normal" if idle and actor is not None and not actor["dead"] else "disabled")
        self.hold_check.configure(state="normal" if idle and actor is not None and actor["kind"] == "npc" else "disabled")
        self.heal_button.configure(state="normal" if idle and self.may_heal(actor) else "disabled")
        for button in self.refresh_buttons:
            button.configure(state="normal" if idle else "disabled")
        for button in self.stop_buttons:
            button.configure(state="normal" if self.steering() else "disabled")

    def append(self, text):
        for log in self.logs:
            log.configure(state="normal")
            log.insert("end", text.rstrip() + "\n")
            log.see("end")
            log.configure(state="disabled")

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.last_line = payload
                    self.remember(payload)
                    self.append(payload)
                elif kind == "nearby":
                    self.busy = False
                    self.show_nearby(payload)
                elif kind == "done":
                    self.finished()
                elif kind == "loot":
                    self.loot_event(*payload)
                elif kind == "fighter":
                    self.fighter_seen(payload)
        except queue.Empty:
            pass
        self._after = self.root.after(100, self.poll)

    def refresh(self):
        if self.busy or self.steering():
            return
        self.busy = True
        self.update_buttons()
        self.status.set("Reading who is around you…")

        def work():
            try:
                problem = tt.build_tool(lambda text: self.queue.put(("log", text)))
                if problem:
                    raise RuntimeError(problem)
                found = clients.windows()
                if len(found) > 1:
                    raise RuntimeError(TWO_CLIENTS.format(len(found)))
                clients.choose(next(iter(found), None))     # the one open here, whatever another tab picked before
                result = ("ok", tt.run_tool(["nearby"], track=self.offline))
            except Exception as exc:        # busy must clear whatever went wrong, or the tab stays locked
                result = ("error", str(exc))
            self.queue.put(("nearby", result))
        threading.Thread(target=work, daemon=True, name="target-nearby").start()

    def show_nearby(self, result):
        state, data = result
        if state != "ok":
            self.status.set(data)
        elif not data.get("live"):
            self.actors = []
            self.status.set(f"Cannot read the game: {data.get('why')}")
        else:
            self.sector = data.get("sector")
            self.actors = [{"id": str(e["id"]), "name": e["name"], "kind": e["kind"], "distance": float(e["distance"]),
                            "dead": bool(e.get("dead")), "faction": e.get("factionId")} for e in data.get("entities", [])]
            players = sum(1 for a in self.actors if a["kind"] == "player")
            self.status.set(f"{data.get('sectorName') or 'This zone'}  ·  {tt.plural(players, 'player')} and "
                            f"{tt.plural(len(self.actors) - players, 'NPC')} around you")
        self.show_actors()

    def show_actors(self):
        keep = self.selected()
        keep = keep["id"] if keep else None
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for i, actor in enumerate(tt.order_actors(self.actors, self.find.get())):
            iid = f"a{i}"
            self.tree.insert("", "end", iid=iid, tags=("grey",) if actor["dead"] else (),
                             values=(f"{actor['name']}  (dead)" if actor["dead"] else actor["name"],
                                     "Player" if actor["kind"] == "player" else "NPC", f"{actor['distance']:,.0f}"))
            self.rows[iid] = actor
            if actor["id"] == keep:
                self.tree.selection_set(iid)
        # The fighter named last time, picked for you: on the healer's PC, Refresh then Follow and heal is all there is to do.
        if keep is None:
            named = next((iid for iid, actor in self.rows.items() if actor["kind"] == "player" and not actor["dead"]
                          and self.named_fighter(actor)), None)
            if named is not None:
                self.tree.selection_set(named)
                self.tree.see(named)
        self.show_enemies()
        self.update_buttons()

    def show_enemies(self):
        self.enemies.delete(*self.enemies.get_children())
        self.enemy_names = {}
        for i, row in enumerate(enemy_rows(self.actors, self.hunted.values())):
            iid = f"e{i}"
            self.enemy_names[iid] = row["name"]
            spared = row["name"].lower() in self.hunted or not hunted({"kind": "npc", "faction": 16, "name": row["name"]}, typed_names(self.avoid.get()))
            self.enemies.insert("", "end", iid=iid, values=(TICKED if spared else UNTICKED, row["name"], row["alive"],
                                                            "" if row["nearest"] is None else f"{row['nearest']:,.0f}"))

    def toggle_enemy(self, event):
        name = self.enemy_names.get(self.enemies.identify_row(event.y))
        if name is not None and not self.steering():
            self.tick_enemy(name)
        return "break"

    def tick_enemy(self, name):
        if self.hunted.pop(name.lower(), None) is None:
            self.hunted[name.lower()] = name
        self.show_enemies()
        self.update_buttons()

    def track(self):
        actor = self.selected()
        if self.busy or self.steering() or actor is None or actor["dead"]:
            return
        if self.other_live():
            self.append(OTHER_LIVE)
            return
        hold = self.hold_left.get() and actor["kind"] == "npc"
        self.append(f"Keeping the camera on {actor['name']}{', left mouse button held once on it' if hold else ''}. Starting in 5 s...")
        try:
            self.start_live(["camera", actor["id"], "--pulse", "24", *(["--hold-left"] if hold else [])])
            self.track_button.configure(text="Tracking...")
        except (OSError, RuntimeError) as exc:
            self.process = None
            self.append("Could not start: " + str(exc))
        self.update_buttons()

    def heal(self):
        """This PC is the healer, Neocron focused here, and the fighter is played on another computer."""
        actor = self.selected()
        if self.busy or self.steering() or not self.may_heal(actor):
            return
        if not self.named_fighter(actor):
            self.append(f"Type {actor['name']} in Fighter first: Follow and heal only follows the fighter named there.")
            return
        if self.other_live():
            self.append(OTHER_LIVE)
            return
        self.append(f"Tracking {actor['name']} and following. Slot 1 every 30 s, slots 2 and 3 every 120 s, on both of you.")
        try:
            FIGHTER_FILE.write_text(actor["name"], encoding="utf-8")
            self.append("Starting in 5 s: Neocron must stay the focused window here.")
            self.heal_name = actor["name"]
            self.start_alone(actor["id"])
            self.heal_button.configure(text="Healing...")
        except (OSError, RuntimeError) as exc:
            self.process = None
            self.heal_name = None
            self.append("Could not start: " + str(exc))
        self.update_buttons()

    def start_alone(self, fighter_id):
        self.start_live(["follow", fighter_id, "--heal", "--distance", str(HEAL_DISTANCE), "--pulse", "24", "--run",
                          *[word for pair in self.measured.items() for word in pair]])

    def remember(self, line):
        found = re.match(r"\s*(calibration|gains) (\S+) (\S+)\s*$", line)
        if found:
            self.measured[f"--{found.group(1)}"] = f"{found.group(2)},{found.group(3)}"

    def find_fighter(self):
        """A healer alone, some time after its follow ended: is the fighter here and alive?"""
        self.heal_retry = None
        refocus = "lost focus" in self.last_line

        def work():
            try:
                if refocus and not clients.focus():
                    self.queue.put(("log", "Could not bring Neocron to the front. Trying again.\n"))
                data = tt.run_tool(["nearby"], track=self.offline)
            except Exception as exc:
                data = {"live": False, "why": str(exc)}
            self.queue.put(("fighter", data))
        threading.Thread(target=work, daemon=True, name="target-fighter").start()

    def fighter_seen(self, data):
        name = self.heal_name
        if name is None:
            return
        found = next((e for e in data.get("entities", []) if e["kind"] == "player" and not e.get("dead") and e["name"].lower() == name.lower()), None)
        try:
            if found is not None:
                self.append(f"Going back to {name}.")
                self.status.set(f"Following {name}.")
                self.start_alone(str(found["id"]))
                return
        except (OSError, RuntimeError) as exc:
            self.process = None
            self.append("Could not start: " + str(exc))
        self.status.set(f"Cannot read the game: {data.get('why')}" if data.get("live") is False else f"Waiting for {name} to be alive in this zone.")
        self.heal_retry = self.root.after(HEAL_RETRY * 1000, self.find_fighter)

    def start_live(self, args):
        problem = tt.build_tool()
        if problem:
            raise RuntimeError(problem)
        tt.clear_stop()
        self.last_line = ""
        self.process = subprocess.Popen([str(tt.EXE), *args], cwd=tt.PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=tt.NO_WINDOW)

        def pump(process):
            for line in process.stdout:
                if line.strip() and not line.lstrip().startswith("{"):
                    self.queue.put(("log", line))
            process.wait()
            self.queue.put(("done", None))
        threading.Thread(target=pump, args=(self.process,), daemon=True, name="target-camera").start()

    def open_notes(self):
        """The notes the hunt keeps on every fight, in the default viewer."""
        if not NOTES_FILE.exists():
            self.append("No hunt notes yet: they're written after each fight.")
            return
        try:
            os.startfile(NOTES_FILE)
        except OSError as exc:
            self.append(f"Could not open the hunt notes: {exc}")

    def keep_pin(self):
        try:
            PIN_FILE.write_text("1" if self.pin.get() else "0", encoding="utf-8")
        except OSError:
            pass

    def pinned(self, runner):
        """The Pin camera tick, handed to a runner's engine."""
        engine = getattr(runner, "engine", None)
        if engine is not None:
            engine.pin = bool(self.pin.get())
        return runner

    def avoid_names(self):
        """Names ticked in the list and names, or parts of names, typed in Don't attack; the box is kept for next time."""
        typed = typed_names(self.avoid.get())
        try:
            AVOID_FILE.write_text(", ".join(typed), encoding="utf-8")
        except OSError:
            pass
        names = list(self.hunted.values())
        return names + [name for name in typed if name.lower() not in {n.lower() for n in names}]

    def start_hunt(self):
        if self.sector in (INSIDE, OUTSIDE) and self.dungeon_runner:
            return self.start_dungeon()         # Regant's Legacy: the sweep through it, not the zone hunt
        names, reach = self.avoid_names(), self.reach_units()
        problem = self.hunt_problem(None, reach)
        if problem:
            self.status.set(problem)
            self.append(problem)
            return
        self.looting = Control()
        spared = f", leaving {', '.join(names)} alone" if names else ""
        self.append(f"Hunt: every robot, mutant and animal here{spared}; never humans or players. Click into Neocron now. Starting in 5 s...")
        self.update_buttons()
        self.loot_start = self.root.after(5000, self.begin_hunt, names, reach)

    def hunt_problem(self, names, reach):
        if self.busy:
            return "Still reading who is around you. Try Start hunt again in a moment."
        if self.steering():
            return "Press Stop first: a follow or heal is running on this tab."
        if self.other_live():
            return OTHER_LIVE
        if names is not None and not names:
            return "Tick an enemy first: click its row in the Enemies list. If the list is empty, press Refresh."
        if reach is None:
            return f"Attack from must be a whole number from 40 to {REACH_MOST}."
        return None

    def begin_hunt(self, names, reach):
        self.loot_start = None
        try:
            clients.focus()         # no need to have clicked into the game in time
            runner = self.pinned(self.loot_runner(names, reach, lambda kind, payload: self.queue.put(("loot", (kind, payload))), self.looting))
            threading.Thread(target=runner.run, daemon=True, name="hunt").start()
        except Exception as exc:
            self.loot_event("done", f"Hunt could not start: {exc}")

    def start_dungeon(self):
        """Every robot, mutant and animal in Regant's Legacy's main area, one at a time, except Don't attack; the Attack from box still counts."""
        reach, avoid = self.reach_units(), self.avoid_names()
        problem = self.hunt_problem(None, reach)
        if problem:
            self.status.set(problem)
            self.append(problem)
            return
        self.looting = Control()
        spared = f", leaving {', '.join(avoid)} alone" if avoid else ""
        self.append(f"Regant's Legacy: every creature in the main area{spared}, one at a time; never humans or players. Then out for 5 min and back in. "
                    "Start inside it or outside its door. Click into Neocron now. Starting in 5 s...")
        self.update_buttons()
        self.loot_start = self.root.after(5000, self.begin_dungeon, reach, avoid)

    def begin_dungeon(self, reach, avoid=()):
        self.loot_start = None
        try:
            clients.focus()
            runner = self.pinned(self.dungeon_runner(reach, lambda kind, payload: self.queue.put(("loot", (kind, payload))), self.looting, avoid))
            threading.Thread(target=runner.run, daemon=True, name="dungeon").start()
        except Exception as exc:
            self.loot_event("done", f"The Regant's Legacy hunt could not start: {exc}")

    def start_stand(self):
        """Stay put and shoot every robot, mutant and animal that comes within Attack from, over and over, except Don't attack."""
        reach, avoid = self.reach_units(), self.avoid_names()
        problem = self.hunt_problem(None, reach)
        if problem:
            self.status.set(problem)
            self.append(problem)
            return
        self.looting = Control()
        spared = f", leaving {', '.join(avoid)} alone" if avoid else ""
        self.append(f"Stand and hunt: from where you stand, every creature within {reach} units{spared}, nearest first, over and over; "
                    "never humans or players, and never a step. Click into Neocron now. Starting in 5 s...")
        self.update_buttons()
        self.loot_start = self.root.after(5000, self.begin_stand, reach, avoid)

    def begin_stand(self, reach, avoid=()):
        self.loot_start = None
        try:
            clients.focus()
            runner = self.pinned(self.stand_runner(reach, lambda kind, payload: self.queue.put(("loot", (kind, payload))), self.looting, avoid))
            threading.Thread(target=runner.run, daemon=True, name="stand").start()
        except Exception as exc:
            self.loot_event("done", f"Stand and hunt could not start: {exc}")

    def loot_event(self, kind, payload):
        if kind in ("log", "status"):
            self.append(payload)
        elif kind == "done":
            self.append(payload)
            self.looting = None
            self.update_buttons()
            self.refresh()

    def stop(self):
        if self.looting is not None:
            self.looting.stopped.set()
            if self.loot_start is not None:
                self.root.after_cancel(self.loot_start)
                self.loot_event("done", "Hunt stopped.")
            return
        was_healing, self.heal_name = self.heal_name, None
        if self.heal_retry is not None:
            self.root.after_cancel(self.heal_retry)
            self.heal_retry = None
        process = self.process
        if process is None:
            if was_healing:
                self.finished()
            return
        self.stop_button.configure(state="disabled")
        threading.Thread(target=tt.stop_walk, args=(process,), daemon=True, name="target-stop").start()

    def finished(self):
        self.process = None
        self.append("Ended.")
        # A VM left running behind other windows lost focus again and again (1 Nov): the next look takes it back.
        if self.heal_name is not None and "Stop pressed" not in self.last_line:
            what = "Bringing Neocron back to the front and looking" if "lost focus" in self.last_line else "Looking"
            self.append(f"{what} for {self.heal_name} again in {HEAL_RETRY} s. Stop ends this.")
            self.heal_retry = self.root.after(HEAL_RETRY * 1000, self.find_fighter)
            self.update_buttons()
            return
        self.heal_name = None
        self.measured = {}
        self.track_button.configure(text="Track")
        self.heal_button.configure(text="Follow and heal")
        self.update_buttons()
        self.refresh()

    def close(self):
        """Stop a running camera follow and any actor read; the window is closing."""
        self.closed = True
        self.heal_name = None
        for pending in (self._after, self.heal_retry):
            if pending is not None:
                try:
                    self.root.after_cancel(pending)
                except tk.TclError:
                    pass
        if self.process is not None:
            tt.stop_walk(self.process)
            self.process = None
        if self.looting is not None:
            self.looting.stopped.set()
        for process in list(self.offline):
            try:
                process.kill()
            except OSError:
                pass
