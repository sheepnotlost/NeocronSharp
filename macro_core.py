"""Research sequence and configuration. Importing this module sends no input."""

from copy import deepcopy
import json
import math
from pathlib import Path
import threading
import time
from recipes import RECIPES, catalog

STACKS = ("T", "E", "A", "L")
POINTS = (*STACKS, "input", "start", "quantity_field", "quantity_ok")
SAMPLE_OFFSETS = tuple((x, y) for y in range(-12, 13, 4) for x in range(-12, 13, 4))


def default_profile():
    return {
        "version": 1,
        "client_size": None,
        "points": {},
        "samples": {},
        "operation": "tech_parts",
        "research_operation": "tech_parts",
        "blueprints": {"count": 1},
        "construction": {"recipe": "weaponpart_7", "available": 10000, "count": 0, "count_slots":False},
        "custom_recipes": {},
        "hidden_recipes": [],
        "materials": {},
        "recycling": {"recipe":None},
        "preferences": {"skin":"basic","stop_sound":False},
        "stacks": {name: {"available": 0, "count": 0} for name in STACKS},
        "settings": {
            "positioning": "visual",
            "drag_button": "left", "drag_modifier": "none",
            "drag_seconds": 0.4, "settle_seconds": 0.35,
            "dialog_timeout": 3.0,
            "color_tolerance": 30, "changed_pixels": 5,
        },
    }


def validate_profile(profile, require_ready=True):
    if not isinstance(profile, dict) or profile.get("version") != 1:
        raise ValueError("Unsupported profile format.")
    operation = profile.get("operation", "tech_parts")
    if operation not in ("tech_parts", "blueprints", "construction", "recycling"):
        raise ValueError("Choose research or construction.")
    preferences=profile.get("preferences",{})
    from appearance import SKINS
    if not isinstance(preferences,dict) or preferences.get("skin","basic") not in SKINS or type(preferences.get("stop_sound",False)) is not bool:
        raise ValueError("Choose a valid skin and optional stop sound setting.")
    recycling=profile.get("recycling",{"recipe":None})
    if not isinstance(recycling,dict):raise ValueError("Invalid recycling selection.")
    if recycling.get("recipe") is not None:
        from recycling import load_catalog
        if recycling["recipe"] not in {r["id"] for r in load_catalog()["recipes"]}:
            raise ValueError("Choose a recycling recipe from the catalog.")
    if profile.get("research_operation", "tech_parts") not in ("tech_parts", "blueprints"):
        raise ValueError("Invalid research mode.")
    construction = profile.get("construction", {"recipe": "weaponpart_7", "available": 1, "count": 1})
    book=catalog(profile)
    if not isinstance(construction, dict) or (construction.get("recipe") is not None and construction.get("recipe") not in book):
        raise ValueError("Choose a supported construction recipe.")
    if type(construction.get("count_slots",False)) is not bool:
        raise ValueError("Slot counter must be enabled or disabled.")
    materials = profile.get("materials", {})
    if not isinstance(materials, dict) or len(materials) > 500:
        raise ValueError("Invalid materials list.")
    for key, row in materials.items():
        if (not isinstance(key, str) or not isinstance(row, dict) or len(row) > 12 or any(
                not isinstance(n, str) or not 1 <= len(n) <= 40 or not isinstance(c, str)
                or not 2 <= len(c) <= 4 for n, c in row.items())):
            raise ValueError("Invalid materials list.")
    if type(construction.get("gogo_refill",False)) is not bool:
        raise ValueError("GoGuardian refills must be enabled or disabled.")
    if construction.get("search_mode","fast") not in ("fast","all_cells"):
        raise ValueError("Choose Fast datacubes or Thorough every-cell inventory search.")
    minimum=construction.get("stop_at_slots")
    if minimum is not None and (type(minimum) is not int or not 0<=minimum<=5):
        raise ValueError("Choose a slot stopping threshold from 0 to 5, or disable it.")
    for key in ("available", "count"):
        if type(construction.get(key)) is not int or not 0 <= construction[key] <= 10000:
            raise ValueError(f"Construction {key} must be an integer from 0 to 10000.")
    blueprints = profile.get("blueprints", {"count": 1})
    if (not isinstance(blueprints, dict) or type(blueprints.get("count")) is not int
            or not 0 <= blueprints["count"] <= 10000):
        raise ValueError("Blueprint count must be an integer from 0 to 10000; zero repeats until stopped.")
    size = profile.get("client_size")
    if size is not None and (not isinstance(size, list) or len(size) != 2
                             or any(type(n) is not int or n < 100 for n in size)):
        raise ValueError("Invalid calibrated game size.")
    stacks = profile.get("stacks", {})
    if not isinstance(stacks, dict):
        raise ValueError("Invalid stack configuration.")
    enabled = []
    for name in STACKS:
        row = stacks.get(name, {})
        if not isinstance(row, dict):
            raise ValueError(f"Invalid configuration for {name}.")
        for key in ("available", "count"):
            n = row.get(key)
            if type(n) is not int or not 0 <= n <= 10000:
                raise ValueError(f"{name}: {key} must be an integer from 0 to 10000.")
        if row["count"] > row["available"]:
            raise ValueError(f"{name}: requested count exceeds the available stack size.")
        if row["count"]:
            enabled.append(name)
    settings = profile.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("Invalid sequence settings.")
    if settings.get("positioning", "visual") not in ("visual", "manual"):
        raise ValueError("Invalid positioning mode.")
    if settings.get("drag_button") not in ("left", "right"):
        raise ValueError("Drag button must be left or right.")
    if settings.get("drag_modifier") not in ("none", "shift", "ctrl"):
        raise ValueError("Drag modifier must be none, shift, or ctrl.")
    for key, low, high in (
        ("drag_seconds", 0.1, 5), ("settle_seconds", 0.1, 5),
        ("dialog_timeout", 0.5, 15),
    ):
        check_number(settings.get(key), low, high, key)
    for key, high in (("color_tolerance", 255), ("changed_pixels", len(SAMPLE_OFFSETS))):
        n = settings.get(key)
        if type(n) is not int or not 1 <= n <= high:
            raise ValueError(f"Invalid {key}.")
    points = profile.get("points", {})
    samples = profile.get("samples", {})
    if not isinstance(points, dict) or not isinstance(samples, dict):
        raise ValueError("Invalid calibration data.")
    for name, point in points.items():
        if name not in POINTS or not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"Invalid point: {name}.")
        if size is None or any(type(n) is not int for n in point):
            raise ValueError(f"Invalid coordinates: {name}.")
        if not (12 <= point[0] < size[0] - 12 and 12 <= point[1] < size[1] - 12):
            raise ValueError(f"{name} must be at least 12 pixels inside the game client.")
    for name, sample in samples.items():
        if name not in ("input", "quantity_ok") or not isinstance(sample, list):
            raise ValueError("Invalid reference sample.")
        if len(sample) != len(SAMPLE_OFFSETS) or any(type(c) is not int or not 0 <= c <= 0xFFFFFF for c in sample):
            raise ValueError(f"Invalid reference pixels for {name}.")
    if require_ready:
        if operation == "recycling":
            if recycling.get("recipe") is None:raise ValueError("Choose a recycling recipe first.")
            return profile
        if operation == "construction":
            if construction.get("recipe") is None:raise ValueError("Choose or add a construction recipe first.")
            if settings.get("positioning", "visual") != "visual":
                raise ValueError("Construction requires automatic visual detection.")
            if construction["available"] < 1:
                raise ValueError("Enter the actual number of blueprints in the construction stack.")
            if construction["count"] > construction["available"]:
                raise ValueError("Requested builds exceed the available blueprint stack.")
            return profile
        if operation == "blueprints":
            if settings.get("positioning", "visual") != "visual":
                raise ValueError("Blueprint research requires automatic visual detection.")
            return profile
        if not enabled:
            raise ValueError("Set a research count greater than zero for at least one stack.")
        if settings.get("positioning", "visual") == "visual":
            return profile
        if size is None:
            raise ValueError("Bind the game and calibrate its controls first.")
        for name in (*enabled, "input", "start", "quantity_field", "quantity_ok"):
            if name not in points:
                raise ValueError(f"Capture the {name} position first.")
        for name in ("input", "quantity_ok"):
            if name not in samples:
                raise ValueError(f"Capture the {name} reference first.")
    return profile


def check_number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be a number between {low} and {high}.")


def monitor_only_profile(profile):
    profile = deepcopy(profile)
    if isinstance(profile, dict):
        profile.setdefault("operation", "tech_parts")
        profile.setdefault("blueprints", {"count": 1})
        profile.setdefault("research_operation", profile["operation"] if profile["operation"] in ("tech_parts", "blueprints") else "tech_parts")
        profile.setdefault("construction", {"recipe": "weaponpart_7", "available": 1, "count": 1})
        profile.setdefault("custom_recipes", {})
        profile.setdefault("hidden_recipes", [])
        profile.setdefault("materials", {})
        profile.setdefault("recycling", {"recipe":None})
        profile.setdefault("preferences", {"skin":"basic","stop_sound":False})
        profile.pop("favorites", None)  # Favorites were removed; drop old shortcuts.
        stacks = profile.get("stacks")
        if isinstance(stacks, dict):
            for row in stacks.values():
                if isinstance(row, dict):
                    row.pop("seconds", None)
        settings = profile.get("settings")
        if isinstance(settings, dict):
            for key in ("mode", "research_timeout", "minimum_research_seconds"):
                settings.pop(key, None)
    return profile


def save_profile(path, profile):
    profile = monitor_only_profile(profile)
    validate_profile(profile, require_ready=False)
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_profile(path):
    profile = monitor_only_profile(json.loads(Path(path).read_text(encoding="utf-8")))
    return validate_profile(profile, require_ready=False)


def samples_match(actual, reference, tolerance, changed_limit):
    if len(actual) != len(reference):
        return False
    changed = sum(
        max(abs(((a >> shift) & 255) - ((b >> shift) & 255)) for shift in (0, 8, 16)) > tolerance
        for a, b in zip(actual, reference)
    )
    return changed < changed_limit


class Interrupted(RuntimeError):
    pass


class Control:
    def __init__(self):
        self.stopped = threading.Event()
        self.paused = threading.Event()

    def toggle_pause(self):
        if self.paused.is_set():
            self.paused.clear()
        else:
            self.paused.set()


class ResearchRunner:
    def __init__(self, profile, backend, control, emit=lambda *args: None,
                 clock=time.monotonic, sleep=time.sleep):
        validate_profile(profile)
        self.profile = monitor_only_profile(profile)
        self.backend = backend
        self.control = control
        self.emit = emit
        self.clock = clock
        self.sleep = sleep
        self.settings = self.profile["settings"]
        self.points = self.profile["points"]
        self.completed = 0

    def guard(self):
        if self.control.stopped.is_set():
            raise Interrupted("Stopped. Check the current item before restarting.")
        self.backend.check_focus(self.profile["client_size"])

    def checkpoint(self, safe_pause=False):
        self.guard()
        if self.control.paused.is_set():
            if not safe_pause:
                raise Interrupted("Paused during item transfer. Batch stopped; restore the UI and counts before restarting.")
            self.emit("status", "Paused.")
            while self.control.paused.is_set():
                self.guard()
                self.sleep(0.02)
            self.emit("status", "Resumed.")

    def wait(self, seconds, safe_pause=False):
        remaining = seconds
        while remaining > 0.000001:
            self.checkpoint(safe_pause)
            start = self.clock()
            self.sleep(min(0.02, remaining))
            remaining -= max(0, self.clock() - start)

    def sample_matches(self, name):
        self.guard()
        actual = self.backend.sample(self.points[name])
        return samples_match(actual, self.profile["samples"][name],
                             self.settings["color_tolerance"], self.settings["changed_pixels"])

    def move(self, point):
        self.checkpoint()
        self.backend.move(point)

    def click(self, point):
        self.move(point)
        self.checkpoint()
        self.backend.button("left", True)
        try:
            self.wait(0.06)
        finally:
            self.backend.button("left", False)

    def drag(self, source, destination):
        button = self.settings["drag_button"]
        modifier = self.settings["drag_modifier"]
        self.move(source)
        try:
            if modifier != "none":
                self.checkpoint()
                self.backend.key(modifier, True)
            self.checkpoint()
            self.backend.button(button, True)
            self.wait(0.12)
            for step in range(1, 17):
                self.move(tuple(round(source[i] + (destination[i] - source[i]) * step / 16) for i in (0, 1)))
                self.wait(self.settings["drag_seconds"] / 16)
        finally:
            self.backend.release_all()
        self.wait(self.settings["settle_seconds"])

    def type_one(self):
        try:
            self.checkpoint()
            self.backend.key("ctrl", True)
            self.checkpoint()
            self.backend.key("a", True)
            self.wait(0.05)
            self.backend.key("a", False)
            self.backend.key("ctrl", False)
            # Live (26 Oct): Ctrl+A did not replace a default "55" in the
            # split dialog and the typed 1 produced "551". Clear the field
            # on both sides of the caret as well, then type the 1.
            for name in ("backspace", "delete"):
                for _ in range(6):
                    self.checkpoint()
                    self.backend.key(name, True)
                    self.wait(0.02)
                    self.backend.key(name, False)
            self.checkpoint()
            self.backend.key("1", True)
            self.wait(0.05)
        finally:
            self.backend.release_all()

    def type_number(self, number):
        """Replace a quantity field's content with a positive integer (same clearing as type_one)."""
        digits = str(int(number))
        try:
            self.checkpoint()
            self.backend.key("ctrl", True)
            self.checkpoint()
            self.backend.key("a", True)
            self.wait(0.05)
            self.backend.key("a", False)
            self.backend.key("ctrl", False)
            for name in ("backspace", "delete"):
                for _ in range(6):
                    self.checkpoint()
                    self.backend.key(name, True)
                    self.wait(0.02)
                    self.backend.key(name, False)
            for digit in digits:
                self.checkpoint()
                self.backend.key(digit, True)
                self.wait(0.05)
                self.backend.key(digit, False)
                self.wait(0.03)
        finally:
            self.backend.release_all()

    def transfer_one(self, name, available):
        if not self.sample_matches("input"):
            raise Interrupted("Processor input is not empty. Clear it before starting a batch.")
        self.drag(self.points[name], self.points["input"])
        # Move away from all sampled controls so the game cursor cannot cover a reference.
        self.move((24, 80))
        elapsed = 0.0
        dialog_seen = False
        while elapsed < self.settings["dialog_timeout"]:
            if self.sample_matches("quantity_ok"):
                dialog_seen = True
                break
            self.wait(0.1)
            elapsed += 0.1
        if dialog_seen:
            self.click(self.points["quantity_field"])
            self.type_one()
            self.click(self.points["quantity_ok"])
            self.move((24, 80))
            self.wait(self.settings["settle_seconds"])
            if self.sample_matches("quantity_ok"):
                raise Interrupted("Quantity dialog did not close. No research was started.")
        elif available > 1:
            raise Interrupted("Expected quantity dialog was not detected. Check the transfer and calibration.")
        # A stack containing a single item may transfer without a split dialog.
        if self.sample_matches("input"):
            raise Interrupted("No loaded part detected in the Processor. No research was started.")

    def await_research(self, name):
        stable_empty = 0
        while True:
            self.checkpoint(safe_pause=True)
            stable_empty = stable_empty + 1 if self.sample_matches("input") else 0
            if stable_empty >= 3:
                return
            self.wait(0.2, safe_pause=True)

    def run(self):
        try:
            self.guard()
            for name in STACKS:
                row = self.profile["stacks"][name]
                for _ in range(row["count"]):
                    self.checkpoint(safe_pause=True)
                    self.emit("status", f"{name}: loading one part ({row['count']} requested remaining).")
                    self.transfer_one(name, row["available"])
                    self.click(self.points["start"])
                    self.move((24, 80))
                    self.emit("status", f"{name}: researching; switch away from Neocron to stop.")
                    self.await_research(name)
                    row["available"] -= 1
                    row["count"] -= 1
                    self.completed += 1
                    self.emit("cycle", {"stack": name, "available": row["available"],
                                        "count": row["count"], "completed": self.completed})
            self.emit("done", f"Finished {self.completed} cycles. The final result remains in the Processor.")
        except Exception as exc:
            self.emit("error", f"{exc} Completed cycles: {self.completed}. Check the current item and counts before restarting.")
        finally:
            self.backend.release_all()
