"""The suite opens the NeocronSharp (C#) windows; it never runs them in-process or sends game input."""
import subprocess
import unittest
from unittest import mock

import neocronsharp_link


class LinkTests(unittest.TestCase):
    def test_each_button_starts_the_built_app_with_its_window_argument(self):
        calls = []
        with mock.patch.object(neocronsharp_link.Path, "exists", return_value=True):
            for _, arguments in neocronsharp_link.WINDOWS:
                neocronsharp_link.open_window(arguments, popen=lambda cmd, cwd: calls.append((cmd, cwd)))
        self.assertEqual([cmd[1:] for cmd, _ in calls], [[], ["--recorder"], ["--navigation"]])
        self.assertTrue(all(cmd[0].endswith("NeocronSharp.exe") for cmd, _ in calls))
        self.assertTrue(all(cwd.endswith("dist") for _, cwd in calls))

    def test_a_missing_build_says_so_instead_of_failing_silently(self):
        with mock.patch.object(neocronsharp_link, "EXECUTABLE", neocronsharp_link.PROJECT / "dist" / "missing.exe"):
            with self.assertRaisesRegex(RuntimeError, "not built"):
                neocronsharp_link.open_window()
            self.assertIn("Build", neocronsharp_link.status())

    def test_a_failed_build_reports_its_last_line(self):
        failed = subprocess.CompletedProcess([], 1, stdout="line one\nerror CS0001: boom\n", stderr="")
        with mock.patch.object(neocronsharp_link.shutil, "which", return_value="dotnet"):
            with self.assertRaisesRegex(RuntimeError, "CS0001"):
                neocronsharp_link.build(run=lambda *a, **k: failed)

    def test_the_merged_project_ships_the_built_app_and_its_sources(self):
        self.assertTrue(neocronsharp_link.SOLUTION.exists())
        self.assertTrue(neocronsharp_link.EXECUTABLE.exists())
