"""Traversal tab: the place list, Find, sections and the follow list, from canned engine JSON (no engine, no input)."""
import json
import subprocess
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import traversal_tab as tt

ALLPLACES = json.dumps({
    "here": {"zone": 1, "name": "PLAZA SEC-1", "live": True, "x": -1121.4, "z": 2922.2},
    "places": [
        {"zone": 1, "zoneName": "PLAZA SEC-1", "away": 0, "target": "-1,2,3", "name": "ARCHER SHOP", "kind": "Trader", "category": ""},
        {"zone": 1, "zoneName": "PLAZA SEC-1", "away": 0, "target": "apt:1", "name": "PLAZA APARTMENT 1", "kind": "Apartment door", "category": "PLAZA APARTMENTS"},
        {"zone": 1, "zoneName": "PLAZA SEC-1", "away": 0, "target": "exit:Pub", "name": "PEPPER PUB", "kind": "Entrance", "category": ""},
        {"zone": 1, "zoneName": "PLAZA SEC-1", "away": 0, "target": "4,5,6", "name": "Nearest GenRep: GENE REPLICATOR 2", "kind": "Nearest", "category": "UTILITIES"},
        {"zone": 1, "zoneName": "PLAZA SEC-1", "away": 0, "target": "arrive", "name": "PLAZA SEC-1", "kind": "Zone", "category": "NEOCRON CITY SECTORS"},
        {"zone": 2, "zoneName": "PLAZA SEC-2", "away": 1, "target": "exit:Club", "name": "VENUS CLUB", "kind": "Entrance", "category": ""},
        {"zone": 2, "zoneName": "PLAZA SEC-2", "away": 1, "target": "arrive", "name": "PLAZA SEC-2", "kind": "Zone", "category": ""},
        {"zone": 1573, "zoneName": "Reactor Room", "away": 2, "target": "arrive", "name": "REACTOR ROOM", "kind": "Entrance", "category": "JONES MISSION LOCATIONS"},
        {"zone": 1064, "zoneName": "ABANDONED CELLAR", "away": 1, "target": "arrive", "name": "ABANDONED CELLAR", "kind": "Entrance", "category": "PLAZA DUNGEONS"},
        {"zone": 2001, "zoneName": "OUTPOST A", "away": 3, "target": "arrive", "name": "CRASHED BIRD", "kind": "Uplink", "category": "Wasteland"},
    ],
    "notPlaced": [{"category": "UTILITIES", "name": "PRIMARY APARTMENT", "why": "your own apartment: not in the game files"}],
})
NEARBY = {"live": True, "sectorName": "PLAZA SEC-1", "entities": [
    {"id": "n1", "name": "Copbot", "kind": "npc", "distance": 12.0, "dead": False},
    {"id": "p2", "name": "Faraway", "kind": "player", "distance": 300.0, "dead": False},
    {"id": "p1", "name": "Buddy", "kind": "player", "distance": 40.0, "dead": False},
    {"id": "n2", "name": "Rat", "kind": "npc", "distance": 5.0, "dead": True},
]}


class ListTests(unittest.TestCase):
    def setUp(self):
        self.here, self.places = tt.parse_allplaces(ALLPLACES)

    def test_sections_in_order_with_headers(self):
        sections = tt.build_sections(self.places)
        self.assertEqual([s["key"] for s in sections], ["1", "2", tt.BUILDINGS, tt.OUTPOSTS, tt.NOT_YET])
        self.assertEqual(sections[0]["title"], "PLAZA SEC-1  ·  you are here  ·  5 places")
        self.assertEqual(sections[1]["title"], "PLAZA SEC-2  ·  1 zone away  ·  2 places")
        self.assertEqual(sections[2]["title"], "More buildings and dungeons  ·  2 places")
        self.assertEqual(sections[3]["title"], "Wasteland outposts and landmarks  ·  1 place")
        self.assertEqual(sections[4]["title"], "Not walkable yet  ·  1 place")

    def test_order_within_a_zone(self):
        kinds = [p["kind"] for _, p in tt.build_sections(self.places)[0]["places"]]
        self.assertEqual(kinds, ["Zone", "Nearest", "Entrance", "Apartment door", "Trader"])

    def test_single_place_interiors_are_pooled_nearest_first(self):
        sections = {s["key"]: s for s in tt.build_sections(self.places)}
        pooled = [p["zoneName"] for _, p in sections[tt.BUILDINGS]["places"]]
        self.assertEqual(pooled, ["ABANDONED CELLAR", "Reactor Room"])
        self.assertEqual([p["name"] for _, p in sections[tt.OUTPOSTS]["places"]], ["CRASHED BIRD"])
        name, kind = tt.place_text(sections[tt.BUILDINGS]["places"][0][1], True)
        self.assertEqual(name, "Abandoned Cellar   (ABANDONED CELLAR, 1 zone away)")
        self.assertEqual(kind, "Plaza Dungeons")
        self.assertEqual(tt.place_text(self.places[4], False), ("PLAZA SEC-1  (anywhere)", "Neocron City Sectors"))

    def test_not_placed_rows_are_never_walkable(self):
        grey = [p for p in self.places if p["why"]]
        self.assertEqual(len(grey), 1)
        self.assertFalse(tt.walkable(grey[0]))
        self.assertTrue(all(tt.walkable(p) for p in self.places if not p["why"]))

    def test_find_matches_name_zone_type_and_category(self):
        def found(text):
            return sorted(p["name"] for s in tt.build_sections(self.places, text) for _, p in s["places"])
        self.assertEqual(found("pepper"), ["PEPPER PUB"])
        self.assertEqual(found("reactor room"), ["REACTOR ROOM"])                 # zone name
        self.assertEqual(found("apartment door"), ["PLAZA APARTMENT 1"])          # type
        self.assertEqual(found("dungeons"), ["ABANDONED CELLAR"])                 # category
        self.assertEqual(found("nothing like this"), [])

    def test_follow_list_puts_players_first_then_nearest(self):
        actors = [dict(e) for e in NEARBY["entities"]]
        self.assertEqual([a["name"] for a in tt.order_actors(actors)], ["Buddy", "Faraway", "Rat", "Copbot"])
        self.assertEqual([a["name"] for a in tt.order_actors(actors, "far")], ["Faraway"])

    def test_title_keeps_short_and_numbered_words(self):
        self.assertEqual(tt.title("PEPPER PUB"), "Pepper Pub")
        self.assertEqual(tt.title("NExT HQ SEC-1"), "NExT HQ SEC-1")


class FakeProcess:
    def __init__(self, exits):
        self.exits, self.killed = exits, False

    def wait(self, timeout=None):
        if not self.exits and not self.killed:
            raise subprocess.TimeoutExpired("traversal", timeout)
        return 0

    def kill(self):
        self.killed = True


class StopTests(unittest.TestCase):
    def test_f8_held_until_the_walker_exits(self):
        keys = []
        tt.stop_walk(FakeProcess(exits=True), key=lambda *k: keys.append(k))
        self.assertEqual(keys, [(0x77, 0x42, 0), (0x77, 0x42, 2)])

    def test_a_walker_that_will_not_stop_is_ended_and_its_keys_released(self):
        keys, process = [], FakeProcess(exits=False)
        tt.stop_walk(process, key=lambda *k: keys.append(k))
        self.assertTrue(process.killed)
        self.assertEqual(keys, [(0x77, 0x42, 0), (0x77, 0x42, 2), (0, 0x11, 0x0A), (0, 0x2A, 0x0A)])


class TabTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.frame = tk.Frame(self.root)
        self.frame.pack()
        self.tab = tt.TraversalTab(self.frame, self.root, autoload=False)
        self.tab.show_allplaces(("ok", json.loads(ALLPLACES)))

    def tearDown(self):
        self.tab.close()
        self.root.destroy()

    def log(self):
        return self.tab.log.get("1.0", "end").strip()

    def test_status_line_and_only_your_zone_open(self):
        self.assertEqual(self.tab.status.get(), "PLAZA SEC-1  ·  you are at -1121, 2922  ·  10 places to walk to")
        self.assertEqual(self.tab.sections_shown(), [("1", True), ("2", False), (tt.BUILDINGS, False),
                                                     (tt.OUTPOSTS, False), (tt.NOT_YET, False)])
        self.assertEqual(len(self.tab.tree.get_children("s:1")), 5)
        self.assertEqual(self.tab.tree.item("s:" + tt.NOT_YET, "text"), "Not walkable yet  ·  1 place")
        self.assertEqual(str(self.tab.walk_button.cget("state")), "disabled")

    def test_greyed_row_shows_its_reason_and_cannot_be_walked(self):
        grey = self.tab.tree.get_children("s:" + tt.NOT_YET)[0]
        self.assertIn("grey", self.tab.tree.item(grey, "tags"))
        self.tab.tree.selection_set(grey)
        self.root.update()
        self.assertEqual(str(self.tab.walk_button.cget("state")), "disabled")
        self.assertEqual(str(self.tab.show_button.cget("state")), "disabled")
        self.assertIn("Primary Apartment: not walkable yet (your own apartment", self.log())
        with patch.object(self.tab, "start_live") as start, patch.object(self.tab, "start_offline") as offline:
            self.tab.walk()
            self.tab.show_route()
        start.assert_not_called()
        offline.assert_not_called()

    def test_walk_there_runs_travel_for_the_selected_place(self):
        pub = next(iid for iid, p in self.tab.rows.items() if p["name"] == "PEPPER PUB")
        self.tab.tree.selection_set(pub)
        self.root.update()
        self.assertEqual(str(self.tab.walk_button.cget("state")), "normal")
        with patch.object(self.tab, "start_live") as start:
            self.tab.walk()
        start.assert_called_once_with("walk", ["travel", "1", "exit:Pub", "--pulse", "12", "--run"])
        self.assertIn("Running to Pepper Pub in PLAZA SEC-1", self.log())

    def test_find_opens_matches_and_clearing_restores_sections(self):
        self.tab.find.set("cellar")
        self.assertEqual(self.tab.sections_shown(), [(tt.BUILDINGS, True)])
        self.tab.find.set("")
        self.assertEqual(self.tab.sections_shown()[1], ("2", False))

    def test_open_all_close_all_and_kept_choices(self):
        self.tab.set_all_sections(True)
        self.assertTrue(all(is_open for _, is_open in self.tab.sections_shown()))
        self.tab.set_all_sections(False)
        self.assertFalse(any(is_open for _, is_open in self.tab.sections_shown()))
        self.tab.show_places()                                   # a refresh keeps what the user closed
        self.assertFalse(any(is_open for _, is_open in self.tab.sections_shown()))

    def test_follow_mode_lists_players_first_and_never_follows_the_dead(self):
        self.tab.mode.set("follow")
        self.tab.mode_changed()
        self.tab.show_nearby(("ok", NEARBY))
        names = [self.tab.actor_tree.item(i, "values")[0] for i in self.tab.actor_tree.get_children()]
        self.assertEqual(names, ["Buddy", "Faraway", "Rat  (dead)", "Copbot"])
        self.assertEqual(self.tab.status.get(), "PLAZA SEC-1  ·  2 players and 2 NPCs around you")
        self.assertEqual(self.tab.distance.get(), "150")
        dead = self.tab.actor_tree.get_children()[2]
        self.tab.actor_tree.selection_set(dead)
        self.root.update()
        self.assertEqual(str(self.tab.follow_button.cget("state")), "disabled")
        self.tab.actor_tree.selection_set(self.tab.actor_tree.get_children()[0])
        self.root.update()
        with patch.object(self.tab, "start_live") as start:
            self.tab.follow()
        start.assert_called_once_with("follow", ["follow", "p1", "--distance", "150", "--pulse", "12", "--run"])
        self.tab.find_actor.set("cop")
        self.assertEqual(len(self.tab.actor_tree.get_children()), 1)


class AppTests(unittest.TestCase):
    def test_traversal_tab_has_no_start(self):
        from app import App

        class NoInput:
            def release_all(self):
                pass
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            app = App(root, profile_path=Path(folder) / "profile.json", backend=NoInput())
            try:
                self.assertEqual(app.tabs.tab(app.traversal_tab, "text"), "Traversal")
                self.assertFalse(app.traversal.autoload)
                app.tabs.select(app.traversal_tab)
                root.update()
                self.assertEqual(str(app.start_button.cget("state")), "disabled")
                with self.assertRaises(ValueError):
                    app.collect()
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
