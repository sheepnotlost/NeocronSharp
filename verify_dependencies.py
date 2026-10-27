"""Verify the portable runtime and visual assets without capturing or sending input."""

import argparse
from importlib.metadata import version
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent


def verify():
    runtime = (ROOT / "runtime").resolve()
    if Path(sys.executable).resolve().parent != runtime:
        raise RuntimeError("Use Launch.cmd so the program runs with its bundled Python.")
    if struct.calcsize("P") != 8:
        raise RuntimeError("The portable runtime must be 64-bit.")
    import tkinter
    import numpy
    import cv2
    for module in (tkinter, numpy, cv2):
        if not Path(module.__file__).resolve().is_relative_to(runtime):
            raise RuntimeError(f"{module.__name__} was loaded outside the bundled runtime.")
    tcl = tkinter.Tcl()
    if not Path(tcl.call("info", "library")).resolve().is_relative_to(runtime):
        raise RuntimeError("Tcl was loaded outside the bundled runtime.")
    # Exercise the native libraries and verify all shipped recognition artwork.
    from vision import Detector
    Detector()
    from text_reader import TextReader
    TextReader()
    from recycling import load_catalog
    data=load_catalog()
    from construction_catalog import load_construction_catalog
    construction_data=load_construction_catalog()
    if not (ROOT/"assets/stopped.wav").is_file():
        raise RuntimeError("Bundled stop sound is missing.")
    cv2.cvtColor(numpy.zeros((2, 2, 3), dtype=numpy.uint8), cv2.COLOR_RGB2GRAY)
    return (f"Bundled dependencies ready: Python {sys.version.split()[0]} (64-bit), "
            f"NumPy {version('numpy')}, OpenCV {version('opencv-python-headless')}, "
            f"Tcl/Tk {tkinter.TkVersion}, Windows OCR, {len(data['recipes'])} recycling / {len(construction_data['recipes'])} construction catalog entries. No installation or game input needed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        result = verify()
        if not args.quiet:
            print(result)
    except Exception as exc:
        print(f"Bundled dependency check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
