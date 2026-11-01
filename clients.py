"""Which Neocron clients are open, told apart by their health and PSI, read from each window without giving it focus.

The engine reads the client named in NEOCRON_PID, which is only needed when two are open.
"""
import ctypes
from ctypes import wintypes
import os
import re
import subprocess

STATS = (("HLT", .835, .875), ("PSI", .915, .955))      # the rows of the readout, as fractions of the window's height


def label(pid, stats):
    """(30132, {"HLT": 768, "PSI": 433}) -> "HLT 768, PSI 433 (30132)"."""
    shown = ", ".join(f"{name} {value}" for name, value in stats.items())
    return f"{shown} ({pid})" if shown else f"Client {pid}"


def choose(pid):
    """Point the engine at this client, or at the only one (None)."""
    if pid is None:
        os.environ.pop("NEOCRON_PID", None)
    else:
        os.environ["NEOCRON_PID"] = str(pid)


def windows():
    """{pid: window} of the running clients."""
    out = subprocess.run(["tasklist", "/fi", "imagename eq neocronclient.exe", "/fo", "csv", "/nh"], capture_output=True,
                         text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    pids = {int(line.split(",")[1].strip('"')) for line in out.splitlines() if line.lower().startswith('"neocronclient')}
    found = {}
    user32 = ctypes.windll.user32

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and user32.IsWindowVisible(hwnd):
            found[owner.value] = hwnd
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit), 0)
    return found


def capture(hwnd):
    """A window's picture, focused or not."""
    import numpy as np
    from PIL import Image
    user32, gdi = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]

    class Header(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint), ("width", ctypes.c_int), ("height", ctypes.c_int), ("planes", ctypes.c_ushort),
                    ("bits", ctypes.c_ushort), ("rest", ctypes.c_uint * 6)]
    box = wintypes.RECT()
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.GetClientRect(hwnd, ctypes.byref(box))
    width, height = box.right, box.bottom
    screen = user32.GetDC(hwnd)
    memory = gdi.CreateCompatibleDC(screen)
    picture = gdi.CreateCompatibleBitmap(screen, width, height)
    try:
        gdi.SelectObject(memory, picture)
        user32.PrintWindow(hwnd, memory, 3)
        header = Header(40, width, -height, 1, 32)
        pixels = ctypes.create_string_buffer(width*height*4)
        gdi.GetDIBits(memory, picture, 0, height, pixels, ctypes.byref(header), 0)
        return np.array(Image.frombuffer("RGBA", (width, height), pixels, "raw", "BGRA", 0, 1).convert("RGB"))
    finally:
        gdi.DeleteObject(picture)
        gdi.DeleteDC(memory)
        user32.ReleaseDC(hwnd, screen)


def stats(frame, detector):
    """{"HLT": maximum, "PSI": maximum} from a client's readout; a row it can't read is left out."""
    height, width = frame.shape[:2]
    gray, found = detector.gray(frame), {}
    for name, top, bottom in STATS:
        crop = gray[int(top*height):int(bottom*height), int(.85*width):int(.95*width)]
        text = " ".join(word for word, *_ in sorted(detector.text_reader().read_words(crop), key=lambda w: w[1]))
        match = re.search(r"(\d+)\D+(\d+)", text)
        if match:
            found[name] = int(match.group(2))
    return found


def list_clients():
    """[{"pid", "label", "psi"}], and only worth reading the windows for when there is a choice to make."""
    found = windows()
    if len(found) < 2:
        return [{"pid": pid, "label": label(pid, {}), "psi": 0} for pid in found]
    from vision import Detector
    detector = Detector()
    rows = [(pid, stats(capture(hwnd), detector)) for pid, hwnd in sorted(found.items())]
    return [{"pid": pid, "label": label(pid, read), "psi": read.get("PSI", 0)} for pid, read in rows]
