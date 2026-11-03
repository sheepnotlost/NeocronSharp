"""TL 60 Job Loop, a sub-tab of Research: runs mission_runner.py for TL60 or TL130 jobs with its own buttons, not Start."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

import clients
import traversal_tab as tt
from macro_core import Control


HOW = ("Stand at the R.N. terminal in a faction headquarters with the crosshair on it, and keep the 3 blueprints the job "
       "asks for in Inventory. Finish any job already open first: taking a new one fails the old one and costs a fee.")


class JobsTab:
    def __init__(self, parent, root, other_live=lambda: False, mission_runner=None):
        self.root = root
        self.other_live = other_live        # a walk, follow, camera or hunt is steering the same mouse
        self.mission_runner = mission_runner  # makes a MissionRunner(emit, control) bound to the game
        self.control = None                 # the running loop's Control
        self.countdown = None               # its 5 s countdown
        self.job = "TL60"                   # which jobs it runs
        self.queue = queue.Queue()
        self.closed = False

        host = ttk.Frame(parent, padding=12)
        host.pack(fill="both", expand=True)
        host.columnconfigure(0, weight=1)
        host.rowconfigure(3, weight=1)
        self.how = tk.StringVar(value=HOW)
        ttk.Label(host, textvariable=self.how, wraplength=900).grid(row=0, column=0, sticky="ew")
        buttons = ttk.Frame(host)
        buttons.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.start_button = ttk.Button(buttons, text="Start TL60 job loop", command=lambda: self.start("TL60"))
        self.tl130_button = ttk.Button(buttons, text="Start TL130 job loop", command=lambda: self.start("TL130"))
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop)
        for button in (self.start_button, self.tl130_button, self.stop_button):
            button.pack(side="left", padx=(0, 6))
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(host, textvariable=self.status, font=("Segoe UI", 11, "bold"), wraplength=900).grid(
            row=2, column=0, sticky="ew", pady=(8, 4))
        logs = ttk.Frame(host)
        logs.grid(row=3, column=0, sticky="nsew")
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log = tk.Text(logs, height=5, wrap="word", state="disabled", font=("Consolas", 9), relief="flat", padx=6, pady=4)
        self.log.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(logs, orient="vertical", command=self.log.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=bar.set)
        self.update_buttons()
        self._after = self.root.after(100, self.poll)

    def steering(self):
        return self.control is not None

    def update_buttons(self):
        for button in (self.start_button, self.tl130_button):
            button.configure(state="normal" if self.mission_runner and not self.steering() else "disabled")
        self.stop_button.configure(state="normal" if self.steering() else "disabled")

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def say(self, text):
        self.status.set(text)
        self.append(text)

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                self.event(*self.queue.get_nowait())
        except queue.Empty:
            pass
        self._after = self.root.after(100, self.poll)

    def event(self, kind, payload):
        if kind == "log":
            self.append(payload)
        elif kind == "status":
            self.say(payload)
        elif kind == "built":
            self.built(payload)
        elif kind == "done":
            self.say(payload)
            self.control = None
            self.update_buttons()

    def start(self, job="TL60"):
        if self.steering():
            return
        self.job = job
        if self.other_live():
            self.say("A walk, follow, camera or hunt is running. Stop it first.")
            return
        self.control = Control()
        self.say(f"{job} jobs start in 5 s: stand at the terminal with the crosshair on it.")
        self.update_buttons()
        self.countdown = self.root.after(5000, self.begin)

    def begin(self):
        """A fresh download has no traversal.exe yet: only the Traversal and Target Acquisition tabs built it."""
        self.countdown = None
        threading.Thread(target=lambda: self.queue.put(("built", tt.build_tool(lambda text: self.queue.put(("log", text))))),
                         daemon=True, name="jobs-build").start()

    def built(self, problem):
        if problem or self.control.stopped.is_set():
            self.event("done", problem or "Job loop stopped.")
            return
        try:
            clients.focus()         # no need to have clicked into the game in time
            runner = self.mission_runner(lambda kind, payload: self.queue.put((kind, payload)), self.control, self.job)
            threading.Thread(target=runner.run, daemon=True, name="jobs").start()
        except Exception as exc:
            self.event("done", f"The job loop could not start: {exc}")

    def stop(self):
        if self.control is None:
            return
        self.control.stopped.set()
        if self.countdown is not None:
            self.root.after_cancel(self.countdown)
            self.countdown = None
            self.event("done", "Job loop stopped.")

    def close(self):
        self.closed = True
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass
        self.stop()
