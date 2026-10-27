"""Exercise actual Tk geometry in an invisible, non-activating window; no game input."""

from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest

from app import App
from appearance import SKINS, apply_skin


class NoInput:
    def release_all(self):
        pass


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        # A withdrawn window never gets its final client geometry. Map an
        # invisible, disabled window instead, so Tk lays it out without focus.
        self.root.attributes("-alpha", 0)
        self.root.attributes("-disabled", True)
        self.app = App(self.root, Path(self.temp.name) / "profile.json", NoInput())
        self.root.geometry("1040x840+0+0")
        self.root.deiconify()
        self.root.update_idletasks()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_research_paragraph_uses_settings_panel_width_in_every_skin(self):
        app = self.app
        label = next(w for w in app.settings_frame.winfo_children() if isinstance(w, ttk.Label))
        for skin in SKINS:
            apply_skin(self.root, skin, app.heading)
            for geometry in ("960x800", "1040x840", "2560x1390"):
                with self.subTest(skin=skin, geometry=geometry):
                    self.root.geometry(geometry + "+0+0")
                    self.root.update_idletasks()
                    self.assertGreater(label.winfo_width(), 180)
                    self.assertLess(app.settings_frame.winfo_width() - label.winfo_width(), 70)
                    self.assertAlmostEqual(float(label.cget("wraplength")), label.winfo_width() - 4, delta=1)
                    self.assertLess(label.winfo_reqheight(), 160)
                    self.assertLess(app.operation_frame.winfo_y(), 300)

    def test_divider_changes_log_height_while_start_and_tabs_remain_available(self):
        app = self.app
        split = app.main_split
        for tab in app.tabs.tabs():
            app.tabs.select(tab)
            self.root.update_idletasks()
            split.sash_place(0, 0, 300)
            self.root.update_idletasks()
            enlarged = app.log.winfo_height()
            split.sash_place(0, 0, 470)
            self.root.update_idletasks()
            with self.subTest(tab=app.tabs.tab(tab, "text")):
                self.assertGreater(enlarged - app.log.winfo_height(), 140)
                self.assertTrue(app.start_button.winfo_ismapped())
                self.assertTrue(app.tabs.winfo_ismapped())
                workspace = self.root.nametowidget(str(split.panes()[0]))
                start_bottom = (app.start_button.winfo_rooty() - workspace.winfo_rooty()
                                + app.start_button.winfo_height())
                self.assertLess(start_bottom, workspace.winfo_height())

    def test_log_is_read_only_and_scrollable_after_resizing(self):
        app = self.app
        for index in range(80):
            app.report(f"Activity entry {index}")
        app.main_split.sash_place(0, 0, 450)
        self.root.update_idletasks()
        self.assertEqual(str(app.log.cget("state")), "disabled")
        self.assertTrue(app.log_scrollbar.winfo_ismapped())
        self.assertGreater(app.log.yview()[0], 0)
        app.log.yview_moveto(0)
        self.root.update_idletasks()
        self.assertEqual(app.log.yview()[0], 0)
        self.assertIn("Activity entry 79", app.log.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
