import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from app import App
from macro_core import default_profile, validate_profile


class NavRayProfileTests(unittest.TestCase):
    def test_default_profile_and_validation(self):
        profile = default_profile()
        self.assertEqual(profile["navray"], {"destination": ""})
        profile["operation"] = "navray"
        with self.assertRaises(ValueError):
            validate_profile(profile)                      # needs Category > Destination
        profile["navray"]["destination"] = "Faction HQs > Black Dragon"
        validate_profile(profile)
        profile["navray"]["destination"] = ""
        profile["navray"]["scan"] = True                   # reading the lists needs no destination
        validate_profile(profile)
        profile["navray"]["scan"] = False
        profile["navray"]["destination"] = "x" * 200 + " > y"
        with self.assertRaises(ValueError):
            validate_profile(profile)

    def test_tab_collects_and_restores_the_destination(self):
        class NoInput:
            def release_all(self):pass
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            root = tk.Tk();root.withdraw();app = App(root, profile_path=path, backend=NoInput())
            try:
                app.tabs.select(app.navray_tab)
                app.navray_catalog = {"FACTION HQS": ["PROTOPHARM", "BLACK DRAGON"]}
                app.navray_category.set("FACTION HQS");app.pick_navray_category("BLACK DRAGON")
                profile = app.collect()
                self.assertEqual(profile["operation"], "navray")
                self.assertEqual(profile["navray"]["destination"], "FACTION HQS > BLACK DRAGON")
                self.assertFalse(profile["navray"]["scan"])
            finally:
                app.close()
