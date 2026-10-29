"""Traversal tab: walk to any place, or follow someone, from inside the suite window.

A Tk port of Nav Walker. The work is done by traversal\\traversal.exe (C#): "allplaces",
"preview" and "nearby" only read (the game's position read-only, the level files), and
"travel" / "follow" walk the character live. This module lists the places, starts those
commands (offline ones on worker threads, results handed back through root.after), shows
their output, and stops a walk with F8, the key the walker watches.
"""
import ctypes
import json
import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "traversal"
EXE = PROJECT / "bin" / "Release" / "net9.0" / "traversal.exe"
HOOKCTL = ROOT / "NeocronHook" / "bin" / "hookctl.exe"
NO_WINDOW = 0x08000000
NOT_YET, OUTPOSTS, BUILDINGS = "not-yet", "wasteland", "buildings"
SECTION_TITLES = {NOT_YET: "Not walkable yet", OUTPOSTS: "Wasteland outposts and landmarks",
                  BUILDINGS: "More buildings and dungeons"}
KIND_ORDER = {"Zone": 0, "Nearest": 1, "Entrance": 2, "Apartment door": 3}
GREY = "#8a9590"


# ---- the engine ----

def build_tool(progress=None):
    """Build traversal.exe with the .NET SDK if it is missing; returns an error text or None."""
    if EXE.exists():
        return None
    if not PROJECT.is_dir():
        return f"The Traversal engine is missing: {PROJECT} not found."
    if progress:
        progress("Building the Traversal engine, one moment...")
    try:
        done = subprocess.run(["dotnet", "build", "-c", "Release", "-nologo", "-v", "q"], cwd=PROJECT,
                              capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Could not build the Traversal engine: {exc}"
    return None if EXE.exists() else "Building the Traversal engine failed: " + (done.stdout + done.stderr)[-400:].strip()


def run_tool(args, timeout=300, track=None):
    """Run one offline engine command and return the last JSON line it prints, parsed."""
    process = subprocess.Popen([str(EXE), *args], cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if track is not None:
        track.add(process)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
        raise RuntimeError(f"The engine took over {timeout} s and was stopped.")
    finally:
        if track is not None:
            track.discard(process)
    found = [line.strip() for line in out.splitlines() if line.strip().startswith(("{", "["))]
    if not found:
        said = [line for line in (err + out).strip().splitlines() if line.strip()]
        raise RuntimeError(said[-1] if said else "The engine printed nothing.")
    return json.loads(found[-1])


def keybd_event(vk, scan, flags):
    ctypes.windll.user32.keybd_event(vk, scan, flags, 0)


def stop_walk(process, key=keybd_event):
    """Stop a walk. The walker only looks at F8 between steps (not while it builds a map), so hold F8
    down until it has gone, up to 5 s; if it is still running, end it and release the W and Shift keys
    it may have been holding (scan-code key-ups, as the walker sends them)."""
    try:
        key(0x77, 0x42, 0)                    # F8 down
        try:
            process.wait(5)
            return
        except subprocess.TimeoutExpired:
            pass
        finally:
            key(0x77, 0x42, 2)                # F8 up
        process.kill()
        try:
            process.wait(2)
        except subprocess.TimeoutExpired:
            pass
    except OSError:
        return                                 # already gone
    scan_up = 0x0008 | 0x0002                  # KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    key(0, 0x11, scan_up)                      # W
    key(0, 0x2A, scan_up)                      # left Shift


# ---- the lists (pure, so tests need no engine) ----

def title(name):
    """"PEPPER PUB" -> "Pepper Pub"; short words, mixed case and words with digits stay as they are."""
    return " ".join(w if len(w) <= 2 or any(c.islower() for c in w) or any(c.isdigit() for c in w)
                    else w[0].upper() + w[1:].lower() for w in name.split(" "))


def parse_allplaces(data):
    """allplaces JSON -> (here, places). notPlaced entries become places with a reason and no target."""
    if isinstance(data, str):
        data = json.loads(data)
    places = [{"zone": int(p["zone"]), "zoneName": p["zoneName"], "away": int(p["away"]), "target": p["target"],
               "name": p["name"], "kind": p["kind"], "category": p.get("category") or "", "why": None}
              for p in data.get("places", [])]
    places += [{"zone": 0, "zoneName": "", "away": 1 << 30, "target": "", "name": p["name"], "kind": "Not yet",
                "category": p.get("category") or "", "why": p.get("why") or "no place for it in the game files"}
               for p in data.get("notPlaced", [])]
    return data.get("here") or {}, places


def walkable(place):
    """Greyed rows (a reason, no target) are never walked to."""
    return bool(place) and place.get("why") is None and bool(place.get("target")) and place.get("zone", 0) > 0


def matches(place, find):
    find = find.strip().lower()
    return not find or any(find in (place.get(k) or "").lower() for k in ("name", "zoneName", "category", "kind"))


def section_key(place, per_zone):
    if place["why"] is not None:
        return NOT_YET
    if per_zone.get(place["zone"], 0) > 1 or place["away"] == 0:
        return str(place["zone"])
    return OUTPOSTS if place["category"] == "Wasteland" else BUILDINGS


def plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def build_sections(places, find=""):
    """The sections the tree shows, in order: one per zone with several places (or the zone you are in),
    then single-place buildings and dungeons, wasteland outposts, and the places not walkable yet.
    Each is {key, title, places, mixed}; places are (index into places, place)."""
    per_zone = {}
    for place in places:
        if place["why"] is None:
            per_zone[place["zone"]] = per_zone.get(place["zone"], 0) + 1
    groups = {}
    for index, place in enumerate(places):
        if matches(place, find):
            groups.setdefault(section_key(place, per_zone), []).append((index, place))
    rank = {BUILDINGS: 1, OUTPOSTS: 2, NOT_YET: 3}

    def order(item):
        key, rows = item
        return rank.get(key, 0), min(p["away"] for _, p in rows), rows[0][1]["zoneName"]

    sections = []
    for key, rows in sorted(groups.items(), key=order):
        mixed = key in (OUTPOSTS, BUILDINGS)
        rows.sort(key=lambda r: (r[1]["away"] if mixed else 0, KIND_ORDER.get(r[1]["kind"], 4), r[1]["kind"], r[1]["name"]))
        first = rows[0][1]
        if key in SECTION_TITLES:
            head = SECTION_TITLES[key]
        else:
            away = "you are here" if first["away"] == 0 else f"{plural(first['away'], 'zone')} away"
            head = f"{first['zoneName']}  ·  {away}"
        sections.append({"key": key, "title": f"{head}  ·  {plural(len(rows), 'place')}", "places": rows,
                         "mixed": mixed, "here": key.isdigit() and first["away"] == 0})
    return sections


def place_text(place, mixed):
    name = title(place["name"]) if place["why"] is not None or place["kind"] != "Zone" else f"{place['name']}  (anywhere)"
    if mixed:
        name += f"   ({place['zoneName']}, {plural(place['away'], 'zone')} away)"
    return name, title(place["category"]) if place["category"] else place["kind"]


def order_actors(actors, find=""):
    """Players first (the usual reason to follow), each group nearest first."""
    find = find.strip().lower()
    return sorted((a for a in actors if not find or find in a["name"].lower()),
                  key=lambda a: (0 if a["kind"] == "player" else 1, a["distance"]))


# ---- the tab ----

class TraversalTab:
    def __init__(self, parent, root, autoload=True):
        self.root = root
        self.autoload = autoload            # read the game on first view; tests turn it off
        self.queue = queue.Queue()
        self.process = None                 # the live walk or follow
        self.live_kind = None
        self.busy = False                   # an offline command is running
        self.offline = set()                # their processes, ended on close
        self.closed = False
        self.places, self.here = [], {}
        self.rows = {}                      # tree iid -> place
        self.open = {}                      # section key -> open, as the user left it
        self.actors, self.actor_rows = [], {}
        self.nearby_loaded = False
        self.mode_status = {"walk": "Press Refresh to read the game.", "follow": "Press Refresh to see who is around you."}
        self._loaded = False
        self._after = None

        host = ttk.Frame(parent, padding=12)
        host.pack(fill="both", expand=True)
        host.columnconfigure(0, weight=1)
        host.rowconfigure(2, weight=1)
        modes = ttk.Frame(host)
        modes.grid(row=0, column=0, sticky="ew")
        self.mode = tk.StringVar(value="walk")
        for value, text in (("walk", "Walk to a place"), ("follow", "Follow someone")):
            ttk.Radiobutton(modes, text=text, value=value, variable=self.mode, style="Toolbutton",
                            command=self.mode_changed).pack(side="left", padx=(0, 6))
        self.status = tk.StringVar(value=self.mode_status["walk"])
        ttk.Label(host, textvariable=self.status, font=("Segoe UI", 11, "bold"), wraplength=900).grid(
            row=1, column=0, sticky="ew", pady=(8, 4))
        self.walk_page = ttk.Frame(host)
        self.follow_page = ttk.Frame(host)
        for page in (self.walk_page, self.follow_page):
            page.grid(row=2, column=0, sticky="nsew")
            page.columnconfigure(0, weight=1)
            page.rowconfigure(1, weight=1)
        self.follow_page.grid_remove()
        self.build_walk_page(self.walk_page)
        self.build_follow_page(self.follow_page)
        logs = ttk.Frame(host)
        logs.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        logs.columnconfigure(0, weight=1)
        self.log = tk.Text(logs, height=5, wrap="word", state="disabled", font=("Consolas", 9), relief="flat", padx=6, pady=4)
        self.log.grid(row=0, column=0, sticky="ew")
        bar = ttk.Scrollbar(logs, orient="vertical", command=self.log.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=bar.set)
        parent.bind("<Map>", self.first_view, add="+")
        self.update_buttons()
        self._after = self.root.after(100, self.poll)

    # ---- layout ----

    def build_walk_page(self, page):
        top = ttk.Frame(page)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(top, text="Find:").pack(side="left")
        self.find = tk.StringVar()
        ttk.Entry(top, textvariable=self.find, width=26).pack(side="left", padx=(6, 8))
        self.find.trace_add("write", lambda *_: self.show_places())
        ttk.Button(top, text="Open all", command=lambda: self.set_all_sections(True)).pack(side="left")
        ttk.Button(top, text="Close all", command=lambda: self.set_all_sections(False)).pack(side="left", padx=(6, 12))
        self.run = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Run", variable=self.run).pack(side="left")
        self.overlay = tk.BooleanVar(value=False)
        self.overlay_box = None
        if HOOKCTL.exists():
            self.overlay_box = ttk.Checkbutton(top, text="In-game panel", variable=self.overlay, command=self.toggle_overlay)
            self.overlay_box.pack(side="left", padx=(12, 0))
        holder = ttk.Frame(page)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(holder, columns=("type",), show="tree headings", selectmode="browse", height=8)
        self.tree.heading("#0", text="Place", anchor="w")
        self.tree.heading("type", text="Type", anchor="w")
        self.tree.column("#0", width=480, stretch=True)
        self.tree.column("type", width=200, stretch=False)
        self.tree.tag_configure("section", font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("grey", foreground=GREY)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.place_selected())
        self.tree.bind("<<TreeviewOpen>>", lambda e: self.remember_section(True))
        self.tree.bind("<<TreeviewClose>>", lambda e: self.remember_section(False))
        self.tree.bind("<Double-1>", self.double_click)
        buttons = ttk.Frame(page)
        buttons.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.walk_button = ttk.Button(buttons, text="Walk there", command=self.walk)
        self.show_button = ttk.Button(buttons, text="Show route", command=self.show_route)
        self.stop_button = ttk.Button(buttons, text="Stop (F8)", command=self.stop)
        self.refresh_button = ttk.Button(buttons, text="Refresh", command=self.refresh)
        for button in (self.walk_button, self.show_button, self.stop_button, self.refresh_button):
            button.pack(side="left", padx=(0, 6))
        ttk.Label(buttons, text="Press Tab in-game first. Starts in 5 s; F8 stops.").pack(side="left", padx=(6, 0))

    def build_follow_page(self, page):
        top = ttk.Frame(page)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(top, text="Find:").pack(side="left")
        self.find_actor = tk.StringVar()
        ttk.Entry(top, textvariable=self.find_actor, width=22).pack(side="left", padx=(6, 12))
        self.find_actor.trace_add("write", lambda *_: self.show_actors())
        ttk.Label(top, text="Stay within:").pack(side="left")
        self.distance = tk.StringVar(value="150")
        ttk.Spinbox(top, from_=40, to=2000, increment=25, textvariable=self.distance, width=7).pack(side="left", padx=6)
        ttk.Label(top, text="units").pack(side="left", padx=(0, 12))
        self.follow_run = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Run", variable=self.follow_run).pack(side="left")
        holder = ttk.Frame(page)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.actor_tree = ttk.Treeview(holder, columns=("name", "type", "distance"), show="headings", selectmode="browse", height=8)
        for column, text, width, anchor in (("name", "Name", 420, "w"), ("type", "Type", 100, "w"), ("distance", "Distance", 110, "e")):
            self.actor_tree.heading(column, text=text, anchor=anchor)
            self.actor_tree.column(column, width=width, anchor=anchor, stretch=column == "name")
        self.actor_tree.tag_configure("grey", foreground=GREY)
        self.actor_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.actor_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.actor_tree.configure(yscrollcommand=scroll.set)
        self.actor_tree.bind("<<TreeviewSelect>>", lambda e: self.update_buttons())
        self.actor_tree.bind("<Double-1>", lambda e: self.follow())
        buttons = ttk.Frame(page)
        buttons.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.follow_button = ttk.Button(buttons, text="Follow", command=self.follow)
        self.follow_stop_button = ttk.Button(buttons, text="Stop (F8)", command=self.stop)
        self.refresh_actors_button = ttk.Button(buttons, text="Refresh", command=self.refresh_nearby)
        for button in (self.follow_button, self.follow_stop_button, self.refresh_actors_button):
            button.pack(side="left", padx=(0, 6))
        ttk.Label(buttons, text="Tab in-game first. Waits within the distance; F8 stops.").pack(side="left", padx=(6, 0))

    # ---- state ----

    def first_view(self, _event=None):
        if self._loaded or not self.autoload:
            return
        self._loaded = True
        self.refresh()

    def mode_changed(self):
        follow = self.mode.get() == "follow"
        (self.follow_page if follow else self.walk_page).grid()
        (self.walk_page if follow else self.follow_page).grid_remove()
        self.status.set(self.mode_status[self.mode.get()])
        if follow and not self.nearby_loaded and self.autoload:
            self.refresh_nearby()

    def set_status(self, mode, text):
        self.mode_status[mode] = text
        if self.mode.get() == mode:
            self.status.set(text)

    def selected_place(self):
        chosen = self.tree.selection()
        return self.rows.get(chosen[0]) if chosen else None

    def selected_actor(self):
        chosen = self.actor_tree.selection()
        return self.actor_rows.get(chosen[0]) if chosen else None

    def update_buttons(self):
        idle = not self.busy and self.process is None
        place, actor = self.selected_place(), self.selected_actor()
        def state(widget, on):
            widget.configure(state="normal" if on else "disabled")
        state(self.walk_button, idle and walkable(place))
        state(self.show_button, idle and walkable(place))
        state(self.refresh_button, idle)
        state(self.follow_button, idle and actor is not None and not actor["dead"])
        state(self.refresh_actors_button, idle)
        state(self.stop_button, self.process is not None)
        state(self.follow_stop_button, self.process is not None)

    def set_busy(self, busy):
        self.busy = busy
        self.update_buttons()

    # ---- log ----

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---- workers ----

    def start_offline(self, kind, args):
        """Run an offline engine command on a worker thread; its result arrives in poll()."""
        self.set_busy(True)

        def work():
            try:
                problem = build_tool(lambda text: self.queue.put(("log", text)))
                if problem:
                    raise RuntimeError(problem)
                result = ("ok", run_tool(args, track=self.offline))
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                result = ("error", str(exc))
            self.queue.put((kind, result))
        threading.Thread(target=work, daemon=True, name=f"traversal-{kind}").start()

    def start_live(self, kind, args):
        problem = build_tool()
        if problem:
            raise RuntimeError(problem)
        self.process = subprocess.Popen([str(EXE), *args], cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        self.live_kind = kind
        self.update_buttons()

        def pump(process):
            for line in process.stdout:
                if line.strip() and not line.lstrip().startswith("{"):
                    self.queue.put(("log", line))
            process.wait()
            self.queue.put(("done", (kind, process.returncode)))
        threading.Thread(target=pump, args=(self.process,), daemon=True, name=f"traversal-{kind}").start()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.append(payload)
                elif kind == "allplaces":
                    self.set_busy(False)
                    self.show_allplaces(payload)
                elif kind == "nearby":
                    self.set_busy(False)
                    self.show_nearby(payload)
                elif kind == "preview":
                    self.set_busy(False)
                    self.show_preview(payload)
                elif kind == "overlay":
                    self.sync_overlay(*payload)
                elif kind == "done":
                    self.finished(*payload)
        except queue.Empty:
            pass
        self._after = self.root.after(100, self.poll)

    # ---- walk to a place ----

    def refresh(self):
        if self.busy or self.process is not None:
            return
        self.set_status("walk", "Reading the game…")
        self.start_offline("allplaces", ["allplaces"])
        if self.overlay_box is not None:
            self.check_overlay()

    def show_allplaces(self, result):
        state, data = result
        if state != "ok":
            self.set_status("walk", data)
            return
        try:
            self.here, self.places = parse_allplaces(data)
        except (KeyError, TypeError, ValueError) as exc:
            self.set_status("walk", f"Could not read the place list: {exc}")
            return
        count = sum(1 for p in self.places if p["why"] is None)
        if self.here.get("live"):
            self.set_status("walk", f"{self.here.get('name')}  ·  you are at {self.here.get('x', 0):.0f}, "
                                    f"{self.here.get('z', 0):.0f}  ·  {count} places to walk to")
        else:
            self.set_status("walk", f"Neocron is not running: zones counted from Plaza 1  ·  {count} places to walk to")
        self.show_places()

    def show_places(self):
        keep = self.tree.selection()
        keep = keep[0] if keep and keep[0] in self.rows else None
        find = self.find.get().strip()
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for section in build_sections(self.places, find):
            key = section["key"]
            is_open = bool(find) or self.open.get(key, section["here"])
            head = self.tree.insert("", "end", iid="s:" + key, text=section["title"], open=is_open, tags=("section",))
            for index, place in section["places"]:
                name, kind = place_text(place, section["mixed"])
                iid = f"p{index}"
                self.tree.insert(head, "end", iid=iid, text=name, values=(kind,),
                                 tags=("grey",) if place["why"] is not None else ())
                self.rows[iid] = place
        if keep in self.rows:
            self.tree.selection_set(keep)
            self.tree.see(keep)
        self.update_buttons()

    def sections_shown(self):
        """(key, open) for each section in the tree, in order."""
        return [(iid[2:], bool(self.tree.item(iid, "open"))) for iid in self.tree.get_children()]

    def remember_section(self, is_open):
        iid = self.tree.focus()
        if iid.startswith("s:") and not self.find.get().strip():
            self.open[iid[2:]] = is_open

    def set_all_sections(self, is_open):
        for iid in self.tree.get_children():
            self.open[iid[2:]] = is_open
            self.tree.item(iid, open=is_open)

    def place_selected(self):
        self.update_buttons()
        place = self.selected_place()
        if place is not None and place["why"] is not None:
            self.clear_log()
            self.append(f"{title(place['name'])}: not walkable yet ({place['why']}).")

    def double_click(self, event):
        if self.tree.identify_row(event.y) in self.rows:
            self.walk()

    def walk(self):
        place = self.selected_place()
        if self.busy or self.process is not None or not walkable(place):
            return
        where = place["zoneName"] if place["kind"] == "Zone" else f"{title(place['name'])} in {place['zoneName']}"
        args = ["travel", str(place["zone"]), place["target"], "--pulse", "12"] + (["--run"] if self.run.get() else [])
        self.clear_log()
        self.append(f"{'Running' if self.run.get() else 'Walking'} to {where}. Starting in 5 s...")
        self.walk_where = where
        try:
            self.start_live("walk", args)
            self.walk_button.configure(text="Running..." if self.run.get() else "Walking...")
        except (OSError, RuntimeError) as exc:
            self.process = None
            self.append("Could not start: " + str(exc))
            self.update_buttons()

    def show_route(self):
        place = self.selected_place()
        if self.busy or self.process is not None or not walkable(place):
            return
        self.start_offline("preview", ["preview", str(place["zone"]), place["target"]])

    def show_preview(self, result):
        state, plan = result
        self.clear_log()
        if state != "ok":
            self.append("Could not plan the route: " + plan)
            return
        self.append(f"From {plan.get('start')}: {' > '.join(plan.get('chain', []))}")
        for leg in plan.get("legs", []):
            note = f"  ({leg['note']})" if leg.get("note") else ""
            self.append(f"  {leg.get('from')} > {leg.get('to')}: {leg.get('length', 0):,.0f} units, {leg.get('method')}{note}")
        if not plan.get("ok"):
            self.append("No walkable way there.")
        elif not plan.get("legs"):
            self.append("It is in the zone you are in: no zone lines to cross. Nothing moved.")
        else:
            low, high = (plan.get("minutes") or [0, 0])[:2]
            self.append(f"About {low:g}-{high:g} min. Nothing moved.")
        picture = plan.get("picture")
        if picture and Path(picture).exists():
            try:
                os.startfile(picture)
            except OSError as exc:
                self.append(f"Could not open the route picture: {exc}")

    # ---- follow someone ----

    def refresh_nearby(self):
        if self.busy or self.process is not None:
            return
        self.set_status("follow", "Reading who is around you…")
        self.start_offline("nearby", ["nearby"])

    def show_nearby(self, result):
        state, data = result
        if state != "ok":
            self.set_status("follow", data)
            return
        if not data.get("live"):
            self.actors = []
            self.set_status("follow", f"Cannot read the game: {data.get('why')}")
        else:
            self.actors = [{"id": str(e["id"]), "name": e["name"], "kind": e["kind"], "distance": float(e["distance"]),
                            "dead": bool(e.get("dead"))} for e in data.get("entities", [])]
            players = sum(1 for a in self.actors if a["kind"] == "player")
            npcs = len(self.actors) - players
            self.set_status("follow", f"{data.get('sectorName') or 'This zone'}  ·  {plural(players, 'player')} and "
                                      f"{plural(npcs, 'NPC')} around you")
        self.nearby_loaded = True
        self.show_actors()

    def show_actors(self):
        keep = self.selected_actor()
        keep = keep["id"] if keep else None
        self.actor_tree.delete(*self.actor_tree.get_children())
        self.actor_rows = {}
        for i, actor in enumerate(order_actors(self.actors, self.find_actor.get())):
            iid = f"a{i}"
            self.actor_tree.insert("", "end", iid=iid, tags=("grey",) if actor["dead"] else (),
                                   values=(f"{actor['name']}  (dead)" if actor["dead"] else actor["name"],
                                           "Player" if actor["kind"] == "player" else "NPC", f"{actor['distance']:,.0f}"))
            self.actor_rows[iid] = actor
            if actor["id"] == keep:
                self.actor_tree.selection_set(iid)
        self.update_buttons()

    def follow_distance(self):
        try:
            return max(40, min(2000, int(float(self.distance.get()))))
        except ValueError:
            return 150

    def follow(self):
        actor = self.selected_actor()
        if self.busy or self.process is not None or actor is None or actor["dead"]:
            return
        distance = self.follow_distance()
        self.distance.set(str(distance))
        args = ["follow", actor["id"], "--distance", str(distance), "--pulse", "12"] + (["--run"] if self.follow_run.get() else [])
        self.clear_log()
        self.append(f"Following {actor['name']}, staying within {distance:,} units. Starting in 5 s...")
        try:
            self.start_live("follow", args)
            self.follow_button.configure(text="Following...")
        except (OSError, RuntimeError) as exc:
            self.process = None
            self.append("Could not start: " + str(exc))
            self.update_buttons()

    # ---- the live walk ending ----

    def stop(self):
        process = self.process
        if process is None:
            return
        self.stop_button.configure(state="disabled")
        self.follow_stop_button.configure(state="disabled")
        threading.Thread(target=stop_walk, args=(process,), daemon=True, name="traversal-stop").start()

    def finished(self, kind, code):
        self.process = None
        self.live_kind = None
        self.walk_button.configure(text="Walk there")
        self.follow_button.configure(text="Follow")
        self.update_buttons()
        if kind == "walk":
            self.append(f"Arrived: {getattr(self, 'walk_where', '')}." if code == 0 else "Stopped.")
            self.refresh()
        else:
            self.append("Follow ended.")
            self.refresh_nearby()

    # ---- in-game panel (NeocronHook), shown only when hookctl.exe is present ----

    def check_overlay(self):
        def work():
            try:
                listing = subprocess.run(["tasklist", "/m", "NeocronHook.dll", "/fi", "imagename eq neocronclient.exe"],
                                         capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
                self.queue.put(("overlay", ("neocronclient.exe" in listing.lower(), None)))
            except (OSError, subprocess.SubprocessError):
                self.queue.put(("overlay", (False, None)))
        threading.Thread(target=work, daemon=True, name="traversal-overlay").start()

    def toggle_overlay(self):
        load = self.overlay.get()
        self.overlay_box.configure(state="disabled")

        def work():
            try:
                said = subprocess.run([str(HOOKCTL), "inject" if load else "unload"], capture_output=True, text=True,
                                      timeout=60, creationflags=NO_WINDOW).stdout.strip()
                text = ("Overlay: " if load else "Overlay removed: ") + said
            except (OSError, subprocess.SubprocessError) as exc:
                text = f"Overlay: {exc}"
            self.queue.put(("log", text))
            self.check_overlay()
        threading.Thread(target=work, daemon=True, name="traversal-overlay").start()

    def sync_overlay(self, loaded, _unused):
        if self.overlay_box is not None:
            self.overlay.set(loaded)
            self.overlay_box.configure(state="normal")

    # ---- closing ----

    def close(self):
        """Stop any running walk (F8, then end it) and any offline command; the window is closing."""
        self.closed = True
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass
        if self.process is not None:
            stop_walk(self.process)
            self.process = None
        for process in list(self.offline):
            try:
                process.kill()
            except OSError:
                pass
