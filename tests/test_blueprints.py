from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import json

from macro_core import Control, Interrupted, default_profile, load_profile, save_profile, validate_profile
from test_macro import FakeClock
from vision import Anchor, Ambiguous, Detector, NotFound, cv2, np
from vision_runner import BlueprintRunner


class BlueprintBackend:
    def __init__(self, clock, durations=(1, 8, 240)):
        self.clock = clock
        self.durations = durations
        self.focus = True
        self.finish_at = None
        self.result = True  # An old result must not complete a new attempt.
        self.produce_result = True
        self.accept_start = True
        self.hidden = False
        self.ambiguous = False
        self.dialog = False
        self.starts = []
        self.events = []
        self.held = False
        self.position = None
        self.anchor = Anchor(300, 400, 1, .99)

    def check_focus(self, size):
        if not self.focus:
            raise Interrupted("Game lost focus")

    def capture(self):
        if self.finish_at is not None and self.clock.now >= self.finish_at:
            self.finish_at = None
            self.result = self.produce_result
        # Relocate on every screenshot, including while processing and just before Start.
        self.anchor = Anchor(100 + (int(self.clock.now * 100) % 8) * 70,
                             120 + (int(self.clock.now * 70) % 6) * 60, 1, .99)
        return {"anchor": self.anchor, "busy": self.finish_at is not None,
                "result": self.result, "hidden": self.hidden,
                "ambiguous": self.ambiguous, "dialog": self.dialog}

    def move(self, point):
        self.position = list(point)
        self.events.append(("move", self.position))

    def button(self, name, down):
        self.events.append((name, down))
        if down:
            assert name == "left" and self.position == self.anchor.start_point()
            assert self.finish_at is None, "Start clicked while processing"
            self.held = True
        elif self.held:
            self.held = False
            if self.accept_start:
                self.starts.append(tuple(self.position))
                self.finish_at = self.clock.now + self.durations[(len(self.starts)-1) % len(self.durations)]
                self.result = False

    def release_all(self):
        if self.held:
            self.held = False
            self.events.append(("left", False))


class BlueprintDetector:
    def processor(self, frame, checkpoint=lambda: None):
        checkpoint()
        if frame["hidden"]:
            raise NotFound("Processor window not found")
        if frame["ambiguous"]:
            raise Ambiguous("Multiple possible processor windows")
        return frame["anchor"]

    def quantity(self, frame, checkpoint=lambda: None):
        checkpoint()
        return {"one": True} if frame["dialog"] else None

    def blueprint_state(self, frame, anchor):
        return {"busy": frame["busy"], "result": frame["result"]}


class RecordedBlueprintBackend(BlueprintBackend):
    """Replay real overlapping-window images through the production detector."""
    def __init__(self, clock):
        super().__init__(clock, durations=(.6, .8))
        self.captures = 0
        folder = Path(__file__).parent / "fixtures"
        self.images = {state: cv2.cvtColor(cv2.imread(str(folder / f"processor_overlap_{state}.png")),
                                         cv2.COLOR_BGR2RGB) for state in ("busy", "done")}

    def capture(self):
        state = super().capture()
        x, y = ((120, 80), (1100, 600), (600, 180))[self.captures % 3]
        self.captures += 1
        self.anchor = Anchor(x+26, y, 1, 1, (x+448, y+174))
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[y:y+208, x:x+516] = self.images["busy" if state["busy"] else "done"]
        return frame


class BlueprintRunnerTests(unittest.TestCase):
    def setup_run(self, count=3):
        self.profile = default_profile()
        self.profile["operation"] = "blueprints"
        self.profile["blueprints"]["count"] = count
        self.profile["client_size"] = [2560, 1440]
        self.clock = FakeClock()
        self.backend = BlueprintBackend(self.clock)
        self.control = Control()
        self.messages = []
        self.runner = BlueprintRunner(self.profile, self.backend, self.control,
                                      lambda kind, data: self.messages.append((kind, data)),
                                      self.clock.clock, self.clock.sleep, detector=BlueprintDetector())

    def errors(self):
        return [data for kind, data in self.messages if kind == "error"]

    def test_real_overlapping_frames_complete_repeated_copies_while_moving_every_capture(self):
        self.setup_run(count=3)
        self.profile["client_size"] = [1920, 1080]
        self.backend = RecordedBlueprintBackend(self.clock)
        with tempfile.TemporaryDirectory() as folder:
            self.runner = BlueprintRunner(self.profile, self.backend, self.control,
                                          lambda k, v: self.messages.append((k, v)),
                                          self.clock.clock, self.clock.sleep, diagnostic_dir=folder)
            self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.runner.completed, 3)
        self.assertEqual(len(self.backend.starts), 3)
        self.assertGreater(len(set(self.backend.starts)), 1)
        self.assertTrue(self.backend.result)

    def test_green_results_continue_repeating_with_the_production_detector(self):
        self.setup_run(count=3)
        self.profile["client_size"] = [1920, 1080]
        self.backend = RecordedBlueprintBackend(self.clock)
        # Keep the replay window geometry while replacing only the red result
        # area with the actual green result from the different-item screenshot.
        folder = Path(__file__).parent / "fixtures"
        green = cv2.cvtColor(cv2.imread(str(folder / "blueprint_green_done.png")), cv2.COLOR_BGR2RGB)
        green = cv2.resize(green, (516, 208), interpolation=cv2.INTER_AREA)
        self.backend.images["done"][70:140, 416:476] = green[70:140, 416:476]
        with tempfile.TemporaryDirectory() as diagnostics:
            self.runner = BlueprintRunner(self.profile, self.backend, self.control,
                                          lambda k,v: self.messages.append((k,v)),
                                          self.clock.clock, self.clock.sleep, diagnostic_dir=diagnostics)
            self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.runner.completed, 3)
        self.assertEqual(len(self.backend.starts), 3)

    def test_only_start_is_clicked_with_relocation_and_variable_research_durations(self):
        self.setup_run()
        original = deepcopy(self.profile)
        self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.runner.completed, 3)
        self.assertEqual(len(self.backend.starts), 3)
        self.assertGreater(len(set(self.backend.starts)), 1)
        self.assertGreater(self.clock.now, 249)
        self.assertTrue(self.backend.result)
        self.assertEqual(self.profile, original)
        self.assertEqual([e for e in self.backend.events if e[0] == "left"].count(("left", True)), 3)

    def test_existing_processing_run_is_monitored_without_duplicate_start(self):
        self.setup_run(count=1)
        self.backend.finish_at = 4
        self.backend.result = False
        self.runner.run()
        self.assertFalse(self.errors(), self.messages)
        self.assertEqual(self.runner.completed, 1)
        self.assertFalse(self.backend.starts)
        self.assertFalse(self.backend.events)

    def test_stale_result_and_ignored_start_never_cause_click_spam_or_false_completion(self):
        self.setup_run()
        self.backend.accept_start = False
        self.clock.on_sleep = lambda: self.control.stopped.set() if self.clock.now > 20 else None
        self.runner.run()
        self.assertEqual(self.runner.completed, 0)
        self.assertEqual(self.backend.events.count(("left", True)), 1)
        self.assertIn("Stopped", self.errors()[0])

    def test_research_ending_without_blueprint_stops_before_next_click(self):
        self.setup_run()
        self.backend.produce_result = False
        self.runner.run()
        self.assertIn("without a visible blueprint", self.errors()[0])
        self.assertEqual(len(self.backend.starts), 1)
        self.assertEqual(self.runner.completed, 0)

    def test_continuous_mode_stops_on_focus_loss(self):
        self.setup_run(count=0)
        self.clock.on_sleep = lambda: setattr(self.backend, "focus", False) if len(self.backend.starts) >= 4 else None
        self.runner.run()
        self.assertIn("Game lost focus", self.errors()[0])
        self.assertEqual(self.runner.completed, 3)
        self.assertEqual(len(self.backend.starts), 4)
        self.assertFalse(self.backend.held)

    def test_disappeared_processor_during_research_never_completes_or_reuses_coordinates(self):
        self.setup_run()
        self.clock.on_sleep = lambda: setattr(self.backend, "hidden", True) if self.backend.starts else None
        self.runner.run()
        self.assertIn("No stale coordinates", self.errors()[0])
        self.assertEqual(self.runner.completed, 0)
        self.assertEqual(len(self.backend.starts), 1)

    def test_ambiguous_processor_and_pending_dialog_prevent_input(self):
        for condition in ("ambiguous", "dialog"):
            with self.subTest(condition=condition):
                self.setup_run()
                setattr(self.backend, condition, True)
                self.runner.run()
                self.assertTrue(self.errors())
                self.assertFalse(self.backend.events)


class BlueprintRecognitionTests(unittest.TestCase):
    def test_actual_green_blueprint_is_recognized_for_the_different_item(self):
        crop = cv2.cvtColor(cv2.imread(str(Path(__file__).parent / "fixtures" / "blueprint_green_done.png")),
                            cv2.COLOR_BGR2RGB)
        for x,y in ((109,582), (1500,800)):
            frame = np.zeros((1440,2560,3), dtype=np.uint8)
            frame[y:y+crop.shape[0], x:x+crop.shape[1]] = crop
            detector = Detector()
            # No full-resolution fallback is needed on this actual rendering.
            detector.processor_full_search = lambda *a, **k: self.fail("Slow full search was used")
            anchor = detector.processor(frame)
            self.assertAlmostEqual(anchor.scale, 4/3)
            self.assertEqual(detector.blueprint_state(frame,anchor), {"busy":False, "result":True})

    def test_result_recognition_accepts_blue_cyan_and_neutral_cube_shading(self):
        original = cv2.cvtColor(cv2.imread(str(Path(__file__).parent / "fixtures" / "blueprint_done.png")),
                                cv2.COLOR_BGR2RGB)
        detector = Detector()
        for color in ("blue", "cyan", "neutral"):
            with self.subTest(color=color):
                frame = original.copy()
                region = frame[70:140,416:476]
                if color=="blue":
                    region[:]=region[:,:,[2,1,0]]
                elif color=="cyan":
                    intensity=region.max(axis=2)
                    region[:,:,0]=0;region[:,:,1]=intensity;region[:,:,2]=intensity
                else:
                    region[:]=region.max(axis=2)[:,:,None]
                anchor = detector.processor(frame)
                self.assertTrue(detector.blueprint_state(frame,anchor)["result"])

    def test_recording_ready_busy_and_complete_after_moves_and_scaling(self):
        fixtures = Path(__file__).parent / "fixtures"
        for scale in (1, 4/3, 1.7):
            for name, busy, result in (("blueprint_ready", False, False),
                                       ("blueprint_busy", True, False),
                                       ("blueprint_done", False, True)):
                with self.subTest(scale=scale, name=name):
                    crop = cv2.cvtColor(cv2.imread(str(fixtures / f"{name}.png")), cv2.COLOR_BGR2RGB)
                    crop = cv2.resize(crop, None, fx=scale, fy=scale)
                    frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
                    frame[700:700+crop.shape[0], 950:950+crop.shape[1]] = crop
                    detector = Detector()
                    anchor = detector.processor(frame)
                    self.assertAlmostEqual(anchor.scale, scale)
                    self.assertEqual(detector.blueprint_state(frame, anchor), {"busy": busy, "result": result})


class BlueprintConfigurationTests(unittest.TestCase):
    def test_old_profiles_keep_tech_part_mode_and_gain_blueprint_defaults(self):
        profile = default_profile()
        profile.pop("operation")
        profile.pop("blueprints")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            loaded = load_profile(path)
        self.assertEqual(loaded["operation"], "tech_parts")
        self.assertEqual(loaded["blueprints"], {"count": 1})

    def test_blueprints_require_no_tech_stacks_and_save_operation_and_count(self):
        profile = default_profile()
        profile["operation"] = "blueprints"
        for count in (0, 1, 10000):
            profile["blueprints"]["count"] = count
            validate_profile(profile)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "profile.json"
                save_profile(path, profile)
                self.assertEqual(load_profile(path), profile)

    def test_invalid_counts_and_operations_are_rejected(self):
        for count in (-1, 10001, True, 1.5, "3"):
            profile = default_profile()
            profile["operation"] = "blueprints"
            profile["blueprints"]["count"] = count
            with self.assertRaises(ValueError):
                validate_profile(profile)
        profile["blueprints"]["count"] = 1
        profile["operation"] = "unknown"
        with self.assertRaises(ValueError):
            validate_profile(profile)


if __name__ == "__main__":
    unittest.main()
