"""Windows helpers: DPI awareness, cursor position, mouse MOVE only, hotkeys."""
import ctypes
import ctypes.wintypes as wt
import threading

user32 = ctypes.windll.user32

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY = 0x0312


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def get_cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _send_move(dx, dy, flags):
    inp = INPUT(type=INPUT_MOUSE)
    inp.u.mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def move_to(x, y, mode="absolute"):
    """The ONLY input function in this codebase. Moves the cursor; never clicks."""
    if mode == "absolute":
        vx, vy = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw, vh = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        nx = int((x - vx) * 65535 / (vw - 1))
        ny = int((y - vy) * 65535 / (vh - 1))
        _send_move(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)
    elif mode == "relative":
        cx, cy = get_cursor_pos()
        _send_move(x - cx, y - cy, MOUSEEVENTF_MOVE)
    else:
        raise ValueError(mode)


def foreground_title():
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def parse_hotkey(s):
    parts = [p.strip().lower() for p in s.split("+")]
    mods = MOD_NOREPEAT
    for p in parts[:-1]:
        mods |= {"ctrl": MOD_CONTROL, "alt": MOD_ALT}[p]
    return mods, ord(parts[-1].upper())


class HotkeyListener(threading.Thread):
    """Registers global hotkeys on its own thread; calls callbacks[id]() when pressed."""

    def __init__(self, hotkeys):
        super().__init__(daemon=True)
        self.hotkeys = hotkeys  # {id: (hotkey_string, callback)}
        self._tid = None
        self.failed = []        # hotkeys another program (or a second copy of this app) already owns

    def run(self):
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        for hid, (hk, _) in self.hotkeys.items():
            mods, vk = parse_hotkey(hk)
            if not user32.RegisterHotKey(None, hid, mods, vk):
                self.failed.append(hk)
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                cb = self.hotkeys.get(msg.wParam)
                if cb:
                    cb[1]()
        for hid in self.hotkeys:
            user32.UnregisterHotKey(None, hid)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT


def focus_window(title_contains):
    """Bring the first visible top-level window whose title contains the text to the front."""
    found = []
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if title_contains.lower() in buf.value.lower():
                    found.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    if not found:
        return False
    hwnd = found[0]
    fg = user32.GetForegroundWindow()
    cur = ctypes.windll.kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    user32.AttachThreadInput(cur, fg_tid, True)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur, fg_tid, False)
    if user32.GetForegroundWindow() != hwnd:
        # Windows' foreground lock refused (another app is in front): this call is exempt from it
        user32.SwitchToThisWindow(hwnd, True)
        user32.BringWindowToTop(hwnd)
    return user32.GetForegroundWindow() == hwnd


MOUSEEVENTF_WHEEL = 0x0800


def wheel(notches):
    """Scroll the mouse wheel at the current cursor position. Positive = up (content moves down), negative = down.
    One notch is 120 units. Not a click: used only to scroll item windows."""
    inp = INPUT(type=INPUT_MOUSE)
    inp.u.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(int(notches * 120) & 0xFFFFFFFF).value, MOUSEEVENTF_WHEEL, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
