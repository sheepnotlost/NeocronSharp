"""Embed the screen-reading counter in the suite's UI and single-worker lifecycle."""

import json
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np

from ntc import config, ocr
from ntc.app import App as CounterApp
from ntc.scanner import Scanner

STATE_FILES = ("lists.json", "known_items.json", "config.json")


def import_counter_state(source, destination):
    """Copy valid standalone state once. Never modify source or overwrite a file."""
    source, destination = Path(source), Path(destination)
    candidates = []
    for name in STATE_FILES:
        src, dst = source / name, destination / name
        if src.is_file() and not dst.exists():
            data = json.loads(src.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"{name} must contain a JSON object.")
            if name == "lists.json":
                lists = data.get("lists")
                if not isinstance(lists, dict) or not lists:
                    raise ValueError("lists.json contains no named lists.")
                for item in lists.values():
                    if not isinstance(item, dict) or not isinstance(item.get("entries"), list):
                        raise ValueError("lists.json has an invalid list.")
                    for entry in item["entries"]:
                        if not isinstance(entry, dict) or not {"id", "label", "cells"} <= entry.keys() or not isinstance(entry["cells"], list):
                            raise ValueError("lists.json has an invalid scan entry.")
            candidates.append((src, dst))
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for src, dst in candidates:
        # Exclusive create also protects a destination written since validation.
        try:
            with dst.open("xb") as output, src.open("rb") as original:
                shutil.copyfileobj(original, output)
        except FileExistsError:
            continue
        copied.append(src.name)
    return copied


class CounterSession:
    """Translate client RGB captures and input into the existing counter API.

    Every input is checked against the suite's bound HWND, identity and size.
    No focus acquisition and no desktop/primary-monitor coordinate assumptions.
    """

    def __init__(self, backend, size, cfg, names, stopped):
        self.backend, self.size, self.stopped = backend, list(size), stopped
        self.scanner = Scanner(cfg, names, grab=self.grab, move=self.move,
                               get_cursor=self.backend.cursor_client, foreground=self.foreground,
                               focus=lambda _title: None, grab_region=self.grab_region, wheel=self.wheel)
        # A close request before the worker starts must survive Scanner.scan().
        self.scanner.abort_event = stopped

    def check(self):
        if self.stopped.is_set():
            raise RuntimeError("Tech Counter scan stopped.")
        try:
            self.backend.check_focus(self.size)
        except Exception:
            self.stopped.set()
            raise

    def foreground(self):
        try:
            self.check()
        except (ValueError, RuntimeError):
            return ""
        return self.scanner.cfg["game_window_title_contains"]

    def grab(self):
        self.check()
        return np.ascontiguousarray(self.backend.capture()[:, :, ::-1])

    def grab_region(self, x, y, width, height):
        self.check()
        frame = self.backend.capture_region((x, y, x + width, y + height))
        return np.ascontiguousarray(frame[y:y + height, x:x + width, ::-1])

    def move(self, x, y, _mode="absolute"):
        self.check()
        if self.scanner.aborted():
            raise RuntimeError("Tech Counter stopped after mouse movement. No automatic resume.")
        self.backend.move((int(x), int(y)))

    def wheel(self, notches):
        self.check()
        if self.scanner.aborted():
            return
        self.backend.scroll(notches)

    def run(self, target, items, progress):
        self.check()
        original = self.backend.cursor_client()
        try:
            return self.scanner.scan(target, progress, items=items, activate_game=False,
                                     reset_abort=False, restore_cursor=False)
        finally:
            # Focus loss or physical mouse movement gives control back permanently.
            if not self.scanner.aborted():
                self.move(*original)


class TechCounterPanel(CounterApp):
    def __init__(self, owner, host, data_dir):
        self.owner = owner
        data_dir = Path(data_dir)
        migration = ""
        source = data_dir.parent.parent / "Neocron Tech Counter"
        try:
            copied = import_counter_state(source, data_dir) if source.is_dir() else []
            if copied:
                migration = "Imported existing counter data; the standalone files are unchanged."
        except (OSError, ValueError) as exc:
            migration = f"Existing counter data was not imported: {exc}"
        instructions = ttk.Label(host, text="Open a cabinet or Inventory, then Start.", wraplength=900)
        instructions.pack(fill="x", padx=8, pady=6)
        body = ttk.Frame(host)
        body.pack(fill="both", expand=True)
        super().__init__(root=owner.root, body=body, on_scan=owner.start, data_dir=data_dir)
        self._disabled_states = []
        self.import_button = ttk.Button(body, text="Import standalone counter folder…", command=self.import_folder)
        self.import_button.pack(side="bottom", anchor="w", padx=6, pady=4)
        if migration:
            self.status.set(migration)
        self.job = None
        self.session = None

    def start_scan(self):
        self.owner.start()

    def prepare(self):
        ocr.configure(self.cfg["tesseract_path"])
        ocr.require()
        self.on_target_selected()
        self.job = (self.store.active, self.target_var.get(), self.cfg["log_items"])
        self.last_warnings = []
        self.status.set("Starting in 3 seconds — focus Neocron.")

    def run_scan(self, control):
        list_name, target, items = self.job
        try:
            self.session = CounterSession(self.owner.backend, self.owner.profile["client_size"],
                                          dict(self.cfg), self.names, control.stopped)
            results = self.session.run(target, items, lambda msg: self.owner.events.put(("counter_progress", msg)))
            self.owner.events.put(("counter_done", (results, list_name)))
        except Exception as exc:
            self.owner.events.put(("counter_error", str(exc)))

    def set_editing(self, enabled):
        self.busy = not enabled
        if enabled:
            for widget, state in self._disabled_states:
                if widget.winfo_exists():
                    widget.state(["!disabled", *state])
            self._disabled_states = []
            self.refresh()
            return
        def disable(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, (ttk.Button, ttk.Combobox, ttk.Menubutton, ttk.Entry, ttk.Treeview)):
                    self._disabled_states.append((widget, widget.state()))
                    widget.state(["disabled"])
                disable(widget)
        disable(self.body)

    def edit_entry(self):
        if not self.busy:
            super().edit_entry()

    def show_where(self, event=None):
        if not self.busy:
            super().show_where(event)

    def _window(self, *args, **kwargs):
        win, host = super()._window(*args, **kwargs)
        # Existing edits must be finished before starting a game operation.
        win.transient(self.root)
        win.grab_set()
        return win, host

    def import_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self.root, title="Select the standalone Neocron Tech Counter folder")
        if not folder:
            return
        try:
            copied = import_counter_state(folder, self.data_dir)
            if copied:
                from ntc.lists import ListStore
                from ntc.names import Names
                self.store = ListStore(self.data_dir / "lists.json")
                self.names = Names(self.data_dir / "known_items.json")
                self.cfg = config.load(self.cfg_path)
                self.target_var.set(self.cfg["scan_target"])
                self.log_var.set({"all": "all items", "techs": "techs only"}[self.cfg["log_items"]])
                self.last_added = []
                self.refresh()
            self.status.set("Imported: " + ", ".join(copied) if copied else
                            "No new files imported. Existing suite counter files are always kept.")
        except (OSError, ValueError) as exc:
            self._error(exc)
