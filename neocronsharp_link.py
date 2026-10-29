"""Show NeocronSharp (C#, in the NeocronSharp/ folder) inside the suite's own window.

NeocronSharp reads the game client's memory read-only (fingerprinted build) for the NPC/player tracker, the
native sector map, coordinate recording, point navigation, the loot library, environment/BSP export, quests and
plugins. It runs as its own process, but the suite only ever starts it embedded (--embedded): each of its pages
sits in a suite tab and it never opens a window of its own. Nothing here sends game input.
"""

import os
import shutil
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "NeocronSharp"
EXECUTABLE = PROJECT / "dist" / "NeocronSharp.exe"
SOLUTION = PROJECT / "NeocronSharp.sln"

# The suite tabs that show NeocronSharp, with the pages each one holds (names match NeocronSharp's "page <name>"
# command). A tab with several pages gets a row of buttons to pick one; Tools holds what used to be separate windows.
TABS = (
    ("Tracker", ("Tracker",)),
    ("Quests", ("Quests",)),
    ("Loot library", ("Loot library",)),
    ("Tools", ("Player", "Recorder", "Navigation", "Environment")),
    ("Plugins", ("Plugins",)),
)
PAGES = tuple(page for _, pages in TABS for page in pages)


def tab_of(page):
    """The suite tab that shows NeocronSharp page `page`, or None."""
    return next((tab for tab, pages in TABS if page in pages), None)


def status():
    """One short line saying whether NeocronSharp can be opened."""
    if not EXECUTABLE.exists():
        return "NeocronSharp is not built yet. Use Build."
    if not dotnet_desktop_ready():
        return "Install the .NET 9 Desktop Runtime to open NeocronSharp."
    return "Ready."


def dotnet_desktop_ready():
    """True when a .NET 9 Windows Desktop runtime is installed (NeocronSharp is a framework-dependent app)."""
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App"]
    if os.environ.get("DOTNET_ROOT"):
        roots.insert(0, Path(os.environ["DOTNET_ROOT"]) / "shared" / "Microsoft.WindowsDesktop.App")
    return any(root.is_dir() and any(child.name.startswith("9.") for child in root.iterdir()) for root in roots)


def command(arguments=()):
    return [str(EXECUTABLE), *arguments]


class EmbeddedTracker:
    """One NeocronSharp tracker process shown inside the suite's NeocronSharp tabs (TABS).

    It starts on first use with --embedded and takes one command per line on stdin (see EmbeddedHost.cs):
    the window handle of the tab to sit in, and the page to show.
    """

    def __init__(self, popen=subprocess.Popen):
        self.popen = popen
        self.process = None
        self.page = None  # A page NeocronSharp switched to itself, for the suite to follow.

    def running(self):
        return self.process is not None and self.process.poll() is None

    def take_page(self):
        page, self.page = self.page, None
        return page

    def listen(self, stdout):
        """NeocronSharp writes "page <name>" when it changes page itself (e.g. its NPC quests button)."""
        for line in stdout:
            if line.startswith("page "):
                self.page = line[5:].strip()

    def show(self, parent, page):
        """Put the tracker into window handle `parent` on `page`, starting it if needed. Raises RuntimeError."""
        if not self.running():
            if not EXECUTABLE.exists():
                raise RuntimeError("NeocronSharp is not built yet. Use Build (needs the .NET 9 SDK).")
            self.process = self.popen(command(("--embedded",)), cwd=str(EXECUTABLE.parent), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True)
            if self.process.stdout is not None:
                threading.Thread(target=self.listen, args=(self.process.stdout,), daemon=True).start()
        self.send(f"parent {int(parent)}")
        self.send(f"page {page}")

    def send(self, line):
        try:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError("NeocronSharp closed. Open the tab again to restart it.") from exc

    def close(self, wait=2.0):
        """Ask the tracker to leave the suite's window and exit; stop it if it does not."""
        if not self.running():
            return
        try:
            self.send("quit")
            self.process.stdin.close()
        except (RuntimeError, OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            self.process.terminate()


def build(run=subprocess.run):
    """Build the C# solution (Release) and refresh dist/. Needs the .NET 9 SDK. Returns a short result line."""
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        raise RuntimeError("The .NET 9 SDK is not installed, so NeocronSharp cannot be built here.")
    result = run([dotnet, "build", str(SOLUTION), "-c", "Release"], cwd=str(PROJECT), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Build failed: " + (result.stdout or result.stderr).strip().splitlines()[-1][:160])
    output = PROJECT / "src" / "NeocronSharp" / "bin" / "Release" / "net9.0-windows"
    EXECUTABLE.parent.mkdir(exist_ok=True)
    for item in output.iterdir():
        if item.is_file():
            shutil.copy2(item, EXECUTABLE.parent / item.name)
    return "NeocronSharp built."
