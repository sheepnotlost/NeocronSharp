"""The Job Loop tab: its buttons and countdown, with a fake runner (no engine, no input)."""
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

import jobs_tab


class Runner:
    def __init__(self):
        self.ran = threading.Event()

    def run(self):
        self.ran.set()


class JobsTabTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.frame = tk.Frame(self.root)
        self.frame.pack()
        self.busy = False
        self.started, self.jobs = [], []
        self.runner = Runner()
        self.tab = jobs_tab.JobsTab(self.frame, self.root, other_live=lambda: self.busy, mission_runner=self.make)

    def tearDown(self):
        self.tab.close()
        self.root.destroy()

    def make(self, emit, control, job):
        self.started.append(control)
        self.jobs.append(job)
        return self.runner

    def state(self, button):
        return str(button.cget("state"))

    def counted(self, button=None):
        waiting = []
        with patch.object(self.tab.root, "after", lambda ms, call, *args: waiting.append(call) or "later"):
            (button or self.tab.start_button).invoke()
        return waiting[0]

    def test_the_countdown_comes_before_the_runner_and_the_stop_is_live(self):
        begin = self.counted()
        self.assertEqual(self.started, [])
        self.assertEqual(self.state(self.tab.start_button), "disabled")
        self.assertEqual(self.state(self.tab.stop_button), "normal")
        with patch.object(jobs_tab.tt, "build_tool", lambda progress=None: None), patch.object(jobs_tab.clients, "focus", lambda: True):
            begin()
            self.tab.event(*self.tab.queue.get(timeout=5))
        self.assertEqual(self.started, [self.tab.control])
        self.assertEqual(self.jobs, ["TL60"])
        self.assertTrue(self.runner.ran.wait(5))

    def test_the_tl130_button_runs_tl130_jobs_and_both_wait_while_one_runs(self):
        begin = self.counted(self.tab.tl130_button)
        self.assertEqual([self.state(b) for b in (self.tab.start_button, self.tab.tl130_button)], ["disabled"]*2)
        with patch.object(jobs_tab.tt, "build_tool", lambda progress=None: None), patch.object(jobs_tab.clients, "focus", lambda: True):
            begin()
            self.tab.event(*self.tab.queue.get(timeout=5))
        self.assertEqual(self.jobs, ["TL130"])

    def test_a_fresh_download_builds_the_engine_first(self):
        built = []
        begin = self.counted()
        with patch.object(jobs_tab.tt, "build_tool", lambda progress=None: built.append(progress) or "No .NET here."):
            begin()
            self.tab.event(*self.tab.queue.get(timeout=5))
        self.assertEqual(len(built), 1)
        self.assertEqual(self.started, [])
        self.assertFalse(self.tab.steering())
        self.assertEqual(self.tab.status.get(), "No .NET here.")

    def test_stop_during_the_countdown_cancels_it(self):
        self.tab.start()
        self.tab.stop()
        self.assertFalse(self.tab.steering())
        self.assertIsNone(self.tab.countdown)
        self.assertEqual(self.state(self.tab.start_button), "normal")
        self.assertEqual(self.state(self.tab.stop_button), "disabled")

    def test_stop_during_the_build_starts_nothing(self):
        begin = self.counted()
        with patch.object(jobs_tab.tt, "build_tool", lambda progress=None: None):
            begin()
            self.tab.stop()
            self.tab.event(*self.tab.queue.get(timeout=5))
        self.assertEqual(self.started, [])
        self.assertFalse(self.tab.steering())

    def test_it_refuses_while_something_else_steers(self):
        self.busy = True
        self.tab.start()
        self.assertFalse(self.tab.steering())
        self.assertIn("Stop it first", self.tab.status.get())

    def test_the_runner_ending_frees_the_button_and_says_why(self):
        self.tab.control = jobs_tab.Control()
        self.tab.event("status", "Talking to a recruiter.")
        self.assertEqual(self.tab.status.get(), "Talking to a recruiter.")
        self.tab.event("done", "No recruiter here. 3 jobs done.")
        self.assertEqual(self.tab.status.get(), "No recruiter here. 3 jobs done.")
        self.assertEqual(self.state(self.tab.start_button), "normal")

    def test_a_runner_that_cannot_start_says_so(self):
        def broken(emit, control, job):
            raise ImportError("no module")
        self.tab.mission_runner = broken
        self.tab.control = jobs_tab.Control()
        with patch.object(jobs_tab.clients, "focus", lambda: True):
            self.tab.built(None)
        self.assertIn("could not start: no module", self.tab.status.get())
        self.assertFalse(self.tab.steering())


class AppTests(unittest.TestCase):
    def test_it_is_a_sub_tab_of_research_with_no_start_and_shares_the_mouse(self):
        from app import App

        class NoInput:
            def release_all(self):
                pass
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            app = App(root, profile_path=Path(folder) / "profile.json", backend=NoInput())
            try:
                self.assertEqual(app.tabs.tab(app.job_loop_tab, "text"), "Job Loop")
                app.tabs.select(app.research_tab)
                root.update()
                self.assertEqual(str(app.start_button.cget("state")), "normal")
                app.tabs.select(app.job_loop_tab)
                root.update()
                self.assertEqual(str(app.start_button.cget("state")), "disabled")
                with self.assertRaisesRegex(ValueError, "own buttons"):
                    app.collect()
                self.assertFalse(app.jobs.other_live())
                app.target.process = object()
                self.assertTrue(app.jobs.other_live())
                app.target.process = None
                app.jobs.control = jobs_tab.Control()
                self.assertTrue(app.target.other_live())
                self.assertTrue(app.traversal.other_live())
                app.jobs.control = None
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
