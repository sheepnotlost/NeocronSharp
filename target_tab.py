"""Target Acquisition tab: keep the camera on a player or NPC while you move yourself.

Follow's target list without the walk: the work is done by traversal.exe's "camera" command,
which sends mouse movement only (no movement keys, no clicks) and stops on Stop or F8.
The one option adds a click: on an NPC it can hold the left mouse button (--hold-left).
The loot sequence (loot_runner.py) repeats fight, run and loot on the NPC names you add.
Follow and heal runs without focus: traversal.exe's "heal" keeps your place beside a player, casting every 30 s.
"""
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import clients
import traversal_tab as tt
from macro_core import Control


def loot_names(text):
    """"Small Spider, Rat" -> ["Small Spider", "Rat"], without repeats."""
    return list(dict.fromkeys(name.strip() for name in text.split(",") if name.strip()))


class TargetTab:
    def __init__(self, parent, root, autoload=True, other_live=lambda: False, loot_runner=None):
        self.root = root
        self.autoload = autoload            # read the game on first view; tests turn it off
        self.other_live = other_live        # a walk or follow is steering the same mouse
        self.loot_runner = loot_runner      # makes a LootRunner(names, emit, control) bound to the game
        self.looting = None                 # the running loot sequence's Control
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
        for column, text, width, anchor in (("name", "Name", 420, "w"), ("type", "Type", 100, "w"), ("distance", "Distance", 110, "e")):
            self.tree.heading(column, text=text, anchor=anchor)
            self.tree.column(column, width=width, anchor=anchor, stretch=column == "name")
        self.tree.tag_configure("grey", foreground=tt.GREY)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_buttons())
        self.tree.bind("<Double-1>", lambda e: self.track())
        buttons = ttk.Frame(host)
        buttons.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.track_button = ttk.Button(buttons, text="Track", command=self.track)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop)
        self.refresh_button = ttk.Button(buttons, text="Refresh", command=self.refresh)
        self.heal_button = ttk.Button(buttons, text="Follow and heal", command=self.heal)
        for button in (self.track_button, self.stop_button, self.refresh_button, self.heal_button):
            button.pack(side="left", padx=(0, 6))
        ttk.Label(buttons, text="Tab in-game first. You do the walking; F8 stops.").pack(side="left", padx=(6, 0))
        loot = ttk.Frame(host)
        loot.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        loot.columnconfigure(1, weight=1)
        ttk.Label(loot, text="Loot sequence, NPCs:").grid(row=0, column=0, sticky="w")
        self.loot_names = tk.StringVar()
        self.loot_names.trace_add("write", lambda *_: self.update_buttons())
        ttk.Entry(loot, textvariable=self.loot_names).grid(row=0, column=1, sticky="ew", padx=6)
        self.add_loot_button = ttk.Button(loot, text="Add selected", command=self.add_loot_name)
        self.add_loot_button.grid(row=0, column=2, padx=(0, 6))
        self.loot_button = ttk.Button(loot, text="Start loot sequence", command=self.start_loot)
        self.loot_button.grid(row=0, column=3)
        logs = ttk.Frame(host)
        logs.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        logs.columnconfigure(0, weight=1)
        self.log = tk.Text(logs, height=5, wrap="word", state="disabled", font=("Consolas", 9), relief="flat", padx=6, pady=4)
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

    def steering(self):
        return self.process is not None or self.looting is not None

    def update_buttons(self):
        if not getattr(self, "ready", False):
            return
        idle = not self.busy and not self.steering()
        actor = self.selected()
        names = loot_names(self.loot_names.get())
        self.add_loot_button.configure(state="normal" if idle and actor is not None and actor["kind"] == "npc" else "disabled")
        self.loot_button.configure(state="normal" if idle and names and self.loot_runner else "disabled")
        self.track_button.configure(state="normal" if idle and actor is not None and not actor["dead"] else "disabled")
        self.hold_check.configure(state="normal" if idle and actor is not None and actor["kind"] == "npc" else "disabled")
        self.heal_button.configure(state="normal" if idle and actor is not None and actor["kind"] == "player" and not actor["dead"] else "disabled")
        self.refresh_button.configure(state="normal" if idle else "disabled")
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
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
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
        """The client chosen above is the healer. It needs no focus: put the crosshair on the player, then start."""
        actor = self.selected()
        if self.busy or self.steering() or actor is None or actor["dead"] or actor["kind"] != "player":
            return
        if self.other_live():
            self.append("A walk or follow is running on the Traversal tab. Stop it first.")
            return
        self.append(f"Following {actor['name']} from where you stand now. Casting every 30 s.")
        try:
            self.start_live(["heal", actor["id"]])
            self.heal_button.configure(text="Healing...")
        except (OSError, RuntimeError) as exc:
            self.process = None
            self.append("Could not start: " + str(exc))
        self.update_buttons()

    def start_live(self, args):
        problem = tt.build_tool()
        if problem:
            raise RuntimeError(problem)
        tt.clear_stop()
        self.process = subprocess.Popen([str(tt.EXE), *args], cwd=tt.PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=tt.NO_WINDOW)

        def pump(process):
            for line in process.stdout:
                if line.strip() and not line.lstrip().startswith("{"):
                    self.queue.put(("log", line))
            process.wait()
            self.queue.put(("done", None))
        threading.Thread(target=pump, args=(self.process,), daemon=True, name="target-camera").start()

    def add_loot_name(self):
        actor = self.selected()
        if actor is not None and actor["kind"] == "npc":
            self.loot_names.set(", ".join(loot_names(f"{self.loot_names.get()}, {actor['name']}")))

    def start_loot(self):
        names = loot_names(self.loot_names.get())
        if self.busy or self.steering() or not names or self.loot_runner is None:
            return
        if self.other_live():
            self.append("A walk or follow is running on the Traversal tab. Stop it first.")
            return
        self.looting = Control()
        self.append("Loot sequence: click into Neocron now. Starting in 5 s...")
        self.update_buttons()
        self.loot_start = self.root.after(5000, self.begin_loot, names)

    def begin_loot(self, names):
        self.loot_start = None
        try:
            runner = self.loot_runner(names, lambda kind, payload: self.queue.put(("loot", (kind, payload))), self.looting)
            threading.Thread(target=runner.run, daemon=True, name="loot-sequence").start()
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
                self.loot_event("done", "Loot sequence stopped.")
            return
        process = self.process
        if process is None:
            return
        self.stop_button.configure(state="disabled")
        threading.Thread(target=tt.stop_walk, args=(process,), daemon=True, name="target-stop").start()

    def finished(self):
        self.process = None
        self.track_button.configure(text="Track")
        self.heal_button.configure(text="Follow and heal")
        self.append("Ended.")
        self.update_buttons()
        self.refresh()

    def close(self):
        """Stop a running camera follow and any actor read; the window is closing."""
        self.closed = True
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
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
