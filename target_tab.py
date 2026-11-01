"""Target Acquisition tab: keep the camera on a player or NPC while you move yourself.

Follow's target list without the walk: the work is done by traversal.exe's "camera" command,
which sends mouse movement only (no movement keys, no clicks) and stops on Stop or F8.
"""
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import traversal_tab as tt


class TargetTab:
    def __init__(self, parent, root, autoload=True, other_live=lambda: False):
        self.root = root
        self.autoload = autoload            # read the game on first view; tests turn it off
        self.other_live = other_live        # a walk or follow is steering the same mouse
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
        for button in (self.track_button, self.stop_button, self.refresh_button):
            button.pack(side="left", padx=(0, 6))
        ttk.Label(buttons, text="Tab in-game first. Turns the camera only; F8 stops.").pack(side="left", padx=(6, 0))
        logs = ttk.Frame(host)
        logs.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        logs.columnconfigure(0, weight=1)
        self.log = tk.Text(logs, height=5, wrap="word", state="disabled", font=("Consolas", 9), relief="flat", padx=6, pady=4)
        self.log.grid(row=0, column=0, sticky="ew")
        bar = ttk.Scrollbar(logs, orient="vertical", command=self.log.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=bar.set)
        parent.bind("<Map>", self.first_view, add="+")
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

    def update_buttons(self):
        idle = not self.busy and self.process is None
        actor = self.selected()
        self.track_button.configure(state="normal" if idle and actor is not None and not actor["dead"] else "disabled")
        self.refresh_button.configure(state="normal" if idle else "disabled")
        self.stop_button.configure(state="normal" if self.process is not None else "disabled")

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
                elif kind == "nearby":
                    self.busy = False
                    self.show_nearby(payload)
                elif kind == "done":
                    self.finished()
        except queue.Empty:
            pass
        self._after = self.root.after(100, self.poll)

    def refresh(self):
        if self.busy or self.process is not None:
            return
        self.busy = True
        self.update_buttons()
        self.status.set("Reading who is around you…")

        def work():
            try:
                problem = tt.build_tool(lambda text: self.queue.put(("log", text)))
                if problem:
                    raise RuntimeError(problem)
                result = ("ok", tt.run_tool(["nearby"], track=self.offline))
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
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
            self.actors = [{"id": str(e["id"]), "name": e["name"], "kind": e["kind"], "distance": float(e["distance"]),
                            "dead": bool(e.get("dead"))} for e in data.get("entities", [])]
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
        self.update_buttons()

    def track(self):
        actor = self.selected()
        if self.busy or self.process is not None or actor is None or actor["dead"]:
            return
        if self.other_live():
            self.append("A walk or follow is running on the Traversal tab. Stop it first.")
            return
        self.append(f"Keeping the camera on {actor['name']}. Starting in 5 s...")
        try:
            self.start_live(["camera", actor["id"], "--pulse", "24"])
            self.track_button.configure(text="Tracking...")
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

    def stop(self):
        process = self.process
        if process is None:
            return
        self.stop_button.configure(state="disabled")
        threading.Thread(target=tt.stop_walk, args=(process,), daemon=True, name="target-stop").start()

    def finished(self):
        self.process = None
        self.track_button.configure(text="Track")
        self.append("Camera follow ended.")
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
        for process in list(self.offline):
            try:
                process.kill()
            except OSError:
                pass
