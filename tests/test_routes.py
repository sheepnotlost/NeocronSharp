"""Route library: area names, recording, hints and the area map."""
from pathlib import Path
import tempfile
import unittest

import cv2

import routes

FIXTURES = Path(__file__).parent / "fixtures"


class RouteTests(unittest.TestCase):
    def test_area_names_are_normalised(self):
        for raw in ("PLAZASEC-1 J", "PLAZA SEC-I", "PLAZA  SEC-1 B", "OUTZONE SEC-3"):
            self.assertRegex(routes.normalize_area(raw), r"^[A-Z]+ SEC-\d$")
        self.assertEqual(routes.normalize_area("PLAZASEC-1 J"), "PLAZA SEC-1")
        self.assertEqual(routes.normalize_area("PLAZA SEC-I"), "PLAZA SEC-1")
        self.assertEqual(routes.normalize_area("NEOCRON SUBWAY"), "NEOCRON SUBWAY")

    def test_the_location_is_read_from_a_real_frame(self):
        for name in ("navray_straight_ahead_2000.png", "navray_sparse_big_dashes_2560.png"):
            gray = cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2GRAY)
            self.assertEqual(routes.read_area(gray), "PLAZA SEC-1")

    def test_walks_are_recorded_kept_best_and_mapped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "routes.json"
            book = routes.RouteBook(path)
            legs = [{"turn": -40, "seconds": 3.0, "dashes": 4, "reason": "passed 4 dashes"}]
            book.record("PLAZA SEC-1", "TRADER DIRECTORY > WEAPONS", "PLAZA SEC-1", legs, 30.0)
            slower = book.record("PLAZA SEC-1", "TRADER DIRECTORY > WEAPONS", "PLAZA SEC-1", [{"turn": 90}], 50.0)
            self.assertEqual(slower["walks"], 2)
            self.assertEqual(slower["seconds"], 30.0)                      # the quicker walk stays the best
            book.record("PLAZA SEC-1", "FACTION HQS > BLACK DRAGON", "VIAROSSO SEC-2", [], 12.0)
            book.save()
            again = routes.RouteBook(path)
            self.assertEqual(again.first_turn("PLAZA SEC-1", "TRADER DIRECTORY > WEAPONS"), -1)   # looked left first
            self.assertEqual(again.first_turn("PLAZA SEC-1", "unknown"), 0)
            area = again.areas()["PLAZA SEC-1"]
            self.assertEqual(area["routes"], 2)
            self.assertEqual(area["leads_to"], ["PLAZA SEC-1", "VIAROSSO SEC-2"])

    def test_a_missing_or_broken_library_starts_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "routes.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(routes.RouteBook(path).data, {"routes": {}})
