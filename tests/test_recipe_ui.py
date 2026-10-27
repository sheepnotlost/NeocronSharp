from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from app import App
from macro_core import load_profile
from recipes import RECIPES,catalog,find_recipe


class RecipeUiTests(unittest.TestCase):
    def test_remove_custom_and_builtin_entries_and_restore_from_catalog(self):
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"profile.json"
            root=tk.Tk();root.withdraw();app=App(root,profile_path=path,backend=NoInput())
            try:
                app.tabs.select(app.construction_tab)
                app.construction_available.set("55");app.construction_count.set("12")
                app.construction_recipe.set("Crahn Energy Ball");app.recipe_aliases.set("");app.save_custom_recipe()
                key=find_recipe("Crahn Energy Ball",catalog(app.profile))
                app.remove_job_recipe()
                loaded=load_profile(path)
                self.assertNotIn(key,catalog(loaded));self.assertNotIn("favorites",loaded)
                self.assertNotIn("Crahn Energy Ball",app.construction_choice.cget("values"))
                self.assertEqual(app.construction_available.get(),"55")
                self.assertEqual(app.construction_count.get(),"12")
                for recipe in RECIPES.values():
                    app.construction_recipe.set(recipe["name"]);app.remove_job_recipe()
                loaded=load_profile(path)
                self.assertFalse(catalog(loaded));self.assertIsNone(loaded["construction"]["recipe"])
                self.assertEqual(app.construction_recipe.get(),"")
                app.populate()  # Empty Job book can reopen and Research still works.
                row=next(r for r in app.build_catalog_data["recipes"] if r.get("saved_recipe")=="weaponpart_7")
                app.build_tree.selection_set(row["id"]);app.use_build_recipe()
                self.assertEqual(find_recipe("WP7",catalog(load_profile(path))),"weaponpart_7")
                self.assertEqual(app.construction_recipe.get(),"Tangent Weaponpart 7")
                # Persisted counts remain independent of recipe removal/restoration.
                self.assertEqual(app.profile["construction"]["available"],10000)
                self.assertIsNone(app.countdown);self.assertIsNone(app.worker)
            finally:app.close()

    def test_add_select_by_alias_reload_and_report_custom_recipe_without_input(self):
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"profile.json"
            root=tk.Tk();root.withdraw()
            app=App(root,profile_path=path,backend=NoInput())
            try:
                app.tabs.select(app.construction_tab)
                app.construction_recipe.set("Custom Test Blaster 13")
                app.save_custom_recipe()   # aliases are no longer entered; a new name starts with none
                loaded=load_profile(path)
                key=find_recipe("Custom Test Blaster 13",catalog(loaded))
                self.assertIsNotNone(key)
                self.assertIn("Custom Test Blaster 13",app.construction_choice.cget("values"))
                app.construction_recipe.set("custom test blaster 13")
                app.count_slots.set(True)
                profile=app.collect()
                self.assertEqual(profile["construction"]["recipe"],key)
                self.assertTrue(profile["construction"]["count_slots"])
                app.events.put(("construction_cycle",{"recipe":key,"available":0,"completed":1,"remaining":0,
                                                       "slot_counts":{2:1},"slot_unread":0,"slot_na":0}))
                app.poll()
                self.assertIn("Custom Test Blaster 13",app.status.get())
                self.assertIn("2: 1",app.slot_summary.get())
                self.assertEqual(load_profile(path)["construction"]["available"],0)
            finally:app.close()
