"""Always-on-top results window with persistent lists (SPEC 8, 13)."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import config, export, ocr, sets, skin, winapi
from .scanner import TARGETS
from .lists import ListStore
from .names import Names
from .scanner import Scanner

EXPORT_DIR = config.ROOT / "exports"
FLAGS_BAD = {"QTY_UNCERTAIN", "NAME_UNREAD"}
LOG_LABELS = {"all": "all items", "techs": "techs only"}
WIN_W = 560            # wide enough for the long item names and every button


class App:
    def __init__(self, store=None, *, root=None, body=None, on_scan=None, data_dir=None):
        self.embedded = root is not None
        self.data_dir = Path(data_dir) if data_dir is not None else config.ROOT
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg_path = self.data_dir / "config.json"
        self.export_dir = self.data_dir / "exports"
        self.cfg = config.load(self.cfg_path)
        self.names = Names(self.data_dir / "known_items.json")
        self.store = store or ListStore(self.data_dir / "lists.json")
        self.scanner = Scanner(self.cfg, self.names)
        self.busy = False
        self.last_added = []            # entry ids added by this session's most recent scan (for Undo)
        self.last_warnings = []
        self.sets_refresh = None         # set while the Sets window is open, so it follows the list
        self.closing = False

        if self.embedded:
            self.root, self.body = root, body
            self._build(on_scan)
            self.refresh()
            return

        skin.set_app_id()
        skin.load_font()                                           # before Tk starts, so Blinker is found
        self.root = tk.Tk()
        self.root.title("Neocron Tech Counter")
        w = self.root.winfo_screenwidth()
        self.root.geometry(f"{WIN_W}x700+{w - WIN_W - 20}+40")     # right edge, clear of the cabinet
        self.root.attributes("-topmost", True)
        skin.style(self.root)
        self.frame = skin.frame(self.root, "Neocron Tech Counter", big=True, minsize=(WIN_W, 560))
        self.body = self.frame.body if self.frame else self.root
        self._build()
        skin.apply(self)
        self.refresh()

        self.hotkeys = winapi.HotkeyListener({
            1: (self.cfg["hotkey_scan"], lambda: self.root.after(0, self.start_scan)),
            2: (self.cfg["hotkey_abort"], self.scanner.request_abort),
        })
        self.hotkeys.start()
        self.root.after(800, self._check_hotkeys)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # -- layout ------------------------------------------------------------
    def _build(self, on_scan=None):
        r = self.body
        top = ttk.Frame(r)
        top.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(top, text="List:").pack(side="left")
        self.list_var = tk.StringVar()
        self.list_box = ttk.Combobox(top, textvariable=self.list_var, state="readonly", width=18)
        self.list_box.pack(side="left", padx=4)
        self.list_box.bind("<<ComboboxSelected>>", self.on_list_selected)
        ttk.Button(top, text="New", width=6, command=self.new_list).pack(side="left")
        ttk.Button(top, text="Rename", width=8, command=self.rename_list).pack(side="left", padx=2)
        ttk.Button(top, text="Delete", width=7, command=self.delete_list).pack(side="left")

        bar = ttk.Frame(r)
        bar.pack(fill="x", padx=6, pady=2)
        self.scan_btn = ttk.Button(bar, text="Scan", command=on_scan or self.start_scan)
        if not self.embedded:
            self.scan_btn.pack(side="left", fill="x", expand=True)
        self.undo_btn = ttk.Button(bar, text="Undo last scan", command=self.undo_last)
        self.undo_btn.pack(side="left", fill="x", expand=True, padx=4)
        mb = ttk.Menubutton(bar, text="Export ▾")
        menu = tk.Menu(mb, tearoff=0)
        menu.add_command(label="Copy to clipboard", command=self.export_clipboard)
        menu.add_command(label="Save CSV", command=lambda: self.export_file("csv"))
        menu.add_command(label="Save CSV by cabinet", command=lambda: self.export_file("cabinets.csv"))
        menu.add_command(label="Save TXT", command=lambda: self.export_file("txt"))
        menu.add_command(label="Save JSON", command=lambda: self.export_file("json"))
        mb["menu"] = menu
        mb.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(bar, text="Sets...", command=self.open_sets).pack(side="left", fill="x", expand=True)

        opts = ttk.Frame(r)
        opts.pack(fill="x", padx=6, pady=(0, 2))
        ttk.Label(opts, text="Scan:").pack(side="left")
        self.target_var = tk.StringVar(value=self.cfg["scan_target"])
        target_box = ttk.Combobox(opts, textvariable=self.target_var, state="readonly", width=10, values=list(TARGETS))
        target_box.pack(side="left", padx=(2, 12))
        target_box.bind("<<ComboboxSelected>>", self.on_target_selected)
        ttk.Label(opts, text="Log:").pack(side="left")
        self.log_var = tk.StringVar(value=LOG_LABELS[self.cfg["log_items"]])
        log_box = ttk.Combobox(opts, textvariable=self.log_var, state="readonly", width=12, values=list(LOG_LABELS.values()))
        log_box.pack(side="left", padx=2)
        log_box.bind("<<ComboboxSelected>>", self.on_target_selected)

        self.status = tk.StringVar(value="Ready")
        ttk.Label(r, textvariable=self.status, wraplength=WIN_W - 30).pack(fill="x", padx=8)

        self.footer = tk.StringVar(value="")
        ttk.Label(r, textvariable=self.footer, wraplength=WIN_W - 30, justify="left").pack(
            side="bottom", fill="x", padx=8, pady=8)

        # A draggable divider between the item list and the scans list: either one can be made larger or smaller.
        self.paned = ttk.PanedWindow(r, orient="vertical")
        self.paned.pack(fill="both", expand=True, padx=6, pady=(6, 2))

        top = ttk.Frame(self.paned)
        self.tree = ttk.Treeview(top, columns=("item", "qty"), show="headings", height=4)
        self.tree.heading("item", text="Item (whole list; double-click for where)")
        self.tree.heading("qty", text="Qty")
        self.tree.column("item", width=440, stretch=True)
        self.tree.column("qty", width=60, anchor="e", stretch=False)
        self.tree.tag_configure("flag", background="#fff3a0", foreground="black")
        sb = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self.show_where)
        self.paned.add(top, weight=3)

        bottom = ttk.Frame(self.paned)
        eb = ttk.Frame(bottom)
        eb.pack(side="bottom", fill="x", pady=(2, 0))
        for text, cmd in (("Edit", self.edit_entry), ("Rename", self.rename_entry), ("Delete scan", self.delete_entry),
                          ("Add manual entry", self.add_manual)):
            ttk.Button(eb, text=text, command=cmd).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Label(bottom, text="Scans in this list (double-click to edit; drag the bar above to resize):").pack(anchor="w")
        lst = ttk.Frame(bottom)
        lst.pack(fill="both", expand=True)
        self.entries_tree = ttk.Treeview(lst, columns=("label", "items", "slots", "time"), show="headings", height=4)
        for col, text, width, anchor in (("label", "Cabinet", 170, "w"), ("items", "Items", 70, "e"),
                                         ("slots", "Slots", 70, "e"), ("time", "Time", 190, "w")):
            self.entries_tree.heading(col, text=text)
            self.entries_tree.column(col, width=width, anchor=anchor)
        sb2 = ttk.Scrollbar(lst, orient="vertical", command=self.entries_tree.yview)
        self.entries_tree.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.entries_tree.pack(side="left", fill="both", expand=True)
        self.entries_tree.bind("<Double-1>", lambda _e: self.edit_entry())
        self.paned.add(bottom, weight=2)

    # -- refresh -----------------------------------------------------------
    def refresh(self):
        s = self.store
        self.list_box["values"] = s.names()
        self.list_var.set(s.active)

        flagged = {c["name"] for e in s.entries() for c in e["cells"] if FLAGS_BAD & set(c.get("flags", []))}
        self.tree.delete(*self.tree.get_children())
        totals = s.totals()
        for name, qty in totals.items():
            self.tree.insert("", "end", values=(name, qty), tags=("flag",) if name in flagged else ())

        self.entries_tree.delete(*self.entries_tree.get_children())
        for e in s.entries():
            self.entries_tree.insert("", "end", iid=e["id"], values=(
                e["label"], sum(c["qty"] for c in e["cells"]), len(e["cells"]), e["time"].replace("T", " ")))

        ids = {e["id"] for e in s.entries()}
        undo_ok = any(i in ids for i in self.last_added)
        self.undo_btn.state(["!disabled"] if undo_ok else ["disabled"])
        n = len(s.entries())
        text = (f"Total: {sum(totals.values())} items in {s.slot_count()} slots across {n} "
                f"scan{'s' if n != 1 else ''} · {len(totals)} unique")
        if self.last_warnings:
            text += "\n" + "\n".join(self.last_warnings)
        self.footer.set(text)
        if self.sets_refresh:
            self.sets_refresh()

    def selected_entry_id(self):
        sel = self.entries_tree.selection()
        if not sel:
            messagebox.showinfo("Pick a scan", "Select a scan in the 'Scans in this list' table first.", parent=self.root)
            return None
        return sel[0]

    def _error(self, e):
        messagebox.showerror("Cannot do that", str(e), parent=self.root)

    # -- lists -------------------------------------------------------------
    def on_list_selected(self, _e=None):
        if self.busy:
            self.list_var.set(self.store.active)
            return
        self.store.set_active(self.list_var.get())
        self.last_warnings = []
        self.refresh()

    def new_list(self):
        name = simpledialog.askstring("New list", "Name for the new list:", parent=self.root)
        if name is None:
            return
        try:
            self.store.create(name)
        except ValueError as e:
            return self._error(e)
        self.last_warnings = []
        self.refresh()

    def rename_list(self):
        name = simpledialog.askstring("Rename list", "New name:", initialvalue=self.store.active, parent=self.root)
        if name is None:
            return
        try:
            self.store.rename(self.store.active, name)
        except ValueError as e:
            return self._error(e)
        self.refresh()

    def delete_list(self):
        if self.busy:
            return
        name = self.store.active
        n = len(self.store.entries())
        if messagebox.askyesno("Delete list", f"Delete the list '{name}' and its {n} scan(s)? This cannot be undone.",
                               parent=self.root):
            self.store.delete(name)
            self.last_added, self.last_warnings = [], []
            self.refresh()

    # -- scanning ----------------------------------------------------------
    def on_target_selected(self, _e=None):
        self.cfg["scan_target"] = self.target_var.get()
        self.cfg["log_items"] = {v: k for k, v in LOG_LABELS.items()}[self.log_var.get()]
        config.save(self.cfg, self.cfg_path)

    def start_scan(self):
        if self.busy:
            return
        self.busy = True
        self.scan_btn.state(["disabled"])
        self.status.set("Scanning...")
        self.last_warnings = []
        self.scan_thread = threading.Thread(target=self._scan_worker, args=(self.store.active, self.target_var.get()),
                                            daemon=True)
        self.scan_thread.start()

    def _ui(self, fn, *args):
        """Run fn on the UI thread. Does nothing once the window is closing (a scan thread may still be finishing)."""
        if self.closing:
            return
        try:
            self.root.after(0, fn, *args)
        except (RuntimeError, tk.TclError):
            pass

    def _scan_worker(self, list_name, target):
        try:
            results = self.scanner.scan(target, lambda msg: self._ui(self.status.set, f"Scanning {msg}"),
                                        items=self.cfg["log_items"])
            self._ui(self.finish_scan, results, list_name)
        except Exception as e:  # shown to the user, never silent
            self._ui(self.fail_scan, str(e))

    def fail_scan(self, msg):
        self.busy = False
        self.scan_btn.state(["!disabled"])
        self.status.set(msg)

    def finish_scan(self, results, list_name):
        """Add every window that was scanned to the list it was started from, one entry per window."""
        self.busy = False
        self.scan_btn.state(["!disabled"])
        self.last_warnings = [w for r in results for w in r.warnings]
        added = []
        for result in results:
            if result.cells:
                added.append((self.store.add_scan(result, list_name), result))
        self.last_added = [e["id"] for e, _ in added]
        if not added:
            self.status.set(self.last_warnings[0] if self.last_warnings else "Nothing found")
        else:
            shown = list_name if list_name in self.store.names() else self.store.active
            parts = ", ".join(f"{e['label']} ({sum(r.totals.values())} items)" for e, r in added)
            self.status.set(f"Added {parts} to '{shown}' in {sum(r.duration_s for _, r in added):.0f} s")
        self.refresh()

    def undo_last(self):
        for eid in self.last_added:
            try:
                self.store.delete_entry(eid)
            except KeyError:
                pass
        if self.last_added:
            self.status.set("Last scan removed")
        self.last_added = []
        self.refresh()

    # -- entries -----------------------------------------------------------
    def rename_entry(self):
        eid = self.selected_entry_id()
        if not eid:
            return
        _, entry = self.store.find_entry(eid)
        label = simpledialog.askstring("Rename scan", "Label:", initialvalue=entry["label"], parent=self.root)
        if label is None:
            return
        try:
            self.store.rename_entry(eid, label)
        except ValueError as e:
            return self._error(e)
        self.refresh()

    def delete_entry(self):
        eid = self.selected_entry_id()
        if not eid:
            return
        _, entry = self.store.find_entry(eid)
        if messagebox.askyesno("Delete scan", f"Delete '{entry['label']}' from this list?", parent=self.root):
            self.store.delete_entry(eid)
            if eid in self.last_added:
                self.last_added.remove(eid)
            self.refresh()

    def add_manual(self):
        entry = self.store.add_manual("Manual")
        self.refresh()
        self.open_editor(entry["id"])

    def edit_entry(self):
        eid = self.selected_entry_id()
        if eid:
            self.open_editor(eid)

    def _window(self, title, geometry=None, minsize=(360, 200), parent=None):
        """A skinned always-on-top window; returns (window, the frame to build the widgets in)."""
        win = tk.Toplevel(parent or self.root)
        win.title(title)
        if geometry:
            win.geometry(geometry)
        if self.embedded:
            win.minsize(*minsize)
            return win, win
        win.attributes("-topmost", True)
        fr = skin.frame(win, title, minsize=minsize, minimizable=False)
        if not fr:
            skin.apply_toplevel(win)
        return win, (fr.body if fr else win)

    def open_editor(self, eid):
        _, entry = self.store.find_entry(eid)
        win, host = self._window(f"Edit: {entry['label']}", minsize=(520, 160))
        win.transient(self.root)
        body = ttk.Frame(host)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        rows = []   # dicts: {"cell": dict|None, "name": StringVar, "qty": StringVar, "deleted": bool}

        def add_row(cell=None):
            i = len(rows)
            name = tk.StringVar(value=cell["name"] if cell else "")
            qty = tk.StringVar(value=str(cell["qty"]) if cell else "1")
            pos = f"r{cell['row'] + 1} c{cell['col'] + 1}" if cell and cell.get("row") is not None else "manual"
            row = {"cell": cell, "name": name, "qty": qty, "deleted": False}
            widgets = [ttk.Label(body, text=pos, width=8),
                       ttk.Entry(body, textvariable=name, width=46),
                       ttk.Entry(body, textvariable=qty, width=5)]

            def remove():
                row["deleted"] = True
                for w_ in widgets + [btn]:
                    w_.grid_remove()
            btn = ttk.Button(body, text="Remove", width=8, command=remove)
            for col, w_ in enumerate(widgets + [btn]):
                w_.grid(row=i, column=col, padx=3, pady=1)
            rows.append(row)

        for c in entry["cells"]:
            add_row(c)

        def apply():
            new_cells = []
            for row in rows:
                if row["deleted"]:
                    continue
                name = " ".join(row["name"].get().split())
                if not name:
                    continue
                try:
                    qty = max(1, int(row["qty"].get()))
                except ValueError:
                    return messagebox.showerror("Quantity", f"'{row['qty'].get()}' is not a whole number.", parent=win)
                cell = dict(row["cell"]) if row["cell"] else {"row": None, "col": None, "raw_ocr": "", "flags": []}
                if row["cell"] and name != cell["name"]:
                    self.names.teach(cell.get("raw_ocr", ""), name)
                if row["cell"] and (name != cell["name"] or qty != cell["qty"]):
                    cell["flags"] = []
                cell["name"], cell["qty"] = name, qty
                new_cells.append(cell)
            self.store.set_cells(eid, new_cells)
            win.destroy()
            self.refresh()

        buttons = ttk.Frame(host)
        buttons.pack(pady=(0, 8))
        ttk.Button(buttons, text="Add row", command=add_row).pack(side="left", padx=4)
        ttk.Button(buttons, text="Apply", command=apply).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="left", padx=4)
        skin.fit(win)

    def show_where(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        item, total = self.tree.item(sel[0])["values"]
        lines = [f"{label}: {qty}" for label, qty in self.store.where_is(str(item))]
        messagebox.showinfo(str(item), f"Total {total}\n\n" + "\n".join(lines), parent=self.root)

    # -- export ------------------------------------------------------------
    def _export_text(self, kind):
        s = self.store
        where = s.locations()
        if kind == "clipboard":
            return export.to_clipboard(s.to_result(), where)
        if kind == "cabinets.csv":
            return export.to_csv_by_cabinet(s)
        if kind == "json":
            return export.to_json_list(s)
        return export.FORMATS[kind](s.to_result(), where)

    def export_clipboard(self):
        if not self.store.entries():
            return self.status.set("Nothing to export yet")
        self.root.clipboard_clear()
        self.root.clipboard_append(self._export_text("clipboard"))
        self.status.set(f"Copied '{self.store.active}' to clipboard")

    def export_file(self, kind):
        if not self.store.entries():
            return self.status.set("Nothing to export yet")
        self.export_dir.mkdir(parents=True, exist_ok=True)
        ext = kind.split(".")[-1]
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self.store.active).strip().replace(" ", "_")
        suffix = "_by_cabinet" if kind == "cabinets.csv" else ""
        initial = export.default_filename(ext).replace("cabinet_", f"{safe}{suffix}_", 1)
        path = filedialog.asksaveasfilename(parent=self.root, initialdir=self.export_dir, defaultextension=f".{ext}",
                                            initialfile=initial)
        if path:
            Path(path).write_text(self._export_text(kind), encoding="utf-8")
            self.status.set(f"Saved {Path(path).name}")

    # -- sets --------------------------------------------------------------
    def open_sets(self):
        """Window showing which rares the active list can complete (SPEC 15)."""
        if self.sets_refresh and getattr(self, "sets_win", None) and self.sets_win.winfo_exists():
            self.sets_win.lift()
            return
        win, host = self._window("Sets", "1240x640+30+50", minsize=(760, 320))
        self.sets_win = win
        items = sets.load()
        state = {"shown": []}

        bar = ttk.Frame(host)
        bar.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(bar, text="Show:").pack(side="left")
        show_var = tk.StringVar(value="in progress")
        ttk.Combobox(bar, textvariable=show_var, state="readonly", width=18, values=list(sets.FILTERS)).pack(
            side="left", padx=(2, 12))
        ttk.Label(bar, text="Search:").pack(side="left")
        search_var = tk.StringVar()
        ttk.Entry(bar, textvariable=search_var, width=22).pack(side="left", padx=(2, 12))
        summary = tk.StringVar()
        ttk.Label(host, textvariable=summary, justify="left").pack(fill="x", padx=10)

        frame = ttk.Frame(host)
        frame.pack(fill="both", expand=True, padx=8, pady=6)
        cols = ("item", "group", "status", "have", "missing", "where")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c, text, w, anc in (("item", "Item", 200, "w"), ("group", "Category", 190, "w"), ("status", "Status", 110, "w"),
                                ("have", "Have", 50, "center"), ("missing", "Missing", 200, "w"),
                                ("where", "Where", 440, "w")):
            tree.heading(c, text=text)
            tree.column(c, width=w, anchor=anc, stretch=(c == "where"))
        tree.tag_configure("done", **skin.TAGS["done"])
        tree.tag_configure("near", **skin.TAGS["near"])
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        def refresh():
            statuses, unknown = sets.analyze(self.store.locations(), items)
            state["shown"] = sets.select(statuses, show_var.get(), search_var.get())
            win.title(f"Sets - list '{self.store.active}'")
            tree.delete(*tree.get_children())
            for i, st in enumerate(state["shown"]):
                tag = ("done",) if not st.missing else (("near",) if len(st.missing) == 1 else ())
                tree.insert("", "end", iid=str(i), tags=tag, values=(
                    st.name, st.group, st.status, st.have_text, ", ".join(sets.ABBREV[p] for p in st.missing),
                    st.where_text()))
            done = sum(1 for st in statuses if not st.missing)
            one = sum(1 for st in statuses if len(st.missing) == 1 and st.held)
            text = (f"{done} complete, {one} missing one part, {sum(1 for st in statuses if st.held)} in progress "
                    f"of {len(statuses)} rares. Showing {len(state['shown'])}.")
            if unknown:
                text += f"\nParts of items not in the database: {', '.join(unknown[:6])}{'...' if len(unknown) > 6 else ''}"
            summary.set(text)

        def detail(_e=None):
            sel = tree.selection()
            if not sel:
                return
            d, dhost = self._window("Parts", minsize=(300, 160), parent=win)
            txt = tk.Text(dhost, width=78, height=12, font=("Consolas", 10), bg=skin.FIELD, fg=skin.TEXT,
                          insertbackground=skin.MINT, bd=0, highlightthickness=0)
            txt.insert("1.0", sets.detail(state["shown"][int(sel[0])]))
            txt.configure(state="disabled")
            txt.pack(padx=8, pady=8)
            skin.fit(d)

        def copy():
            win.clipboard_clear()
            win.clipboard_append(sets.to_clipboard(state["shown"]))
            summary.set(summary.get().split("\n")[0] + "  Copied.")

        def save_csv():
            self.export_dir.mkdir(parents=True, exist_ok=True)
            path = filedialog.asksaveasfilename(parent=win, initialdir=self.export_dir, defaultextension=".csv",
                                                initialfile=f"sets_{self.store.active.replace(' ', '_')}.csv")
            if path:
                Path(path).write_text(sets.to_csv(state["shown"]), encoding="utf-8")

        ttk.Button(bar, text="Refresh", command=refresh).pack(side="left")
        ttk.Button(bar, text="Copy", command=copy).pack(side="left", padx=4)
        ttk.Button(bar, text="Save CSV", command=save_csv).pack(side="left")
        show_var.trace_add("write", lambda *_: refresh())
        search_var.trace_add("write", lambda *_: refresh())
        tree.bind("<Double-1>", detail)

        def closed(_e=None):
            self.sets_refresh = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", closed)
        self.sets_refresh = refresh
        refresh()

    def _check_hotkeys(self):
        if self.hotkeys.failed:
            self.status.set(f"Hotkey {', '.join(self.hotkeys.failed)} is taken (is the app open twice?). "
                            "Use the Scan button instead.")

    def close(self):
        """Closing during a scan stops it first, so the mouse is put back and nothing keeps moving it."""
        self.closing = True
        if self.busy and getattr(self, "scan_thread", None):
            self.scanner.request_abort()
            self.scan_thread.join(timeout=5)
        self.hotkeys.stop()
        self.root.destroy()

    def run(self):
        ocr.configure(self.cfg["tesseract_path"])
        if not ocr.available():
            messagebox.showwarning("Tesseract missing", f"Install Tesseract OCR from {ocr.INSTALL_URL}")
        self.root.mainloop()


def main():
    App().run()
