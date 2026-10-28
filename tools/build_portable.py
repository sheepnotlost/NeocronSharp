"""Build and relocation-test the complete offline Windows app bundle."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "NeocronSharp Portable.zip"
FILES = ("app.py", "tech_counter.py", "TECH-COUNTER-INTEGRATION.md", "macro_core.py", "windows_backend.py", "vision.py", "vision_runner.py",
         "recipes.py", "gogo.py", "neocronsharp_link.py", "routes.py", "pathvision.py", "navray.py", "navray_runner.py", "construction_catalog.py", "inventory_tracking.py", "construction_runner.py", "recycling.py", "appearance.py", "skin_chrome.py", "text_reader.py", "verify_dependencies.py", "Launch.cmd", "Launch.ps1", "Install-Dependencies.cmd",
         "Check-Dependencies.cmd", "requirements.txt", "README.md", "profile.json", "SPEC-SHEET.md", "SPEC.md", "TASKS.md", "FEATURE-IDEAS.md", "CLAUDE-HANDOFF.md", "CLAUDE-PROMPT.txt")


def create_archive():
    files = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    for folder in ("runtime", "assets", "data", "styling", "ntc"):
        files.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, "NeocronSharp/" + path.relative_to(ROOT).as_posix())
    print(f"Archive created: {ARCHIVE} ({ARCHIVE.stat().st_size / 1024**2:.1f} MiB)", flush=True)


def main():
    subprocess.run([str(ROOT / "runtime/python.exe"), str(ROOT / "verify_dependencies.py"), "--quiet"],
                   cwd=ROOT, check=True)
    create_archive()

    checks = ROOT / "analysis"
    checks.mkdir(exist_ok=True)
    extracted = Path(tempfile.mkdtemp(prefix="portable-relocation-", dir=checks)).resolve()
    try:
        with zipfile.ZipFile(ARCHIVE) as archive:
            archive.extractall(extracted)
        bundle = extracted / "NeocronSharp"
        environment = os.environ.copy()
        # Deliberately make installed Python/Codex paths unusable for the child.
        environment["PYTHONHOME"] = str(extracted / "no-external-python")
        environment["PYTHONPATH"] = str(extracted / "no-external-packages")
        environment["TCL_LIBRARY"] = str(extracted / "no-external-tcl")
        environment["TK_LIBRARY"] = str(extracted / "no-external-tk")
        windows = Path(os.environ["SystemRoot"])
        environment["PATH"] = str(windows / "System32")
        powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
        for mode in ("-CheckDependencies", "-SmokeUi"):
            subprocess.run([str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(bundle / "Launch.ps1"), mode], cwd=checks, env=environment, check=True)
        print("Extracted bundle passed dependency and UI checks with conflicting Python/Tcl settings and a clean PATH.",
              flush=True)
    finally:
        # Verify the absolute cleanup target stays in this task's analysis folder.
        if extracted.parent != checks.resolve() or not extracted.is_relative_to(checks.resolve()):
            raise RuntimeError("Refusing to clean up outside the portable-test directory.")
        shutil.rmtree(extracted)


if __name__ == "__main__":
    main()
