from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from construction_catalog import load_construction_catalog, filter_construction
from macro_core import default_profile, load_profile, save_profile
from recipes import catalog, find_recipe


class CatalogDataTests(unittest.TestCase):
    def test_longer_custom_tooltip_name_is_not_overridden_by_builtin_prefix(self):
        from recipes import add_recipe
        from vision import Detector,cv2,np
        profile=default_profile();key=add_recipe(profile,"Crahn Holy Heal Sanctum")
        d=Detector();d.recipes=catalog(profile)
        label=np.zeros((17,650),np.uint8)
        label[1:16,1:79]=d.templates["tooltip_prefix"]
        cv2.putText(label,"30 TB Capacity: Crahn Holy Heal Sanctum",(84,13),cv2.FONT_HERSHEY_SIMPLEX,.45,220,1,cv2.LINE_AA)
        cv2.rectangle(label,(0,0),(649,16),220,1)
        frame=np.zeros((900,1600,3),np.uint8);frame[400:417,500:1150]=cv2.cvtColor(label,cv2.COLOR_GRAY2RGB)
        d.known_tooltip_recipe=lambda *args:"holy_heal"
        self.assertEqual(d.tooltip_recipe(frame,[700,380],1),key)

    def test_broad_sources_methods_and_no_invented_materials(self):
        data=load_construction_catalog();rows=data["recipes"]
        self.assertEqual(len(rows),1263)
        self.assertEqual(len({r["id"] for r in rows}),1263)
        self.assertGreater(len({r["category"] for r in rows}),30)
        self.assertTrue(all(r["source_url"].startswith("https://") for r in rows))
        self.assertEqual(next(r for r in rows if r["name"]=="Pain Easer")["method"],"rare_parts")
        self.assertEqual(next(r for r in rows if r["name"]=="Crahn Holy Heal")["method"],"verified_example")
        self.assertIsNone(next(r for r in rows if r["name"]=="Crahn Blessed Heal")["ingredients"])
        self.assertTrue(any(r["name"]=="Tangent Weaponpart 8" for r in filter_construction(rows,"wp8")))

    def test_old_profile_favorites_are_dropped_on_load(self):
        profile=default_profile();profile["favorites"]=[{"kind":"construction","id":"weaponpart_7"}]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"profile.json"
            path.write_text(json.dumps(profile),encoding="utf-8")
            self.assertNotIn("favorites",load_profile(path))


@contextmanager
def ui():
    class NoInput:
        def release_all(self):pass
    with tempfile.TemporaryDirectory() as folder,patch("app.stop_sound"):
        root=tk.Tk();root.withdraw();app=App(root,Path(folder)/"profile.json",NoInput())
        try:yield app
        finally:app.close()


class CatalogUiTests(unittest.TestCase):
    def test_catalog_loads_only_selected_recipe_and_preserves_job_counts(self):
        with ui() as app:
            app.construction_count.set("2");app.construction_available.set("55")
            app.tabs.select(app.construction_tab);app.construction_pages.select(app.construction_catalog_tab)
            app.build_query.set("Crahn Blessed Heal")
            row=next(r for r in app.build_catalog_data["recipes"] if r["name"]=="Crahn Blessed Heal")
            app.build_tree.selection_set(row["id"])
            with self.assertRaisesRegex(ValueError,"Load a catalog item"):app.collect()
            app.use_build_recipe()
            key=find_recipe(row["name"],catalog(app.profile))
            self.assertIsNotNone(key)
            self.assertEqual(len(catalog(app.profile)),4)
            self.assertEqual(app.tabs.select(),str(app.construction_tab))
            self.assertEqual(app.construction_pages.select(),str(app.construction_job))
            self.assertEqual(app.construction_available.get(),"55")
            self.assertEqual(app.construction_count.get(),"2")
            self.assertEqual(app.collect()["construction"]["recipe"],key)
            self.assertIsNone(app.countdown);self.assertIsNone(app.worker)

    def test_rare_reference_cannot_be_loaded_as_a_blueprint(self):
        with ui() as app:
            row=next(r for r in app.build_catalog_data["recipes"] if r["name"]=="Pain Easer")
            app.build_tree.selection_set(row["id"]);app.show_build_recipe()
            self.assertEqual(str(app.use_build_button.cget("state")),"disabled")
            with self.assertRaises(ValueError):app.store_build_recipe()
            self.assertNotIn("Pain Easer",[r["name"] for r in catalog(app.profile).values()])

    def test_materials_row_saves_per_recipe_and_reloads(self):
        with ui() as app:
            app.tabs.select(app.construction_tab);app.construction_pages.select(app.construction_job)
            app.construction_recipe.set("WP9");app.select_recipe()
            self.assertIn("Gamonin=GAM",app.materials_text.get())     # built-in table shown
            app.materials_text.set("Gamonin=GAM, Metal D=MET")
            collected=app.collect()
            self.assertEqual(collected["materials"]["weaponpart_9"],{"Gamonin":"GAM","Metal D":"MET"})
            app.materials_text.set("nonsense")
            with self.assertRaisesRegex(ValueError,"Materials"):app.collect()

    def test_no_favorites_tab_or_drag_options_and_drag_is_plain_left(self):
        with ui() as app:
            self.assertNotIn("Favorites",[app.tabs.tab(t,"text") for t in app.tabs.tabs()])
            self.assertFalse(hasattr(app,"favorites_tab"))
            app.profile["settings"]["drag_button"]="right";app.profile["settings"]["drag_modifier"]="shift"
            app.tabs.select(app.construction_tab);app.construction_pages.select(app.construction_job)
            app.construction_recipe.set("WP7");app.construction_available.set("5");app.construction_count.set("1")
            settings=app.collect()["settings"]
            self.assertEqual((settings["drag_button"],settings["drag_modifier"]),("left","none"))
