from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from appearance import SKINS, stop_sound
from construction_runner import ConstructionRunner
from macro_core import Control, Interrupted, default_profile, load_profile, save_profile, validate_profile
from recycling import load_catalog, filter_recipes, RecyclingRunner
from test_construction import ConstructionBackend, ConstructionDetector
from test_macro import FakeClock
from vision import Anchor, Detector


class SlotThresholdTests(unittest.TestCase):
    def test_qualifying_result_stops_before_loading_another_blueprint(self):
        profile=default_profile();profile["operation"]="construction";profile["client_size"]=[1920,1080]
        profile["construction"]={"recipe":"holy_heal","available":4,"count":0,"count_slots":False,"stop_at_slots":4}
        clock=FakeClock();backend=ConstructionBackend(clock,"holy_heal",4)
        backend.settle_result=True;backend.result_slots=[0,2,4,5]
        events=[]
        runner=ConstructionRunner(profile,backend,Control(),lambda k,v:events.append((k,v)),clock.clock,clock.sleep,
                                  detector=ConstructionDetector())
        runner.run()
        self.assertFalse([e for e in events if e[0]=="error"],events)
        self.assertEqual(runner.completed,3)
        self.assertEqual(len(backend.transfers),3)
        self.assertEqual(len(backend.starts),3)
        self.assertEqual(backend.available,1)
        self.assertTrue(backend.output)
        self.assertIn("4 slots",[v for k,v in events if k=="done"][-1])

    def test_invalid_threshold_and_counter_type_are_rejected(self):
        for key,value in (("stop_at_slots",6),("stop_at_slots",-1),("stop_at_slots",True),("count_slots","yes")):
            profile=default_profile();profile["construction"][key]=value
            with self.assertRaises(ValueError):validate_profile(profile,require_ready=False)


class RecyclingCatalogTests(unittest.TestCase):
    def test_all_entries_have_sources_and_positive_published_quantities(self):
        data=load_catalog()
        self.assertEqual(len(data["recipes"]),201)
        self.assertEqual(sum(not r.get("verification") for r in data["recipes"]),161)
        self.assertEqual(len({r["id"] for r in data["recipes"]}),201)
        self.assertTrue(all(r["source_url"].startswith("https://") for r in data["recipes"]))
        rifle=next(r for r in data["recipes"] if r["name"]=="Mendicant Rifle")
        self.assertEqual({i["name"]:i["quantity"] for i in rifle["ingredients"]},
                         {"Metal Plate":3,"Wire Junk":3,"Metal Pipes":1})
        self.assertEqual(data["known_incomplete"][0]["name"],"Swamp Shaman Trophy")

    def test_searches_names_ingredients_and_categories(self):
        recipes=load_catalog()["recipes"]
        self.assertTrue(filter_recipes(recipes,"wp" )==[])  # names are preserved, not fabricated aliases
        self.assertTrue(any(r["name"]=="Trisol" for r in filter_recipes(recipes,"solantium","Chemicals")))
        self.assertTrue(any(r["name"]=="Antidote" for r in filter_recipes(recipes,"antidote","Drugs")))


class RecycleBackend:
    def __init__(self,clock):
        self.clock=clock;self.focus=True;self.position=None;self.starts=0;self.finish=None
        self.output=False;self.tool=True;self.wrong_result=False;self.processor=Anchor(100,200,1,1)
    def check_focus(self,size):
        if not self.focus:raise Interrupted("Game lost focus")
    def capture(self):
        if self.finish is not None and self.clock.now>=self.finish:
            self.finish=None;self.output=True;self.processor=Anchor(450,300,1,1)
        return {"busy":self.finish is not None,"result":self.output,"processor":self.processor}
    def move(self,point):self.position=point
    def button(self,name,down):
        if not down and self.position==self.processor.start_point():
            self.starts+=1;self.finish=self.clock.now+.3
    def release_all(self):pass


class RecycleDetector:
    input_point=staticmethod(Detector.input_point)
    def __init__(self,backend,recipe):self.backend=backend;self.recipe=recipe
    def processor(self,frame,checkpoint=lambda:None):checkpoint();return frame["processor"]
    def quantity(self,frame,checkpoint=lambda:None):checkpoint();return None
    def progress_busy(self,frame,processor):return frame["busy"]
    def result_details(self,frame,point,scale):
        if "recycling_tool" in self.recipes:
            return {"recipe":"recycling_tool","slots":None} if self.backend.tool else None
        if frame["result"]:
            return {"recipe":"wrong" if self.backend.wrong_result else self.recipe,"slots":None}
        return None


class RecyclingRunnerTests(unittest.TestCase):
    def setup_run(self):
        profile=default_profile();profile["operation"]="recycling";profile["client_size"]=[1920,1080]
        recipe=next(r["id"] for r in load_catalog()["recipes"] if r["name"]=="Trisol")
        profile["recycling"]["recipe"]=recipe
        self.clock=FakeClock();self.backend=RecycleBackend(self.clock);self.events=[]
        self.runner=RecyclingRunner(profile,self.backend,Control(),lambda k,v:self.events.append((k,v)),
                                     self.clock.clock,self.clock.sleep,detector=RecycleDetector(self.backend,recipe))
    def test_one_prepared_run_relocates_verifies_output_and_stops(self):
        self.setup_run();self.runner.run()
        self.assertEqual(self.backend.starts,1)
        self.assertEqual(self.runner.completed,1)
        self.assertFalse([e for e in self.events if e[0]=="error"],self.events)
    def test_wrong_tool_never_starts(self):
        self.setup_run();self.backend.tool=False;self.runner.run()
        self.assertEqual(self.backend.starts,0)
        self.assertIn("Tool name was not verified",[v for k,v in self.events if k=="error"][0])
    def test_wrong_result_never_retries_start(self):
        self.setup_run();self.backend.wrong_result=True;self.runner.run()
        self.assertEqual(self.backend.starts,1)
        self.assertEqual(self.runner.completed,0)
        self.assertTrue([e for e in self.events if e[0]=="error"])
    def test_focus_loss_stops_prepared_recycling(self):
        self.setup_run()
        self.clock.on_sleep=lambda:setattr(self.backend,"focus",False) if self.backend.starts else None
        self.runner.run()
        self.assertEqual(self.backend.starts,1)
        self.assertEqual(self.runner.completed,0)
        self.assertIn("Game lost focus",[v for k,v in self.events if k=="error"][0])


class AppearanceUiTests(unittest.TestCase):
    def test_dead_sector_restores_original_layouts_and_fonts_after_other_skins(self):
        from tkinter import ttk
        from appearance import apply_skin
        from skin_chrome import TREATMENTS
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder,patch("app.stop_sound"):
            root=tk.Tk();root.withdraw();app=App(root,Path(folder)/"profile.json",NoInput())
            try:
                style=ttk.Style(root)
                apply_skin(root,"amber",app.heading)
                names=("TLabelframe","TButton","TEntry","TCombobox","TNotebook.Tab")
                baseline={name:style.layout(name) for name in names}
                fonts={name:str(style.lookup(name,"font")) for name in ("TButton","TLabelframe.Label")}
                for key in TREATMENTS:
                    apply_skin(root,key,app.heading)
                    self.assertIn(f"Macro.{key}.panel",str(style.layout("TLabelframe")))
                    self.assertTrue(app.heading.cget("image"))
                    self.assertEqual(app.start_button.cget("style"),"Start.TButton")
                apply_skin(root,"amber",app.heading)
                self.assertEqual({name:style.layout(name) for name in names},baseline)
                self.assertEqual({name:str(style.lookup(name,"font")) for name in fonts},fonts)
                self.assertFalse(app.heading.cget("image"))
                self.assertEqual(app.start_button.cget("style"),"TButton")
            finally:app.close()

    def test_all_ten_skins_preserve_jobs_and_preferences_persist(self):
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder,patch("app.stop_sound"):
            root=tk.Tk();root.withdraw();app=App(root,Path(folder)/"profile.json",NoInput())
            try:
                self.assertEqual(len(SKINS),15);self.assertIn("basic",SKINS)
                app.tabs.select(app.construction_tab)
                before=app.collect();before.pop("preferences")
                for key,skin in SKINS.items():
                    app.skin_var.set(skin["name"]);app.save_preferences()
                    current=app.collect();current.pop("preferences")
                    self.assertEqual(current,before)
                    self.assertEqual(load_profile(app.profile_path)["preferences"]["skin"],key)
                app.tabs.select(app.recycling_tab);app.recycle_query.set("Trisol")
                profile=app.collect();validate_profile(profile)
                self.assertEqual(profile["operation"],"recycling")
            finally:app.close()

    def test_optional_stop_sound_is_deduplicated_per_batch(self):
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder,patch("app.stop_sound") as sound:
            root=tk.Tk();root.withdraw();app=App(root,Path(folder)/"profile.json",NoInput())
            try:
                app.stop_sound_var.set(True)
                app.events.put(("error","Game lost focus"));app.poll()
                app.events.put(("done","Already ended"));app.poll()
                sound.assert_called_once_with(True)
                app._stop_sound_played=False
                app.events.put(("done","Slot target reached"));app.poll()
                self.assertEqual(sound.call_count,2)
            finally:app.close()
            self.assertEqual(sound.call_count,2)

    def test_disabled_audio_never_calls_windows_playback(self):
        with patch("winsound.PlaySound") as sound:
            self.assertFalse(stop_sound(False))
            sound.assert_not_called()
