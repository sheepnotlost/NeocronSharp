"""Neocron research macro setup panel. Run with --check for input-free validation."""

import argparse
import ctypes
from copy import deepcopy
import logging
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from macro_core import (Control, STACKS, default_profile,
                        load_profile, save_profile, validate_profile)
from windows_backend import WindowsBackend
from recipes import RECIPES, catalog, find_recipe, add_recipe, remove_recipe
from recycling import load_catalog, filter_recipes
from appearance import SKINS, apply_skin, stop_sound
from construction_catalog import load_construction_catalog, filter_construction
import gogo

ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "profile.json"
OPERATION_LABELS = {"tech_parts": "Tech parts (T / E / A / L)", "blueprints": "Item → blueprint"}
SEARCH_LABELS={"fast":"Fast — datacube icons","all_cells":"Thorough — every cell"}


class App:
    def __init__(self, root, profile_path=PROFILE_PATH, backend=None):
        self.root = root
        self.backend = backend if backend is not None else WindowsBackend()
        self.profile_path = Path(profile_path)
        self.profile = default_profile()
        self.events = queue.Queue()
        self.worker = None
        self.control = None
        self.countdown = None
        self._stop_sound_played=False
        self.editable = []
        self.root.title("Neocron Macro Suite")
        self.root.iconbitmap(str(ROOT / "assets" / "research-tool.ico"))
        self.root.geometry("1040x840")
        self.root.minsize(960, 800)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        load_error = None
        if self.profile_path.exists():
            try:
                self.profile = load_profile(self.profile_path)
            except (ValueError, OSError, TypeError) as exc:
                load_error = str(exc)
        self.profile["settings"]["positioning"] = "visual"
        # Drag controls are not options; never keep an older right/modifier drag.
        self.profile["settings"]["drag_button"] = "left"
        self.profile["settings"]["drag_modifier"] = "none"
        self.profile["points"] = {}
        self.profile["samples"] = {}
        self.recipes=catalog(self.profile)
        self.recycle_data=load_catalog()
        self.build_catalog_data=load_construction_catalog()
        self.build_ui()
        self.populate()
        apply_skin(self.root,self.profile.get("preferences",{}).get("skin","basic"),self.heading)
        if load_error:
            self.report("Could not load profile: " + load_error)
        self.root.after(30, self.poll)

    def build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f5")
        style.configure("TLabel", background="#f3f5f5", foreground="#192c2d", font=("Segoe UI", 10))
        style.configure("TLabelframe", background="#f3f5f5")
        style.configure("TLabelframe.Label", background="#f3f5f5", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        self.heading=ttk.Label(outer, text="Neocron Macro Suite", font=("Segoe UI", 22, "bold"))
        self.heading.grid(row=0, column=0, sticky="w")
        self.bound = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.bound).grid(row=2, column=0, sticky="w", pady=(0, 12))

        self.main_split = tk.PanedWindow(outer, orient="vertical", sashwidth=9,
                                        sashrelief="raised", showhandle=True,
                                        handlesize=12, opaqueresize=True, borderwidth=0)
        self.main_split.grid(row=3, column=0, sticky="nsew")
        workspace = ttk.Frame(self.main_split)
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)
        self.main_split.add(workspace, minsize=250, stretch="always")
        self.tabs = ttk.Notebook(workspace)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.research_tab = ttk.Frame(self.tabs)
        self.construction_tab = ttk.Frame(self.tabs)
        self.recycling_tab = ttk.Frame(self.tabs)
        self.navray_tab = ttk.Frame(self.tabs)
        self.counter_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.research_tab, text="Research")
        self.tabs.add(self.construction_tab, text="Construction")
        self.tabs.add(self.recycling_tab, text="Recycling")
        self.tabs.add(self.navray_tab, text="Nav-Ray")
        self.tabs.add(self.counter_tab, text="Tech Counter")
        scroll_host = ttk.Frame(self.research_tab)
        scroll_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, background="#f3f5f5", highlightthickness=0, height=420)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        columns = ttk.Frame(canvas)
        content_window = canvas.create_window((0, 0), window=columns, anchor="nw")
        columns.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        def scroll_wheel(event):
            widget = event.widget
            while widget is not None:
                if widget in (columns, canvas):
                    canvas.yview_scroll(-int(event.delta / 120), "units")
                    return
                widget = getattr(widget, "master", None)
        self.root.bind("<MouseWheel>", scroll_wheel)
        columns.columnconfigure(0, weight=1)
        left = ttk.Frame(columns)
        left.grid(row=0, column=0, sticky="nsew")

        mode = ttk.LabelFrame(left, text="Research", padding=12)
        mode.pack(fill="x", pady=(0, 14))
        self.operation_var = tk.StringVar()
        mode_choice = ttk.Combobox(mode, textvariable=self.operation_var,
                                  values=list(OPERATION_LABELS.values()), state="readonly", width=30)
        mode_choice.pack(anchor="w", fill="x")
        mode_choice.bind("<<ComboboxSelected>>", lambda event: self.update_mode())
        self.editable.append(mode_choice)

        stacks = self.stacks_frame = ttk.LabelFrame(left, text="Stacks", padding=12)
        stacks.pack(fill="x")
        for col, title in enumerate(("Stack", "Available", "Research", "Position")):
            ttk.Label(stacks, text=title).grid(row=0, column=col, padx=5, pady=(0, 8), sticky="w")
        self.rows = {}
        self.position_labels = {}
        for row, name in enumerate(STACKS, start=1):
            ttk.Label(stacks, text=name, font=("Segoe UI", 11, "bold")).grid(row=row, column=0, padx=5)
            variables = {key: tk.StringVar() for key in ("available", "count")}
            self.rows[name] = variables
            for col, key in enumerate(("available", "count"), start=1):
                entry = ttk.Entry(stacks, textvariable=variables[key], width=9)
                entry.grid(row=row, column=col, padx=5, pady=4)
                self.editable.append(entry)
            var = tk.StringVar()
            self.position_labels[name] = var
            ttk.Label(stacks, textvariable=var, width=12).grid(row=row, column=3, padx=5)
        ttk.Label(stacks, text="0 skips a stack").grid(row=5, column=0, columnspan=4, sticky="w", pady=(9, 0))

        self.blueprint_frame = ttk.LabelFrame(left, text="Blueprint copies", padding=12)
        self.blueprint_count = tk.StringVar(value="1")
        ttk.Label(self.blueprint_frame, text="Copies per batch").grid(row=0, column=0, sticky="w")
        copies = ttk.Entry(self.blueprint_frame, textvariable=self.blueprint_count, width=10)
        copies.grid(row=0, column=1, padx=10, sticky="w")
        self.editable.append(copies)
        ttk.Label(self.blueprint_frame, text="0 repeats until stopped").grid(
                      row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.processor_position = tk.StringVar(value="")
        self.detection_frame = None

        actions = ttk.Frame(workspace)
        actions.grid(row=1, column=0, sticky="ew", pady=(16, 8))
        self.start_button = ttk.Button(actions, text="Start in 3 seconds", command=self.start)
        self.start_button.pack(side="left")
        self.editable.append(self.start_button)
        self.stop_sound_var=tk.BooleanVar(value=self.profile.get("preferences",{}).get("stop_sound",False))
        sound=ttk.Checkbutton(actions,text="Sound when stopped",variable=self.stop_sound_var,command=self.save_preferences)
        sound.pack(side="right",padx=(12,0));self.editable.append(sound)
        self.skin_var=tk.StringVar(value=SKINS[self.profile.get("preferences",{}).get("skin","basic")]["name"])
        skin=ttk.Combobox(actions,textvariable=self.skin_var,values=[s["name"] for s in SKINS.values()],state="readonly",width=22)
        skin.pack(side="right",padx=6);skin.bind("<<ComboboxSelected>>",lambda e:self.save_preferences());self.editable.append(skin)
        ttk.Label(actions,text="Skin").pack(side="right")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(workspace, textvariable=self.status, wraplength=980, font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="ew", pady=6)
        self.log_panel = ttk.Frame(self.main_split)
        self.log_panel.columnconfigure(0, weight=1)
        self.log_panel.rowconfigure(1, weight=1)
        self.main_split.add(self.log_panel, minsize=70, height=120, stretch="never")
        ttk.Label(self.log_panel, text="Log").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(2, 4))
        self.log = tk.Text(self.log_panel, height=5, wrap="word", state="disabled", font=("Consolas", 9),
                           background="#e6eceb", relief="flat", padx=8, pady=6)
        self.log.grid(row=1, column=0, sticky="nsew")
        self.log_scrollbar = ttk.Scrollbar(self.log_panel, orient="vertical", command=self.log.yview)
        self.log_scrollbar.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=self.log_scrollbar.set)
        self.build_construction_tab()
        self.build_recycling_tab()
        self.build_navray_tab()
        from tech_counter import TechCounterPanel
        self.counter = TechCounterPanel(self, self.counter_tab, self.profile_path.parent / "tech-counter")
        self.install_responsive_text()
        self.tabs.bind("<<NotebookTabChanged>>",lambda e:self.sync_start_button())

    def install_responsive_text(self):
        """Wrap paragraphs to their allocated width, including after skin changes.

        Fixed wrap lengths also made labels impose large minimum column sizes.
        Let the geometry manager allocate width, then calculate line wrapping
        from that actual width so a narrower pane cannot hide the line ending.
        """
        self.responsive_labels=[]
        def resize(event):
            label=event.widget
            if event.width<=8:
                return  # Hidden/new widgets have no usable width yet.
            width=max(1,event.width-4)
            if round(float(label.cget("wraplength")))!=width:
                label.configure(wraplength=width)
        def walk(widget):
            if isinstance(widget,ttk.Label) and float(widget.cget("wraplength") or 0)>0:
                widget.configure(width=1,anchor="w",justify="left")
                manager=widget.winfo_manager()
                if manager=="grid":
                    info=widget.grid_info()
                    first=int(info.get("column",0))
                    span=int(info.get("columnspan",1))
                    parent=widget.nametowidget(str(info["in"]))
                    # Sticky alone cannot stretch text in an unweighted grid.
                    # Give a spanned column the remaining panel width.
                    if not any(parent.columnconfigure(col)["weight"] for col in range(first,first+span)):
                        parent.columnconfigure(first+span-1,weight=1)
                    sticky=info.get("sticky","")
                    widget.grid_configure(sticky="".join(c for c in "nsew" if c in sticky or c in "ew"))
                elif manager=="pack":
                    side=widget.pack_info().get("side","top")
                    widget.pack_configure(fill="x",**({"expand":True} if side in ("left","right") else {}))
                widget.bind("<Configure>",resize,add="+")
                self.responsive_labels.append(widget)
            for child in widget.winfo_children():walk(child)
        walk(self.root)

    def build_navray_tab(self):
        host=ttk.Frame(self.navray_tab,padding=12);host.pack(fill="both",expand=True)
        host.columnconfigure(1,weight=1)
        ttk.Label(host,text="Destination").grid(row=0,column=0,sticky="w",pady=5)
        self.navray_destination=tk.StringVar()
        entry=ttk.Entry(host,textvariable=self.navray_destination,width=1)
        entry.grid(row=0,column=1,sticky="ew",padx=(10,0),pady=5);self.editable.append(entry)
        ttk.Label(host,text="Category > Destination. Open Nav-Ray first.").grid(row=1,column=1,sticky="w",padx=(10,0))

    def build_recycling_tab(self):
        host=ttk.Frame(self.recycling_tab,padding=12);host.pack(fill="both",expand=True)
        host.columnconfigure(0,weight=3);host.columnconfigure(1,weight=2);host.rowconfigure(1,weight=1)
        filters=ttk.Frame(host);filters.grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,10))
        ttk.Label(filters,text="Find item / ingredient").pack(side="left")
        self.recycle_query=tk.StringVar()
        query=ttk.Entry(filters,textvariable=self.recycle_query,width=24);query.pack(side="left",padx=8)
        self.recycle_category=tk.StringVar(value="All")
        categories=["All"]+sorted({r["category"] for r in self.recycle_data["recipes"]})
        category=ttk.Combobox(filters,textvariable=self.recycle_category,values=categories,state="readonly",width=22)
        category.pack(side="left");self.editable.extend((query,category))
        self.recycle_count=tk.StringVar()
        ttk.Label(filters,textvariable=self.recycle_count).pack(side="left",padx=10)
        table=ttk.Frame(host);table.grid(row=1,column=0,sticky="nsew",padx=(0,14));table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        self.recycle_tree=ttk.Treeview(table,columns=("tl","category"),selectmode="browse",height=15)
        self.recycle_tree.heading("#0",text="Result item");self.recycle_tree.column("#0",width=270,minwidth=150)
        self.recycle_tree.heading("tl",text="TL");self.recycle_tree.column("tl",width=40,stretch=False)
        self.recycle_tree.heading("category",text="Category");self.recycle_tree.column("category",width=120,minwidth=80)
        self.recycle_tree.grid(row=0,column=0,sticky="nsew")
        scroll=ttk.Scrollbar(table,orient="vertical",command=self.recycle_tree.yview);scroll.grid(row=0,column=1,sticky="ns")
        self.recycle_tree.configure(yscrollcommand=scroll.set)
        self.recycle_tree.bind("<<TreeviewSelect>>",lambda e:self.show_recycle_recipe())
        self.recycle_tree.bind("<Button-1>",lambda e:"break" if self.locked() else None)
        detail_host=ttk.Frame(host);detail_host.grid(row=1,column=1,sticky="nsew")
        detail_canvas=tk.Canvas(detail_host,background="#f3f5f5",highlightthickness=0)
        detail_scroll=ttk.Scrollbar(detail_host,orient="vertical",command=detail_canvas.yview)
        detail_scroll.pack(side="right",fill="y");detail_canvas.pack(side="left",fill="both",expand=True)
        detail_canvas.configure(yscrollcommand=detail_scroll.set)
        details=ttk.Frame(detail_canvas)
        detail_window=detail_canvas.create_window((0,0),window=details,anchor="nw")
        details.bind("<Configure>",lambda e:detail_canvas.configure(scrollregion=detail_canvas.bbox("all")))
        detail_canvas.bind("<Configure>",lambda e:detail_canvas.itemconfigure(detail_window,width=e.width))
        self.recycle_description=tk.StringVar()
        ttk.Label(details,textvariable=self.recycle_description,wraplength=340,justify="left").pack(anchor="nw")
        source=ttk.Button(details,text="Open recipe source",command=self.open_recycle_source)
        source.pack(anchor="w",pady=(10,14));self.editable.append(source)
        self.recycle_query.trace_add("write",lambda *args:self.filter_recycling())
        self.recycle_category.trace_add("write",lambda *args:self.filter_recycling())
        self.filter_recycling()

    def filter_recycling(self):
        old=self.recycle_tree.selection()
        self.recycle_tree.delete(*self.recycle_tree.get_children())
        rows=filter_recipes(self.recycle_data["recipes"],self.recycle_query.get(),self.recycle_category.get())
        for row in rows:
            name=row["name"]+(" [legacy]" if row.get("verification") else "")
            self.recycle_tree.insert("","end",iid=row["id"],text=name,values=(row["tech_level"] or "—",row["category"]))
        self.recycle_count.set(f"{len(rows)} / {len(self.recycle_data['recipes'])} recipes")
        if rows:self.recycle_tree.selection_set(old[0] if old and any(r["id"]==old[0] for r in rows) else rows[0]["id"])
        self.show_recycle_recipe()

    def show_recycle_recipe(self):
        selection=self.recycle_tree.selection()
        row=next((r for r in self.recycle_data["recipes"] if selection and r["id"]==selection[0]),None)
        if row is None:self.recycle_description.set("No matching recipe.");return
        text=row["name"]+"\n"+row["category"]+f" · TL {row['tech_level'] if row['tech_level'] is not None else 'not listed'}\n\nIngredients:\n"
        text+="\n".join(f"{p['quantity']} × {p['name']}" for p in row["ingredients"])
        if row["requirements"]:text+="\n\nItem requirements: "+row["requirements"]
        self.recycle_description.set(text)

    def open_recycle_source(self):
        selection=self.recycle_tree.selection()
        row=next((r for r in self.recycle_data["recipes"] if selection and r["id"]==selection[0]),None)
        if row:
            import webbrowser
            webbrowser.open(row["source_url"])

    def save_preferences(self):
        key=next(k for k,v in SKINS.items() if v["name"]==self.skin_var.get())
        self.profile["preferences"]={"skin":key,"stop_sound":self.stop_sound_var.get()}
        apply_skin(self.root,key,self.heading)
        try:save_profile(self.profile_path,self.profile)
        except (ValueError,OSError) as exc:self.report("Could not save preferences: "+str(exc))

    def notify_stop(self):
        if self._stop_sound_played:return
        self._stop_sound_played=True
        stop_sound(self.stop_sound_var.get())

    def build_construction_tab(self):
        self.construction_pages=ttk.Notebook(self.construction_tab)
        self.construction_pages.pack(fill="both",expand=True)
        self.construction_job=ttk.Frame(self.construction_pages)
        self.construction_catalog_tab=ttk.Frame(self.construction_pages)
        self.construction_pages.add(self.construction_job,text="Job")
        self.construction_pages.add(self.construction_catalog_tab,text="Catalog")
        canvas=tk.Canvas(self.construction_job,background="#f3f5f5",highlightthickness=0)
        scrollbar=ttk.Scrollbar(self.construction_job,orient="vertical",command=canvas.yview)
        scrollbar.pack(side="right",fill="y")
        canvas.pack(side="left",fill="both",expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        body=ttk.Frame(canvas,padding=12)
        content=canvas.create_window((0,0),window=body,anchor="nw")
        body.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(content,width=e.width))
        def scroll(event):
            widget=event.widget
            while widget is not None:
                if widget in (body,canvas):
                    canvas.yview_scroll(-int(event.delta/120),"units")
                    return
                widget=getattr(widget,"master",None)
        self.root.bind("<MouseWheel>",scroll,add="+")
        body.columnconfigure(0,weight=1)
        form=ttk.LabelFrame(body,text="Construction job",padding=12)
        form.grid(row=0,column=0,sticky="new")
        form.columnconfigure(1,weight=1)
        self.construction_recipe=tk.StringVar()
        self.construction_available=tk.StringVar(value="1")
        self.construction_count=tk.StringVar(value="0")
        for row,label in ((0,"Recipe"),(2,"Build this batch")):
            ttk.Label(form,text=label).grid(row=row,column=0,sticky="w",pady=5)
        choice=self.construction_choice=ttk.Combobox(form,textvariable=self.construction_recipe,
                            values=[r["name"] for r in self.recipes.values()],state="normal",width=1)
        choice.grid(row=0,column=1,sticky="ew",padx=(10,0))
        choice.bind("<<ComboboxSelected>>",lambda event:self.select_recipe())
        choice.bind("<FocusOut>",lambda event:self.refresh_recipe())
        self.editable.append(choice)
        for row,var in ((2,self.construction_count),):
            entry=ttk.Entry(form,textvariable=var,width=10)
            entry.grid(row=row,column=1,sticky="w",padx=(10,0),pady=5)
            self.editable.append(entry)
        ttk.Label(form,text="0 = until blueprints run out").grid(row=3,column=1,sticky="w",padx=(10,0))
        self.recipe_description=tk.StringVar()
        self.recipe_aliases=tk.StringVar()  # kept for saved recipes; no longer shown
        self.materials_text=tk.StringVar()
        ttk.Label(form,text="Materials").grid(row=5,column=0,sticky="w",pady=(8,4))
        materials=ttk.Entry(form,textvariable=self.materials_text,width=1)
        materials.grid(row=5,column=1,sticky="ew",padx=(10,0),pady=(8,4));self.editable.append(materials)
        ttk.Label(form,text="Name=LABEL, ...  (for GoGuardian)").grid(row=4,column=1,sticky="w",padx=(10,0))
        save=ttk.Button(form,text="Add / update recipe",command=self.save_custom_recipe)
        actions=ttk.Frame(form);actions.grid(row=6,column=0,columnspan=2,sticky="ew",pady=4)
        save.grid(in_=actions,row=0,column=0,sticky="w")
        self.editable.append(save)
        remove=self.remove_recipe_button=ttk.Button(form,text="Remove recipe",command=self.remove_job_recipe)
        remove.grid(in_=actions,row=0,column=1,sticky="w",padx=8);self.editable.append(remove)
        self.gogo_refill=tk.BooleanVar(value=False)
        gogo_check=ttk.Checkbutton(form,text="More Materials in GoGo",variable=self.gogo_refill)
        gogo_check.grid(row=7,column=0,columnspan=2,sticky="w",pady=(12,0));self.editable.append(gogo_check)
        ttk.Label(form,text="Keep GoGuardian open").grid(row=8,column=0,columnspan=2,sticky="w",pady=(2,0))
        self.count_slots=tk.BooleanVar(value=False)
        counter=ttk.Checkbutton(form,text="Count slots on constructed weapons / spells",variable=self.count_slots)
        counter.grid(row=9,column=0,columnspan=2,sticky="w",pady=(12,0))
        self.editable.append(counter)
        self.slot_summary=tk.StringVar(value="")
        ttk.Label(form,textvariable=self.slot_summary,wraplength=485).grid(row=10,column=0,columnspan=2,sticky="w",pady=(4,0))
        stop_row=ttk.Frame(form)
        stop_row.grid(row=11,column=0,columnspan=2,sticky="ew",pady=(8,0))
        self.stop_on_slots=tk.BooleanVar(value=False)
        self.minimum_slots=tk.StringVar(value="4")
        stop_check=ttk.Checkbutton(stop_row,text="Stop at",variable=self.stop_on_slots,
                                 command=lambda:self.count_slots.set(True) if self.stop_on_slots.get() else None)
        stop_check.pack(side="left")
        stop_value=ttk.Combobox(stop_row,textvariable=self.minimum_slots,values=list(range(6)),state="readonly",width=3)
        stop_value.pack(side="left",padx=6)
        ttk.Label(stop_row,text="or more slots").pack(side="left")
        self.editable.extend((stop_check,stop_value))
        settings=ttk.LabelFrame(body,text="Search",padding=12)
        settings.grid(row=1,column=0,sticky="new",pady=(12,0))
        settings.columnconfigure(1,weight=1)
        self.search_mode=tk.StringVar(value=SEARCH_LABELS["fast"])
        ttk.Label(settings,text="Inventory search").grid(row=0,column=0,sticky="w",pady=4)
        search=ttk.Combobox(settings,textvariable=self.search_mode,values=list(SEARCH_LABELS.values()),state="readonly",width=1)
        search.grid(row=0,column=1,padx=10,pady=4,sticky="ew");self.editable.append(search)
        self.build_construction_catalog()

    def refresh_recipe(self):
        try:key=find_recipe(self.construction_recipe.get(),self.recipes)
        except ValueError:key=None
        recipe=self.recipes.get(key)
        if recipe:
            self.recipe_description.set((f"{recipe['category']} · Item tech level {recipe['level']}\n"
                                        +"Ingredients (handled by the game):\n"+", ".join(recipe["ingredients"]))
                                       if recipe.get("level") is not None else
                                       "Custom recipe · ingredients are handled by Neocron. Completion is verified by the result's tooltip name.")
        else:
            self.recipe_description.set("New recipe · enter the item's name or shorthand. It is saved when you add it or start the batch.")

    def scroll_body(self,parent):
        canvas=tk.Canvas(parent,background="#f3f5f5",highlightthickness=0)
        scroll=ttk.Scrollbar(parent,orient="vertical",command=canvas.yview)
        scroll.pack(side="right",fill="y");canvas.pack(side="left",fill="both",expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        body=ttk.Frame(canvas,padding=10);window=canvas.create_window((0,0),window=body,anchor="nw")
        body.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window,width=e.width))
        def wheel(event):
            widget=event.widget
            while widget is not None:
                if widget in (body,canvas):canvas.yview_scroll(-int(event.delta/120),"units");return
                widget=getattr(widget,"master",None)
        self.root.bind("<MouseWheel>",wheel,add="+")
        return body

    def build_construction_catalog(self):
        host=ttk.Frame(self.construction_catalog_tab,padding=12);host.pack(fill="both",expand=True)
        host.columnconfigure(0,weight=3);host.columnconfigure(1,weight=2);host.rowconfigure(1,weight=1)
        filters=ttk.Frame(host);filters.grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,10))
        ttk.Label(filters,text="Find item / material").pack(side="left")
        self.build_query=tk.StringVar();query=ttk.Entry(filters,textvariable=self.build_query,width=24)
        query.pack(side="left",padx=8)
        self.build_category=tk.StringVar(value="All")
        category=ttk.Combobox(filters,textvariable=self.build_category,state="readonly",width=22,
                              values=["All"]+sorted({r["category"] for r in self.build_catalog_data["recipes"]}))
        category.pack(side="left");self.editable.extend((query,category))
        self.build_count=tk.StringVar();ttk.Label(filters,textvariable=self.build_count).pack(side="left",padx=10)
        table=ttk.Frame(host);table.grid(row=1,column=0,sticky="nsew",padx=(0,12));table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
        self.build_tree=ttk.Treeview(table,columns=("tl","method"),selectmode="browse")
        self.build_tree.heading("#0",text="Item");self.build_tree.column("#0",width=280,minwidth=170)
        self.build_tree.heading("tl",text="TL");self.build_tree.column("tl",width=40,stretch=False)
        self.build_tree.heading("method",text="Build method");self.build_tree.column("method",width=125,minwidth=100)
        self.build_tree.grid(row=0,column=0,sticky="nsew")
        scroll=ttk.Scrollbar(table,orient="vertical",command=self.build_tree.yview);scroll.grid(row=0,column=1,sticky="ns")
        self.build_tree.configure(yscrollcommand=scroll.set)
        self.build_tree.bind("<<TreeviewSelect>>",lambda e:self.show_build_recipe())
        self.build_tree.bind("<Double-1>",lambda e:self.use_build_recipe())
        self.build_tree.bind("<Button-1>",lambda e:"break" if self.locked() else None)
        right=ttk.Frame(host);right.grid(row=1,column=1,sticky="nsew")
        body=self.scroll_body(right)
        self.build_description=tk.StringVar()
        ttk.Label(body,textvariable=self.build_description,wraplength=330,justify="left").pack(anchor="w")
        self.use_build_button=ttk.Button(body,text="Use blueprint recipe",command=self.use_build_recipe)
        self.use_build_button.pack(anchor="w",pady=(12,5))
        source=ttk.Button(body,text="Open item source",command=self.open_build_source);source.pack(anchor="w",pady=5)
        self.editable.extend((self.use_build_button,source))
        self.build_query.trace_add("write",lambda *args:self.filter_build_catalog())
        self.build_category.trace_add("write",lambda *args:self.filter_build_catalog())
        self.construction_pages.bind("<<NotebookTabChanged>>",lambda e:self.sync_start_button())
        self.filter_build_catalog()

    def selected_build_recipe(self):
        selection=self.build_tree.selection()
        return next((r for r in self.build_catalog_data["recipes"] if selection and r["id"]==selection[0]),None)

    def filter_build_catalog(self):
        old=self.build_tree.selection();self.build_tree.delete(*self.build_tree.get_children())
        rows=filter_construction(self.build_catalog_data["recipes"],self.build_query.get(),self.build_category.get())
        labels={"verified_example":"Recorded example","check_blueprint":"Check blueprint","rare_parts":"Rare parts only","recycling_only":"Recycling entry"}
        for row in rows:self.build_tree.insert("","end",iid=row["id"],text=row["name"],values=(row["level"] if row["level"] is not None else "—",labels[row["method"]]))
        self.build_count.set(f"{len(rows)} / {len(self.build_catalog_data['recipes'])} items")
        if rows:self.build_tree.selection_set(old[0] if old and any(r["id"]==old[0] for r in rows) else rows[0]["id"])
        self.show_build_recipe()

    def show_build_recipe(self):
        row=self.selected_build_recipe()
        if row is None:self.build_description.set("No matching item.")
        else:
            materials="\n".join(row["ingredients"]) if row["ingredients"] else "Not published in the imported category listing. Read the actual blueprint in game."
            self.build_description.set(f"{row['name']}\n{row['category']} · TL {row['level'] if row['level'] is not None else '—'}"
                                       +(f"\n\n{materials}" if row["ingredients"] else ""))
        state="normal" if row and row["method"] in ("verified_example","check_blueprint") and not self.locked() else "disabled"
        self.use_build_button.configure(state=state)

    def store_build_recipe(self):
        row=self.selected_build_recipe()
        if not row or row["method"] not in ("verified_example","check_blueprint"):
            raise ValueError("Select an item supported by the blueprint workflow.")
        profile=deepcopy(self.profile)
        key=find_recipe(row["name"],catalog(profile))
        if key is None:key=add_recipe(profile,row["name"])
        save_profile(self.profile_path,profile);self.profile=profile;self.recipes=catalog(profile)
        self.construction_choice.configure(values=[r["name"] for r in self.recipes.values()])
        return key

    def load_construction_recipe(self,key):
        self.construction_recipe.set(self.recipes[key]["name"]);self.select_recipe()
        self.tabs.select(self.construction_tab);self.construction_pages.select(self.construction_job)
        self.sync_start_button();self.report("Loaded construction recipe: "+self.recipes[key]["name"]+". Check counts, then Start.")

    def use_build_recipe(self):
        if self.locked():return
        try:self.load_construction_recipe(self.store_build_recipe())
        except (ValueError,OSError) as exc:self.report(str(exc))

    def open_build_source(self):
        row=self.selected_build_recipe()
        if row:
            import webbrowser
            webbrowser.open(row["source_url"])

    def sync_start_button(self):
        if not hasattr(self,"start_button") or self.locked():return
        browser=self.tabs.select()==str(self.construction_tab) and self.construction_pages.select()==str(self.construction_catalog_tab)
        self.start_button.configure(state="disabled" if browser else "normal")

    def materials_for(self,key):
        """Saved or built-in labels, else the catalog's parts with guessed labels to correct."""
        known=gogo.ingredients_for(key,self.profile)
        if known:return gogo.format_materials(known)
        name=self.recipes.get(key,{}).get("name")
        row=next((r for r in self.build_catalog_data["recipes"] if r["name"]==name and r.get("parts")),None)
        return gogo.format_materials(gogo.materials_from_parts(row["parts"])) if row else ""

    def typed_aliases(self):
        """Aliases belong to a saved recipe; a newly typed name starts with none (the hidden
        field still holds the previous recipe's, which would clash with it)."""
        try:known=find_recipe(self.construction_recipe.get(),self.recipes)
        except ValueError:known=None
        return self.recipe_aliases.get().split(",") if known else []

    def select_recipe(self):
        key=find_recipe(self.construction_recipe.get(),self.recipes)
        self.recipe_aliases.set(", ".join(self.recipes[key].get("aliases",())) if key else "")
        self.materials_text.set(self.materials_for(key) if key else "")
        self.refresh_recipe()

    def save_custom_recipe(self):
        if self.locked():return
        try:
            profile=deepcopy(self.profile)
            key=add_recipe(profile,self.construction_recipe.get(),self.typed_aliases())
            profile["construction"]["recipe"]=key
            save_profile(self.profile_path,profile)
            self.profile=profile
            self.recipes=catalog(profile)
            self.construction_choice.configure(values=[r["name"] for r in self.recipes.values()])
            self.construction_recipe.set(self.recipes[key]["name"])
            self.refresh_recipe()
            self.report("Recipe saved: "+self.recipes[key]["name"])
        except (ValueError,OSError) as exc:self.report(str(exc))

    def remove_job_recipe(self):
        if self.locked():return
        try:
            profile=deepcopy(self.profile)
            key=find_recipe(self.construction_recipe.get(),catalog(profile))
            name=remove_recipe(profile,key)
            remaining=catalog(profile)
            selected=next(iter(remaining),None)
            profile["construction"]["recipe"]=selected
            save_profile(self.profile_path,profile)
            self.profile=profile;self.recipes=remaining
            self.construction_choice.configure(values=[r["name"] for r in remaining.values()])
            self.construction_recipe.set(remaining[selected]["name"] if selected else "")
            self.select_recipe()
            self.report(f"Removed {name} from Job. You can add it again by name or from Catalog.")
        except (ValueError,OSError) as exc:self.report(str(exc))

    def populate(self):
        for name, values in self.rows.items():
            for key, var in values.items():
                var.set(str(self.profile["stacks"][name][key]))
        operation=self.profile.get("operation", "tech_parts")
        self.operation_var.set(OPERATION_LABELS[operation if operation in OPERATION_LABELS else self.profile["research_operation"]])
        self.blueprint_count.set(str(self.profile.get("blueprints", {"count": 1})["count"]))
        construction=self.profile["construction"]
        selected=self.recipes.get(construction["recipe"],{})
        self.construction_recipe.set(selected.get("name",""))
        self.recipe_aliases.set(", ".join(selected.get("aliases",())))
        self.materials_text.set(self.materials_for(construction["recipe"]) if construction["recipe"] else "")
        self.construction_available.set(str(construction["available"]))
        self.construction_count.set(str(construction["count"]))
        self.search_mode.set(SEARCH_LABELS[construction.get("search_mode","fast")])
        self.count_slots.set(construction.get("count_slots",False))
        self.gogo_refill.set(construction.get("gogo_refill",False))
        self.stop_on_slots.set(construction.get("stop_at_slots") is not None)
        self.minimum_slots.set(str(construction.get("stop_at_slots") if construction.get("stop_at_slots") is not None else 4))
        self.refresh_recipe()
        self.navray_destination.set(self.profile.get("navray",{}).get("destination",""))
        self.tabs.select(self.navray_tab if operation=="navray" else self.recycling_tab if operation=="recycling" else self.construction_tab if operation=="construction" else self.research_tab)
        recycle_id=self.profile.get("recycling",{}).get("recipe")
        if recycle_id and self.recycle_tree.exists(recycle_id):
            self.recycle_tree.selection_set(recycle_id);self.recycle_tree.see(recycle_id);self.show_recycle_recipe()
        self.update_mode()
        self.refresh_positions()

    def update_mode(self):
        blueprint = self.operation_var.get() == OPERATION_LABELS["blueprints"]
        self.stacks_frame.pack_forget()
        self.blueprint_frame.pack_forget()
        (self.blueprint_frame if blueprint else self.stacks_frame).pack(fill="x")

    def refresh_positions(self):
        for name, var in self.position_labels.items():
            var.set("Auto detect")

    def collect(self):
        if self.tabs.select()==str(self.counter_tab):
            raise ValueError("Tech Counter uses its own scan settings. Click Start in 3 seconds to scan.")
        if self.tabs.select()==str(self.construction_tab) and self.construction_pages.select()==str(self.construction_catalog_tab):
            raise ValueError("Load a catalog item into its job tab before starting.")
        profile = deepcopy(self.profile)
        try:
            profile["research_operation"]=next(key for key,label in OPERATION_LABELS.items()
                                                if label==self.operation_var.get())
            if self.tabs.select()==str(self.navray_tab):
                profile["operation"]="navray"
                profile["navray"]={"destination":self.navray_destination.get().strip()}
            elif self.tabs.select()==str(self.recycling_tab):
                profile["operation"]="recycling"
                selection=self.recycle_tree.selection()
                profile["recycling"]={"recipe":selection[0] if selection else None}
            elif self.tabs.select()==str(self.construction_tab):
                profile["operation"]="construction"
                key=find_recipe(self.construction_recipe.get(),catalog(profile))
                if key is None:
                    key=add_recipe(profile,self.construction_recipe.get(),self.typed_aliases())
                typed=gogo.parse_materials(self.materials_text.get())
                if typed and typed!=(gogo.INGREDIENT_CODES.get(key) or {}):
                    profile.setdefault("materials",{})[key]=typed
                elif key in profile.get("materials",{}) and not typed:
                    profile["materials"].pop(key)
                profile["construction"]={"recipe":key,
                                         # The stack size is no longer asked for; 10000 means "unknown"
                                         # and the batch ends when no blueprint can be found.
                                         "available":10000,
                                         "count":int(self.construction_count.get()),
                                         "search_mode":next(k for k,v in SEARCH_LABELS.items() if v==self.search_mode.get()),
                                         "gogo_refill":self.gogo_refill.get(),
                                         "count_slots":self.count_slots.get() or self.stop_on_slots.get(),
                                         "stop_at_slots":int(self.minimum_slots.get()) if self.stop_on_slots.get() else None}
            else:
                profile["operation"] = next(key for key, label in OPERATION_LABELS.items()
                                            if label == self.operation_var.get())
                profile["research_operation"]=profile["operation"]
            if profile["operation"] == "blueprints":
                profile["blueprints"] = {"count": int(self.blueprint_count.get())}
            elif profile["operation"] == "tech_parts":
                for name, values in self.rows.items():
                    profile["stacks"][name] = {"available": int(values["available"].get()),
                                               "count": int(values["count"].get())}
            # Drag controls are no longer options: every recorded transfer is a
            # plain left drag. Reset any older saved right-button/modifier choice.
            profile["settings"]["drag_button"]="left"
            profile["settings"]["drag_modifier"]="none"
            profile["preferences"]={"skin":next(k for k,v in SKINS.items() if v["name"]==self.skin_var.get()),
                                    "stop_sound":self.stop_sound_var.get()}
        except ValueError as exc:
            if "invalid literal for int()" in str(exc) or "could not convert string to float" in str(exc):
                raise ValueError("Enter whole numbers for the stack and batch counts.") from None
            raise
        return validate_profile(profile, require_ready=False)

    def active(self):
        return self.worker is not None and self.worker.is_alive()

    def locked(self):
        return self.active() or self.countdown is not None

    def set_editing(self, enabled):
        self.counter.set_editing(enabled)
        for widget in self.editable:
            widget.configure(state=("readonly" if isinstance(widget, ttk.Combobox) and widget is not self.construction_choice else "normal")
                             if enabled else "disabled")
        selected=self.tabs.select()
        for tab in self.tabs.tabs():
            self.tabs.tab(tab,state="normal" if enabled or tab==selected else "disabled")
        page=self.construction_pages.select()
        for tab in self.construction_pages.tabs():
            self.construction_pages.tab(tab,state="normal" if enabled or tab==page else "disabled")
        if enabled:
            self.sync_start_button()
            self.show_build_recipe()

    def ensure_bound(self):
        title, size = self.backend.bind_foreground()
        if "neocron" not in title.lower():
            self.backend.hwnd = None
            raise ValueError("Focus Neocron before the countdown finishes.")
        self.profile["client_size"] = size
        self.profile["points"] = {}
        self.profile["samples"] = {}
        self.bound.set(f"Bound: {title}  ·  {size[0]} × {size[1]} client pixels")
        self.backend.check_focus(self.profile["client_size"])

    def show_detected(self, payload):
        x, y = payload["processor"]
        self.processor_position.set(f"Processor detected at {x}, {y} · template scale {payload['scale']:g}")
        for name, var in self.position_labels.items():
            candidates = payload["stacks"].get(name, [])
            var.set(f"{candidates[0][0]}, {candidates[0][1]}" if len(candidates) == 1
                    else "Ambiguous" if candidates else "Not visible")

    def start(self):
        if self.locked():
            return
        try:
            self._counter_job = self.tabs.select()==str(self.counter_tab)
            if self._counter_job:
                self.counter.prepare()
                self._stop_sound_played=False
                self.save_preferences()
                self.set_editing(False)
                self.begin_countdown(3)
                return
            profile = self.collect()
            validate_profile(profile)
            # Report a broken/copied bundle before starting the focus countdown.
            import vision_runner, construction_runner
            self.profile = profile
            self._stop_sound_played=False
            self.recipes=catalog(profile)
            self.construction_choice.configure(values=[r["name"] for r in self.recipes.values()])
            self.slot_summary.set("Slot totals: "+" · ".join(f"{i}: 0" for i in range(6))
                                  if self.count_slots.get() else "Slot counter off.")
            save_profile(self.profile_path, profile)
            self.set_editing(False)
            self.begin_countdown(3)
        except (ValueError, OSError, RuntimeError) as exc:
            self.report(str(exc))

    def begin_countdown(self, seconds):
        if seconds:
            self.report(f"Starting in {seconds} — focus Neocron. Switching away stops the batch.")
            self.countdown = self.root.after(1000, lambda: self.begin_countdown(seconds - 1))
            return
        self.countdown = None
        self.control = Control()
        try:
            from vision_runner import BlueprintRunner, VisualRunner
            from construction_runner import ConstructionRunner
            self.ensure_bound()
            if getattr(self,"_counter_job",False):
                self.worker = threading.Thread(target=self.counter.run_scan, args=(self.control,),
                                               daemon=False, name="tech-counter-scan")
                self.worker.start()
                return
            from recycling import RecyclingRunner
            from navray_runner import NavRayRunner
            runner_class = {"blueprints":BlueprintRunner,"tech_parts":VisualRunner,"construction":ConstructionRunner,
                            "recycling":RecyclingRunner,"navray":NavRayRunner}[self.profile["operation"]]
            runner = runner_class(self.profile, self.backend, self.control,
                                  lambda kind, payload: self.events.put((kind, payload)))
            self.worker = threading.Thread(target=runner.run, daemon=False, name="macro-sequence")
            self.worker.start()
        except (ValueError, RuntimeError) as exc:
            self.report(str(exc))
            if getattr(self,"_counter_job",False):self.counter.status.set(str(exc))
            self.notify_stop()
            self.set_editing(True)

    def cancel_work(self):
        if self.countdown is not None:
            self.root.after_cancel(self.countdown)
            self.countdown = None
            self.set_editing(True)
            self.report("Start cancelled.")
        if self.control is not None and self.active():
            self.control.stopped.set()
            self.control.paused.clear()
            self.report("Stopping before closing.")

    def report(self, message):
        self.status.set(message)
        logging.info(message)
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def poll(self):
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "counter_progress":
                self.counter.status.set("Scanning " + payload)
                self.status.set("Tech Counter: " + payload)
            elif kind == "counter_done":
                self.counter.finish_scan(*payload)
                self.report("Tech Counter: " + self.counter.status.get())
                self.notify_stop()
            elif kind == "counter_error":
                self.counter.fail_scan(payload)
                self.report("Tech Counter: " + payload)
                self.notify_stop()
            elif kind == "materials":
                self.profile.setdefault("materials",{})[payload["recipe"]]=payload["codes"]
                try:
                    if find_recipe(self.construction_recipe.get(),self.recipes)==payload["recipe"]:
                        self.materials_text.set(gogo.format_materials(payload["codes"]))
                except ValueError:pass
                try:save_profile(self.profile_path,self.profile)
                except (ValueError,OSError) as exc:self.report("Could not save material labels: "+str(exc))
            elif kind == "detected":
                self.show_detected(payload)
            elif kind == "blueprint_cycle":
                remaining = "repeating until stopped" if payload["continuous"] else f"{payload['count']} copies remaining"
                self.report(f"Blueprint: completed {payload['completed']}; {remaining}.")
            elif kind == "construction_cycle":
                self.construction_available.set(str(payload["available"]))
                self.profile["construction"]["available"]=payload["available"]
                self.report(f"{self.recipes[payload['recipe']]['name']}: completed {payload['completed']}; {payload['remaining']} builds remaining.")
                if "slot_counts" in payload:
                    self.slot_summary.set("Slot totals: "+" · ".join(f"{i}: {payload['slot_counts'].get(i,0)}" for i in range(6))
                                          +f" · unread: {payload['slot_unread']} · N/A: {payload['slot_na']}")
                try:
                    save_profile(self.profile_path,self.profile)
                except (ValueError,OSError) as exc:
                    self.report("Could not save remaining blueprints: "+str(exc))
            elif kind == "cycle":
                name = payload["stack"]
                for key in ("available", "count"):
                    self.rows[name][key].set(str(payload[key]))
                    self.profile["stacks"][name][key] = payload[key]
                self.report(f"{name}: completed cycle {payload['completed']}; {payload['count']} requested remaining.")
                try:
                    save_profile(self.profile_path, self.profile)
                except (ValueError, OSError) as exc:
                    self.report("Could not save remaining counts: " + str(exc))
            else:
                self.report(payload)
                if kind in ("done","error"):self.notify_stop()
        if self.worker is not None and not self.worker.is_alive():
            self.worker = None
            self.set_editing(True)
        self.root.after(30, self.poll)

    def close(self):
        self.cancel_work()
        if self.active():
            self.root.after(50, self.close)
            return
        self.backend.release_all()
        self.notify_stop()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate the saved profile without game input.")
    parser.add_argument("--smoke-ui", action="store_true", help="Build and close the UI without sending input.")
    args = parser.parse_args()
    if args.check:
        try:
            profile = load_profile(PROFILE_PATH)
            profile["settings"]["positioning"] = "visual"
            profile["points"] = {}
            profile["samples"] = {}
            validate_profile(profile)
            if profile["operation"] == "construction":
                job=profile["construction"]
                print(f"Configuration valid: {job['count'] or job['available']} builds of {catalog(profile)[job['recipe']]['name']}. No input sent.")
            elif profile["operation"]=="navray":
                print(f"Configuration valid: Nav-Ray walk to {profile['navray']['destination']}. No input sent.")
            elif profile["operation"]=="recycling":
                print("Configuration valid: one prepared recycling run. No input sent.")
            elif profile["operation"] == "blueprints":
                count = profile["blueprints"]["count"]
                print(f"Configuration valid: {count or 'continuous'} blueprint copies. No input sent.")
            else:
                total = sum(row["count"] for row in profile["stacks"].values())
                print(f"Configuration valid: {total} cycles in T/E/A/L order. No input sent.")
            return 0
        except (ValueError, OSError, TypeError) as exc:
            print(f"Configuration not ready: {exc}", file=sys.stderr)
            return 2
    logging.basicConfig(filename=ROOT / "macro.log", level=logging.INFO,
                        format="%(asctime)s %(message)s", encoding="utf-8")
    backend = WindowsBackend()  # Establish DPI awareness before Tk creates its window.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Neocron.MacroSuite")
    root = tk.Tk()
    try:
        app = App(root, backend=backend)
        if args.smoke_ui:
            root.withdraw()
            root.update_idletasks()
            app.collect()
            app.close()
            print("UI smoke check passed. No game input sent.")
        else:
            root.mainloop()
    except Exception as exc:
        logging.exception("Application startup failed")
        if not args.smoke_ui:
            messagebox.showerror("Neocron Macro Suite", str(exc), parent=root)
        else:
            print(str(exc), file=sys.stderr)
        root.destroy()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
