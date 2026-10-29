"""The suite shows NeocronSharp (C#) inside its own tabs; it never opens NeocronSharp windows or sends game input."""
import re
import subprocess
import unittest
from unittest import mock

import neocronsharp_link


class LinkTests(unittest.TestCase):
    def test_nothing_opens_neocronsharp_as_its_own_window(self):
        self.assertFalse(hasattr(neocronsharp_link, "open_window"))
        self.assertFalse(hasattr(neocronsharp_link, "WINDOWS"))
        root = neocronsharp_link.ROOT
        self.assertFalse((root / "Open NPC Tracker.cmd").exists())
        self.assertFalse((root / "Open Coordinate Recorder.cmd").exists())

    def test_every_former_window_is_a_page_the_suite_shows_in_a_tab(self):
        self.assertEqual([name for name, _ in neocronsharp_link.TABS], ["Tracker", "Quests", "Loot library", "Tools", "Plugins"])
        for page in ("Player", "Recorder", "Navigation", "Environment"):
            self.assertEqual(neocronsharp_link.tab_of(page), "Tools")
        self.assertEqual(neocronsharp_link.tab_of("Quests"), "Quests")
        self.assertIsNone(neocronsharp_link.tab_of("Nowhere"))
        self.assertEqual(len(neocronsharp_link.PAGES), len(set(neocronsharp_link.PAGES)))
        tracker = (neocronsharp_link.PROJECT / "src" / "NeocronSharp" / "TrackerForm.cs").read_text(encoding="utf-8")
        tabs = re.findall(r'TabPage\("([^"]+)"\)|_\w+Tab = new\("([^"]+)"\)', tracker)
        names = {a or b for a, b in tabs}
        self.assertEqual(names, set(neocronsharp_link.PAGES))  # "page <name>" only works for a tab the tracker has.
        for window in (".Show(this)", "Application.Run"):  # Save/folder pickers (ShowDialog) are the only pop-ups left.
            self.assertNotIn(window, tracker)

    def test_a_missing_build_says_so_instead_of_failing_silently(self):
        with mock.patch.object(neocronsharp_link, "EXECUTABLE", neocronsharp_link.PROJECT / "dist" / "missing.exe"):
            self.assertIn("Build", neocronsharp_link.status())

    def test_a_failed_build_reports_its_last_line(self):
        failed = subprocess.CompletedProcess([], 1, stdout="line one\nerror CS0001: boom\n", stderr="")
        with mock.patch.object(neocronsharp_link.shutil, "which", return_value="dotnet"):
            with self.assertRaisesRegex(RuntimeError, "CS0001"):
                neocronsharp_link.build(run=lambda *a, **k: failed)

    def test_the_embedded_tracker_starts_once_then_moves_between_tabs(self):
        class Pipe(list):
            def write(self, text): self.append(text)
            def flush(self): pass
            def close(self): self.append("<closed>")

        class Process:
            def __init__(self): self.stdin, self.stdout, self.returncode = Pipe(), None, None
            def poll(self): return self.returncode
            def wait(self, timeout): self.returncode = 0
            def terminate(self): raise AssertionError("a tracker that quits is not killed")

        started = []
        def popen(cmd, cwd, stdin, stdout, text):
            started.append(cmd)
            return Process()
        tracker = neocronsharp_link.EmbeddedTracker(popen=popen)
        with mock.patch.object(neocronsharp_link.Path, "exists", return_value=True):
            tracker.show(101, "Tracker")
            tracker.show(202, "Quests")
        process = tracker.process
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][1:], ["--embedded"])
        self.assertEqual("".join(process.stdin), "parent 101\npage Tracker\nparent 202\npage Quests\n")
        tracker.close()
        self.assertEqual(process.stdin[-2:], ["quit\n", "<closed>"])
        self.assertFalse(tracker.running())

    def test_the_suite_follows_a_page_neocronsharp_opens_itself(self):
        tracker = neocronsharp_link.EmbeddedTracker(popen=None)
        tracker.listen(["Tracker ready\n", "page Quests\n"])
        self.assertEqual(tracker.take_page(), "Quests")
        self.assertIsNone(tracker.take_page())

    def test_the_embedded_tracker_needs_a_build(self):
        with mock.patch.object(neocronsharp_link, "EXECUTABLE", neocronsharp_link.PROJECT / "dist" / "missing.exe"):
            with self.assertRaisesRegex(RuntimeError, "not built"):
                neocronsharp_link.EmbeddedTracker(popen=None).show(1, "Tracker")

    def test_the_merged_project_ships_the_built_app_and_its_sources(self):
        self.assertTrue(neocronsharp_link.SOLUTION.exists())
        self.assertTrue(neocronsharp_link.EXECUTABLE.exists())


class SuiteTabTests(unittest.TestCase):
    def test_the_tools_tab_shows_the_former_windows_and_follows_neocronsharp(self):
        import tempfile
        import tkinter as tk
        from pathlib import Path
        from app import App

        class NoInput:
            def release_all(self): pass

        class Tracker:
            def __init__(self): self.shown, self.page = [], None
            def running(self): return True
            def show(self, parent, page): self.shown.append((parent, page))
            def take_page(self):
                page, self.page = self.page, None
                return page
            def close(self): pass

        tracker = Tracker()
        with tempfile.TemporaryDirectory() as folder, mock.patch("app.stop_sound"):
            root = tk.Tk(); root.withdraw()
            app = App(root, Path(folder) / "profile.json", NoInput(), tracker=tracker)
            try:
                self.assertEqual(list(app.sharp_tabs), ["Tracker", "Quests", "Loot library", "Tools", "Plugins"])
                tools = app.sharp_hosts["Tools"].winfo_id()
                app.tabs.select(app.sharp_tabs["Tools"]); app.show_sharp_page()
                self.assertEqual(tracker.shown[-1], (tools, "Player"))
                app.sharp_pages["Tools"].set("Recorder"); app.show_sharp_page()
                self.assertEqual(tracker.shown[-1], (tools, "Recorder"))
                self.assertEqual(app.selected_sharp_page(), "Recorder")
                tracker.page = "Quests"; app.poll()  # NeocronSharp's NPC quests button
                self.assertEqual(app.tabs.select(), str(app.sharp_tabs["Quests"]))
                tracker.page = "Environment"; app.poll()  # its Environment button
                self.assertEqual(app.tabs.select(), str(app.sharp_tabs["Tools"]))
                self.assertEqual(app.selected_sharp_page(), "Environment")
            finally:
                app.close()
