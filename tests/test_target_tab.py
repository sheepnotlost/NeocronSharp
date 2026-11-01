"""Target Acquisition tab: the actor list and the camera command, from canned engine JSON (no engine, no input)."""
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import clients
import target_tab
from test_traversal_tab import NEARBY


class TargetTabTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.frame = tk.Frame(self.root)
        self.frame.pack()
        self.walking = False
        self.tab = target_tab.TargetTab(self.frame, self.root, autoload=False, other_live=lambda: self.walking)
        self.tab.show_nearby(("ok", NEARBY))

    def tearDown(self):
        self.tab.close()
        self.root.destroy()

    def log(self):
        return self.tab.log.get("1.0", "end").strip()

    def test_lists_players_first_and_never_tracks_the_dead(self):
        names = [self.tab.tree.item(i, "values")[0] for i in self.tab.tree.get_children()]
        self.assertEqual(names, ["Buddy", "Faraway", "Rat  (dead)", "Copbot"])
        self.assertEqual(self.tab.status.get(), "PLAZA SEC-1  ·  2 players and 2 NPCs around you")
        self.assertEqual(str(self.tab.track_button.cget("state")), "disabled")
        self.tab.tree.selection_set(self.tab.tree.get_children()[2])
        self.root.update()
        self.assertEqual(str(self.tab.track_button.cget("state")), "disabled")
        with patch.object(self.tab, "start_live") as start:
            self.tab.track()
        start.assert_not_called()

    def test_track_runs_the_camera_command_and_nothing_that_walks(self):
        self.tab.tree.selection_set(self.tab.tree.get_children()[0])
        self.root.update()
        with patch.object(self.tab, "start_live") as start:
            self.tab.track()
        start.assert_called_once_with(["camera", "p1", "--pulse", "24"])
        self.assertIn("Keeping the camera on Buddy", self.log())

    def test_holds_the_left_button_on_an_npc_when_asked(self):
        self.tab.tree.selection_set(self.tab.tree.get_children()[3])
        self.root.update()
        self.assertEqual(str(self.tab.hold_check.cget("state")), "normal")
        self.tab.hold_left.set(True)
        with patch.object(self.tab, "start_live") as start:
            self.tab.track()
        start.assert_called_once_with(["camera", "n1", "--pulse", "24", "--hold-left"])
        self.assertIn("left mouse button held", self.log())

    def test_never_holds_the_left_button_on_a_player(self):
        self.tab.hold_left.set(True)
        self.tab.tree.selection_set(self.tab.tree.get_children()[0])
        self.root.update()
        self.assertEqual(str(self.tab.hold_check.cget("state")), "disabled")
        with patch.object(self.tab, "start_live") as start:
            self.tab.track()
        start.assert_called_once_with(["camera", "p1", "--pulse", "24"])
        self.assertNotIn("left mouse button", self.log())

    def test_follow_and_heal_is_for_living_players(self):
        children = self.tab.tree.get_children()
        self.tab.tree.selection_set(children[3])
        self.root.update()
        self.assertEqual(str(self.tab.heal_button.cget("state")), "disabled")
        with patch.object(self.tab, "start_live") as start:
            self.tab.heal()
        start.assert_not_called()
        self.tab.clients = [{"pid": 1, "label": "a"}, {"pid": 2, "label": "b"}]
        self.tab.tree.selection_set(children[0])
        self.root.update()
        self.assertEqual(str(self.tab.heal_button.cget("state")), "normal")
        with patch.object(self.tab, "start_live") as start:
            self.tab.heal()
        start.assert_called_once_with(["heal", "p1"])

    def test_alone_in_a_vm_it_heals_only_the_named_fighter_with_real_input(self):
        children = self.tab.tree.get_children()
        self.tab.clients = [{"pid": 1, "label": "a"}]
        self.tab.tree.selection_set(children[0])
        self.root.update()
        self.assertEqual(str(self.tab.heal_button.cget("state")), "disabled")
        with patch.object(self.tab, "start_live") as start:
            self.tab.heal()
        start.assert_not_called()
        self.tab.fighter.set(" buddy ")
        self.root.update()
        self.assertEqual(str(self.tab.heal_button.cget("state")), "normal")
        with tempfile.TemporaryDirectory() as folder, patch.object(target_tab, "FIGHTER_FILE", Path(folder) / "fighter.txt"), \
                patch.object(self.tab, "start_live") as start:
            self.tab.heal()
            self.assertEqual(target_tab.FIGHTER_FILE.read_text(encoding="utf-8"), "Buddy")
        start.assert_called_once_with(["follow", "p1", "--heal", "--distance", "120", "--pulse", "24"])

    def test_a_healer_alone_goes_back_to_the_fighter_until_stopped(self):
        self.tab.heal_name = "Buddy"
        self.tab.process = object()
        with patch.object(self.tab, "refresh"):
            self.tab.finished()
        self.assertIsNotNone(self.tab.heal_retry)
        self.assertTrue(self.tab.steering())
        with patch.object(self.tab, "start_alone") as start:
            self.tab.fighter_seen({"entities": [{"id": "p1", "name": "Buddy", "kind": "player", "dead": True}]})
            start.assert_not_called()
            self.root.after_cancel(self.tab.heal_retry)
            self.tab.fighter_seen({"entities": [{"id": "p9", "name": "buddy", "kind": "player", "dead": False}]})
        start.assert_called_once_with("p9")
        self.tab.heal_retry = self.root.after(60000, lambda: None)
        with patch.object(self.tab, "refresh"):
            self.tab.stop()
        self.assertIsNone(self.tab.heal_retry)
        self.assertIsNone(self.tab.heal_name)
        self.assertFalse(self.tab.steering())

    def test_f8_ends_a_healer_alone_too(self):
        self.tab.heal_name = "Buddy"
        self.tab.last_line = "Stop pressed."
        with patch.object(self.tab, "refresh"):
            self.tab.finished()
        self.assertIsNone(self.tab.heal_name)
        self.assertIsNone(self.tab.heal_retry)

    def test_enemy_list_groups_living_npcs_and_never_lists_players(self):
        actors = [{"name": "Rat", "kind": "npc", "distance": 900., "dead": False}, {"name": "rat", "kind": "npc", "distance": 40., "dead": False},
                  {"name": "Rat", "kind": "npc", "distance": 1., "dead": True}, {"name": "Spider", "kind": "npc", "distance": 10., "dead": False},
                  {"name": "Buddy", "kind": "player", "distance": 5., "dead": False}]
        self.assertEqual([(r["name"], r["alive"], r["nearest"]) for r in target_tab.enemy_rows(actors, ["Ghoul"])],
                         [("Spider", 1, 10.), ("Rat", 2, 40.), ("Ghoul", 0, None)])

    def test_ticks_start_the_hunt_and_outlive_a_refresh(self):
        started = []
        self.tab.loot_runner = lambda names, reach, emit, control: started.append((names, reach))
        self.tab.update_buttons()
        self.assertEqual(str(self.tab.hunt_button.cget("state")), "disabled")
        self.tab.tick_enemy("Copbot")
        self.assertEqual(self.tab.enemies.item("e0", "values")[0], target_tab.TICKED)
        self.assertEqual(str(self.tab.hunt_button.cget("state")), "normal")
        self.tab.reach.set("nope")
        self.assertEqual(str(self.tab.hunt_button.cget("state")), "disabled")
        self.tab.reach.set("300")
        self.tab.show_nearby(("ok", NEARBY))
        self.assertEqual(self.tab.enemies.item("e0", "values")[0], target_tab.TICKED)
        with patch.object(self.tab.root, "after", return_value="id") as after:
            self.tab.start_hunt()
        self.assertTrue(self.tab.steering())
        self.assertEqual(after.call_args.args[2:], (["Copbot"], 300))
        self.tab.loot_event("done", "0 killed.")

    def test_two_clients_are_told_apart_and_the_choice_reaches_the_engine(self):
        found = [{"pid": 11, "label": "HLT 768, PSI 433 (11)"}, {"pid": 22, "label": "HLT 913, PSI 7 (22)"}]
        self.addCleanup(clients.choose, None)
        clients.choose(22)
        self.tab.show_clients(found)
        self.assertEqual(self.tab.client.get(), found[1]["label"])
        self.tab.client.set(found[0]["label"])
        with patch.object(self.tab, "refresh") as refresh:
            self.tab.client_chosen()
        refresh.assert_called_once()
        self.assertEqual(os.environ["NEOCRON_PID"], "11")
        self.tab.show_nearby(("ok", NEARBY))
        self.assertTrue(self.tab.status.get().endswith("around you (seen by HLT 768, PSI 433 (11))"))

    def test_two_clients_start_on_the_healer(self):
        found = [{"pid": 22, "label": "HLT 913, PSI 7 (22)", "psi": 7}, {"pid": 30, "label": "HLT 768, PSI 433 (30)", "psi": 433}]
        self.addCleanup(clients.choose, None)
        clients.choose(None)
        with patch.object(target_tab.tt, "build_tool", return_value=None), patch.object(clients, "list_clients", return_value=found),                 patch.object(target_tab.tt, "run_tool", return_value=NEARBY):
            self.tab.refresh()
            while self.tab.busy:
                self.root.update()
                self.tab.poll()
        self.assertEqual(os.environ["NEOCRON_PID"], "30")
        self.assertEqual(self.tab.client.get(), found[1]["label"])

    def test_will_not_start_while_a_walk_steers_the_same_mouse(self):
        self.walking = True
        self.tab.tree.selection_set(self.tab.tree.get_children()[0])
        self.root.update()
        with patch.object(self.tab, "start_live") as start:
            self.tab.track()
        start.assert_not_called()
        self.assertIn("Stop it first", self.log())

    def test_find_and_a_game_that_cannot_be_read(self):
        self.tab.find.set("cop")
        self.assertEqual(len(self.tab.tree.get_children()), 1)
        self.tab.find.set("")
        self.tab.show_nearby(("ok", {"live": False, "why": "Neocron is not running."}))
        self.assertEqual(self.tab.status.get(), "Cannot read the game: Neocron is not running.")
        self.assertFalse(self.tab.tree.get_children())
        self.tab.show_nearby(("error", "The engine printed nothing."))
        self.assertEqual(self.tab.status.get(), "The engine printed nothing.")


class ClientTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(clients.label(30132, {"HLT": 768, "PSI": 433}), "HLT 768, PSI 433 (30132)")
        self.assertEqual(clients.label(5, {}), "Client 5")

    def test_only_one_client_needs_no_reading(self):
        with patch.object(clients, "windows", return_value={7: 1}), patch.object(clients, "capture") as capture:
            self.assertEqual(clients.list_clients(), [{"pid": 7, "label": "Client 7", "psi": 0}])
        capture.assert_not_called()


class AppTests(unittest.TestCase):
    def test_the_tab_is_in_the_suite_with_no_start_and_shares_the_mouse_with_traversal(self):
        from app import App

        class NoInput:
            def release_all(self):
                pass
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            app = App(root, profile_path=Path(folder) / "profile.json", backend=NoInput())
            try:
                self.assertEqual(app.tabs.tab(app.target_tab, "text"), "Target Acquisition")
                self.assertFalse(app.target.autoload)
                app.tabs.select(app.target_tab)
                root.update()
                self.assertEqual(str(app.start_button.cget("state")), "disabled")
                with self.assertRaisesRegex(ValueError, "own buttons"):
                    app.collect()
                self.assertFalse(app.traversal.other_live())
                app.target.process = object()
                self.assertTrue(app.traversal.other_live())
                app.target.process = None
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
