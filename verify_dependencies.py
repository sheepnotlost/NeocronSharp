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
    import PIL
    import pytesseract
    import mss
    import packaging
    for module in (tkinter, numpy, cv2, PIL, pytesseract, mss, packaging):
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
    from ntc import ocr, sets
    if not (ocr.BUNDLED / "tesseract.exe").is_file() or not (ocr.BUNDLED / "tessdata/eng.traineddata").is_file():
        raise RuntimeError("Bundled Tech Counter OCR executable or English model is missing.")
    ocr.configure("")
    ocr.require()
    # Exercise the executable, DLLs and language model, including after relocation.
    probe = numpy.full((70, 450, 3), 255, dtype=numpy.uint8)
    cv2.putText(probe, "Tech Counter 123", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    if "123" not in pytesseract.image_to_string(probe, config="--psm 7"):
        raise RuntimeError("Bundled Tech Counter OCR could not read its verification image.")
    rares = sets.load()
    cv2.cvtColor(numpy.zeros((2, 2, 3), dtype=numpy.uint8), cv2.COLOR_RGB2GRAY)
    return (f"Bundled dependencies ready: Python {sys.version.split()[0]} (64-bit), "
            f"NumPy {version('numpy')}, OpenCV {version('opencv-python-headless')}, "
            f"Tcl/Tk {tkinter.TkVersion}, Windows OCR, bundled Tesseract, {len(rares)} rare sets, "
            f"{len(data['recipes'])} recycling / {len(construction_data['recipes'])} construction catalog entries. No installation or game input needed.")


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
