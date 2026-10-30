"""Construction queue: several (recipe, count) jobs in a row through the single-job flow; no game input."""
from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from construction_runner import ConstructionRunner
from macro_core import Control, default_profile, load_profile, save_profile, validate_profile
from recipes import remove_recipe
from test_construction import ConstructionBackend, ConstructionDetector
from test_macro import FakeClock
from vision import Anchor, Detector


class QueueBackend(ConstructionBackend):
    """One blueprint recipe per Inventory page; scrolls both ways; Start is refused for recipes short of materials."""
    def __init__(self, clock, pages, available=50):
        super().__init__(clock, pages[0], available)
        self.page_recipes = list(pages)
        self.no_materials = set()
        self.loaded_recipe = None
        self.returned = []
        self.refused = []

    def scroll(self, notches):
        if notches < 0:
            return super().scroll(notches)
        self.check_focus(None)
        assert self.position == self.inventory.point(395, 310), "Scroll targeted stale Inventory coordinates"
        self.scrolls.append(notches)
        if self.page > 0:
            self.page -= 1
            self.inventory = Anchor(self.inventory.x - 15, self.inventory.y - 10, 1, 1)

    def button(self, name, down):
        source = self.held.get(name)
        inputs = [Detector.input_point(self.processor, i) for i in (1, 2)]
        if not down and source is not None and source != self.position and self.loaded and source in inputs:
            self.held.pop(name);self.events.append((name, down))
            self.loaded = False;self.returned.append((self.loaded_recipe, self.position[:]))
            return
        if not down and source == self.position == self.processor.start_point() and self.loaded_recipe in self.no_materials:
            self.held.pop(name);self.events.append((name, down))
            self.refused.append(self.loaded_recipe)  # The game refuses: nothing turns busy, the blueprint stays loaded.
            return
        if not down and source == self.source() and source != self.position:
            self.loaded_recipe = self.page_recipes[self.page]
        super().button(name, down)


class ConstructionQueueTests(unittest.TestCase):
    def setup_queue(self, pages, queue, **construction):
        self.profile = default_profile()
        self.profile["operation"] = "construction"
        self.profile["client_size"] = [1920, 1080]
        self.profile["construction"] = {"recipe": queue[0][0], "available": 10000, "count": 0,
                                        "search_mode": "all_cells", **construction,
                                        "queue": [{"recipe": r, "count": n} for r, n in queue]}
        self.clock = FakeClock()
        self.backend = QueueBackend(self.clock, pages)
        self.events = []
        self.runner = ConstructionRunner(self.profile, self.backend, Control(), lambda k, v: self.events.append((k, v)),
                                         self.clock.clock, self.clock.sleep, detector=ConstructionDetector())
        free_cell = self.backend.inventory.point(39 + 7*44.6 + 22.3, 63 + 5*45.5 + 22.75)
        self.runner.inventory_destination = lambda frame, inventory, code: free_cell

    def kinds(self, kind):
        return [v for k, v in self.events if k == kind]

    def test_jobs_run_in_order_each_from_the_top_of_inventory(self):
        self.setup_queue(["weaponpart_7", "holy_heal"], [("weaponpart_7", 2), ("holy_heal", 3), ("weaponpart_7", 1)])
        self.runner.run()
        self.assertFalse(self.kinds("error"), self.events)
        self.assertEqual(self.runner.completed, 6)
        self.assertEqual(len(self.backend.starts), 6)
        built = [(e["job"], e["recipe"], e["completed"]) for e in self.kinds("construction_cycle")]
        self.assertEqual(built, [(1, "weaponpart_7", 1), (1, "weaponpart_7", 2), (2, "holy_heal", 1), (2, "holy_heal", 2),
                                 (2, "holy_heal", 3), (3, "weaponpart_7", 1)])
        # Holy Heal is a page down; the next Weaponpart 7 job scrolled back up before searching.
        self.assertEqual(self.backend.page, 0)
        self.assertIn(1, self.backend.scrolls)
        self.assertEqual([e["index"] for e in self.kinds("queue_job")], [0, 1, 2])
        self.assertIn("Item 2 of 3: Crahn Holy Heal, 2 of 3 built", " | ".join(self.kinds("status")))
        self.assertIn("Queue finished: 3 of 3 jobs complete, 6 builds.", self.kinds("done")[-1])

    def test_a_job_out_of_blueprints_is_reported_and_skipped(self):
        self.setup_queue(["weaponpart_7"], [("weaponpart_9", 3), ("weaponpart_7", 2)])
        self.runner.run()
        self.assertFalse(self.kinds("error"), self.events)
        self.assertEqual(self.runner.completed, 2)
        self.assertIn("Item 1 of 2: Tangent Weaponpart 9, 0 of 3 built: skipped, out of blueprints.", self.kinds("status"))
        done = self.kinds("done")[-1]
        self.assertIn("1 of 2 jobs complete", done)
        self.assertIn("Skipped: Tangent Weaponpart 9 (out of blueprints, 0 of 3 built).", done)

    def test_a_job_out_of_materials_returns_its_blueprint_and_is_skipped(self):
        self.setup_queue(["weaponpart_7", "holy_heal"], [("holy_heal", 2), ("weaponpart_7", 2)])
        self.backend.no_materials = {"holy_heal"}
        self.runner.run()
        self.assertFalse(self.kinds("error"), self.events)
        self.assertEqual(self.backend.refused, ["holy_heal"])
        self.assertEqual([r for r, _ in self.backend.returned], ["holy_heal"])
        self.assertEqual(self.runner.completed, 2)
        self.assertFalse(self.backend.loaded)
        self.assertIn("Skipped: Crahn Holy Heal (out of materials, 0 of 2 built).", self.kinds("done")[-1])

    def test_a_count_of_zero_builds_until_that_blueprint_runs_out(self):
        self.setup_queue(["weaponpart_7"], [("weaponpart_7", 0), ("weaponpart_9", 1)])
        # Three Weaponpart 7 blueprints, then the stack is gone.
        tooltip = ConstructionDetector.tooltip_recipe
        backend = self.backend
        def limited(detector, frame, point, scale):
            return None if len(backend.transfers) >= 3 else tooltip(detector, frame, point, scale)
        self.runner.detector.tooltip_recipe = limited.__get__(self.runner.detector)
        self.runner.run()
        self.assertFalse(self.kinds("error"), self.events)
        self.assertEqual(self.runner.completed, 3)
        done = self.kinds("done")[-1]
        self.assertIn("1 of 2 jobs complete, 3 builds", done)
        self.assertNotIn("Weaponpart 7 (", done)
        self.assertIn("Tangent Weaponpart 9 (out of blueprints, 0 of 1 built)", done)

    def test_any_other_stop_ends_the_queue_and_says_where(self):
        self.setup_queue(["weaponpart_7"], [("weaponpart_7", 2), ("weaponpart_7", 2)])
        self.clock.on_sleep = lambda: setattr(self.backend, "focus", False) if len(self.backend.starts) >= 3 else None
        self.runner.run()
        error = self.kinds("error")[0]
        self.assertIn("Item 2 of 2: Tangent Weaponpart 7, 0 of 2 built", error)
        self.assertIn("Game lost focus", error)

    def test_single_job_without_a_queue_is_unchanged(self):
        self.setup_queue(["weaponpart_7"], [("weaponpart_7", 1)])
        self.profile["construction"]["queue"] = []
        self.profile["construction"]["count"] = 2
        self.runner = ConstructionRunner(self.profile, self.backend, Control(), lambda k, v: self.events.append((k, v)),
                                         self.clock.clock, self.clock.sleep, detector=ConstructionDetector())
        self.runner.run()
        self.assertEqual(self.kinds("done"), ["Finished 2 builds of Tangent Weaponpart 7. Final result remains in the Processor."])
        self.assertFalse(self.backend.scrolls)
        self.assertNotIn("job", self.kinds("construction_cycle")[0])


class QueueProfileTests(unittest.TestCase):
    def test_queue_saves_loads_and_rejects_bad_rows(self):
        profile = default_profile()
        profile["construction"]["queue"] = [{"recipe": "weaponpart_7", "count": 5}, {"recipe": "holy_heal", "count": 0}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            save_profile(path, profile)
            self.assertEqual(load_profile(path)["construction"]["queue"], profile["construction"]["queue"])
        for bad in ([{"recipe": "missing", "count": 1}], [{"recipe": "holy_heal", "count": -1}],
                    [{"recipe": "holy_heal", "count": True}], [{"recipe": "holy_heal"}], "holy_heal",
                    [{"recipe": "holy_heal", "count": 1}] * 101):
            trial = deepcopy(profile);trial["construction"]["queue"] = bad
            with self.assertRaises(ValueError, msg=bad):validate_profile(trial, require_ready=False)

    def test_removing_a_recipe_drops_its_queued_jobs(self):
        profile = default_profile()
        profile["construction"]["queue"] = [{"recipe": "holy_heal", "count": 1}, {"recipe": "weaponpart_7", "count": 2}]
        remove_recipe(profile, "holy_heal")
        self.assertEqual(profile["construction"]["queue"], [{"recipe": "weaponpart_7", "count": 2}])
        validate_profile(profile, require_ready=False)


class QueueUiTests(unittest.TestCase):
    def test_add_reorder_remove_save_and_report_jobs(self):
        from app import App
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            root = tk.Tk();root.withdraw()
            app = App(root, profile_path=path, backend=NoInput())
            try:
                app.tabs.select(app.construction_tab)
                self.assertIn("Queue empty", app.queue_note.get())
                for name, count in (("WP7", "5"), ("HH", "0"), ("Custom Test Blaster 13", "2")):
                    app.construction_recipe.set(name);app.select_recipe();app.construction_count.set(count)
                    app.add_queue_job()
                app.materials_text.set("Zinc=ZN")
                app.construction_recipe.set("WP9");app.construction_count.set("1");app.add_queue_job()
                saved = load_profile(path)
                self.assertEqual([(r["recipe"], r["count"]) for r in saved["construction"]["queue"]][:2],
                                 [("weaponpart_7", 5), ("holy_heal", 0)])
                self.assertEqual(saved["materials"]["weaponpart_9"], {"Zinc": "ZN"})
                self.assertEqual(len(app.queue_tree.get_children()), 4)
                self.assertEqual(app.queue_tree.item("1", "values")[0], "Until out")
                self.assertIn("Start builds these 4 jobs", app.queue_note.get())
                app.queue_tree.selection_set("0");app.move_queue_job(1)
                self.assertEqual(app.queue_tree.selection(), ("1",))
                app.move_queue_job(1);app.move_queue_job(1);app.move_queue_job(1)  # The last row stays last.
                self.assertEqual([r["recipe"] for r in load_profile(path)["construction"]["queue"]][-1], "weaponpart_7")
                app.queue_tree.selection_set("0");app.remove_queue_job()
                self.assertEqual([r["recipe"] for r in load_profile(path)["construction"]["queue"]][0][:7], "custom_")
                root.update()
                self.assertEqual(app.construction_recipe.get(), "Custom Test Blaster 13")  # Selecting a row fills the form.
                profile = app.collect()
                self.assertEqual(len(profile["construction"]["queue"]), 3)
                app.events.put(("construction_cycle", {"recipe": "holy_heal", "available": 10000, "completed": 2,
                                                       "remaining": 9998, "job": 3, "jobs": 10, "target": 5}))
                app.events.put(("queue_job", {"index": 2, "recipe": "weaponpart_7"}))
                app.poll()
                self.assertEqual(app.status.get(), "Item 3 of 10: Crahn Holy Heal, 2 of 5 built.")
                self.assertEqual(app.queue_tree.selection(), ("2",))
                app.clear_queue()
                self.assertEqual(load_profile(path)["construction"]["queue"], [])
                self.assertIn("Queue empty", app.queue_note.get())
                app.populate()
                self.assertFalse(app.queue_tree.get_children())
            finally:app.close()


if __name__ == "__main__":
    unittest.main()
