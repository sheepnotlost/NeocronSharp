"""GoGuardian refills: window/stack reading on real captures and the refill sequence."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import gogo
from construction_runner import ConstructionRunner
from macro_core import Interrupted
from text_reader import TextReader

FIXTURES = Path(__file__).parent / "fixtures"


def gray_frame(name, size=(1080, 1920), at=(100, 100)):
    image = cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2GRAY)
    frame = np.zeros(size, np.uint8)
    frame[at[1]:at[1]+image.shape[0], at[0]:at[0]+image.shape[1]] = image
    return frame


class GoGoReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = TextReader()

    def test_window_and_ingredient_stacks_are_found_on_two_real_captures(self):
        for name, scale_range in (("gogo_reference.png", (.9, 1.1)), ("gogo_live_2560.png", (.9, 1.1))):
            with self.subTest(name=name):
                frame = gray_frame(name)
                window = gogo.find_gogo(self.reader, frame)
                self.assertIsNotNone(window)
                self.assertTrue(scale_range[0] <= window.scale <= scale_range[1], window)
                codes = {cell["code"] for cell in gogo.read_cells(self.reader, frame, window).values()}
                # A live capture's blurrier labels still yield every ingredient the macro needs.
                self.assertTrue({"GAM", "SOL", "TRS", "MET", "STS", "TIB", "ARI"} <= codes, codes)

    def test_plan_moves_at_most_fifteen_of_each_needed_ingredient(self):
        frame = gray_frame("gogo_reference.png")
        window = gogo.find_gogo(self.reader, frame)
        cells = gogo.read_cells(self.reader, frame, window)
        plan = gogo.plan_refill("weaponpart_9", cells)
        self.assertEqual({name for name, *_ in plan}, {"Gamonin", "Metal D", "Solantium", "Strastin", "Tiberal"})
        self.assertTrue(all(1 <= amount <= gogo.BATCH for *_, amount in plan))
        self.assertEqual({name for name, *_ in gogo.plan_refill("weaponpart_7", cells)}, {"Trisol", "Metal D", "Arillium", "Solantium"})

    def test_unknown_recipes_and_missing_materials_are_refused(self):
        with self.assertRaises(LookupError):gogo.plan_refill("holy_heal", {})
        with self.assertRaises(LookupError):gogo.plan_refill("weaponpart_9", {(0, 0): {"code": "ZZZ", "count": 5, "point": (1, 1)}})

    def test_a_frame_without_the_button_strip_is_not_a_gogo(self):
        self.assertIsNone(gogo.find_gogo(self.reader, np.zeros((1080, 1920), np.uint8)))


class RefillSequenceTests(unittest.TestCase):
    def runner(self, window_present=True, dialog_defaults=(55, 12, 80, 40, 17)):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        gray = gray_frame("gogo_reference.png")
        events = []
        defaults = list(dialog_defaults)
        shown = {"value": None, "open": False}
        reader = TextReader()

        class Detector:
            def gray(self, f):return gray
            def text_reader(self):return reader
            def inventory(self, f, checkpoint=None):
                class Anchor:
                    scale = 1.
                    def point(self, x, y):return [int(x), int(y)]
                return Anchor()
            def read_text(self, crop):
                if not defaults:return ""
                return str(shown["value"] if shown["value"] is not None else defaults[0])
            def quantity(self, f, checkpoint=None, expected=False):
                return {"field": [10, 10], "ok": [20, 10], "one": False, "scale": 1.} if defaults and shown["open"] else None
        outer = self
        r = ConstructionRunner.__new__(ConstructionRunner)
        r.detector = Detector();r.recipe = "weaponpart_9";r.name = "Tangent Weaponpart 9"
        r.settings = {"dialog_timeout": .3, "settle_seconds": 0}
        r.frame = lambda: frame
        r.guard = lambda: None
        r.wait = lambda seconds, safe_pause=False: None
        r.move = lambda point: None
        r.emit = lambda kind, payload=None: events.append((kind, payload))
        def drag(a, b):
            shown["open"] = True
            events.append(("drag", tuple(a), tuple(b)))
        r.drag = drag
        r.click = lambda point: events.append(("click", tuple(point)))
        def type_number(n):
            shown["value"] = n
            events.append(("type", n))
        r.type_number = type_number
        r.inventory_destination = lambda f, inv, code: (500, 600)
        if not window_present:r.detector.gray = lambda f: np.zeros((1080, 1920), np.uint8)
        # the dialog "closes" after Ok is clicked
        original_click = r.click
        def click(point):
            original_click(point)
            if tuple(point) == (20, 10) and defaults:
                defaults.pop(0);shown["value"] = None;shown["open"] = False
        r.click = click
        return r, events, defaults

    def test_each_ingredient_is_dragged_capped_at_fifteen_and_confirmed(self):
        runner, events, _ = self.runner()
        moved = runner.refill_from_gogo()
        self.assertEqual(moved, 5)
        self.assertEqual(sum(e[0] == "drag" for e in events), 5)
        typed = [e[1] for e in events if e[0] == "type"]
        self.assertTrue(typed and all(n <= gogo.BATCH for n in typed), typed)
        self.assertEqual(sum(e == ("click", (20, 10)) for e in events), 5)  # Ok once per ingredient

    def test_a_missing_gogo_window_stops_with_a_clear_message(self):
        runner, events, _ = self.runner(window_present=False)
        with self.assertRaisesRegex(Interrupted, "GoGuardian window not found"):
            runner.refill_from_gogo()
        self.assertFalse([e for e in events if e[0] == "drag"])


class RefusedStartTests(unittest.TestCase):
    def runner(self, enabled, busy_after=None):
        now = {"t": 0.}
        class Detector:
            def quantity(self, f, checkpoint=None, expected=False):return None
            def construction_state(self, f, a, recipe):
                return {"busy": busy_after is not None and now["t"] >= busy_after, "result": True}
            def has_loaded_blueprint(self, f, a):return True
        r = ConstructionRunner.__new__(ConstructionRunner)
        r.detector = Detector();r.recipe = "weaponpart_9"
        r.recipes = {"weaponpart_9": {"result_template": "constructed_weaponpart", "category": "Weapon parts"}}
        r.profile = {"construction": {"gogo_refill": enabled}}
        r.count_slots = False;r.output_details = None
        r.settings = {"refused_start_seconds": 5.0}
        r.clock = lambda: now["t"]
        r.processor_state = lambda: (None, None)
        r.guard = lambda: None
        r.control = type("C", (), {"stopped": type("E", (), {"is_set": lambda self: False})(),
                                  "paused": type("E", (), {"is_set": lambda self: False})()})()
        def wait(seconds, safe_pause=False):now["t"] += max(seconds, .05)
        r.wait = wait
        return r, now

    def test_a_start_that_never_gets_busy_is_reported_refused_only_when_gogo_refills_are_on(self):
        runner, now = self.runner(True)
        self.assertEqual(runner.await_construction(), "refused")
        self.assertGreaterEqual(now["t"], 5.0)

    def test_a_start_that_becomes_busy_in_time_is_not_refused(self):
        runner, _ = self.runner(True, busy_after=1.0)
        # busy, then idle with a result: completes normally
        states = {"calls": 0}
        original = runner.detector.construction_state
        def state(f, a, recipe):
            states["calls"] += 1
            result = original(f, a, recipe)
            if states["calls"] > 30:result["busy"] = False
            return result
        runner.detector.construction_state = state
        self.assertNotEqual(runner.await_construction(), "refused")


if __name__ == "__main__":
    unittest.main()
