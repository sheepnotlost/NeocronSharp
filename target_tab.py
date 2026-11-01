"""Target Acquisition tab: keep the camera on a player or NPC while you move yourself.

Follow's target list without the walk: the work is done by traversal.exe's "camera" command,
which sends mouse movement only (no movement keys, no clicks) and stops on Stop or F8.
The one option adds a click: on an NPC it can hold the left mouse button (--hold-left).
The hunt (loot_runner.py) repeats walk, fight, run and loot on the NPC names ticked in the enemy list, anywhere in the zone.
Follow and heal has two forms. With two clients open here it runs without focus: traversal.exe's "heal" keeps the crosshair on your
other client's character, walks after it and casts every 30 s. With one (a healer in a VM, its fighter elsewhere) it is "follow --heal",
with real mouse input: Follow's routes to the fighter named here, then aiming and a click every 30 s when in reach. If that
ends for any reason but Stop, it looks for the fighter again, so a healer left alone keeps going.
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
from loot_runner import REACH
from macro_core import Control


FIGHTER_FILE = tt.PROJECT / "fighter.txt"
HEAL_DISTANCE = 120          # units from the fighter the healer stops at
HEAL_RETRY = 10              # seconds before a healer alone looks for the fighter again
TICKED, UNTICKED = "\u2611", "\u2610"


def enemy_rows(actors, ticked=()):
    """One row per NPC name, living ones only, nearest first, then any ticked name with none alive here now."""
    rows = {}
    for actor in actors:
        if actor["kind"] == "npc" and not actor["dead"]:
            row = rows.setdefault(actor["name"].lower(), {"name": actor["name"], "alive": 0, "nearest": actor["distance"]})
            row["alive"] += 1
            row["nearest"] = min(row["nearest"], actor["distance"])
    found = sorted(rows.values(), key=lambda row: row["nearest"])
    return found + [{"name": name, "alive": 0, "nearest": None} for name in ticked if name.lower() not in rows]


class TargetTab:
    def __init__(self, parent, root, autoload=True, other_live=lambda: False, loot_runner=None):
        self.root = root
        self.autoload = autoload            # read the game on first view; tests turn it off
        self.other_live = other_live        # a walk or follow is steering the same mouse
        self.loot_runner = loot_runner      # makes a LootRunner(names, reach, emit, control) bound to the game
        self.hunted = {}                    # ticked enemies: lower-case name -> name
        self.heal_name = None               # the fighter a healer alone keeps going back to
        self.heal_retry = None              # its next look
        self.last_line = ""                 # the engine's latest words
        self.measured = []                  # the first follow's calibration and gains, so a retry needs no test moves
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
        ttk.Label(top, text="Client:").pack(side="left", padx=(12, 0))
        self.client = tk.StringVar()
        self.client_box = ttk.Combobox(top, textvariable=self.client, state="readonly", width=30)
        self.client_box.pack(side="left", padx=6)
        self.client_box.bind("<<ComboboxSelected>>", lambda e: self.client_chosen())
        self.clients = []
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
        hunting = ttk.Frame(holder)
        hunting.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        hunting.columnconfigure(0, weight=1)
        hunting.rowconfigure(1, weight=1)
        ttk.Label(hunting, text="Enemies in this zone: click to tick who to hunt").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.enemies = ttk.Treeview(hunting, columns=("hunt", "name", "alive", "nearest"), show="headings", selectmode="none", height=8)
        for column, text, width, anchor in (("hunt", "Hunt", 54, "center"), ("name", "Enemy", 190, "w"), ("alive", "Alive", 50, "e"),
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
        ttk.Label(buttons, text="Fighter:").pack(side="left", padx=(6, 0))
        try:
            saved = FIGHTER_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            saved = ""
        self.fighter = tk.StringVar(value=saved)
        self.fighter.trace_add("write", lambda *_: self.update_buttons())
        ttk.Entry(buttons, textvariable=self.fighter, width=16).pack(side="left", padx=6)
        self.hunt_button = ttk.Button(buttons, text="Start hunt", command=self.start_hunt)
        self.hunt_button.pack(side="right")
        ttk.Label(buttons, text="units").pack(side="right", padx=(0, 8))
        self.reach = tk.StringVar(value=str(REACH))
        self.reach.trace_add("write", lambda *_: self.update_buttons())
        ttk.Entry(buttons, textvariable=self.reach, width=6).pack(side="right", padx=4)
        ttk.Label(buttons, text="Attack from").pack(side="right")
        logs = ttk.Frame(host)
        logs.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        logs.columnconfigure(0, weight=1)
        self.log = tk.Text(logs, height=3, wrap="word", state="disabled", font=("Consolas", 9), relief="flat", padx=6, pady=4)
        self.log.grid(row=0, column=0, sticky="ew")
        bar = ttk.Scrollbar(logs, orient="vertical", command=self.log.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=bar.set)
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
        """A living player. Two clients here: the engine checks it is your other one. One: it must be the fighter you named."""
        if actor is None or actor["dead"] or actor["kind"] != "player":
            return False
        return len(self.clients) > 1 or self.named_fighter(actor)

    def named_fighter(self, actor):
        return actor["name"].lower() == self.fighter.get().strip().lower()

    def steering(self):
        return self.process is not None or self.looting is not None or self.heal_name is not None

    def reach_units(self):
        """The Attack from box, or None while it does not hold a usable distance (Follow stops 40 to 2,000 units away)."""
        text = self.reach.get().strip()
        return int(text) if text.isdigit() and 40 <= int(text) <= 2000 else None

    def update_buttons(self):
        if not getattr(self, "ready", False):
            return
        idle = not self.busy and not self.steering()
        actor = self.selected()
        self.hunt_button.configure(state="normal" if idle and self.hunted and self.reach_units() and self.loot_runner else "disabled")
        self.track_button.configure(state="normal" if idle and actor is not None and not actor["dead"] else "disabled")
        self.hold_check.configure(state="normal" if idle and actor is not None and actor["kind"] == "npc" else "disabled")
        self.heal_button.configure(state="normal" if idle and self.may_heal(actor) else "disabled")
        self.refresh_button.configure(state="normal" if idle else "disabled")
        self.client_box.configure(state="readonly" if idle else "disabled")
        self.stop_button.configure(state="normal" if self.steering() else "disabled")

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

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
                elif kind == "clients":
                    self.show_clients(payload)
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
                found = clients.list_clients()
                # Keep a choice that is still open; with no choice to make, there is nothing to name. Two clients
                # start on the healer: a list never shows its own character, so its list is the one with the fighter.
                if os.environ.get("NEOCRON_PID") not in [str(c["pid"]) for c in found]:
                    clients.choose(max(found, key=lambda c: c["psi"])["pid"] if len(found) > 1 else None)
                self.queue.put(("clients", found))
                result = ("ok", tt.run_tool(["nearby"], track=self.offline))
            except Exception as exc:        # busy must clear whatever went wrong, or the tab stays locked
                result = ("error", str(exc))
            self.queue.put(("nearby", result))
        threading.Thread(target=work, daemon=True, name="target-nearby").start()

    def show_clients(self, found):
        self.clients = found
        self.client_box.configure(values=[c["label"] for c in found])
        chosen = os.environ.get("NEOCRON_PID")
        self.client.set(next((c["label"] for c in found if str(c["pid"]) == chosen), found[0]["label"] if found else ""))

    def client_chosen(self):
        clients.choose(next(c["pid"] for c in self.clients if c["label"] == self.client.get()))
        self.refresh()

    def show_nearby(self, result):
        state, data = result
        if state != "ok":
            self.status.set(data)
        elif not data.get("live"):
            self.actors = []
            self.status.set(f"Cannot read the game: {data.get('why')}")
        else:
            self.actors = [{"id": str(e["id"]), "name": e["name"], "kind": e["kind"], "distance": float(e["distance"]),
                            "dead": bool(e.get("dead"))} for e in data.get("entities", [])]
            players = sum(1 for a in self.actors if a["kind"] == "player")
            seen_by = f" (seen by {self.client.get()})" if len(self.clients) > 1 else ""
            self.status.set(f"{data.get('sectorName') or 'This zone'}  ·  {tt.plural(players, 'player')} and "
                            f"{tt.plural(len(self.actors) - players, 'NPC')} around you{seen_by}")
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
        self.show_enemies()
        self.update_buttons()

    def show_enemies(self):
        self.enemies.delete(*self.enemies.get_children())
        self.enemy_names = {}
        for i, row in enumerate(enemy_rows(self.actors, self.hunted.values())):
            iid = f"e{i}"
            self.enemy_names[iid] = row["name"]
            self.enemies.insert("", "end", iid=iid, values=(TICKED if row["name"].lower() in self.hunted else UNTICKED, row["name"], row["alive"],
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
            self.append("A walk or follow is running on the Traversal tab. Stop it first.")
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
        """Two clients here: the one chosen above is the healer, and it needs no focus. One: this is the healer, focused, and the fighter is elsewhere."""
        actor = self.selected()
        if self.busy or self.steering() or not self.may_heal(actor):
            return
        if self.other_live():
            self.append("A walk or follow is running on the Traversal tab. Stop it first.")
            return
        self.append(f"Tracking {actor['name']} and following. Casting every 30 s.")
        try:
            # A name in the box means the fighter is elsewhere, whatever else is open here: a leftover or closing client
            # made a healer alone in a VM count two (1 Nov), and the engine then looked for the fighter in that one.
            if len(self.clients) > 1 and not self.named_fighter(actor):
                self.start_live(["heal", actor["id"]])
            else:
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
        self.start_live(["follow", fighter_id, "--heal", "--distance", str(HEAL_DISTANCE), "--pulse", "24", "--run", *self.measured])

    def remember(self, line):
        found = re.match(r"\s*(calibration|gains) (\S+) (\S+)\s*$", line)
        if found:
            self.measured += [f"--{found.group(1)}", f"{found.group(2)},{found.group(3)}"]

    def find_fighter(self):
        """A healer alone, some time after its follow ended: is the fighter here and alive?"""
        self.heal_retry = None

        def work():
            try:
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

    def start_hunt(self):
        names, reach = list(self.hunted.values()), self.reach_units()
        if self.busy or self.steering() or not names or reach is None or self.loot_runner is None:
            return
        if self.other_live():
            self.append("A walk or follow is running on the Traversal tab. Stop it first.")
            return
        self.looting = Control()
        self.append(f"Hunt: {', '.join(names)}. Click into Neocron now. Starting in 5 s...")
        self.update_buttons()
        self.loot_start = self.root.after(5000, self.begin_hunt, names, reach)

    def begin_hunt(self, names, reach):
        self.loot_start = None
        try:
            runner = self.loot_runner(names, reach, lambda kind, payload: self.queue.put(("loot", (kind, payload))), self.looting)
            threading.Thread(target=runner.run, daemon=True, name="hunt").start()
        except (ValueError, RuntimeError) as exc:
            self.loot_event("done", str(exc))

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
        # Losing focus inside a VM means someone is using it: taking focus back would fight them.
        if self.heal_name is not None and not any(end in self.last_line for end in ("Stop pressed", "lost focus")):
            self.append(f"Looking for {self.heal_name} again in {HEAL_RETRY} s. Stop ends this.")
            self.heal_retry = self.root.after(HEAL_RETRY * 1000, self.find_fighter)
            self.update_buttons()
            return
        self.heal_name = None
        self.measured = []
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
