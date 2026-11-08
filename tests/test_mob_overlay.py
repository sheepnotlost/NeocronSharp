"""Mobs on map: mobs land where the game's map puts them, one colour per kind, people in grey."""
import unittest

import numpy as np

import mob_overlay as mo


def data(*mobs):
    return {"sectorName": "K 11 - DESERT", "player": {"x": -12813, "z": 7590},
            "entities": [{"name": n, "kind": "npc", "dead": False, "factionId": f, "x": x, "z": z} for n, f, x, z in mobs]}


class MobOverlayTests(unittest.TestCase):
    def test_a_wasteland_mob_lands_where_the_games_map_has_it(self):
        img = mo.render(data(("Sand Snake", 18, 0, 0)), np.zeros(512 * 512, np.float32), half=16384)
        middle = img[40 + mo.SIZE // 2, mo.SIZE // 2]          # the sector's middle, under the 40-pixel title
        self.assertEqual(tuple(int(c) for c in middle), mo.COLORS[0])
        to_px = mo.frame(data(), 16384)
        self.assertEqual(to_px(-12813, 7590), (int(3571 / 32768 * mo.SIZE), int(23974 / 32768 * mo.SIZE)))   # K 11, 8 Nov

    def test_people_are_grey_and_left_out_of_the_legend(self):
        img = mo.render(data(("Sand Snake", 18, 100, 100), ("Pathfinder Soldier", 19, 2000, 2000)))
        self.assertEqual(img.shape[0], mo.SIZE + 50 + mo.LEGEND * 4 + 10)    # one kind, people, you, the note


if __name__ == "__main__":
    unittest.main()
