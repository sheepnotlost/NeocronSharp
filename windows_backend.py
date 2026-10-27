"""Small Windows adapter. No hooks, memory inspection, or background-game input."""

import ctypes
from ctypes import wintypes
import os

from macro_core import Interrupted, SAMPLE_OFFSETS


class WindowsBackend:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("The live macro requires Windows.")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        try:
            self.user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            self.user.SetProcessDPIAware()
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetDC.argtypes = [wintypes.HWND]
        self.user.GetDC.restype = wintypes.HDC
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.gdi.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi.GetPixel.restype = wintypes.DWORD
        class MouseInput(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class KeyboardInput(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class InputUnion(ctypes.Union):
            _fields_ = [("mi", MouseInput), ("ki", KeyboardInput)]

        class Input(ctypes.Structure):
            _anonymous_ = ("value",)
            _fields_ = [("type", wintypes.DWORD), ("value", InputUnion)]

        self.Input = Input
        self.MouseInput = MouseInput
        self.KeyboardInput = KeyboardInput
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT
        self.hwnd = None
        self.pid = None
        self.held_buttons = set()
        self.held_keys = set()

    def bind_foreground(self):
        hwnd = self.user.GetForegroundWindow()
        if not hwnd:
            raise ValueError("No foreground game window found.")
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            raise ValueError("Focus Neocron before the countdown finishes.")
        self.hwnd = hwnd
        self.pid = pid.value
        return self.title(), self.client_size()

    def title(self):
        n = self.user.GetWindowTextLengthW(self.hwnd)
        buffer = ctypes.create_unicode_buffer(n + 1)
        self.user.GetWindowTextW(self.hwnd, buffer, n + 1)
        return buffer.value or "Untitled window"

    def client_size(self):
        rect = wintypes.RECT()
        if not self.user.GetClientRect(self.hwnd, ctypes.byref(rect)):
            raise Interrupted("Cannot read the bound game window.")
        return [rect.right - rect.left, rect.bottom - rect.top]

    def origin(self):
        point = wintypes.POINT(0, 0)
        if not self.user.ClientToScreen(self.hwnd, ctypes.byref(point)):
            raise Interrupted("Cannot locate the game client.")
        return point.x, point.y

    def check_focus(self, expected_size):
        if not self.hwnd or not self.user.IsWindow(self.hwnd):
            raise Interrupted("Bound game window closed. Start again with Neocron focused.")
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        if pid.value != self.pid:
            raise Interrupted("Bound window identity changed. Start again with Neocron focused.")
        if self.user.IsIconic(self.hwnd) or self.user.GetForegroundWindow() != self.hwnd:
            raise Interrupted("Game lost focus. Batch stopped; no automatic resume.")
        if self.client_size() != list(expected_size):
            raise Interrupted("Game client size changed. Restart at the new window size.")

    def cursor_client(self):
        point = wintypes.POINT()
        if not self.user.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("Cannot read mouse position.")
        x, y = self.origin()
        return [point.x - x, point.y - y]

    def sample(self, point):
        x, y = self.origin()
        dc = self.user.GetDC(None)
        if not dc:
            raise RuntimeError("Cannot sample the display.")
        try:
            colors = [int(self.gdi.GetPixel(dc, x + point[0] + dx, y + point[1] + dy))
                      for dx, dy in SAMPLE_OFFSETS]
            if any(c == 0xFFFFFFFF for c in colors):
                raise RuntimeError("Screen sample is outside the visible desktop.")
            if all(c == 0 for c in colors):
                raise RuntimeError("Screen sample is black. Try windowed or borderless mode.")
            return colors
        finally:
            self.user.ReleaseDC(None, dc)

    def capture(self):
        """Capture the bound, foreground client for the macro's own detector."""
        return self._capture(None)

    def capture_region(self, box):
        """Capture fewer game pixels; preserve client coordinates for detection."""
        return self._capture(box)

    def _capture(self, box):
        from vision import np
        client_width, client_height = self.client_size()
        self.check_focus([client_width, client_height])
        left,top,right,bottom=(0,0,client_width,client_height) if box is None else box
        left,top=max(0,int(left)),max(0,int(top))
        right,bottom=min(client_width,int(right)),min(client_height,int(bottom))
        width,height=right-left,bottom-top
        if width<=0 or height<=0:raise RuntimeError("Invalid game capture region.")
        x, y = self.origin()
        x+=left;y+=top
        gdi = self.gdi
        gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi.CreateCompatibleDC.restype = wintypes.HDC
        gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi.SelectObject.restype = wintypes.HGDIOBJ
        gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi.DeleteDC.argtypes = [wintypes.HDC]
        gdi.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]

        class Header(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                        ("height", wintypes.LONG), ("planes", wintypes.WORD),
                        ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                        ("image_size", wintypes.DWORD), ("x_resolution", wintypes.LONG),
                        ("y_resolution", wintypes.LONG), ("colors_used", wintypes.DWORD),
                        ("important_colors", wintypes.DWORD)]

        class Info(ctypes.Structure):
            _fields_ = [("header", Header), ("colors", wintypes.DWORD * 3)]

        gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                 ctypes.c_void_p, ctypes.POINTER(Info), wintypes.UINT]
        screen = self.user.GetDC(None)
        memory = gdi.CreateCompatibleDC(screen)
        bitmap = gdi.CreateCompatibleBitmap(screen, width, height)
        if not screen or not memory or not bitmap:
            if bitmap: gdi.DeleteObject(bitmap)
            if memory: gdi.DeleteDC(memory)
            if screen: self.user.ReleaseDC(None, screen)
            raise RuntimeError("Cannot allocate a game screenshot.")
        previous = gdi.SelectObject(memory, bitmap)
        try:
            if not gdi.BitBlt(memory, 0, 0, width, height, screen, x, y, 0x40CC0020):
                raise RuntimeError("Game screenshot capture failed. Try windowed or borderless mode.")
            gdi.SelectObject(memory, previous)
            previous = None
            info = Info(header=Header(size=ctypes.sizeof(Header), width=width, height=-height,
                                      planes=1, bits=32, compression=0))
            pixels = ctypes.create_string_buffer(width * height * 4)
            if gdi.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(info), 0) != height:
                raise RuntimeError("Cannot read the game's screenshot pixels.")
            self.check_focus([client_width, client_height])
            frame = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)[:, :, 2::-1].copy()
            if not frame.any():
                raise RuntimeError("Game capture is black. Try windowed or borderless mode.")
            if box is not None:
                padded=np.zeros((client_height,client_width,3),dtype=np.uint8)
                padded[top:bottom,left:right]=frame
                return padded
            return frame
        finally:
            if previous is not None: gdi.SelectObject(memory, previous)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            self.user.ReleaseDC(None, screen)

    def move(self, point):
        x, y = self.origin()
        if not self.user.SetCursorPos(x + point[0], y + point[1]):
            raise RuntimeError("Windows rejected mouse movement.")

    def move_relative(self, dx, dy):
        """Raw mouse motion for mouse-look (the game holds the cursor, so absolute moves do not turn the camera)."""
        self.send(self.Input(type=0, mi=self.MouseInput(dx=int(dx), dy=int(dy), dwFlags=0x0001)))

    def send(self, event):
        if self.user.SendInput(1, ctypes.byref(event), ctypes.sizeof(self.Input)) != 1:
            raise RuntimeError("Windows rejected input. Match the game's privilege level and check its input settings.")

    def button(self, button, down):
        flags = {("left", True): 0x0002, ("left", False): 0x0004,
                 ("right", True): 0x0008, ("right", False): 0x0010}
        event = self.Input(type=0, mi=self.MouseInput(dwFlags=flags[(button, down)]))
        self.send(event)
        if down:
            self.held_buttons.add(button)
        else:
            self.held_buttons.discard(button)

    def key(self, name, down):
        scan = {"ctrl": 0x1D, "shift": 0x2A, "a": 0x1E, "w": 0x11, "tab": 0x0F, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
                "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
                "backspace": 0x0E, "delete": 0x53}[name]
        flags = 0x0008 | (0 if down else 0x0002) | (0x0001 if name == "delete" else 0)
        self.send(self.Input(type=1, ki=self.KeyboardInput(wScan=scan, dwFlags=flags)))
        if down:
            self.held_keys.add(name)
        else:
            self.held_keys.discard(name)

    def scroll(self, notches):
        """Wheel at the current pointer; negative notches scroll down."""
        self.send(self.Input(type=0, mi=self.MouseInput(
            mouseData=(int(notches)*120) & 0xFFFFFFFF, dwFlags=0x0800)))

    def release_all(self):
        # Release only inputs pressed by this process; never release the user's other keys.
        for button in tuple(self.held_buttons):
            self.button(button, False)
        for key in tuple(self.held_keys):
            self.key(key, False)
