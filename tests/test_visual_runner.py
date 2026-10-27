import unittest
import json
from pathlib import Path
import tempfile

from macro_core import Control, Interrupted
from test_macro import FakeBackend, FakeClock, ready_profile
from vision import Ambiguous, Anchor, NotFound, cv2, np
from vision_runner import VisualRunner


class VisualBackend(FakeBackend):
    def __init__(self, profile, clock):
        super().__init__(profile, clock)
        self.processor = Anchor(300, 400, 1, .99)
        self.relocations = 0
        self.hidden = False
        self.multiple_stack = False
        self.ambiguous_processor = False
        self.shift_dialog_on_type = False
        self.quantity_value = 1
        self.refuse_quantity_edit = False
        self.sync_positions()

    def sync_positions(self):
        points = self.profile["points"]
        points["input"] = self.processor.point(102.5, 88)
        points["start"] = self.processor.point(421, 174)
        points["quantity_field"] = self.processor.point(184, 40)
        points["quantity_ok"] = self.processor.point(293, 40)

    def update(self):
        was_processing = self.finish_at is not None
        super().update()
        if was_processing and self.finish_at is None:
            self.relocations += 1
            self.processor = Anchor(100+self.relocations*190, 150+self.relocations*70, 1, .99)
            self.sync_positions()

    def capture(self):
        self.update()
        return {"processor": self.processor, "loaded": self.loaded, "dialog": self.dialog,
                "points": {k: v[:] for k, v in self.profile["points"].items()},
                "hidden": self.hidden, "multiple": self.multiple_stack,
                "ambiguous": self.ambiguous_processor, "quantity_value": self.quantity_value}

    def key(self, name, down):
        super().key(name, down)
        if name == "1" and down and not self.refuse_quantity_edit:
            self.quantity_value = 1
        if name == "1" and down and self.shift_dialog_on_type:
            self.profile["points"]["quantity_field"] = [1200, 500]
            self.profile["points"]["quantity_ok"] = [1300, 500]


class FakeDetector:
    def processor(self, frame, checkpoint=lambda: None):
        checkpoint()
        if frame["hidden"]:
            raise NotFound("Processor window not found")
        if frame["ambiguous"]:
            raise Ambiguous("Multiple possible processor windows")
        return frame["processor"]

    def empty_input(self, frame, processor):
        if frame["loaded"]:
            raise Ambiguous("Processor already contains a part")
        return 1

    def stacks(self, frame, checkpoint=lambda: None):
        checkpoint()
        result = {name: [frame["points"][name]] for name in "TEAL"}
        if frame["multiple"]:
            result["T"].append([1000, 900])
        return result

    def quantity(self, frame, checkpoint=lambda: None):
        checkpoint()
        return ({"field": frame["points"]["quantity_field"], "ok": frame["points"]["quantity_ok"],
                 "one": frame["quantity_value"] == 1}
                if frame["dialog"] else None)

    def occupied(self, frame, processor, index):
        return frame["loaded"]

    def input_point(self, processor, index):
        return processor.point(102.5, 88)


class VisualRunnerTests(unittest.TestCase):
    def setup_run(self, counts=None):
        self.profile = ready_profile(counts or {"T": 2})
        self.profile["settings"]["positioning"] = "visual"
        self.clock = FakeClock()
        self.backend = VisualBackend(self.profile, self.clock)
        self.control = Control()
        self.messages = []
        self.runner = VisualRunner(self.profile, self.backend, self.control,
                                   lambda k, v: self.messages.append((k, v)),
                                   self.clock.clock, self.clock.sleep, detector=FakeDetector())

    def errors(self):
        return [p for k, p in self.messages if k == "error"]

    def test_relocates_processor_between_every_run_and_handles_all_four_stacks(self):
        self.setup_run({"T": 2, "E": 1, "A": 1, "L": 1})
        self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.backend.starts, ["T", "T", "E", "A", "L"])
        self.assertEqual(self.backend.relocations, 5)
        self.assertEqual(self.backend.returned_results, 4)
        self.assertTrue(self.backend.output)
        positions = [p["processor"] for k, p in self.messages if k == "detected"]
        self.assertEqual(len(set(tuple(p) for p in positions)), 5)

    def test_hidden_processor_during_research_is_not_false_completion(self):
        self.setup_run()
        self.clock.on_sleep = lambda: setattr(self.backend, "hidden", True) if self.backend.starts else None
        self.runner.run()
        self.assertIn("No stale coordinates", self.errors()[0])
        self.assertEqual(self.runner.completed, 0)
        self.assertEqual(self.backend.starts, ["T"])

    def test_ambiguous_window_prevents_all_input(self):
        self.setup_run()
        self.backend.ambiguous_processor = True
        self.runner.run()
        self.assertTrue(self.errors())
        self.assertFalse(self.backend.events)

    def test_duplicate_source_stack_prevents_all_input(self):
        self.setup_run()
        self.backend.multiple_stack = True
        self.runner.run()
        self.assertIn("Multiple T stacks", self.errors()[0])
        self.assertFalse(self.backend.events)

    def test_dialog_relocated_after_typing_is_found_before_ok(self):
        self.setup_run()
        self.backend.quantity_value = 2
        self.backend.shift_dialog_on_type = True
        self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.runner.completed, 2)

    def test_default_one_is_confirmed_without_retyping(self):
        self.setup_run()
        self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.runner.completed, 2)
        self.assertNotIn(("1", True), self.backend.events)

    def test_unverified_quantity_never_confirms_or_starts(self):
        self.setup_run()
        self.backend.quantity_value = 11
        self.backend.refuse_quantity_edit = True
        self.runner.run()
        self.assertIn("Could not verify quantity 1", self.errors()[0])
        self.assertTrue(self.backend.dialog)
        self.assertFalse(self.backend.starts)

    def test_research_length_varies_without_any_fixed_research_limit(self):
        self.setup_run({"T": 1, "E": 1, "A": 1, "L": 1})
        durations = {"T": .8, "E": 8, "A": 70, "L": 240}
        def update_duration():
            # Set the next part's duration before its Start click.
            if self.backend.loaded_stack and self.backend.finish_at is None:
                self.backend.duration = durations[self.backend.loaded_stack]
        self.clock.on_sleep = update_duration
        self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.runner.completed, 4)
        self.assertGreater(self.clock.now, 300)

    def test_stop_while_monitoring_still_works(self):
        self.setup_run()
        self.backend.duration = 999
        self.clock.on_sleep = lambda: self.control.stopped.set() if self.clock.now > 15 else None
        self.runner.run()
        self.assertIn("Stopped", self.errors()[0])
        self.assertEqual(self.runner.completed, 0)

    def test_focus_loss_while_monitoring_stops_without_resuming_or_next_transfer(self):
        self.setup_run()
        self.backend.duration = 999
        events_at_focus_loss = []
        def lose_focus():
            if self.backend.starts and self.backend.focus:
                events_at_focus_loss.extend(self.backend.events)
                self.backend.focus = False
        self.clock.on_sleep = lose_focus
        self.runner.run()
        self.assertIn("Game lost focus", self.errors()[0])
        self.assertEqual(self.runner.completed, 0)
        self.assertEqual(self.backend.starts, ["T"])
        self.assertEqual(self.backend.events, events_at_focus_loss)
        self.assertFalse(self.backend.buttons)
        self.assertFalse(self.backend.keys)

    def test_focus_loss_before_detection_prevents_all_input(self):
        self.setup_run()
        self.backend.focus = False
        self.runner.run()
        self.assertIn("Game lost focus", self.errors()[0])
        self.assertFalse(self.backend.events)

    def test_failure_diagnostic_uses_the_last_game_frame_without_recapturing(self):
        self.setup_run()
        with tempfile.TemporaryDirectory() as folder:
            self.runner.diagnostic_dir = Path(folder)
            self.runner.last_frame = np.full((40, 60, 3), (25, 80, 130), dtype=np.uint8)
            path = self.runner.save_failure(NotFound("Inventory window not found"))
            self.assertIsNotNone(path)
            image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            self.assertEqual(image[0, 0].tolist(), [25, 80, 130])
            metadata = json.loads((Path(folder) / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["frame_size"], [60, 40])
            self.assertIn("Inventory", metadata["error"])

    def test_stop_during_visual_search_sends_no_input(self):
        self.setup_run()
        self.control.stopped.set()
        self.runner.run()
        self.assertTrue(self.errors())
        self.assertFalse(self.backend.events)


if __name__ == "__main__":
    unittest.main()
