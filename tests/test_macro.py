from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from macro_core import (Control, Interrupted, POINTS, ResearchRunner, SAMPLE_OFFSETS,
                        STACKS, default_profile, load_profile, samples_match,
                        save_profile, validate_profile)

EMPTY = [0x204020] * len(SAMPLE_OFFSETS)
OCCUPIED = [0xB09060] * len(SAMPLE_OFFSETS)
DIALOG = [0x60D080] * len(SAMPLE_OFFSETS)


def ready_profile(counts=None):
    profile = default_profile()
    profile["settings"]["positioning"] = "manual"
    profile["client_size"] = [1920, 1080]
    profile["points"] = {name: [100 + index * 100, 300] for index, name in enumerate(POINTS)}
    profile["samples"] = {"input": EMPTY[:], "quantity_ok": DIALOG[:]}
    for name, count in (counts or {"T": 1}).items():
        profile["stacks"][name].update(available=count, count=count)
    return profile


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.on_sleep = lambda: None

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.on_sleep()


class FakeBackend:
    """Model the inventory, split dialog, input slot, and automatic result return."""
    def __init__(self, profile, clock):
        self.profile = profile
        self.clock = clock
        self.focus = True
        self.position = None
        self.buttons = {}
        self.keys = set()
        self.events = []
        self.available = {n: profile["stacks"][n]["available"] for n in STACKS}
        self.dialog = False
        self.loaded = False
        self.loaded_stack = None
        self.finish_at = None
        self.duration = 4.0
        self.output = False
        self.returned_results = 0
        self.starts = []
        self.dialog_stuck = False
        self.transfer_fails = False

    def check_focus(self, expected_size):
        if not self.focus:
            raise Interrupted("Game lost focus")
        if expected_size != self.profile["client_size"]:
            raise Interrupted("Size changed")

    def update(self):
        if self.finish_at is not None and self.clock.now >= self.finish_at:
            self.loaded = False
            self.output = True
            self.finish_at = None

    def sample(self, point):
        self.update()
        if list(point) == self.profile["points"]["input"]:
            return OCCUPIED[:] if self.loaded else EMPTY[:]
        if list(point) == self.profile["points"]["quantity_ok"]:
            return DIALOG[:] if self.dialog else EMPTY[:]
        raise AssertionError("Unexpected sample")

    def move(self, point):
        self.position = list(point)
        self.events.append(("move", self.position))

    def button(self, name, down):
        self.events.append((name, down))
        if down:
            self.buttons[name] = self.position[:]
            return
        source = self.buttons.pop(name, None)
        if source is None:
            return
        points = self.profile["points"]
        if source != self.position and self.position == points["input"]:
            if self.transfer_fails:
                return
            for stack in STACKS:
                if source == points[stack]:
                    self.loaded_stack = stack
                    self.dialog = self.available[stack] > 1
                    if not self.dialog:
                        self.loaded = True
                        self.available[stack] -= 1
                    return
        if source == self.position == points["quantity_ok"] and self.dialog:
            if not self.dialog_stuck:
                self.dialog = False
                self.loaded = True
                self.available[self.loaded_stack] -= 1
        if source == self.position == points["start"]:
            if not self.loaded or self.dialog:
                raise AssertionError("Start without a loaded part")
            if self.output:
                self.returned_results += 1
                self.output = False
            self.starts.append(self.loaded_stack)
            self.finish_at = self.clock.now + self.duration

    def key(self, key, down):
        self.events.append((key, down))
        if down:
            self.keys.add(key)
        else:
            self.keys.discard(key)

    def release_all(self):
        for key in tuple(self.buttons):
            self.button(key, False)
        for key in tuple(self.keys):
            self.key(key, False)


class RunnerTests(unittest.TestCase):
    def setup_runner(self, profile=None):
        self.profile = profile or ready_profile()
        self.clock = FakeClock()
        self.control = Control()
        self.backend = FakeBackend(self.profile, self.clock)
        self.messages = []
        self.runner = ResearchRunner(self.profile, self.backend, self.control,
                                     lambda kind, value: self.messages.append((kind, value)),
                                     self.clock.clock, self.clock.sleep)

    def errors(self):
        return [payload for kind, payload in self.messages if kind == "error"]

    def test_all_four_stacks_and_automatic_previous_result_return(self):
        self.setup_runner(ready_profile({"T": 2, "E": 1, "A": 2, "L": 1}))
        self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.backend.starts, ["T", "T", "E", "A", "A", "L"])
        self.assertEqual(self.runner.completed, 6)
        self.assertEqual(self.backend.returned_results, 5)
        self.assertTrue(self.backend.output)  # Last result remains; no extra Start.
        self.assertEqual(self.backend.available, dict.fromkeys(STACKS, 0))
        self.assertFalse(self.backend.buttons)
        self.assertFalse(self.backend.keys)

    def test_zero_count_stack_is_skipped(self):
        self.setup_runner(ready_profile({"L": 1}))
        self.runner.run()
        self.assertEqual(self.backend.starts, ["L"])

    def test_partial_batch_leaves_unrequested_units(self):
        profile = ready_profile({"T": 2})
        profile["stacks"]["T"]["available"] = 7
        self.setup_runner(profile)
        self.runner.run()
        self.assertEqual(self.backend.available["T"], 5)
        self.assertEqual(len(self.backend.starts), 2)
        self.assertEqual(sum(event == ("1", True) for event in self.backend.events), 2)

    def test_single_item_without_quantity_dialog_does_not_type(self):
        self.setup_runner()
        self.runner.run()
        self.assertFalse(self.errors())
        self.assertFalse(any(event == ("1", True) for event in self.backend.events))

    def test_missing_dialog_for_multi_item_stack_stops_without_start(self):
        profile = ready_profile({"T": 1})
        profile["stacks"]["T"]["available"] = 5
        self.setup_runner(profile)
        self.backend.transfer_fails = True
        self.runner.run()
        self.assertIn("Expected quantity dialog", self.errors()[0])
        self.assertFalse(self.backend.starts)

    def test_dialog_not_closed_stops_without_start(self):
        self.setup_runner(ready_profile({"T": 2}))
        self.backend.dialog_stuck = True
        self.runner.run()
        self.assertIn("did not close", self.errors()[0])
        self.assertFalse(self.backend.starts)

    def test_long_research_is_monitored_without_timeout_or_retry(self):
        self.setup_runner(ready_profile())
        self.backend.duration = 300
        self.runner.run()
        self.assertFalse(self.errors())
        self.assertEqual(self.backend.starts, ["T"])
        self.assertEqual(self.runner.completed, 1)
        self.assertGreater(self.clock.now, 300)

    def test_stop_during_drag_releases_input_without_start(self):
        self.setup_runner()
        def stop_when_held():
            if self.backend.buttons:
                self.control.stopped.set()
        self.clock.on_sleep = stop_when_held
        self.runner.run()
        self.assertTrue(self.errors())
        self.assertFalse(self.backend.buttons)
        self.assertFalse(self.backend.keys)
        self.assertFalse(self.backend.starts)

    def test_pause_during_drag_requires_recovery(self):
        self.setup_runner()
        self.clock.on_sleep = lambda: self.control.paused.set() if self.backend.buttons else None
        self.runner.run()
        self.assertIn("Paused during item transfer", self.errors()[0])
        self.assertFalse(self.backend.buttons)
        self.assertFalse(self.backend.starts)

    def test_pause_during_research_resumes_without_duplicate_start(self):
        self.setup_runner()
        paused_at = []
        def pause_resume():
            if self.backend.finish_at is not None and not paused_at:
                paused_at.append(self.clock.now)
                self.control.paused.set()
            elif paused_at and self.clock.now > paused_at[0] + 0.5:
                self.control.paused.clear()
        self.clock.on_sleep = pause_resume
        self.runner.run()
        self.assertFalse(self.errors())
        self.assertEqual(self.backend.starts, ["T"])
        self.assertEqual(self.runner.completed, 1)

    def test_focus_loss_during_drag_stops_and_releases(self):
        self.setup_runner()
        self.clock.on_sleep = lambda: setattr(self.backend, "focus", False) if self.backend.buttons else None
        self.runner.run()
        self.assertIn("lost focus", self.errors()[0])
        self.assertFalse(self.backend.starts)
        self.assertFalse(self.backend.buttons)

    def test_occupied_initial_input_prevents_any_movement(self):
        self.setup_runner()
        self.backend.loaded = True
        self.runner.run()
        self.assertIn("not empty", self.errors()[0])
        self.assertFalse(self.backend.events)

    def test_waiting_for_research_can_still_be_stopped(self):
        self.setup_runner()
        self.backend.duration = 999
        def stop_during_research():
            if self.backend.starts and self.clock.now > 8:
                self.control.stopped.set()
        self.clock.on_sleep = stop_during_research
        self.runner.run()
        self.assertIn("Stopped", self.errors()[0])
        self.assertEqual(self.runner.completed, 0)
        self.assertEqual(self.backend.starts, ["T"])

    def test_original_profile_is_not_mutated(self):
        self.setup_runner()
        original = deepcopy(self.profile)
        self.runner.run()
        self.assertEqual(self.profile, original)


class ConfigurationTests(unittest.TestCase):
    def test_visual_mode_needs_no_coordinates_or_reference_calibration(self):
        profile = default_profile()
        profile["stacks"]["L"].update(available=3, count=3)
        validate_profile(profile)
        self.assertIsNone(profile["client_size"])
        self.assertFalse(profile["points"])
        self.assertFalse(profile["samples"])

    def test_uncalibrated_default_cannot_run(self):
        with self.assertRaises(ValueError):
            validate_profile(default_profile())

    def test_nonfinite_timing_rejected(self):
        profile = ready_profile()
        profile["settings"]["drag_seconds"] = float("nan")
        with self.assertRaises(ValueError):
            validate_profile(profile)

    def test_malformed_profile_sections_rejected_with_explanation(self):
        for key in ("stacks", "settings"):
            profile = ready_profile()
            profile[key] = None
            with self.assertRaises(ValueError):
                validate_profile(profile)

    def test_request_exceeding_stack_rejected(self):
        profile = ready_profile()
        profile["stacks"]["T"]["count"] = 2
        with self.assertRaises(ValueError):
            validate_profile(profile)

    def test_missing_l_calibration_rejected_when_l_enabled(self):
        profile = ready_profile({"L": 1})
        del profile["points"]["L"]
        with self.assertRaisesRegex(ValueError, "L position"):
            validate_profile(profile)

    def test_roundtrip_save_and_load(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            profile = ready_profile()
            save_profile(path, profile)
            self.assertEqual(load_profile(path), profile)

    def test_old_research_timers_are_removed_from_saved_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            profile = ready_profile()
            profile["settings"].update(mode="timed", research_timeout=180, minimum_research_seconds=3)
            profile["stacks"]["T"]["seconds"] = 45
            path.write_text(json.dumps(profile), encoding="utf-8")
            loaded = load_profile(path)
            self.assertNotIn("mode", loaded["settings"])
            self.assertNotIn("research_timeout", loaded["settings"])
            self.assertNotIn("minimum_research_seconds", loaded["settings"])
            self.assertNotIn("seconds", loaded["stacks"]["T"])
            self.assertEqual(loaded["stacks"]["T"]["count"], 1)

    def test_small_pixel_noise_does_not_change_slot_state(self):
        noisy = [c + 2 for c in EMPTY]
        self.assertTrue(samples_match(noisy, EMPTY, 30, 5))
        self.assertFalse(samples_match(OCCUPIED, EMPTY, 30, 5))


class RecordingReferenceTests(unittest.TestCase):
    """Real samples from the supplied video; no image library needed at test time."""
    def test_empty_and_loaded_input_in_recording_are_distinguished(self):
        path = Path(__file__).parent / "fixtures" / "recording_samples.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("loaded_44s", "loaded_49s"):
            self.assertFalse(samples_match(data[key], data["empty_38s"], 30, 5), key)
        self.assertTrue(samples_match(data["empty_72_8s"], data["empty_38s"], 30, 5))

    def test_quantity_button_distinguished_from_absent_dialog(self):
        path = Path(__file__).parent / "fixtures" / "recording_samples.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(samples_match(data["dialog_absent_49s"], data["dialog_open_46s"], 30, 5))


if __name__ == "__main__":
    unittest.main()
