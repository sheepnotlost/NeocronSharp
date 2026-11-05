"""The wasteland world map (traversal/worldmap.py): its file readers and its named places."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "traversal"))
import worldmap  # noqa: E402


class WorldMapTests(unittest.TestCase):
    def test_a_malformed_spawn_file_ends_the_record_list(self):
        self.assertEqual(list(worldmap.elements(b"")), [])
        self.assertEqual(list(worldmap.elements(b"\x04\x00\x00\x00junkjunkjunkjunkjunk")), [])

    def test_names_are_cleaned(self):
        self.assertEqual(worldmap.clean("Yo's Pawn Shop\\nSelling: Tools"), "Yo's Pawn Shop Selling: Tools")
        self.assertEqual(worldmap.clean("---LOW SEC LOGIN--- Plaza1"), "LOW SEC LOGIN Plaza1")

    def test_reference_places_lie_inside_the_wasteland(self):
        # Columns 01-16, rows A-L, measured in cells from the south-west corner.
        for name, gx, gy in worldmap.REFERENCE:
            self.assertTrue(0 <= gx < 16 and 0 <= gy < 12, name)
        canyon = next((gx, gy) for name, gx, gy in worldmap.REFERENCE if name == "Canyon Reloading Point")
        self.assertEqual((chr(65 + int(canyon[1])), int(canyon[0]) + 1), ("F", 12))   # beside Outdoor Cave 3

    @unittest.skipUnless(os.path.isdir(worldmap.INSTALL), "needs the game install")
    def test_a_cells_ground_texture_and_water(self):
        land = worldmap.ground("e_07", 64, texture=8)
        self.assertEqual(land.size, (64, 64))
        sea = worldmap.ground("b_12", 64, texture=8)   # B 12 is mostly sea
        r, g, b = [sum(c) / len(c) for c in zip(*sea.getdata())]
        self.assertGreater(b, r, "the sea is blue")


if __name__ == "__main__":
    unittest.main()
