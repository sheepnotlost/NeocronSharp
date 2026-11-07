"""The team panel's bars, buff icons and timers (2560x1440 game, 7 Nov)."""
from pathlib import Path
import unittest

import cv2
import numpy as np

import team_panel
from text_reader import TextReader

FIXTURES = Path(__file__).parent / "fixtures"


def frame(name, y):
    crop = cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)
    big = np.zeros((1125, 2000, 3), np.uint8)
    big[y:y+crop.shape[0], 0:crop.shape[1]] = crop
    return big


class TeamPanelTests(unittest.TestCase):
    def test_one_member_with_four_buffs(self):
        members = team_panel.read(frame("team_panel_one.png", 480), TextReader(), team_panel.references())
        self.assertEqual(len(members), 1)
        self.assertEqual((members[0].name, members[0].health), ("Canibaal", 100))
        self.assertEqual(members[0].buffs, {5: 496, 2: 87, 4: 80, 3: 84})

    def test_two_members_stacked_the_second_with_no_buffs_and_less_health(self):
        a, b = team_panel.read(frame("team_panel_two.png", 410), TextReader(), team_panel.references())
        self.assertEqual((a.name, a.health, a.buffs), ("Canibaal", 100, {5: 240}))
        self.assertEqual((b.name, b.health, b.buffs), ("Bertel", 97, {}))

    def test_no_panel_no_members(self):
        self.assertEqual(team_panel.read(np.zeros((1125, 2000, 3), np.uint8), TextReader(), team_panel.references()), [])


if __name__ == "__main__":
    unittest.main()
