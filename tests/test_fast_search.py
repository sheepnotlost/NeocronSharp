"""Fast visual proposals still require names, quantity and current controls."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from app import App,SEARCH_LABELS
from macro_core import load_profile,save_profile
import test_construction as fixtures
from vision import Detector,cv2,np


class FastSearchTests(unittest.TestCase):
    def test_latest_video_proposes_two_cube_cells_across_scales(self):
        for scale in (1,4/3,1.7):
            for page in range(3):
                with self.subTest(scale=scale,page=page):
                    crop=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/f"fixtures/construction_fast_2155_{page}.png")),cv2.COLOR_BGR2RGB)
                    crop=cv2.resize(crop,None,fx=scale,fy=scale)
                    frame=np.zeros((1440,2560,3),np.uint8)
                    frame[200:200+crop.shape[0],500:500+crop.shape[1]]=crop
                    detector=Detector();detector.inventory_scale=scale
                    inv,candidates=detector.fast_blueprint_candidates(frame)
                    self.assertLessEqual(len(candidates),4)
                    self.assertGreaterEqual(len(candidates),1)
                    if page==2:self.assertIn((5,3),[c["cell"] for c in candidates])

    def test_neutral_cube_is_admitted_by_shape_and_not_color(self):
        crop=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures/construction_fast_2155_2.png")),cv2.COLOR_BGR2RGB)
        frame=np.zeros((1080,1920,3),np.uint8);frame[300:665,1120:1630]=crop
        detector=Detector();inv=detector.inventory(frame)
        x,y=39+3*44.6,63+5*45.5
        patch=detector.region(frame,inv,(x,y,x+44.6,y+45.5))
        patch[:]=cv2.cvtColor(cv2.cvtColor(patch,cv2.COLOR_RGB2GRAY),cv2.COLOR_GRAY2RGB)
        _,candidates=detector.fast_blueprint_candidates(frame)
        self.assertIn((5,3),[c["cell"] for c in candidates])

    def test_fast_repeated_builds_preserve_transfer_and_quantity_guards(self):
        for recipe in ("weaponpart_7","weaponpart_9","holy_heal"):
            with self.subTest(recipe=recipe):
                run=fixtures.ConstructionRunnerTests();run.setup_run(recipe,search_mode="fast")
                run.runner.run()
                self.assertFalse(run.errors(),run.events)
                self.assertEqual(run.runner.completed,3)
                self.assertEqual(len(run.backend.transfers),3)
                self.assertEqual(len(run.backend.starts),3)

    def test_pending_input_stops_before_any_inventory_hover(self):
        run=fixtures.ConstructionRunnerTests();run.setup_run(search_mode="fast")
        run.backend.loaded=True
        run.runner.run()
        self.assertIn("Pending blueprint",run.errors()[0])
        self.assertFalse(run.backend.events)
        self.assertFalse(run.backend.scrolls)

    def test_ui_defaults_to_fast_and_saves_thorough_as_an_explicit_fallback(self):
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"profile.json";root=tk.Tk();root.withdraw();app=App(root,path,NoInput())
            try:
                self.assertEqual(app.search_mode.get(),SEARCH_LABELS["fast"])
                app.tabs.select(app.construction_tab)
                app.search_mode.set(SEARCH_LABELS["all_cells"])
                save_profile(path,app.collect())
                self.assertEqual(load_profile(path)["construction"]["search_mode"],"all_cells")
            finally:app.close()
