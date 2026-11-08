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
                codes = {cell["code"] for cell in gogo.read_cells(self.reader, frame, window, {"GAM", "SOL", "TRS", "MET", "STS", "TIB", "ARI", "ZZZ"}).values()}
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
        with self.assertRaisesRegex(LookupError,"could not find"):gogo.plan_refill("weaponpart_9", {(0, 0): {"code": "ZZZ", "count": 5, "point": (1, 1)}})
        # A partial set must never start a build with some materials still missing.
        partial={(0,0):{"code":"GAM","count":None,"point":(1,1)},(1,0):{"code":"MET","count":None,"point":(2,1)}}
        with self.assertRaisesRegex(LookupError,"Solantium"):gogo.plan_refill("weaponpart_9", partial)

    def test_missing_label_message_lists_the_labels_that_were_seen(self):
        cells={(0,0):{"code":"GAM","count":None,"point":(1,1)},(1,0):{"code":"W4","count":None,"point":(2,1)}}
        with self.assertRaisesRegex(LookupError,r"Metal D \(MET\).*Labels seen: GAM, W4"):gogo.plan_refill("weaponpart_9", cells)

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
        r.detector = Detector();r.recipe = "weaponpart_9";r.name = "Tangent Weaponpart 9";r.profile = {}
        r.settings = {"dialog_timeout": .3, "settle_seconds": 0}
        r.frame = lambda: frame
        r.guard = lambda: None
        now = [0.]
        r.clock = lambda: now[0]
        def wait(seconds, safe_pause=False):
            now[0] += seconds
        r.wait = wait
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

    def test_a_dialog_that_opens_at_one_is_still_filled_to_fifteen(self):
        # Live: the first ingredient came across as a single item because the dialog
        # reopened at the previous quantity (1). Every ingredient must be typed.
        runner, events, _ = self.runner(dialog_defaults=(1, 15, 15, 15, 15))
        runner.refill_from_gogo()
        typed = [e[1] for e in events if e[0] == "type"]
        self.assertGreaterEqual(len(typed), 1)
        self.assertEqual(typed[0], gogo.BATCH)

    def hover_runner(self, labels, tooltips, materials):
        """Runner whose frame shows a tooltip (named by `tooltips`, keyed by label) after a hover."""
        runner, events, _ = self.runner()
        base = runner.detector.gray(None)
        reader = runner.detector.text_reader()
        window = gogo.find_gogo(reader, base)
        cells = gogo.read_cells(reader, base, window)
        by_point = {tuple(info["point"]): tooltips.get(info["code"], "Something Else") for info in cells.values()}
        cursor = {"point": None}
        hovered = []
        def move(point):
            cursor["point"] = tuple(point)
            if tuple(point) in by_point:hovered.append(by_point[tuple(point)])
        def gray(_frame):
            image = base.copy()
            text = by_point.get(cursor["point"])
            if text:
                x, y = cursor["point"][0] + 20, cursor["point"][1] + 30
                image[y:y+22, x:x+170] = 200
                image[y+1:y+21, x+1:x+169] = 0
                cv2.putText(image, text, (x+6, y+16), cv2.FONT_HERSHEY_SIMPLEX, .5, 255, 1, cv2.LINE_AA)
            return image
        runner.move = move
        runner.detector.gray = gray
        runner.profile = {"materials": {"weaponpart_9": materials}}
        return runner, events, hovered

    def test_a_wrong_label_is_learned_from_the_stacks_tooltip_and_saved(self):
        wrong = {"Gamonin": "GAM", "Metal D": "MET", "Solantium": "SOL", "Strastin": "STX", "Tiberal": "TIB"}
        runner, events, hovered = self.hover_runner(None, {"STS": "Strastin"}, wrong)
        self.assertEqual(runner.refill_from_gogo(), 5)
        saved = [e[1] for e in events if e[0] == "materials"]
        self.assertEqual(saved, [{"recipe": "weaponpart_9", "codes": {**wrong, "Strastin": "STS"}}])
        self.assertEqual(runner.profile["materials"]["weaponpart_9"]["Strastin"], "STS")
        self.assertEqual(hovered[0], "Strastin")
        self.assertLess(len(hovered), 5)
        self.assertEqual(sum(e[0] == "drag" for e in events), 5)

    def test_correct_labels_need_no_hovering(self):
        runner, events, hovered = self.hover_runner(None, {}, {"Gamonin": "GAM", "Metal D": "MET", "Solantium": "SOL", "Strastin": "STS", "Tiberal": "TIB"})
        runner.refill_from_gogo()
        self.assertEqual(hovered, [])
        self.assertFalse([e for e in events if e[0] == "materials"])

    def test_an_unreadable_tooltip_stops_and_lists_the_labels_seen(self):
        wrong = {"Gamonin": "GAM", "Metal D": "MET", "Solantium": "SOL", "Strastin": "STX", "Tiberal": "TIB"}
        runner, events, _ = self.hover_runner(None, {}, wrong)
        with self.assertRaisesRegex(Interrupted, r"Strastin \(STX\).*Labels seen: .*STS"):
            runner.refill_from_gogo()
        self.assertFalse([e for e in events if e[0] in ("drag", "materials")])

    def test_a_missing_gogo_window_stops_with_a_clear_message(self):
        runner, events, _ = self.runner(window_present=False)
        with self.assertRaisesRegex(Interrupted, "GoGuardian window not found"):
            runner.refill_from_gogo()
        self.assertFalse([e for e in events if e[0] == "drag"])

    def counted(self, runner, held):
        """Make Inventory's stacks hold `held[code]` (default 0), going up by what is typed into the dialog."""
        runner.have = lambda code: held.get(code, 0)
        return held

    def test_a_stack_part_full_only_gets_the_rest(self):
        runner, events, _ = self.runner()
        self.counted(runner, {"GAM": 10})
        runner.refill_from_gogo()
        typed = [e[1] for e in events if e[0] == "type"]
        self.assertIn(5, typed)                                  # Gamonin: 15 - 10
        self.assertTrue(all(n <= gogo.BATCH for n in typed))

    def test_a_full_stack_gets_nothing(self):
        runner, events, _ = self.runner()
        self.counted(runner, {"GAM": 15, "MET": 15, "SOL": 15, "STS": 15, "TIB": 15})
        self.assertEqual(runner.refill_from_gogo(), 5)
        self.assertFalse([e for e in events if e[0] in ("drag", "type")])

    def test_a_retry_after_a_transfer_that_landed_does_not_drag_again(self):
        runner, events, _ = self.runner()
        held = {"GAM": 0}
        runner.have = lambda code: held.get(code, 0)
        drags = []
        def drag(a, b):
            drags.append(1)
            held["GAM"] = 15                                     # it landed, though the dialog never showed
        runner.drag = drag
        runner.detector.quantity = lambda f, checkpoint=None, expected=False: None
        runner.transfer("x", (1, 1), lambda: (2, 2), 15, lambda: held["GAM"])
        self.assertEqual(len(drags), 1)

    def test_a_retry_after_an_entered_transfer_with_no_count_does_not_drag_again(self):
        # Blueprints and the stash have no count to check: once a dialog was filled in, a retry never drags again.
        runner, events, _ = self.runner()
        drags = []
        runner.drag = lambda a, b: drags.append(1)
        def enter(amount):
            raise Interrupted("Quantity dialog did not close after the GoGuardian transfer.")
        runner.enter_quantity = enter
        runner.detector.quantity = lambda f, checkpoint=None, expected=False: None
        runner.transfer("x", (1, 1), lambda: (2, 2), 15)
        self.assertEqual(len(drags), 1)

    def test_an_unreadable_count_counts_as_one(self):
        runner, events, _ = self.runner()
        runner.have = lambda code: None
        runner.refill_from_gogo()
        typed = [e[1] for e in events if e[0] == "type"]
        self.assertTrue(typed and all(n == gogo.BATCH - 1 for n in typed))

    def test_grease_is_not_capped(self):
        runner, events, _ = self.runner()
        moved = []
        runner.transfer = lambda label, source, destination, amount, have=None, held=0: moved.append((amount, have))
        from unittest import mock
        with mock.patch.object(gogo, "plan_refill", return_value=[("Construction Grease", "CGR", (5, 5), 40)]):
            runner.have = lambda code: 99
            runner.refill_from_gogo()
        self.assertEqual(moved, [(40, None)])

    def retries(self, events):
        return [e[1] for e in events if e[0] == "status" and "Trying again" in e[1]]

    def test_a_dialog_that_opens_late_is_filled_in_not_dragged_again(self):
        # Live (7 Nov): the game lagged and the Strastin dialog came after the wait for it ended.
        runner, events, _ = self.runner()
        original = runner.detector.quantity
        def quantity(f, checkpoint=None, expected=False):
            return original(f, checkpoint, expected) if runner.clock() >= 1. else None
        runner.detector.quantity = quantity
        self.assertEqual(runner.refill_from_gogo(), 5)
        self.assertEqual(sum(e[0] == "drag" for e in events), 5)
        self.assertEqual(sum(e == ("click", (20, 10)) for e in events), 5)
        self.assertEqual(len(self.retries(events)), 1)
        self.assertIn("(1 of 3)", self.retries(events)[0])

    def test_a_drag_the_game_missed_is_made_again(self):
        runner, events, _ = self.runner()
        drag = runner.drag
        missed = []
        def lagging(a, b):
            if not missed:missed.append((a, b));events.append(("missed",));return
            drag(a, b)
        runner.drag = lagging
        self.assertEqual(runner.refill_from_gogo(), 5)
        self.assertEqual(sum(e[0] == "drag" for e in events), 5)
        self.assertEqual(len(self.retries(events)), 1)

    def test_it_gives_up_after_four_tries(self):
        runner, events, _ = self.runner()
        runner.detector.quantity = lambda f, checkpoint=None, expected=False: None
        with self.assertRaisesRegex(Interrupted, "Expected quantity dialog"):
            runner.refill_from_gogo()
        self.assertEqual(sum(e[0] == "drag" for e in events), ConstructionRunner.TRIES)
        self.assertEqual(len(self.retries(events)), ConstructionRunner.TRIES - 1)

    def test_stop_is_never_tried_again(self):
        runner, events, _ = self.runner()
        def stopped(a, b):
            events.append(("drag", a, b))
            raise Interrupted("Stopped. Check the current item before restarting.")
        runner.drag = stopped
        with self.assertRaisesRegex(Interrupted, "Stopped"):
            runner.refill_from_gogo()
        self.assertEqual(sum(e[0] == "drag" for e in events), 1)
        self.assertFalse(self.retries(events))


class BuildRetryTests(unittest.TestCase):
    """A failed build is tried again from what the Processor shows (the user's ask, 7 Nov: the game lags)."""

    def runner(self, loaded=False, busy=False, dialog=False, ran=False):
        state = {"dialog": dialog}
        clicks = []
        class Processor:
            def start_point(self):return (300, 400)
        class Detector:
            def quantity(self, f, checkpoint=None, expected=False):
                return {"field": [100, 100], "ok": [200, 100], "scale": 1.} if state["dialog"] else None
            def construction_state(self, f, a, recipe):return {"busy": busy}
            def has_loaded_blueprint(self, f, a):return loaded
        r = ConstructionRunner.__new__(ConstructionRunner)
        r.detector = Detector();r.name = "Tangent Weaponpart 9";r.recipe = "weaponpart_9";r.ran = ran
        r.settings = {"settle_seconds": 0}
        r.frame = lambda: None
        r.guard = lambda: None
        r.processor_state = lambda: (None, Processor())
        r.wait = lambda seconds, safe_pause=False: None
        r.step_aside = lambda: None
        r.emit = lambda kind, payload=None: None
        def click(point):
            clicks.append(tuple(point))
            if tuple(point) == (216, 76):state["dialog"] = False      # the dialog's X
        r.click = click
        r.await_construction = lambda: None
        def locate():raise AssertionError("no second blueprint may be loaded")
        r.locate_blueprint = locate
        return r, clicks

    def test_a_loaded_blueprint_is_started(self):
        runner, clicks = self.runner(loaded=True)
        self.assertEqual(runner.build_one({}, False, 2), "built")
        self.assertEqual(clicks, [(300, 400)])

    def test_a_build_under_way_is_only_followed(self):
        runner, clicks = self.runner(busy=True)
        self.assertEqual(runner.build_one({}, False, 2), "built")
        self.assertEqual(clicks, [])

    def test_a_build_that_already_ran_is_counted_not_repeated(self):
        runner, clicks = self.runner(ran=True)
        self.assertEqual(runner.build_one({}, False, 2), "built")
        self.assertEqual(clicks, [])

    def test_a_dialog_left_open_is_closed_with_its_x(self):
        runner, clicks = self.runner(loaded=True, dialog=True)
        self.assertEqual(runner.build_one({}, False, 2), "built")
        self.assertEqual(clicks, [(216, 76), (300, 400)])

    def test_out_of_materials_is_not_tried_again(self):
        from construction_runner import OutOfMaterials
        runner, _ = self.runner()
        calls = []
        def step(attempt):
            calls.append(attempt)
            raise OutOfMaterials("Start was refused.")
        with self.assertRaises(OutOfMaterials):runner.retrying("x", step)
        self.assertEqual(calls, [1])


class MaterialsListTests(unittest.TestCase):
    def test_materials_text_round_trips_and_rejects_bad_entries(self):
        parsed = gogo.parse_materials("Gamonin=gam, Metal D = MET ,Tiberal=TIB")
        self.assertEqual(parsed, {"Gamonin": "GAM", "Metal D": "MET", "Tiberal": "TIB"})
        self.assertEqual(gogo.parse_materials(gogo.format_materials(parsed)), parsed)
        self.assertEqual(gogo.parse_materials(""), {})
        for bad in ("Gamonin", "Gamonin=", "=GAM", "Gamonin=TOOLONG", "Gamonin=G"):
            with self.assertRaises(ValueError, msg=bad):gogo.parse_materials(bad)

    def test_a_users_list_overrides_the_built_in_table_and_works_for_new_recipes(self):
        profile = {"materials": {"weaponpart_9": {"Gamonin": "GAM"}, "custom_x": {"Zinc": "ZN", "Iron": "IRN"}}}
        self.assertEqual(gogo.ingredients_for("weaponpart_9", profile), {"Gamonin": "GAM"})
        self.assertEqual(gogo.ingredients_for("custom_x", profile), {"Zinc": "ZN", "Iron": "IRN"})
        self.assertEqual(gogo.ingredients_for("weaponpart_7", profile)["Trisol"], "TRS")
        self.assertIsNone(gogo.ingredients_for("custom_y", profile))
        cells = {(0, 0): {"code": "ZN", "count": 40, "point": (5, 5)}, (1, 0): {"code": "IRN", "count": 3, "point": (9, 9)}}
        plan = gogo.plan_refill("custom_x", cells, gogo.ingredients_for("custom_x", profile))
        self.assertEqual([(n, a) for n, _, _, a in plan], [("Zinc", 15), ("Iron", 3)])

    def test_the_profile_validates_and_keeps_the_materials_list(self):
        from macro_core import default_profile, validate_profile
        profile = default_profile();profile["materials"] = {"custom_x": {"Zinc": "ZN"}}
        validate_profile(profile, require_ready=False)
        profile["materials"] = {"custom_x": {"Zinc": "Z"}}
        with self.assertRaises(ValueError):validate_profile(profile, require_ready=False)

    def test_catalog_parts_become_a_materials_row_with_guessed_labels(self):
        parts = [{"quantity": 1, "name": "Tangent Weaponpart 3"}, {"quantity": 2, "name": "Tangent Weaponpart 10"},
                 {"quantity": 1, "name": "Gamonin"}, {"quantity": 1, "name": "Trisol"}, {"quantity": 1, "name": "Zinc Oxide"}]
        self.assertEqual(gogo.materials_from_parts(parts),
                         {"Tangent Weaponpart 3": "W3", "Tangent Weaponpart 10": "W10", "Gamonin": "GAM", "Trisol": "TRS", "Zinc Oxide": "ZIN"})
        self.assertEqual(gogo.materials_from_parts(None), {})
        self.assertEqual(gogo.ingredients_for("holy_heal")["Tangent Weaponpart 9"], "W9")

    def test_a_refill_for_a_recipe_without_any_list_explains_what_to_do(self):
        with self.assertRaisesRegex(LookupError, "labels are not known"):gogo.plan_refill("custom_zzz", {})


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


class InventoryStackReadingTests(unittest.TestCase):
    """Finished parts go into GoGuardian 15 at a time (7 Nov). Real 2560x1440 Inventory: W9 x2, x15, x14 stacks."""
    @classmethod
    def setUpClass(cls):
        from vision import Anchor
        cls.reader = TextReader()
        cls.frame = cv2.cvtColor(cv2.imread(str(FIXTURES / "inventory_1440_w9_stack.png")), cv2.COLOR_BGR2RGB)
        cls.inventory = Anchor(37, 17, 1.255, 1.)

    def count(self, col, row):
        below = gogo.inventory_cell(self.frame, self.inventory, col, row+1)
        return gogo.read_count(self.reader, [gogo.inventory_cell(self.frame, self.inventory, col, row), below])

    def test_counts_of_ten_and_up_read_and_short_ones_never_read_high(self):
        self.assertEqual(self.count(3, 0), 15)
        self.assertEqual(self.count(2, 2), 14)
        self.assertEqual(self.count(0, 2), 247)
        self.assertIn(self.count(3, 1), (None, 2))                         # W9 x2: unread is fine, it's under 15

    def test_labels_are_found_even_when_too_short_to_read(self):
        labels = gogo.inventory_labels(self.reader, self.frame, self.inventory)
        self.assertIn((3, 1), labels)                                       # W9
        self.assertNotIn((4, 1), labels)                                    # the W9 box's second cell has no label
        self.assertIn("TIB", labels[(3, 2)][1])
        self.assertNotIn((0, 4), labels)                                    # empty
        self.assertTrue(gogo.same_label(labels[(3, 1)][0], labels[(3, 1)][0].copy()))
        self.assertFalse(gogo.same_label(labels[(3, 1)][0], labels[(3, 2)][0]))

    def test_an_empty_gogo_cell_is_chosen_never_a_full_one(self):
        gray = gray_frame("gogo_reference.png")
        window = gogo.find_gogo(self.reader, gray)
        point = gogo.drop_cell(self.reader, gray, window, "W9")
        self.assertIsNotNone(point)
        col = int((point[0] - window.cell_origin(0, 0)[0]) // (gogo.CELL_W*window.scale))
        row = int((point[1] - window.cell_origin(0, 0)[1]) // (gogo.CELL_H*window.scale))
        x, y = window.cell_origin(col, row)
        s = window.scale
        crop = gray[int(y+7*s):int(y+(gogo.CELL_H-7)*s), int(x+7*s):int(x+(gogo.CELL_W-7)*s)]
        self.assertLess(float(crop.std()), gogo.EMPTY_CONTRAST)


class StashSequenceTests(unittest.TestCase):
    """The runner side, with the readers stood in for."""
    PRODUCT, OTHER, BLUEPRINT = (3, 1), (1, 0), (0, 0)

    def runner(self, count=15, gogo_window=True, labels=None):
        from unittest import mock
        events = []

        class Inventory:
            scale = 1.

            def point(self, x, y):
                return [int(x), int(y)]

        class Window:
            scale = 1.

            def cell_origin(self, col, row):
                return (100 + col*10, 100 + row*10)

            def cell_center(self, col, row):
                return (105 + col*10, 105 + row*10)

            def box(self):
                return (90, 90, 200, 200)

        outer = self
        mask = lambda n: np.full((4, 4), n, np.uint8)
        names = {tuple(gogo.inventory_point(Inventory(), *self.PRODUCT)): ("weaponpart_9", "Tangent Weaponpart 9"),
                 tuple(gogo.inventory_point(Inventory(), *self.OTHER)): ("weaponpart_7", "Tangent Weaponpart 7"),
                 tuple(gogo.inventory_point(Inventory(), *self.BLUEPRINT)): ("weaponpart_9", "BLUEPRINT: Tangent Weaponpart 9"),
                 (105, 115): ("weaponpart_9", "Tangent Weaponpart 9")}
        hovered = []

        class Detector:
            seen = {}

            def inventory(self, f, checkpoint=None):
                return Inventory()

            def text_reader(self):
                return None

            def gray(self, f):
                return np.zeros((10, 10), np.uint8)

            def result_details(self, f, point, scale):
                hovered.append(tuple(point))
                found = names.get(tuple(point))
                return {"recipe": found[0], "slots": None, "text": found[1]} if found else None

        r = ConstructionRunner.__new__(ConstructionRunner)
        r.detector = Detector();r.recipe = "weaponpart_9";r.name = "Tangent Weaponpart 9";r.profile = {}
        r.frame = lambda: np.zeros((10, 10, 3), np.uint8)
        r.guard = lambda: None
        r.wait = lambda seconds, safe_pause=False: None
        r.move = lambda point: None
        r.step_aside = lambda: None
        r.emit = lambda kind, payload=None: events.append((kind, payload))
        r.drag = lambda a, b: events.append(("drag", tuple(a), tuple(b)))
        r.enter_quantity = lambda amount: events.append(("quantity", amount))
        counts = {"value": count}
        all_labels = labels if labels is not None else {
            self.BLUEPRINT: (mask(1), []), self.OTHER: (mask(2), []), self.PRODUCT: (mask(3), []), (5, 0): (mask(4), ["TIB"])}
        patches = [mock.patch.object(gogo, "inventory_labels", lambda reader, f, inv: all_labels),
                   mock.patch.object(gogo, "read_count", lambda reader, cells: counts["value"]),
                   mock.patch.object(gogo, "inventory_cell", lambda f, inv, c, rw: np.zeros((2, 2, 3), np.uint8)),
                   mock.patch.object(gogo, "find_gogo", lambda reader, gray, checkpoint=None: Window() if gogo_window else None),
                   mock.patch.object(gogo, "drop_cell", lambda reader, gray, window, code: (125, 135))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return r, events, hovered, counts

    def test_at_fifteen_the_stack_found_by_its_tooltip_goes_to_an_empty_gogo_cell(self):
        runner, events, hovered, _ = self.runner(count=15)
        self.assertTrue(runner.stash_product())
        product = tuple(gogo.inventory_point(runner.detector.inventory(None), *self.PRODUCT))
        self.assertIn(("drag", product, (125, 135)), events)
        self.assertIn(("quantity", 15), events)
        self.assertNotIn(tuple(gogo.inventory_point(runner.detector.inventory(None), 5, 0)), hovered)  # labelled TIB

    def test_under_fifteen_nothing_moves_and_the_stack_is_remembered(self):
        runner, events, hovered, counts = self.runner(count=14)
        self.assertFalse(runner.stash_product())
        self.assertFalse([e for e in events if e[0] in ("drag", "quantity")])
        before = len(hovered)
        counts["value"] = 15
        self.assertTrue(runner.stash_product())
        self.assertEqual(len(hovered), before)                              # nothing hovered again

    def test_the_next_full_stack_joins_the_one_put_there_last_time(self):
        runner, events, hovered, _ = self.runner(count=15)
        runner.stash_product()
        runner.stash_cell = (0, 1)                                          # where (105, 115) is
        events.clear()
        self.assertTrue(runner.stash_product())
        self.assertEqual([e for e in events if e[0] == "drag"][0][2], (105, 115))

    def test_no_gogo_window_leaves_the_stack_and_says_so(self):
        runner, events, _, _ = self.runner(count=15, gogo_window=False)
        self.assertFalse(runner.stash_product())
        self.assertFalse([e for e in events if e[0] == "drag"])
        self.assertTrue(any("no GoGuardian window" in str(e[1]) for e in events if e[0] == "status"))


class BlueprintRefillTests(unittest.TestCase):
    """Out of blueprints in Inventory: 15 more from GoGuardian (7 Nov). Readers stood in for."""
    BLUEPRINTS, OTHER, TIB = (2, 0), (1, 0), (0, 0)

    def runner(self, blueprints_there=True, window=True):
        from unittest import mock
        events, hovered = [], []

        class Window:
            scale = 1.

            def cell_center(self, col, row):
                return (105 + col*10, 105 + row*10)

            def box(self):
                return (90, 90, 200, 200)

        tips = {Window().cell_center(*self.OTHER): "other", Window().cell_center(*self.TIB): "other"}
        if blueprints_there:
            tips[Window().cell_center(*self.BLUEPRINTS)] = "weaponpart_9"

        class Detector:
            seen = {}

            def inventory(self, f, checkpoint=None):
                return object()

            def text_reader(self):
                return None

            def gray(self, f):
                return np.zeros((10, 10), np.uint8)

            def tooltip_recipe(self, f, point, scale):
                hovered.append(tuple(point))
                return tips.get(tuple(point))

        r = ConstructionRunner.__new__(ConstructionRunner)
        r.detector = Detector();r.recipe = "weaponpart_9";r.name = "Tangent Weaponpart 9";r.profile = {}
        r.frame = lambda: np.zeros((10, 10, 3), np.uint8)
        r.guard = lambda: None
        r.wait = lambda seconds, safe_pause=False: None
        r.move = lambda point: None
        r.step_aside = lambda: None
        r.emit = lambda kind, payload=None: events.append((kind, payload))
        r.drag = lambda a, b: events.append(("drag", tuple(a), tuple(b)))
        r.enter_quantity = lambda amount: events.append(("quantity", amount))
        r.inventory_destination = lambda f, inv, code: (500, 600)
        patches = [mock.patch.object(gogo, "find_gogo", lambda reader, gray, checkpoint=None: Window() if window else None),
                   mock.patch.object(gogo, "read_cells", lambda reader, gray, w, wanted=None: {
                       self.TIB: {"code": "TIB", "count": 185, "point": Window().cell_center(*self.TIB)}}),
                   mock.patch.object(gogo, "occupied_cells", lambda gray, w: [self.TIB, self.OTHER, self.BLUEPRINTS])]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return r, events, hovered

    def test_the_blueprint_stack_is_found_by_its_tooltip_and_fifteen_come_over(self):
        runner, events, hovered = self.runner()
        self.assertTrue(runner.refill_blueprints_from_gogo())
        self.assertIn(("drag", (125, 105), (500, 600)), events)
        self.assertIn(("quantity", 15), events)
        self.assertNotIn((105, 105), hovered)                               # TIB is an ingredient, never hovered

    def test_the_next_time_the_same_stack_is_tried_first_and_others_are_not_hovered_again(self):
        runner, events, hovered = self.runner()
        runner.refill_blueprints_from_gogo()
        hovered.clear()
        runner.refill_blueprints_from_gogo()
        self.assertEqual(hovered, [(125, 105)])

    def test_none_there_or_no_window_moves_nothing_and_says_so(self):
        for there, window, said in ((False, True, "none found in GoGuardian"), (True, False, "no GoGuardian window")):
            with self.subTest(there=there, window=window):
                runner, events, _ = self.runner(blueprints_there=there, window=window)
                self.assertFalse(runner.refill_blueprints_from_gogo())
                self.assertFalse([e for e in events if e[0] == "drag"])
                self.assertTrue(any(said in str(e[1]) for e in events if e[0] == "status"), events)

    def test_a_build_that_runs_out_of_blueprints_takes_more_and_goes_on(self):
        runner, events, _ = self.runner()
        runner.profile = {"construction": {"available": 10000, "gogo_refill": True}}
        runner.queue, runner.job_label, runner.count_slots, runner.stop_at_slots, runner.completed = [], None, False, None, 0
        runner.recipes = {"weaponpart_9": {"name": "Tangent Weaponpart 9", "category": "Weapon parts"}}
        looks = []

        def locate():
            looks.append(1)
            if len(looks) == 1:
                raise Interrupted("No verified Tangent Weaponpart 9 blueprint found in the remaining Inventory rows.")
            return (1, 1), (2, 2)
        runner.locate_blueprint = locate
        runner.confirm_one = lambda available: None
        processor = type("P", (), {"start_point": lambda self: (9, 9)})()
        runner.processor_state = lambda: (None, processor)
        runner.detector.quantity = lambda f, checkpoint=None: None
        runner.detector.has_loaded_blueprint = lambda f, p: True
        runner.click = lambda point: events.append(("click", tuple(point)))
        runner.await_construction = lambda: None
        runner.stash_product = lambda: False
        built, reason = runner.build_job(1, True)
        self.assertEqual((built, reason), (1, "finished"))
        self.assertEqual(len(looks), 2)
        self.assertIn(("quantity", 15), events)


if __name__ == "__main__":
    unittest.main()


class TooltipNameTests(unittest.TestCase):
    def test_names_match_whole_words_only(self):
        names = ["Tangent Weaponpart 1", "Metal D"]
        self.assertEqual(gogo.match_name(["Metal D"], names), "Metal D")
        self.assertEqual(gogo.match_name(["Tangent Weaponpart 10"], names), None)
        self.assertEqual(gogo.match_name(["Quality 80 Tangent Weaponpart 1"], names), "Tangent Weaponpart 1")
        self.assertIsNone(gogo.match_name([], names))

    def test_likely_cells_are_hovered_first(self):
        cells = {(0, 0): {"code": "CUBE"}, (1, 0): {"code": "STS"}, (2, 0): {"code": "W7"}}
        self.assertEqual([k for k, _ in gogo.hover_order(cells, ["Strastin"])][0], (1, 0))
        self.assertTrue(gogo.is_abbreviation("W4", "Tangent Weaponpart 4"))
        self.assertFalse(gogo.is_abbreviation("W5", "Tangent Weaponpart 4"))
