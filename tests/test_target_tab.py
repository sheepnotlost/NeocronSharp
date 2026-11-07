"""Target Acquisition tab: the actor list and the camera command, from canned engine JSON (no engine, no input)."""
import os
from pathlib import Path
import tempfile
import threading
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
        kept = patch.object(target_tab, "AVOID_FILE", Path(tempfile.mkdtemp()) / "avoid.txt")
        kept.start()
        self.addCleanup(kept.stop)
        pin = patch.object(target_tab, "PIN_FILE", Path(tempfile.mkdtemp()) / "pin.txt")
        pin.start()
        self.addCleanup(pin.stop)
        with patch.object(target_tab, "FIGHTER_FILE", Path(tempfile.gettempdir()) / "no-such-fighter.txt"):
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

    def test_it_heals_only_the_named_fighter_with_real_input(self):
        children = self.tab.tree.get_children()
        self.tab.tree.selection_set(children[0])
        self.root.update()
        self.assertEqual(str(self.tab.heal_button.cget("state")), "normal")      # clickable, so it can say why not
        with patch.object(self.tab, "start_live") as start:
            self.tab.heal()
        start.assert_not_called()
        self.assertIn("Type Buddy in Fighter first", self.log())
        self.tab.fighter.set(" buddy ")
        self.root.update()
        self.assertEqual(str(self.tab.heal_button.cget("state")), "normal")
        with tempfile.TemporaryDirectory() as folder, patch.object(target_tab, "FIGHTER_FILE", Path(folder) / "fighter.txt"), \
                patch.object(self.tab, "start_live") as start:
            self.tab.heal()
            self.assertEqual(target_tab.FIGHTER_FILE.read_text(encoding="utf-8"), "Buddy")
        start.assert_called_once_with(["follow", "p1", "--heal", "--distance", "120", "--pulse", "24", "--run"])

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

    def test_f8_ends_a_healer_alone(self):
        self.tab.heal_name = "Buddy"
        self.tab.last_line = "Stopped: Stop pressed."
        with patch.object(self.tab, "refresh"):
            self.tab.finished()
        self.assertIsNone(self.tab.heal_name)
        self.assertIsNone(self.tab.heal_retry)

    def test_lost_focus_takes_it_back_and_follows_again(self):
        self.tab.heal_name = "Buddy"
        self.tab.last_line = "Stopped: Neocron lost focus. Movement stopped; it will not resume automatically."
        self.tab.finished()
        self.assertEqual(self.tab.heal_name, "Buddy")
        self.assertIsNotNone(self.tab.heal_retry)
        self.assertIn("Bringing Neocron back to the front and looking for Buddy again", self.tab.log.get("1.0", "end"))
        self.root.after_cancel(self.tab.heal_retry)
        with patch.object(target_tab.clients, "focus", return_value=True) as focus, \
                patch.object(target_tab.tt, "run_tool", return_value={"live": True, "entities": []}):
            self.tab.find_fighter()
            for thread in [t for t in threading.enumerate() if t.name == "target-fighter"]:
                thread.join(5)
        focus.assert_called_once_with()
        self.assertEqual(self.tab.queue.get_nowait()[0], "fighter")
        self.tab.heal_name = None

    def test_any_other_ending_leaves_the_focus_alone(self):
        self.tab.last_line = "Stopped: The camera's angles could not be read on this game build."
        with patch.object(target_tab.clients, "focus") as focus, patch.object(target_tab.tt, "run_tool", return_value={"live": False, "why": "x"}):
            self.tab.find_fighter()
            for thread in [t for t in threading.enumerate() if t.name == "target-fighter"]:
                thread.join(5)
        focus.assert_not_called()
        self.tab.queue.get_nowait()

    def test_a_retry_makes_no_test_moves(self):
        self.tab.remember("Following Buddy (player) at 120 units.")
        self.tab.remember("calibration 178.5 0.0024\n")
        self.tab.remember("gains 0.002 0.0015\n")
        with patch.object(self.tab, "start_live") as start:
            self.tab.start_alone("p1")
        start.assert_called_once_with(["follow", "p1", "--heal", "--distance", "120", "--pulse", "24", "--run",
                                       "--calibration", "178.5,0.0024", "--gains", "0.002,0.0015"])

    def test_a_failed_read_clears_busy_whatever_it_was(self):
        with patch.object(target_tab.tt, "build_tool", side_effect=KeyError("boom")):
            self.tab.refresh()
            while self.tab.busy:
                self.root.update()
                self.tab.poll()
        self.assertIn("boom", self.tab.status.get())

    def test_enemy_list_groups_living_creatures_and_never_lists_players_or_humans(self):
        actors = [{"name": "Rat", "kind": "npc", "distance": 900., "dead": False, "faction": 18},
                  {"name": "rat", "kind": "npc", "distance": 40., "dead": False, "faction": 18},
                  {"name": "Rat", "kind": "npc", "distance": 1., "dead": True, "faction": 18},
                  {"name": "Spider", "kind": "npc", "distance": 10., "dead": False, "faction": 17},
                  {"name": "Corporal Lines / CityMercs", "kind": "npc", "distance": 3., "dead": False, "faction": 11},
                  {"name": "Buddy", "kind": "player", "distance": 5., "dead": False}]
        self.assertEqual([(r["name"], r["alive"], r["nearest"]) for r in target_tab.enemy_rows(actors, ["Ghoul"])],
                         [("Spider", 1, 10.), ("Rat", 2, 40.), ("Ghoul", 0, None)])

    def test_ticks_start_the_hunt_and_outlive_a_refresh(self):
        started = []
        self.tab.loot_runner = lambda names, reach, emit, control: started.append((names, reach))
        self.tab.tick_enemy("Copbot")
        self.assertEqual(self.tab.enemies.item("e0", "values")[0], target_tab.TICKED)
        self.tab.reach.set("300")
        self.tab.show_nearby(("ok", NEARBY))
        self.assertEqual(self.tab.enemies.item("e0", "values")[0], target_tab.TICKED)
        with patch.object(self.tab.root, "after", return_value="id") as after:
            self.tab.start_hunt()
        self.assertTrue(self.tab.steering())
        self.assertEqual(after.call_args.args[2:], (["Copbot"], 300))
        self.tab.loot_event("done", "0 killed.")

    def test_regants_legacy_needs_no_ticks_and_starts_after_the_countdown(self):
        self.assertEqual(str(self.tab.dungeon_button.cget("state")), "disabled")      # no game bound in a test
        made = []

        class Runner:
            def run(self):
                made.append("ran")
        self.tab.dungeon_runner = lambda reach, emit, control, avoid: made.append((reach, avoid)) or Runner()
        self.tab.update_buttons()
        self.assertEqual(str(self.tab.dungeon_button.cget("state")), "normal")
        self.tab.start_dungeon()
        self.assertIsNotNone(self.tab.looting)
        self.assertEqual(str(self.tab.dungeon_button.cget("state")), "disabled")
        self.assertIn("Regant's Legacy: every creature in the main area, one at a time", self.log())
        self.root.after_cancel(self.tab.loot_start)
        with patch.object(target_tab.clients, "focus"):
            self.tab.begin_dungeon(4000, ["parasite"])
        for thread in [t for t in threading.enumerate() if t.name == "dungeon"]:
            thread.join(5)
        self.assertEqual(made, [(4000, ["parasite"]), "ran"])

    def test_pin_camera_is_handed_to_the_runner_and_kept(self):
        class Runner:
            engine = type("E", (), {"pin": False})()
        self.assertFalse(self.tab.pinned(Runner()).engine.pin)
        self.tab.pin.set(True)
        self.assertTrue(self.tab.pinned(Runner()).engine.pin)
        self.assertEqual(target_tab.PIN_FILE.read_text(encoding="utf-8"), "1")
        self.tab.looting = None

    def test_start_hunt_says_why_it_cannot_start(self):
        self.tab.loot_runner = lambda names, reach, emit, control: None
        self.tab.update_buttons()
        self.assertEqual(str(self.tab.hunt_button.cget("state")), "normal")
        with patch.object(self.tab.root, "after") as after:
            self.tab.reach.set("nope")
            self.tab.start_hunt()
            self.assertIn("40 to 6000", self.tab.status.get())
            self.tab.reach.set("6000")
            self.assertEqual(self.tab.reach_units(), 6000)
            self.tab.reach.set("200")
            self.tab.heal_name = "Buddy"
            self.tab.start_hunt()
            self.assertIn("Press Stop", self.tab.status.get())
            self.tab.heal_name = None
        after.assert_not_called()
        self.assertFalse(self.tab.steering())

    def test_a_hunt_that_fails_to_start_reports_it_and_frees_the_button(self):
        def broken(names, reach, emit, control):
            raise ImportError("no module")
        self.tab.loot_runner = broken
        self.tab.tick_enemy("Copbot")
        self.tab.looting = target_tab.Control()
        with patch.object(self.tab, "refresh"), patch.object(target_tab.clients, "focus") as focus:
            self.tab.begin_hunt(["Copbot"], 200)
        focus.assert_called_once_with()
        self.assertIsNone(self.tab.looting)
        self.assertIn("Hunt could not start: no module", self.tab.log.get("1.0", "end"))
        self.assertEqual(str(self.tab.hunt_button.cget("state")), "normal")

    def read_with(self, windows):
        with patch.object(target_tab.tt, "build_tool", return_value=None), patch.object(clients, "windows", return_value=windows), \
                patch.object(target_tab.tt, "run_tool", return_value=NEARBY) as nearby:
            self.tab.refresh()
            while self.tab.busy:
                self.root.update()
                self.tab.poll()
        return nearby

    def test_two_clients_on_one_pc_are_refused(self):
        self.addCleanup(clients.choose, None)
        nearby = self.read_with({22: 1, 30: 2})
        nearby.assert_not_called()
        self.assertIn("2 Neocron clients are open on this PC. Close all but one", self.tab.status.get())
        self.assertFalse(hasattr(self.tab, "client_box"))

    def test_the_one_client_here_is_read_whatever_another_tab_picked(self):
        self.addCleanup(clients.choose, None)
        clients.choose(99)
        self.read_with({30: 1})
        self.assertEqual(os.environ["NEOCRON_PID"], "30")
        self.assertTrue(self.tab.status.get().endswith("around you"))

    def test_the_named_fighter_is_picked_after_a_refresh(self):
        self.tab.tree.selection_remove(*self.tab.tree.selection())
        self.tab.fighter.set("BUDDY")
        self.tab.show_nearby(("ok", NEARBY))
        self.assertEqual(self.tab.selected()["name"], "Buddy")
        self.tab.tree.selection_set(self.tab.tree.get_children()[1])
        kept = self.tab.selected()["id"]
        self.tab.show_nearby(("ok", NEARBY))
        self.assertEqual(self.tab.selected()["id"], kept)       # a row you picked yourself stays picked

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


class NoDotNetTests(unittest.TestCase):
    def test_says_what_to_do_with_no_sdk(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(target_tab.tt, "EXE", Path(folder) / "traversal.exe"), \
                patch.object(target_tab.tt.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIn("Make VM Copy.cmd", target_tab.tt.build_tool())

    def test_the_vm_copy_leaves_out_what_only_a_developer_needs(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_vm_copy", target_tab.tt.ROOT / "tools" / "make_vm_copy.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        self.assertTrue(tool.wanted("target_tab.py") and tool.wanted("traversal/Follow.cs") and tool.wanted("runtime/python.exe"))
        self.assertFalse(tool.wanted("tests/test_macro.py") or tool.wanted("Research/notes.md"))


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
                self.assertEqual(app.tabs.tab(app.target_tab, "text"), "Track & Heal")
                self.assertEqual(app.tabs.tab(app.hunt_tab, "text"), "Hunt")
                self.assertFalse(app.target.autoload)
                for tab in (app.target_tab, app.hunt_tab):
                    app.tabs.select(tab)
                    root.update()
                    self.assertEqual(str(app.start_button.cget("state")), "disabled")
                self.assertTrue(str(app.target.hunt_button).startswith(str(app.hunt_tab)))       # on the Hunt tab, with its own Stop and Refresh
                self.assertEqual(len(app.target.stop_buttons), 2)
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


class SpareTests(unittest.TestCase):
    def setUp(self):
        kept = patch.object(target_tab, "AVOID_FILE", Path(tempfile.mkdtemp()) / "avoid.txt")
        kept.start()
        self.addCleanup(kept.stop)
        pin = patch.object(target_tab, "PIN_FILE", Path(tempfile.mkdtemp()) / "pin.txt")
        pin.start()
        self.addCleanup(pin.stop)

    def test_nothing_ticked_starts_the_hunt_and_regants_legacy_starts_the_sweep(self):
        root = tk.Tk(); root.withdraw()
        frame = tk.Frame(root); frame.pack()
        with patch.object(target_tab, "FIGHTER_FILE", Path(tempfile.gettempdir()) / "no-such-fighter.txt"):
            tab = target_tab.TargetTab(frame, root, autoload=False, loot_runner=lambda *a: None, dungeon_runner=lambda *a: None)
        try:
            tab.show_nearby(("ok", NEARBY))
            with patch.object(root, "after") as after:
                tab.start_hunt()
            self.assertIn("every robot, mutant and animal here; never humans or players", tab.log.get("1.0", "end"))
            after.assert_called_once()
            tab.looting = None
            tab.show_nearby(("ok", {**NEARBY, "sector": target_tab.INSIDE}))
            with patch.object(root, "after"):
                tab.start_hunt()
            self.assertIn("Regant's Legacy: every creature in the main area, one at a time", tab.log.get("1.0", "end"))
            tab.looting = None
        finally:
            tab.close(); root.destroy()

    def test_typed_names_or_parts_are_left_alone_and_kept(self):
        root = tk.Tk(); root.withdraw()
        frame = tk.Frame(root); frame.pack()
        with patch.object(target_tab, "FIGHTER_FILE", Path(tempfile.gettempdir()) / "no-such-fighter.txt"):
            tab = target_tab.TargetTab(frame, root, autoload=False, loot_runner=lambda *a: None, dungeon_runner=lambda *a: None)
        try:
            tab.show_nearby(("ok", {**NEARBY, "sector": target_tab.INSIDE}))
            tab.avoid.set(" parasite ,  Genotoxic  Slugger,, ")
            self.assertEqual(target_tab.typed_names(tab.avoid.get()), ["parasite", "Genotoxic Slugger"])
            with patch.object(root, "after") as after:
                tab.start_hunt()
            self.assertEqual(after.call_args.args[3], ["parasite", "Genotoxic Slugger"])
            self.assertIn("leaving parasite, Genotoxic Slugger alone", tab.log.get("1.0", "end"))
            self.assertEqual(target_tab.AVOID_FILE.read_text(encoding="utf-8"), "parasite, Genotoxic Slugger")
            tab.looting = None
        finally:
            tab.close(); root.destroy()
