"""Where the mob that hurt you was: only written down when it can only have been one mob."""
import json
import tempfile
import unittest
from pathlib import Path

import mob_reach
from loot_runner import hunted


def mob(name, distance, dead=False, faction=17):
    return {"id": name, "name": name, "kind": "npc", "distance": distance, "dead": dead, "faction": faction}


class MobReachTests(unittest.TestCase):
    def test_the_only_mob_near_is_written_down(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mob-reach.json"
            self.assertEqual(mob_reach.record(path, [mob("Sandcrawler", 80.4), mob("Rat", 50, dead=True), mob("Rat", 5000)], hunted), ("Sandcrawler", 80.4))
            mob_reach.record(path, [mob("Sandcrawler", 420)], hunted)
            self.assertEqual(json.loads(path.read_text())["Sandcrawler"]["away"], [80, 420])

    def test_two_mobs_near_or_a_human_tell_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mob-reach.json"
            self.assertIsNone(mob_reach.record(path, [mob("Sandcrawler", 80), mob("Viper", 300)], hunted))
            self.assertIsNone(mob_reach.record(path, [mob("City Merc", 80, faction=1)], hunted))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
