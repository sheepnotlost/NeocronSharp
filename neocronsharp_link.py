"""Launch the NeocronSharp windows (C#, in the NeocronSharp/ folder) from the suite.

NeocronSharp reads the game client's memory read-only (fingerprinted build) for the NPC/player tracker, the
native sector map, coordinate recording, point navigation, the loot library, environment/BSP export, quests and
plugins. It runs as its own process; the suite only starts it. Nothing here sends game input.
"""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "NeocronSharp"
EXECUTABLE = PROJECT / "dist" / "NeocronSharp.exe"
SOLUTION = PROJECT / "NeocronSharp.sln"

# What each button opens: (label, command-line arguments).
WINDOWS = (
    ("NPC tracker & map", ()),
    ("Coordinate recorder", ("--recorder",)),
    ("Point navigation", ("--navigation",)),
)


def status():
    """One short line saying whether NeocronSharp can be opened."""
    if not EXECUTABLE.exists():
        return "NeocronSharp is not built yet. Use Build."
    if not dotnet_desktop_ready():
        return "Install the .NET 9 Desktop Runtime to open NeocronSharp."
    return "Ready. Opens in its own window."


def dotnet_desktop_ready():
    """True when a .NET 9 Windows Desktop runtime is installed (NeocronSharp is a framework-dependent app)."""
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App"]
    if os.environ.get("DOTNET_ROOT"):
        roots.insert(0, Path(os.environ["DOTNET_ROOT"]) / "shared" / "Microsoft.WindowsDesktop.App")
    return any(root.is_dir() and any(child.name.startswith("9.") for child in root.iterdir()) for root in roots)


def command(arguments=()):
    return [str(EXECUTABLE), *arguments]


def open_window(arguments=(), popen=subprocess.Popen):
    """Start NeocronSharp with `arguments` as a separate process. Raises RuntimeError with a short reason."""
    if not EXECUTABLE.exists():
        raise RuntimeError("NeocronSharp is not built yet. Use Build (needs the .NET 9 SDK).")
    return popen(command(arguments), cwd=str(EXECUTABLE.parent))


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
