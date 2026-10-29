"""Counter integration checks with synthetic data and an injected input backend."""

import json
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np

from app import App
from macro_core import Control
from ntc import config, sets
from ntc.lists import ListStore
from ntc.models import CellRead, ScanResult
from ntc.names import Names
from tech_counter import CounterSession, import_counter_state


class FakeBackend:
    def __init__(self):
        self.focused = True
        self.moves, self.wheels = [], []
        self.cursor = [20, 25]
        self.rgb = np.zeros((100, 150, 3), np.uint8)
        self.rgb[:] = (11, 22, 33)

    def release_all(self):
        pass

    def bind_foreground(self):
        return "Neocron Evolution", [150, 100]

    def check_focus(self, size):
        if not self.focused:
            raise RuntimeError("Game lost focus")

    def cursor_client(self):
        return list(self.cursor)

    def move(self, point):
        self.cursor = list(point)
        self.moves.append(point)

    def scroll(self, notches):
        self.wheels.append(notches)

    def capture(self):
        return self.rgb.copy()

    def capture_region(self, box):
        return self.rgb.copy()  # suite region captures are full-size padded images


class CounterStateTests(unittest.TestCase):
    def test_import_preserves_source_and_existing_suite_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source, dest = Path(temp) / "old", Path(temp) / "new"
            source.mkdir()
            old = ListStore(source / "lists.json")
            old.create("Rare cabinet")
            names = {"names": ["Core Part Of Test"], "aliases": {}, "part_types": []}
            (source / "known_items.json").write_text(json.dumps(names))
            before = (source / "lists.json").read_bytes()
            copied = import_counter_state(source, dest)
            self.assertEqual(set(copied), {"lists.json", "known_items.json"})
            migrated = ListStore(dest / "lists.json")
            self.assertIn("Rare cabinet", migrated.names())
            migrated.create("Suite-only list")
            self.assertEqual(import_counter_state(source, dest), [])
            self.assertIn("Suite-only list", ListStore(dest / "lists.json").names())
            self.assertEqual((source / "lists.json").read_bytes(), before)

    def test_invalid_import_does_not_copy_any_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source, dest = Path(temp) / "old", Path(temp) / "new"
            source.mkdir()
            (source / "lists.json").write_text('{"lists":{"Bad":{}}}')
            (source / "config.json").write_text('{}')
            with self.assertRaises(ValueError):
                import_counter_state(source, dest)
            self.assertFalse(dest.exists())

    def test_list_totals_locations_undo_and_sets_survive_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lists.json"
            store = ListStore(path)
            rare = sets.load()[0]
            cells = [CellRead(i, 0, f"{part} Part Of {rare['name']}", "", 2, [])
                     for i, part in enumerate(rare["needs"])]
            result = ScanResult(started_at="2026-10-27T12:00:00", cells=cells, kind="cabinet")
            result.recompute()
            entry = store.add_scan(result, store.active)
            reopened = ListStore(path)
            statuses, unknown = sets.analyze(reopened.locations())
            completed = next(s for s in statuses if s.name == rare["name"])
            self.assertEqual(completed.complete_sets, 2)
            self.assertFalse(unknown)
            self.assertEqual(sum(reopened.totals().values()), 2 * len(cells))
            reopened.delete_entry(entry["id"])
            self.assertEqual(ListStore(path).totals(), {})


class CounterBackendTests(unittest.TestCase):
    def make_session(self, temp):
        backend = FakeBackend()
        session = CounterSession(backend, [150, 100], dict(config.DEFAULTS),
                                 Names(Path(temp) / "names.json"), threading.Event())
        return backend, session

    def test_client_rgb_frames_and_regions_are_converted_to_counter_bgr(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, session = self.make_session(temp)
            np.testing.assert_array_equal(session.grab()[0, 0], [33, 22, 11])
            region = session.grab_region(7, 8, 9, 10)
            self.assertEqual(region.shape, (10, 9, 3))
            np.testing.assert_array_equal(region[0, 0], [33, 22, 11])
            self.assertEqual(backend.moves, [])

    def test_focus_loss_stops_all_input_and_never_restores_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, session = self.make_session(temp)
            def lose_focus(*args, **kwargs):
                backend.focused = False
                return []
            with patch.object(session.scanner, "scan", side_effect=lose_focus):
                session.run("all", "techs", lambda _message: None)
            self.assertTrue(session.stopped.is_set())
            for operation in (lambda: session.move(10, 10), lambda: session.wheel(-2), session.grab):
                with self.assertRaises(RuntimeError):
                    operation()
            self.assertEqual(backend.moves, [])
            self.assertEqual(backend.wheels, [])

    def test_physical_mouse_movement_does_not_restore_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, session = self.make_session(temp)
            def drift(*args, **kwargs):
                session.scanner._placed = (1, 1)
                backend.cursor = [100, 70]
                return []
            with patch.object(session.scanner, "scan", side_effect=drift):
                session.run("all", "all", lambda _message: None)
            self.assertTrue(session.stopped.is_set())
            self.assertEqual(backend.moves, [])

    def test_completed_scan_restores_pointer_and_disables_focus_acquisition(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, session = self.make_session(temp)
            with patch.object(session.scanner, "scan", return_value=[]) as scan:
                session.run("inventory", "techs", lambda _message: None)
            self.assertEqual(backend.moves, [(20, 25)])
            self.assertFalse(scan.call_args.kwargs["activate_game"])
            self.assertFalse(scan.call_args.kwargs["reset_abort"])
            self.assertFalse(scan.call_args.kwargs["restore_cursor"])

    def test_close_before_worker_starts_cannot_be_cleared_by_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            backend, session = self.make_session(temp)
            session.stopped.set()
            with patch.object(session.scanner, "scan") as scan:
                with self.assertRaises(RuntimeError):
                    session.run("all", "all", lambda _message: None)
            scan.assert_not_called()
            self.assertEqual(backend.moves, [])


class CounterUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, profile_path=Path(self.temp.name) / "profile.json", backend=FakeBackend())

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_embedded_tab_has_shared_root_and_no_registered_hotkeys(self):
        app = self.app
        self.assertEqual([app.tabs.tab(t, "text") for t in app.tabs.tabs()],
                         ["Research", "Construction", "Recycling", "Traversal", "Tech Counter", *app.sharp_tabs])
        self.assertEqual(list(app.sharp_tabs)[0], "Tracker")
        self.assertIs(app.counter.root, self.root)
        self.assertFalse(hasattr(app.counter, "hotkeys"))
        self.assertEqual(app.counter.scan_btn.winfo_manager(), "")
        self.assertEqual(app.counter.data_dir, Path(self.temp.name) / "tech-counter")

    def test_start_counter_uses_countdown_without_validating_crafting_counts(self):
        app = self.app
        app.tabs.select(app.counter_tab)
        app.construction_available.set("not a number")
        with patch("tech_counter.ocr.require"):
            app.start()
        self.assertIsNotNone(app.countdown)
        self.assertTrue(app._counter_job)
        self.assertTrue(app.counter.busy)
        self.assertEqual(app.tabs.tab(app.construction_tab, "state"), "disabled")
        with patch.object(app.counter, "prepare") as prepare:
            app.start()
        prepare.assert_not_called()
        app.cancel_work()
        self.assertFalse(app.counter.busy)
        self.assertFalse(app.counter.import_button.instate(["disabled"]))

    def test_counter_cannot_be_collected_as_a_research_job(self):
        self.app.tabs.select(self.app.counter_tab)
        with self.assertRaisesRegex(ValueError, "Tech Counter"):
            self.app.collect()

    def test_countdown_dispatches_counter_through_shared_worker(self):
        app = self.app
        app.tabs.select(app.counter_tab)
        app._counter_job = True
        called = threading.Event()
        with patch.object(app.counter, "run_scan", side_effect=lambda control: called.set()):
            app.begin_countdown(0)
            app.worker.join(timeout=2)
        self.assertTrue(called.is_set())
        self.assertEqual(app.worker.name, "tech-counter-scan")
        app.poll()
        self.assertIsNone(app.worker)

    def test_results_and_errors_flow_to_suite_status_and_stop_sound(self):
        app = self.app
        result = ScanResult(started_at="2026-10-27T12:00:00", kind="inventory",
                            cells=[CellRead(0, 0, "Core Part Of Test", "", 3, [])])
        result.recompute()
        with patch.object(app, "notify_stop") as tone:
            app.events.put(("counter_done", ([result], app.counter.store.active)))
            app.poll()
            tone.assert_called_once()
        self.assertEqual(app.counter.store.totals()["Core Part Of Test"], 3)
        self.assertIn("Tech Counter: Added", app.status.get())
        app.events.put(("counter_error", "Game lost focus"))
        app.poll()
        self.assertIn("Game lost focus", app.status.get())


if __name__ == "__main__":
    unittest.main()
