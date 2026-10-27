from pathlib import Path
import random
import unittest

from vision import Ambiguous, Detector, NotFound, cv2, np

FIXTURES = Path(__file__).parent / "fixtures"


def read_image(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB)


def scene(processor=(200, 200), inventory=(1800, 700), loaded=False, initial=False):
    frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
    frame[:] = (65, 70, 60)
    for point, name in ((processor, "processor_initial" if initial else "processor_loaded" if loaded else "processor_idle"),
                        (inventory, "inventory")):
        x, y = point
        image = read_image(name)
        h, w = image.shape[:2]
        frame[y:y+h, x:x+w] = image
    return frame


class DetectionTests(unittest.TestCase):
    def test_actual_overlapping_processor_busy_and_done_after_relocation(self):
        detector = Detector()
        for name, busy in (("processor_overlap_busy", True), ("processor_overlap_done", False)):
            image = read_image(name)
            for x, y in ((1283, 412), (40, 40), (1750, 1000)):
                frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
                frame[y:y+208, x:x+516] = image
                anchor = detector.processor(frame)
                self.assertAlmostEqual(anchor.x, x+26, delta=1)
                self.assertAlmostEqual(anchor.y, y, delta=1)
                start = anchor.start_point()
                self.assertAlmostEqual(start[0], x+448, delta=1)
                self.assertAlmostEqual(start[1], y+174, delta=1)
                self.assertEqual(detector.blueprint_state(frame, anchor), {"busy": busy, "result": not busy})

    def test_processor_subpixel_rendering_variations_preserve_start_position(self):
        image = read_image("processor_overlap_done")
        detector = Detector()
        for dx, dy in ((0, 0), (.25, .25), (.5, .5), (.75, .75), (.25, .75), (.75, .25)):
            with self.subTest(dx=dx, dy=dy):
                frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
                x, y = 400, 500
                frame[y:y+208, x:x+516] = image
                frame = cv2.warpAffine(frame, np.float32([[1, 0, dx], [0, 1, dy]]), (1920, 1080))
                anchor = detector.processor(frame)
                start = anchor.start_point()
                self.assertAlmostEqual(start[0], x+448+dx, delta=2)
                self.assertAlmostEqual(start[1], y+174+dy, delta=2)
                self.assertEqual(detector.blueprint_state(frame, anchor), {"busy": False, "result": True})

    def test_different_processor_rendering_variations_still_reject_duplicate_windows(self):
        frame = scene()
        image = read_image("processor_overlap_done")
        frame[900:1108, 700:1216] = image
        with self.assertRaises(Ambiguous):
            Detector().processor(frame)

    def test_actual_apartment_processor_is_recognized_after_relocation(self):
        crop = read_image("processor_apartment")
        detector = Detector()
        for x, y in ((904, 696), (40, 40), (1700, 1000)):
            frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
            frame[y:y+208, x:x+516] = crop
            anchor = detector.processor(frame)
            self.assertEqual((anchor.x, anchor.y), (x+26, y))
            self.assertEqual(anchor.point(421, 174), [x+447, y+174])
            self.assertEqual(detector.blueprint_state(frame, anchor), {"busy": False, "result": True})

    def test_processor_opaque_caption_does_not_depend_on_translucent_trim(self):
        frame = scene()
        caption = frame[203:219, 244:352].copy()
        frame[200:227, 226:378] = (170, 30, 60)
        frame[203:219, 244:352] = caption
        anchor = Detector().processor(frame)
        self.assertEqual((anchor.x, anchor.y), (226, 200))

    def test_processor_navigation_caption_without_start_does_not_create_ambiguity(self):
        frame = scene()
        title = cv2.imread(str(Path(__file__).parents[1] / "assets" / "processor_title.png"), 0)
        frame[45:61, 1030:1138] = cv2.cvtColor(title, cv2.COLOR_GRAY2RGB)
        anchor = Detector().processor(frame)
        self.assertEqual((anchor.x, anchor.y), (226, 200))

    def test_processor_caption_alone_never_selects_a_start_coordinate(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        title = cv2.imread(str(Path(__file__).parents[1] / "assets" / "processor_title.png"), 0)
        frame[45:61, 1030:1138] = cv2.cvtColor(title, cv2.COLOR_GRAY2RGB)
        with self.assertRaises(NotFound):
            Detector().processor(frame)

    def test_processor_can_recover_from_an_outdated_scale_hint(self):
        detector = Detector()
        detector.last_scale = .75
        anchor = detector.processor(scene())
        self.assertEqual((anchor.x, anchor.y, anchor.scale), (226, 200, 1))

    def test_random_processor_positions_at_2560_by_1440(self):
        rng = random.Random(32)
        detector = Detector()
        for _ in range(6):
            x, y = rng.randrange(10, 1200), rng.randrange(10, 1100)
            frame = scene((x, y))
            anchor = detector.processor(frame)
            self.assertEqual((anchor.x, anchor.y), (x+26, y))
            self.assertEqual(detector.empty_input(frame, anchor), 1)

    def test_real_initial_processor_artwork_with_different_background(self):
        frame = scene(initial=True)
        anchor = Detector().processor(frame)
        self.assertEqual((anchor.x, anchor.y), (226, 200))

    def test_loaded_slot_detected_after_translation(self):
        frame = scene((900, 950), loaded=True)
        detector = Detector()
        anchor = detector.processor(frame)
        self.assertTrue(detector.occupied(frame, anchor, 1))
        with self.assertRaises(Ambiguous):
            detector.empty_input(frame, anchor)

    def test_hidden_processor_never_produces_old_coordinates(self):
        detector = Detector()
        detector.processor(scene())
        with self.assertRaises(NotFound):
            detector.processor(np.zeros((1440, 2560, 3), dtype=np.uint8))

    def test_duplicate_processor_is_ambiguous(self):
        frame = scene()
        image = read_image("processor_idle")
        frame[900:1108, 500:1016] = image
        with self.assertRaises(Ambiguous):
            Detector().processor(frame)

    def test_title_alone_without_start_is_rejected(self):
        frame = scene()
        frame[350:405, 580:705] = 0
        with self.assertRaises(NotFound):
            Detector().processor(frame)

    def test_stack_labels_follow_inventory_translation(self):
        detector = Detector()
        for x, y in ((1800, 700), (900, 400), (20, 900)):
            frame = scene((200, 100), (x, y))
            detector.processor(frame)
            found = detector.stacks(frame)
            for name in "TEA":
                self.assertEqual(len(found[name]), 1, (name, found))
            self.assertEqual(found["T"][0], [x+351, y+86])
            self.assertFalse(found["L"])  # L is not visible in the user's recording.

    def test_actual_current_inventory_and_stack_positions(self):
        image = read_image("inventory_current")
        for x, y in ((40, 40), (1750, 850)):
            frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
            frame[y:y+488, x:x+680] = image
            detector = Detector()
            detector.last_scale = 4/3
            inventory = detector.inventory(frame)
            self.assertEqual((inventory.x, inventory.y), (x+32, y+4))
            found = detector.stacks(frame)
            self.assertEqual(found["T"], [[x+471, y+118]])
            self.assertEqual(found["E"], [[x+530, y+118]])
            self.assertEqual(found["A"], [[x+530, y+300]])
            self.assertFalse(found["L"])

    def test_inventory_does_not_require_old_window_trim(self):
        frame = scene()
        # Remove the trim that the old full-header template depended on.
        frame[700:729, 1800:2300] = (180, 40, 70)
        original = read_image("inventory")
        frame[703:719, 1848:1955] = original[3:19, 48:155]
        detector = Detector()
        inventory = detector.inventory(frame)
        self.assertEqual((inventory.x, inventory.y), (1822, 700))
        self.assertEqual(len(detector.stacks(frame)["T"]), 1)

    def test_inventory_title_without_load_headers_is_rejected(self):
        frame = scene()
        frame[735:770, 1850:2300] = 0
        with self.assertRaises(NotFound):
            Detector().inventory(frame)

    def test_duplicate_inventory_is_ambiguous(self):
        frame = scene()
        image = read_image("inventory")
        frame[800:1154, 200:700] = image
        with self.assertRaises(Ambiguous):
            Detector().inventory(frame)

    def test_inventory_search_can_recover_from_an_outdated_scale_hint(self):
        frame = scene()
        detector = Detector()
        detector.last_scale = 1.7
        inventory = detector.inventory(frame)
        self.assertEqual(inventory.scale, 1.0)

    def test_l_label_recognized_using_same_game_font(self):
        detector = Detector()
        # Put the shipped L glyph on a green slot, using the game's own font.
        glyph = cv2.imread(str(Path(__file__).parents[1] / "assets" / "label_L.png"), 0)
        cell = np.zeros((46, 45, 3), dtype=np.uint8)
        cell[:] = (25, 90, 60)
        h, w = glyph.shape
        cell[5:5+h, 4:4+w][glyph > 127] = (200, 220, 210)
        self.assertEqual(detector.read_label(cell), "L")

    def test_quantity_dialog_moves_independently(self):
        detector = Detector()
        detector.last_scale = 1.0
        for x, y in ((30, 40), (800, 1100), (2100, 200)):
            frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
            image = read_image("quantity")
            frame[y:y+62, x:x+323] = image
            dialog = detector.quantity(frame)
            self.assertEqual(dialog["field"], [x+184, y+32])
            self.assertEqual(dialog["ok"], [x+293, y+32])
            self.assertTrue(dialog["one"])

    def test_current_user_quantity_dialog_at_actual_rendered_scale(self):
        for x, y in ((20, 40), (1300, 900)):
            frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
            image = read_image("quantity_current")
            frame[y:y+98, x:x+450] = image
            detector = Detector()
            detector.last_scale = 4/3
            dialog = detector.quantity(frame)
            self.assertIsNotNone(dialog)
            self.assertEqual(dialog["field"], [x+253, y+50])
            self.assertEqual(dialog["ok"], [x+398, y+50])
            self.assertTrue(dialog["one"])

    def test_quantity_eleven_is_not_mistaken_for_one(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        image = read_image("quantity_current")
        image[46:60, 247:254] = image[46:60, 234:241]
        frame[100:198, 200:650] = image
        detector = Detector()
        detector.last_scale = 4/3
        dialog = detector.quantity(frame)
        self.assertIsNotNone(dialog)
        self.assertFalse(dialog["one"])

    def test_scaled_processor_geometry(self):
        original = scene()
        for scale in (1.25, 1.7):
            frame = cv2.resize(original, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            detector = Detector()
            anchor = detector.processor(frame)
            self.assertAlmostEqual(anchor.scale, scale)
            self.assertAlmostEqual(anchor.x, 226*scale, delta=1)
            self.assertAlmostEqual(anchor.y, 200*scale, delta=1)
            self.assertFalse(detector.occupied(frame, anchor, 1))

    def test_stack_labels_at_larger_rendered_scales(self):
        for scale in (1.25, 4/3, 1.5, 1.7):
            frame = cv2.resize(scene(), None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            detector = Detector()
            detector.processor(frame)
            found = detector.stacks(frame)
            for name in "TEA":
                self.assertEqual(len(found[name]), 1, (scale, name, found))

    def test_all_four_stack_labels_with_synthetic_l_stack(self):
        frame = scene()
        # The recording has T/E/A. Compose the game's L glyph over a copied tech
        # tile to verify L handling without claiming a real recorded L stack.
        tile = frame[763:809, 2129:2173].copy()
        tile[2:17, 2:14] = tile[2, 2]
        glyph = cv2.imread(str(Path(__file__).parents[1] / "assets" / "label_L.png"), 0)
        h, w = glyph.shape
        tile[5:5+h, 4:4+w][glyph > 127] = (200, 220, 210)
        frame[991:1037, 2129:2173] = tile
        for scale in (1.0, 1.7):
            scaled = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            detector = Detector()
            detector.processor(scaled)
            found = detector.stacks(scaled)
            for name in "TEAL":
                self.assertEqual(len(found[name]), 1, (scale, name, found))


if __name__ == "__main__":
    unittest.main()
