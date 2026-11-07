"""The game's pixel font (1024x768, UI scale 1.0): the user's VM screenshots, 7 Nov."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import gogo
import pixelfont
from vision import Detector

FIXTURES = Path(__file__).parent / "fixtures"


def rgb(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)


class PixelFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.windows = rgb("pixel_1024_windows.png")
        cls.dialog = rgb("pixel_quantity_dialog.png")
        cls.tooltip = rgb("pixel_blueprint_tooltip.png")

    def setUp(self):
        self.detector = Detector()

    def test_inventory_is_found_by_its_load_words_and_grid(self):
        inventory = self.detector.inventory(self.windows)
        self.assertEqual((inventory.x, inventory.y), (49, 309))
        self.assertAlmostEqual(inventory.scale, .862, places=2)
        self.assertTrue(self.detector.pixel)
        self.assertTrue(getattr(self.detector.text_reader(), "pixel", False))
        # the cheap re-check keeps it
        self.assertEqual(self.detector.current_inventory(self.windows, inventory), inventory)

    def test_goguardian_labels_and_counts_are_read(self):
        self.detector.inventory(self.windows)
        gray = self.detector.gray(self.windows)
        reader = self.detector.text_reader()
        window = gogo.find_gogo(reader, gray)
        self.assertIsNotNone(window)
        cells = gogo.read_cells(reader, gray, window)
        read = {key: (info["code"], info["count"]) for key, info in cells.items()}
        self.assertEqual(read[(0, 1)], ("GAM", 69))
        self.assertEqual(read[(4, 1)], ("SOL", 199))
        self.assertEqual(read[(1, 2)], ("STS", 184))
        self.assertEqual(read[(3, 2)], ("TIB", 154))
        self.assertEqual(read[(0, 0)], ("W9", 45))
        plan = gogo.plan_refill("weaponpart_9", cells, gogo.ingredients_for("weaponpart_9"))
        self.assertEqual([name for name, *_ in plan], ["Gamonin", "Metal D", "Solantium", "Strastin", "Tiberal"])
        self.assertEqual(plan[3][2], window.cell_center(1, 2))      # Strastin: its x184 stack

    def test_the_quantity_dialog_and_its_one(self):
        self.detector.inventory(self.windows)
        frame = self.windows.copy()
        frame[400:400+self.dialog.shape[0], 300:300+self.dialog.shape[1]] = self.dialog
        dialog = self.detector.quantity(frame)
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog["one"])
        self.assertEqual(dialog["value"], 1)
        # Ok's middle, the field and the X, in the screenshot's own pixels (+ where it was pasted)
        self.assertLess(abs(dialog["ok"][0] - (300+269)) + abs(dialog["ok"][1] - (400+35)), 4)
        self.assertLess(abs(dialog["field"][0] - (300+177)) + abs(dialog["field"][1] - (400+34)), 5)
        self.assertLess(abs(dialog["close"][0] - (300+286)) + abs(dialog["close"][1] - (400+14)), 4)
        self.assertIsNone(self.detector.quantity(self.windows))
        # a 15 is not a 1
        frame[400+29:400+40, 300+164:300+166] = frame[400+29:400+40, 300+170:300+172]
        two = frame.copy()
        two[400+32:400+38, 300+168:300+174] = (220, 220, 220)
        self.assertFalse(self.detector.quantity(two)["one"])

    def test_a_one_with_its_text_cursor_over_another_window(self):
        # 7 Nov: "1_" beside the field's border read as not-one, so the macro closed the box with its X
        dialog = self.detector.pixel_quantity(rgb("pixel_quantity_over_window.png"))
        self.assertTrue(self.detector.pixel is not True or dialog["one"])
        self.detector.pixel = True
        dialog = self.detector.quantity(rgb("pixel_quantity_over_window.png"))
        self.assertTrue(dialog["one"])
        self.assertLess(abs(dialog["ok"][0] - 291) + abs(dialog["ok"][1] - 90), 8)

    def test_the_blueprint_tooltip_is_read(self):
        self.detector.inventory(self.windows)
        frame = self.windows.copy()
        frame[300:300+self.tooltip.shape[0], 40:40+self.tooltip.shape[1]] = self.tooltip
        point = (40+140, 300+35)
        self.assertEqual(self.detector.tooltip_recipe(frame, point, .862), "weaponpart_9")
        self.assertIn("WEAPONPART 9", self.detector.last_tooltip_raw)
        self.assertIsNone(self.detector.tooltip_recipe(self.windows, point, .862))
        self.detector.recipes = {key: value for key, value in self.detector.recipes.items() if key != "weaponpart_9"}
        self.assertEqual(self.detector.tooltip_recipe(frame, point, .862), "unknown")

    def test_letters_drawn_like_digits_settle_by_word(self):
        self.assertEqual(pixelfont._settle("50L"), "SOL")
        self.assertEqual(pixelfont._settle("5T5"), "STS")
        self.assertEqual(pixelfont._settle("X150"), "X150")
        self.assertEqual(pixelfont._settle("150"), "150")
        self.assertTrue(pixelfont.same_name("TANGENT WEAP0NPART 9", "Tangent Weaponpart 9"))
        self.assertFalse(pixelfont.same_name("TANGENT WEAPONPART 9", "Tangent Weaponpart 7"))
        self.assertFalse(pixelfont.same_name("TANGENT WEAPONPART 91", "Tangent Weaponpart 9"))

    def test_other_fonts_turn_the_pixel_search_off(self):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with self.assertRaises(RuntimeError):
            self.detector.inventory(frame)
        self.assertIsNot(self.detector.pixel, True)


if __name__ == "__main__":
    unittest.main()
