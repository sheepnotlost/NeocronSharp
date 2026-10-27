"""Research workflow with fresh visual localization on every cycle and before Start."""

from datetime import datetime, timezone
import json
from pathlib import Path

from macro_core import Interrupted, ResearchRunner, STACKS
from vision import Ambiguous, Detector, NotFound, cv2


class VisualRunner(ResearchRunner):
    def __init__(self, *args, detector=None, diagnostic_dir=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.detector = detector if detector is not None else Detector()
        self.input_index = 1
        self.last_frame = None
        self.diagnostic_dir = Path(diagnostic_dir) if diagnostic_dir is not None else Path(__file__).parent / "diagnostics"

    def frame(self):
        self.guard()
        frame = self.backend.capture()
        self.guard()
        self.last_frame = frame
        return frame

    def save_failure(self, error):
        # This is the last frame captured from the bound, focused game client.
        # Do not capture the desktop or another application after focus loss.
        if self.last_frame is None or not hasattr(self.last_frame, "shape"):
            return None
        try:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            path = self.diagnostic_dir / "latest.png"
            if not cv2.imwrite(str(path), cv2.cvtColor(self.last_frame, cv2.COLOR_RGB2BGR)):
                return None
            metadata = {"saved_at_utc": datetime.now(timezone.utc).isoformat(),
                        "error": str(error), "completed_cycles": self.completed,
                        "frame_size": list(self.last_frame.shape[:2][::-1]),
                        "processor_scale": self.detector.last_scale if hasattr(self.detector, "last_scale") else None}
            (self.diagnostic_dir / "latest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            return path
        except (OSError, cv2.error):
            return None

    def processor_state(self):
        # A disappearing or obscured Processor must never count as an empty input.
        last_error = None
        for attempt in range(8):
            self.checkpoint(safe_pause=True)
            frame = self.frame()
            try:
                return frame, self.detector.processor(frame, checkpoint=self.guard)
            except NotFound as exc:
                last_error = exc
                if attempt == 0:
                    shape = getattr(frame, "shape", None)
                    size = f" in the {shape[1]}x{shape[0]} game view" if shape else ""
                    self.emit("status", f"Looking for the Processor{size}. "
                              "Open it fully, uncovered and inside the game window.")
                self.wait(0.25, safe_pause=True)
        raise Interrupted(f"{last_error} No stale coordinates were used.")

    def find_cycle(self, name):
        last_error = None
        self.emit("status", f"{name}: finding Processor and Inventory in the current game image.")
        for attempt in range(8):
            self.checkpoint(safe_pause=True)
            frame = self.frame()
            try:
                if self.detector.quantity(frame, checkpoint=self.guard) is not None:
                    raise Ambiguous("A quantity dialog is already open. Resolve the pending transfer first.")
                processor = self.detector.processor(frame, checkpoint=self.guard)
                self.input_index = self.detector.empty_input(frame, processor)
                if attempt == 0:
                    self.emit("status", f"{name}: Processor found; locating Inventory and the source stack.")
                stacks = self.detector.stacks(frame, checkpoint=self.guard)
                candidates = stacks[name]
                if len(candidates) > 1:
                    raise Ambiguous(f"Multiple {name} stacks are visible. Keep one visible source stack per type.")
                if not candidates:
                    raise NotFound(f"Visible {name} stack not found in Inventory.")
                self.emit("detected", {"processor": [processor.x, processor.y],
                                       "scale": processor.scale, "stacks": stacks})
                return candidates[0], self.detector.input_point(processor, self.input_index)
            except NotFound as exc:
                last_error = exc
                self.wait(0.25, safe_pause=True)
        raise Interrupted(f"{last_error} No stale coordinates were used.")

    def transfer_visual(self, name, available):
        source, destination = self.find_cycle(name)
        self.emit("status", f"{name}: Processor located; transferring one part.")
        self.drag(source, destination)
        self.move((24, 80))
        elapsed = 0.0
        dialog = None
        while elapsed < self.settings["dialog_timeout"]:
            dialog = self.detector.quantity(self.frame(), checkpoint=self.guard)
            if dialog:
                break
            self.wait(0.1)
            elapsed += 0.1
        if dialog:
            self.emit("status", "Quantity dialog found; checking that the quantity is one.")
            if not dialog.get("one"):
                self.click(dialog["field"])
                self.type_one()
                self.move((24, 80))
                self.wait(self.settings["settle_seconds"])
            dialog = self.detector.quantity(self.frame(), checkpoint=self.guard)
            if dialog is None:
                raise Interrupted("Quantity dialog disappeared before confirmation. Batch stopped.")
            if not dialog.get("one"):
                raise Interrupted("Could not verify quantity 1. The dialog was left open; no research was started.")
            self.click(dialog["ok"])
            self.move((24, 80))
            self.wait(self.settings["settle_seconds"])
            if self.detector.quantity(self.frame(), checkpoint=self.guard) is not None:
                raise Interrupted("Quantity dialog did not close. No research was started.")
        elif available > 1:
            raise Interrupted("Expected quantity dialog was not detected. No research was started.")
        # Reacquire the Processor: the dialog and Processor can be in new locations.
        frame, processor = self.processor_state()
        if not self.detector.occupied(frame, processor, self.input_index):
            raise Interrupted("No part recognized in the input slot. No research was started.")
        self.click(processor.start_point())
        self.move((24, 80))

    def await_visual(self, name):
        empty_samples = 0
        while True:
            self.checkpoint(safe_pause=True)
            frame, processor = self.processor_state()
            if self.detector.quantity(frame, checkpoint=self.guard) is not None:
                raise Interrupted("Unexpected quantity dialog during research.")
            empty_samples = empty_samples+1 if not self.detector.occupied(frame, processor, self.input_index) else 0
            if empty_samples >= 3:
                return
            self.wait(0.2, safe_pause=True)

    def execute(self):
        for name in STACKS:
            row = self.profile["stacks"][name]
            for _ in range(row["count"]):
                self.transfer_visual(name, row["available"])
                self.emit("status", f"{name}: researching; tracking the Processor visually.")
                self.await_visual(name)
                row["available"] -= 1
                row["count"] -= 1
                self.completed += 1
                self.emit("cycle", {"stack": name, "available": row["available"],
                                    "count": row["count"], "completed": self.completed})
        self.emit("done", f"Finished {self.completed} cycles. Final result remains in the Processor.")

    def run(self):
        try:
            self.guard()
            self.execute()
        except Exception as exc:
            diagnostic = self.save_failure(exc)
            if diagnostic is not None:
                self.emit("status", f"Last game frame saved locally: {diagnostic}")
            self.emit("error", f"{exc} Completed cycles: {self.completed}. Check the current item and counts before restarting.")
        finally:
            self.backend.release_all()


class BlueprintRunner(VisualRunner):
    """Only click Start; observe a full processing-to-result transition per copy."""

    def blueprint_state(self):
        frame, processor = self.processor_state()
        if self.detector.quantity(frame, checkpoint=self.guard) is not None:
            raise Interrupted("A quantity dialog is open. Prepare the blueprint research inputs first.")
        state = self.detector.blueprint_state(frame, processor)
        self.emit("detected", {"processor": [processor.x, processor.y],
                               "scale": processor.scale, "stacks": {}})
        return processor, state

    def await_blueprint(self, seen_busy=False):
        idle_samples = 0
        while True:
            _, state = self.blueprint_state()
            if state["busy"]:
                seen_busy = True
                idle_samples = 0
            elif seen_busy:
                idle_samples += 1
                if idle_samples >= 3:
                    if not state["result"]:
                        raise Interrupted("Research ended without a visible blueprint result. Check the Processor before restarting.")
                    return
            self.wait(.05, safe_pause=True)

    def execute(self):
        target = self.profile["blueprints"]["count"]
        while target == 0 or self.completed < target:
            self.emit("status", "Blueprint: finding the Processor and checking its progress.")
            processor, state = self.blueprint_state()
            if state["busy"]:
                # Adopt an existing run rather than clicking Start while it is processing.
                self.emit("status", "Blueprint: research in progress; monitoring for completion.")
                self.await_blueprint(seen_busy=True)
            else:
                # Completion already has three idle observations. Re-verify the
                # current location once before clicking, without an extra idle wait.
                self.click(processor.start_point())
                self.move((24, 80))
                self.emit("status", "Blueprint: Start clicked; waiting for progress and a new blueprint result.")
                self.await_blueprint()
            self.completed += 1
            remaining = max(0, target - self.completed) if target else 0
            self.emit("blueprint_cycle", {"completed": self.completed,
                                          "count": remaining, "continuous": target == 0})
        self.emit("done", f"Finished {self.completed} blueprint copies. Final result remains in the Processor.")
