"""Nav-Ray debugging: what the route follower saw and decided, drawn on the game picture.

annotate() marks one frame (dash candidates, the chained dashes, the traced route, the aim, the corner and a state
line). BlackBox keeps the last minute of frames and status lines cheaply and writes them out after a run. Overlay
draws the same marks live over the game in a click-through window that never takes focus and is hidden from screen
capture, so the bot never reads its own drawings.

Every drawing stays out of the HUD areas the bot reads, and uses colours far from the dash hue, so a marked frame
(or an overlay that did get captured) can never be mistaken for dashes or HUD text.
"""
import collections
import json
import queue
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

# ---- what is drawn where ----
# Areas the bot reads (fractions of the frame: x0, y0, x1, y1). Nothing is ever drawn inside them.
PROTECTED = (
    (0.0, 0.0, 1.0, .06),      # top menu strip (NAV-RAY item, UI toggle)
    (0.0, 0.0, .20, .20),      # Location / Time panel: the HUD colour and the zone name are read here
    (0.0, .78, 1.0, 1.0),      # chat and vitals (HLT is read at .84-.875)
    (.92, 0.0, 1.0, 1.0),      # right edge
    (.25, .50, .75, .57),      # "Entering new district" banner
    (.35, .02, .65, .075),     # actor target bar (navray_runner.actor_target reads down to .075)
)
BANNER = (.30, .078, .70, .10)   # the state line: top centre, below the menu and the target bar, above SCENE_BOX (.10)
KEY_COLOR = "#010203"            # the overlay's transparent colour (never drawn)
HUE_NAMES = {"green": 71, "red": 0, "magenta": 151, "blue": 115}   # centres of pathvision.COLOR_HUES


def _hue(value):
    if isinstance(value, str):
        return HUE_NAMES.get(value, 71)
    return 71 if value is None else int(value) % 180


def _distance(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def _rgb(hue):
    return tuple(int(v) for v in cv2.cvtColor(np.uint8([[[hue % 180, 255, 255]]]), cv2.COLOR_HSV2RGB)[0, 0])


def palette(dash_hue):
    """RGB colours for a dash hue (OpenCV 0-180): the complementary hue, an accent (magenta when it is far from
    both, else 45 hue units off the dashes) and white. None of them lies within 45 hue units of the dashes."""
    hue = _hue(dash_hue)
    comp = (hue + 90) % 180
    accent = 150 if _distance(150, hue) >= 45 and _distance(150, comp) >= 25 else (hue + 135) % 180
    return {"comp": _rgb(comp), "accent": _rgb(accent), "white": (255, 255, 255), "black": (0, 0, 0)}


def protected_boxes(width, height):
    return [(round(x0*width), round(y0*height), round(x1*width), round(y1*height)) for x0, y0, x1, y1 in PROTECTED]


def banner_text(info):
    parts = [str(info.get("state") or "")]
    if info.get("time") is not None:
        parts.append(f"{float(info['time']):.1f}s")
    if info.get("error") is not None:
        parts.append(f"steer {float(info['error']):+.3f}")
    parts.append(f"{len(info.get('points') or ())} marks")
    if info.get("hue") is not None:
        parts.append(f"hue {info['hue']}")
    return "  ".join(p for p in parts if p)


def _xy(point, sx, sy):
    return round(float(point[0])*sx), round(float(point[1])*sy)


def shapes(info, width, height):
    """The drawing for `info`, in pixels of a width x height picture. Coordinates in `info` are pixels of
    info["size"] (the game frame), else of this picture."""
    size = info.get("size") or (width, height)
    sx, sy = width/float(size[0]), height/float(size[1])
    t = max(1, round(width/1280))                     # thin: 2 px at 2560
    colours = palette(info.get("hue"))
    out = []
    route = [_xy(p, sx, sy) for p in info.get("route") or ()]
    if len(route) >= 2:
        out.append(("line", route, colours["accent"], t))
    for p in info.get("candidates") or ():
        out.append(("circle", _xy(p, sx, sy), 4*t, colours["white"], 1))
    for p in info.get("points") or ():
        out.append(("circle", _xy(p, sx, sy), 10*t, colours["comp"], t))
    if info.get("corner") is not None:
        out.append(("diamond", _xy(info["corner"], sx, sy), 12*t, colours["accent"], t))
    if info.get("aim") is not None:
        out.append(("cross", _xy(info["aim"], sx, sy), 16*t, colours["comp"], t))
    x0, y0, x1, y1 = BANNER
    out.append(("text", (round(x0*width), round(y0*height), round(x1*width), round(y1*height)), banner_text(info),
                colours["white"], colours["black"]))
    return out


# ---- raster form (the black box, test frames) ----
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _fit(text, box, thickness=1):
    """Font scale and text cut to fit the box (cv2 Hershey font)."""
    x0, y0, x1, y1 = box
    scale = max(.3, .7*(y1 - y0)/22.0)
    while text and cv2.getTextSize(text, FONT, scale, thickness)[0][0] > x1 - x0 - 8:
        text = text[:-1]
    return text, scale


def _raster(out, drawing):
    for shape in drawing:
        kind = shape[0]
        # LINE_8, never anti-aliased: a blend with the scene could land near the dash hue.
        if kind == "line":
            cv2.polylines(out, [np.int32(shape[1])], False, shape[2], shape[3], cv2.LINE_8)
        elif kind == "circle":
            cv2.circle(out, shape[1], shape[2], shape[3], shape[4], cv2.LINE_8)
        elif kind == "cross":
            (x, y), r, colour, t = shape[1:]
            cv2.line(out, (x - r, y), (x + r, y), colour, t, cv2.LINE_8)
            cv2.line(out, (x, y - r), (x, y + r), colour, t, cv2.LINE_8)
        elif kind == "diamond":
            (x, y), r, colour, t = shape[1:]
            cv2.polylines(out, [np.int32([(x, y - r), (x + r, y), (x, y + r), (x - r, y)])], True, colour, t, cv2.LINE_8)
        elif kind == "text":
            box, text, colour, back = shape[1:]
            thickness = max(1, round((box[3] - box[1])/30))
            text, scale = _fit(text, box, thickness)
            cv2.rectangle(out, box[:2], (box[2] - 1, box[3] - 1), back, -1, cv2.LINE_8)
            (w, h), _ = cv2.getTextSize(text, FONT, scale, thickness)
            cv2.putText(out, text, ((box[0] + box[2] - w)//2, (box[1] + box[3] + h)//2), FONT, scale, colour,
                        thickness, cv2.LINE_8)


def annotate(frame_rgb, info):
    """An RGB copy of the frame with the marks for `info` drawn on it, the protected HUD areas untouched.

    info keys (all optional): candidates [(x, y, ...)], points [(x, y)], route [(x, y)], aim (x, y), corner (x, y)
    or None, error (steer error, fraction of the width), state (text), hue (dash hue int or colour name),
    time (seconds), size (w, h) of the frame the coordinates are in (default: this frame)."""
    height, width = frame_rgb.shape[:2]
    out = frame_rgb.copy()
    _raster(out, shapes(info, width, height))
    for x0, y0, x1, y1 in protected_boxes(width, height):
        out[y0:y1, x0:x1] = frame_rgb[y0:y1, x0:x1]   # put the HUD back exactly
    return out


def view_info(view, frame_shape, state, hue, candidates=(), error=None, corner=None, **extra):
    """An info dict from a pathvision.PathView (or None) and the frame it was found in."""
    height, width = frame_shape[:2]
    info = {"state": state, "hue": hue, "size": (width, height), "candidates": [tuple(c[:2]) for c in candidates],
            "error": error, "corner": corner}
    if view is not None:
        info.update(points=list(view.points), route=list(view.route or view.points), aim=view.aim)
        if corner is None and 0 <= view.corner < len(view.route):
            info["corner"] = view.route[view.corner]
    info.update(extra)
    return info


def _plain(value):
    """A JSON-ready copy (numpy numbers and tuples become plain numbers and lists)."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


# ---- the black box: the last minute of a run ----
class BlackBox:
    """Ring buffer of the last `seconds` of frames (at most `fps` a second, 1280-wide JPEG) with their info, plus
    the status lines. add() and event() are thread-safe and cheap; save() writes it all out after a run.
    Frames are kept by reference: the caller must not change an array after handing it in.

    Memory: JPEGs at most `max_bytes`, plus at most `max_keys` full-size frames (the first, the latest state
    changes and the last), plus `max_events` status lines."""

    def __init__(self, seconds=60.0, fps=3.0, width=1280, quality=80, max_bytes=64 << 20, max_keys=6,
                 max_events=5000):
        self.seconds, self.interval, self.width, self.quality = float(seconds), 1.0/fps, int(width), int(quality)
        self.fps, self.max_bytes, self.max_keys = float(fps), int(max_bytes), max(2, int(max_keys))
        self.cap = int(self.seconds*self.fps) + 1      # a clock jump must not let the buffer grow
        self.lock = threading.Lock()
        self.frames = collections.deque()             # (time, jpeg bytes, info)
        self.jpeg_bytes = 0
        self.events = collections.deque(maxlen=int(max_events))   # (time, kind, text)
        self.first = None                             # (time, label, full frame, info)
        self.changes = collections.deque(maxlen=self.max_keys - 2)
        self.last = None
        self.state = None
        self.due = None
        self.started = None

    def __len__(self):
        return len(self.frames)

    @property
    def nbytes(self):
        with self.lock:
            keys = [k for k in (self.first, self.last, *self.changes) if k is not None]
            return self.jpeg_bytes + sum(k[2].nbytes for k in keys)

    def _small_size(self, width, height):
        if width <= self.width:
            return width - width % 2, height - height % 2
        return self.width, max(2, round(height*self.width/width/2)*2)     # even sides for the video codec

    def add(self, frame_rgb, info=None, now=None):
        """Keep the frame if a slot is due (else drop it). Returns whether it was kept."""
        now = time.monotonic() if now is None else float(now)
        with self.lock:
            if self.due is not None and now < self.due:
                return False
            self.due = now + self.interval - 1e-6        # a gap of at least one interval: never over `fps`
            if self.started is None:
                self.started = now
        height, width = frame_rgb.shape[:2]
        info = _plain(dict(info or {}))
        info.setdefault("size", [width, height])
        small = cv2.resize(frame_rgb, self._small_size(width, height), interpolation=cv2.INTER_AREA)
        # Encoded as it is (RGB in the BGR slots, 2 ms saved); save() decodes it straight back to RGB.
        ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            return False
        jpeg = jpeg.tobytes()
        state = info.get("state")
        # Kept by reference, not copied (9 ms at 2560x1440): every capture is a new array that nobody changes.
        full = frame_rgb
        with self.lock:
            self.frames.append((now, jpeg, info))
            self.jpeg_bytes += len(jpeg)
            while self.frames and (now - self.frames[0][0] > self.seconds or len(self.frames) > self.cap
                                   or self.jpeg_bytes > self.max_bytes):
                self.jpeg_bytes -= len(self.frames.popleft()[1])
            if self.first is None:
                self.first = (now, "first", full, info)
            elif state != self.state:
                self.changes.append((now, str(state or "none"), full, info))
            self.state = state
            self.last = (now, "last", full, info)
        return True

    def event(self, kind, text, now=None):
        now = time.monotonic() if now is None else float(now)
        with self.lock:
            if self.started is None:
                self.started = now
            self.events.append((now, str(kind), None if text is None else str(text)))

    def clear(self):
        with self.lock:
            self.frames.clear()
            self.events.clear()
            self.changes.clear()
            self.jpeg_bytes, self.first, self.last, self.state, self.due, self.started = 0, None, None, None, None, None

    def save(self, folder):
        """Write video.mp4 (marked frames, `fps`), frames.jsonl (each frame's info), events.jsonl (status lines)
        and key_NN_<state>.png full-size frames with _marked.jpg twins. Returns the folder. Takes a few seconds
        (PNG encoding at 2560x1440): call it off the walking thread."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with self.lock:
            frames, events = list(self.frames), list(self.events)
            keys = [k for k in (self.first, *self.changes, self.last) if k is not None]
            started = self.started or 0.0
        with open(folder / "events.jsonl", "w", encoding="utf-8") as handle:
            for when, kind, text in events:
                handle.write(json.dumps({"t": round(when - started, 3), "kind": kind, "text": text}, ensure_ascii=False) + "\n")
        with open(folder / "frames.jsonl", "w", encoding="utf-8") as handle:
            for n, (when, _, info) in enumerate(frames):
                handle.write(json.dumps({"n": n, "t": round(when - started, 3), "info": info}, ensure_ascii=False) + "\n")
        if frames:
            first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
            size = (first.shape[1], first.shape[0])
            writer = cv2.VideoWriter(str(folder / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, size)
            try:
                for when, jpeg, info in frames:
                    rgb = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)    # stored RGB (see add)
                    if (rgb.shape[1], rgb.shape[0]) != size:          # the game window was resized mid-run
                        rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
                    marked = annotate(rgb, dict(info, time=when - started if info.get("time") is None else info["time"]))
                    writer.write(cv2.cvtColor(marked, cv2.COLOR_RGB2BGR))
            finally:
                writer.release()
        for n, (when, label, full, info) in enumerate(keys, 1):
            name = f"key_{n:02d}_{''.join(c if c.isalnum() else '_' for c in label)[:40]}"
            bgr = cv2.cvtColor(full, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(folder / f"{name}.png"), bgr, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            marked = annotate(full, dict(info, time=when - started if info.get("time") is None else info["time"]))
            # The marked twin only needs to be looked at: JPEG, 50 ms instead of a second or two for a PNG.
            cv2.imwrite(str(folder / f"{name}_marked.jpg"), cv2.cvtColor(marked, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
        return folder


# ---- the live overlay ----
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
OVERLAY_STYLE = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
WDA_EXCLUDEFROMCAPTURE = 0x11
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010

_USER32 = None


def user32():
    """A private user32 handle (its own argtypes: windows_backend sets its own on another handle). None off Windows."""
    global _USER32
    if _USER32 is None and sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetWindowLongW.restype = ctypes.c_long
        user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user.SetWindowLongW.restype = ctypes.c_long
        user.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user.SetWindowDisplayAffinity.restype = wintypes.BOOL
        user.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetWindowDisplayAffinity.restype = wintypes.BOOL
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wintypes.UINT]
        _USER32 = user
    return _USER32


def set_affinity(hwnd, mode=WDA_EXCLUDEFROMCAPTURE):
    """SetWindowDisplayAffinity; False when refused (WDA_EXCLUDEFROMCAPTURE needs Windows 10 2004 or later)."""
    user = user32()
    return bool(user and user.SetWindowDisplayAffinity(hwnd, mode))


class Overlay:
    """The marks drawn live over the game client: a borderless, topmost, click-through window that never takes
    focus (the macro stops when the game loses focus) and is excluded from screen capture (the bot must not
    read its own marks). If capture exclusion is refused, only the state line is drawn (it lies outside every
    area the bot reads) and `report` is told once.

    Tk is single-threaded: post() may be called from any thread; pump() (or start()) runs on the Tk thread."""

    def __init__(self, master, rect=None, alpha=1.0, report=None, affinity=set_affinity):
        import tkinter as tk
        self.alpha, self.report = float(alpha), report
        self.inbox = queue.Queue()
        self.rect = tuple(rect) if rect else (0, 0, 640, 360)
        self.info, self.job, self.closed = {}, None, False
        self.top = tk.Toplevel(master)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes("-alpha", 0.0)            # invisible until show(); hide() only drops the alpha again
        self.top.attributes("-topmost", True)
        self.top.attributes("-transparentcolor", KEY_COLOR)
        self.canvas = tk.Canvas(self.top, bg=KEY_COLOR, highlightthickness=0, bd=0,
                                width=self.rect[2], height=self.rect[3])
        self.canvas.pack(fill="both", expand=True)
        self.top.geometry("{2}x{3}+{0}+{1}".format(*self.rect))
        self.top.update_idletasks()                   # Tk makes the wrapper window here, before it is ever shown
        self.hwnd = int(self.top.wm_frame(), 16) if user32() else None
        self.styled = self._style()
        self.excluded = False
        if self.hwnd:
            self.excluded = bool(affinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE))
        self.note = None if self.excluded else (
            "Nav-Ray overlay: this Windows cannot hide the overlay from screen capture; only the state line is drawn.")
        if self.note and report:
            report(self.note)

    def _style(self):
        """The extended style bits, set before the first show (Tk itself only adds LAYERED and TOOLWINDOW)."""
        user = user32()
        if not (user and self.hwnd):
            return False
        user.SetWindowLongW(self.hwnd, GWL_EXSTYLE, user.GetWindowLongW(self.hwnd, GWL_EXSTYLE) | OVERLAY_STYLE)
        return user.GetWindowLongW(self.hwnd, GWL_EXSTYLE) & OVERLAY_STYLE == OVERLAY_STYLE

    def _raise(self):
        user = user32()
        if user and self.hwnd:
            user.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    @staticmethod
    def client_rect(backend):
        """(x, y, width, height) of the game client on screen, from windows_backend."""
        x, y = backend.origin()
        width, height = backend.client_size()
        return (x, y, width, height)

    def show(self):
        # Shown natively without activation: Tk's own deiconify is not guaranteed never to activate.
        user = user32()
        self._style()
        if user and self.hwnd:
            user.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        else:
            self.top.deiconify()
        self._raise()
        self.top.attributes("-alpha", self.alpha)

    def hide(self):
        # Alpha 0 rather than unmapping: showing again never goes through a map that could activate it.
        self.top.attributes("-alpha", 0.0)

    def place(self, rect):
        rect = tuple(int(v) for v in rect)
        if rect != self.rect:
            self.rect = rect
            self.canvas.configure(width=rect[2], height=rect[3])
            self.top.geometry("{2}x{3}+{0}+{1}".format(*rect))
            self._raise()

    def post(self, info, rect=None):
        """Queue a new drawing (and optionally a new client rect). Any thread."""
        if not self.closed:
            self.inbox.put((info, rect))

    def pump(self):
        """Take the newest posted drawing and redraw. Tk thread only. Returns whether anything was drawn."""
        latest = None
        try:
            while True:
                latest = self.inbox.get_nowait()
        except queue.Empty:
            pass
        if latest is None or self.closed:
            return False
        info, rect = latest
        if rect is not None:
            self.place(rect)
        self.info = dict(info or {})
        self.draw()
        return True

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        width, height = self.rect[2], self.rect[3]
        drawing = shapes(self.info, width, height)
        if not self.excluded:
            drawing = [s for s in drawing if s[0] == "text"]   # captured: only the state line, which no reader looks at
        for shape in drawing:
            kind = shape[0]
            if kind == "line":
                canvas.create_line(*[v for p in shape[1] for v in p], fill=_hex(shape[2]), width=shape[3], tags="mark")
            elif kind == "circle":
                (x, y), r, colour, t = shape[1:]
                canvas.create_oval(x - r, y - r, x + r, y + r, outline=_hex(colour), width=t, tags="mark")
            elif kind == "cross":
                (x, y), r, colour, t = shape[1:]
                canvas.create_line(x - r, y, x + r, y, fill=_hex(colour), width=t, tags="mark")
                canvas.create_line(x, y - r, x, y + r, fill=_hex(colour), width=t, tags="mark")
            elif kind == "diamond":
                (x, y), r, colour, t = shape[1:]
                canvas.create_polygon(x, y - r, x + r, y, x, y + r, x - r, y, outline=_hex(colour), fill="",
                                      width=t, tags="mark")
            elif kind == "text":
                (x0, y0, x1, y1), text, colour, back = shape[1:]
                px = max(8, round(.7*(y1 - y0)))
                text = text[:max(1, int((x1 - x0 - 8)/(.6*px)))]     # Consolas is about .55 em wide
                canvas.create_rectangle(x0, y0, x1, y1, fill=_hex(back), outline="", tags="banner")
                canvas.create_text((x0 + x1)//2, (y0 + y1)//2, text=text, fill=_hex(colour),
                                   font=("Consolas", -px), tags=("banner", "state"))
        # The HUD areas in the transparent colour, over everything: what lies there shows through untouched.
        for x0, y0, x1, y1 in protected_boxes(width, height):
            canvas.create_rectangle(x0, y0, x1, y1, fill=KEY_COLOR, outline="", width=0, tags="mask")

    def start(self, every=100):
        """Pump on the Tk loop every `every` ms until close()."""
        if self.closed:
            return
        self.pump()
        self.job = self.top.after(every, self.start, every)

    def close(self):
        self.closed = True
        if self.job is not None:
            try:
                self.top.after_cancel(self.job)
            except Exception:
                pass
        try:
            self.top.destroy()
        except Exception:
            pass


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)
