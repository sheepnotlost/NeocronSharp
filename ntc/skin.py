"""Neocron HUD skin: game font, gem-and-frosted-glass colours, cut-corner window frame (SPEC 16).

Colours start from the game's default HUD green (HUD Color 0), are pushed to brighter, more saturated "gem" tones,
brought down in brightness and covered with a light matte film (haze plus fine grain), so they look like jewel
candy seen through frosted glass. Blinker (the game's HUD font) is loaded privately from assets/fonts. All images are
drawn at runtime with Pillow, so there is nothing to download.
"""
import colorsys
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk

from .config import RES

ASSETS = RES / "assets"
FONT_FILE = ASSETS / "fonts" / "Blinker-Regular.ttf"
FAMILY = "Blinker"


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


HAZE = (150, 178, 164)          # the matte film: a pale grey-green, like frosted glass


def gem(h, sat=1.3, val=1.12, dim=0.82, haze=0.10):
    """Brighter and more saturated first, then dimmed, then covered with the matte film."""
    r, g, b = (c / 255 for c in _rgb(h))
    hh, ss, vv = colorsys.rgb_to_hsv(r, g, b)
    ss, vv = min(1.0, ss * sat), min(1.0, vv * val)          # brighter in itself ...
    vv *= dim                                                # ... then reduce the brightness ...
    c = [x * 255 for x in colorsys.hsv_to_rgb(hh, ss, vv)]
    return _hex([x * (1 - haze) + hz * haze for x, hz in zip(c, HAZE)])      # ... and a matte finish over it


BG = "#07140e"        # window background (HUD panel near-black green)
FIELD = "#0b1f16"     # tables / inputs
RAISED = "#12392a"    # headings
SLOT = "#1f7d52"      # selection = an item slot
LINE = "#16402b"      # borders / grid lines
MINT = gem("#4ee491")                     # HUD frame mint: vivid emerald, soft
NEON = gem("#b9ffd8", 1.2, 1.0, 0.92, 0.06)     # hot core of a neon line
TEXT = gem("#bdf0d2", 1.15, 1.0, 0.92, 0.05)
EDGE = gem("#2fd081", 1.2, 1.0, 0.72, 0.10)     # window and plate outline
LCD_BG = "#02100a"
LCD_FG = gem("#72ffb2", 1.25, 1.05, 0.9, 0.06)
AMBER = gem("#f2b13c", 1.3, 1.1, 0.88, 0.08)
DONE_BG = "#1b6d46"
WARN_BG = "#33290a"
SUB = "#6aa488"


def set_app_id():
    """Own taskbar identity: without it Windows groups the window under python.exe and shows Python's icon."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NeocronTechCounter.App")
    except (AttributeError, OSError):
        pass


def load_font():
    """Make Blinker available to this process only (no install, gone when the app closes). Call before Tk starts."""
    if FONT_FILE.exists():
        try:
            ctypes.windll.gdi32.AddFontResourceExW(str(FONT_FILE), 0x10, 0)     # FR_PRIVATE
        except (AttributeError, OSError):
            pass


# -- images -------------------------------------------------------------------------------------------------
def matte(im, haze=0.07, grain=4.0, gloss=0.18, seed=7):
    """Frosted-glass finish for a plate: a soft gloss on the upper part, a faint haze and fine grain over the colour.
    The image's own transparency is kept."""
    w, h = im.size
    alpha = im.getchannel("A")
    arr = np.asarray(im.convert("RGB")).astype(np.float32)
    arr = arr * (1 - haze) + np.array(HAZE, np.float32) * haze
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    g = np.clip(1 - t / 0.55, 0, 1) ** 1.7 * gloss
    arr = arr + (255 - arr) * g                                          # gloss lightens, never blows out
    arr = arr + np.random.default_rng(seed).normal(0, grain, (h, w, 1)).astype(np.float32)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def _chamfer(w, h, c):
    return [(c, 0), (w - 1, 0), (w - 1, h - 1 - c), (w - 1 - c, h - 1), (0, h - 1), (0, c)]


def _gradient(size, top, bottom):
    w, h = size
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    arr = np.repeat(arr, w, axis=1)
    return Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")


def _button_image(border, fill_top, fill_bottom, glow=0.0):
    """A cut-corner gem plate (Neocron window shape) with a slim bright edge; 9-slice friendly."""
    w, h, c, S = 48, 30, 7, 4
    big = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon([(x * S, y * S) for x, y in _chamfer(w, h, c)], fill=_rgb(border))
    inner = [(x * S + S, y * S + S) for x, y in _chamfer(w - 2, h - 2, c - 1)]
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).polygon(inner, fill=255)
    big.paste(_gradient(big.size, _rgb(fill_top), _rgb(fill_bottom)), (0, 0), mask)
    im = matte(big.resize((w, h), Image.LANCZOS))
    if glow:
        halo = im.getchannel("A").filter(ImageFilter.GaussianBlur(2))
        g = Image.new("RGBA", im.size, _rgb(MINT) + (0,))
        g.putalpha(halo.point(lambda v: int(v * glow)))
        im = Image.alpha_composite(g, im)
    return im


def _neon_line(width, height=9):
    """A thin soft-glowing horizontal line that fades out at both ends."""
    base = Image.new("RGBA", (width, height), _rgb(BG) + (255,))
    mid = height // 2
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(glow).line((8, mid, width - 8, mid), fill=_rgb(MINT) + (255,), width=4)
    glow = glow.filter(ImageFilter.GaussianBlur(1.8))
    glow.putalpha(glow.getchannel("A").point(lambda v: min(255, int(v * 1.4))))
    im = Image.alpha_composite(base, glow)
    ImageDraw.Draw(im).line((14, mid, width - 14, mid), fill=_rgb(NEON) + (255,), width=2)
    fade = Image.new("L", (width, height), 255)
    fd = ImageDraw.Draw(fade)
    ramp = min(120, width // 4)
    for x in range(ramp):
        v = int(255 * x / ramp)
        fd.line((x, 0, x, height), fill=v)
        fd.line((width - 1 - x, 0, width - 1 - x, height), fill=v)
    return Image.composite(im, base, fade)


def _bracket(size=12, corner="nw"):
    """A small corner bracket, like the targeting marks on the Neocron HUD."""
    S = 4
    im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    t = S * 2
    d.rectangle((0, 0, size * S, t), fill=_rgb(MINT))
    d.rectangle((0, 0, t, size * S), fill=_rgb(MINT))
    im = im.resize((size, size), Image.LANCZOS)
    rot = {"nw": None, "ne": Image.FLIP_LEFT_RIGHT, "sw": Image.FLIP_TOP_BOTTOM, "se": Image.ROTATE_180}[corner]
    return im.transpose(rot) if rot is not None else im


def _font(size):
    try:
        return ImageFont.truetype(str(FONT_FILE), size)
    except OSError:
        return ImageFont.load_default()


def _header(width, height=64):
    """Header strip: the tech sprite and the title in soft-glowing Blinker, with a neon line underneath."""
    im = _gradient((width, height), _rgb("#0d2a1e"), _rgb(BG))               # frosted-glass strip
    im = matte(im, haze=0.05, grain=3.0, gloss=0.07)
    sprite = Image.open(ASSETS / "tech_sprite.png").convert("RGBA")
    k = (height - 16) / sprite.height
    sp = sprite.resize((int(sprite.width * k), int(sprite.height * k)), Image.LANCZOS)
    halo = sp.getchannel("A").filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(2.5))
    g = Image.new("RGBA", sp.size, _rgb(MINT) + (0,))
    g.putalpha(halo.point(lambda v: min(255, int(v * 0.9))))
    im.alpha_composite(g, (10, 4))
    im.alpha_composite(sp, (10, 4))
    font, small = _font(26), _font(13)
    tx = 20 + sp.width
    text = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(text).text((tx, 6), "NEOCRON TECH COUNTER", font=font, fill=_rgb(MINT) + (255,))
    im.alpha_composite(text.filter(ImageFilter.GaussianBlur(3)))
    ImageDraw.Draw(im).text((tx, 6), "NEOCRON TECH COUNTER", font=font, fill=_rgb(NEON) + (255,))
    ImageDraw.Draw(im).text((tx + 2, 37), "CABINET  /  INVENTORY  SCANNER", font=small, fill=_rgb(SUB) + (255,))
    line = _neon_line(width)
    im.alpha_composite(line, (0, height - line.height))
    return im


def _title_strip(width, height, text):
    """Slim title bar for the extra windows."""
    im = matte(_gradient((width, height), _rgb("#0d2a1e"), _rgb(BG)), haze=0.05, grain=3.0, gloss=0.07)
    d = ImageDraw.Draw(im)
    d.text((38, (height - 20) // 2 - 2), text, font=_font(17), fill=_rgb(NEON) + (255,))
    im.alpha_composite(_neon_line(width, 7), (0, height - 7))
    return im


# -- ttk styles -------------------------------------------------------------------------------------------
def style(root):
    """ttk styles for every window of the app."""
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=BG)
    font, bold, btn = (FAMILY, 11), (FAMILY, 11, "bold"), (FAMILY, 10, "bold")
    st.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=LINE, lightcolor=BG,
                 darkcolor=BG, troughcolor=BG, focuscolor=MINT, selectbackground=SLOT, selectforeground="#ffffff",
                 font=font, insertcolor=MINT)
    imgs = root._skin_images = getattr(root, "_skin_images", [])
    plates = {k: ImageTk.PhotoImage(v, master=root) for k, v in {
        "normal": _button_image(EDGE, gem("#27b673", 1.4, 1.25, 0.76, 0.07), gem("#0c6a40", 1.4, 1.3, 0.72, 0.07)),
        "hover": _button_image(MINT, gem("#3fe595", 1.4, 1.25, 0.82, 0.06), gem("#12804f", 1.4, 1.3, 0.8, 0.06), 0.5),
        "pressed": _button_image(MINT, gem("#0c6a40", 1.4, 1.3, 0.7, 0.07), gem("#1fa266", 1.4, 1.25, 0.76, 0.07)),
        "disabled": _button_image("#1b4a33", "#0d241a", "#0a1c14")}.items()}
    imgs.extend(plates.values())
    if "NC.Button.plate" not in st.element_names():
        st.element_create("NC.Button.plate", "image", plates["normal"], ("disabled", plates["disabled"]),
                          ("pressed", plates["pressed"]), ("active", plates["hover"]), border=9, sticky="nsew")
    st.layout("TButton", [("NC.Button.plate", {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
    st.configure("TButton", foreground="#ecfff4", padding=(6, 3), font=btn, anchor="center", width=0)
    st.map("TButton", foreground=[("disabled", "#35634b"), ("active", "#ffffff")])
    # the Export menu button uses the same plate; its label already ends in an arrow, so no second indicator
    st.layout("TMenubutton", [("NC.Button.plate", {"sticky": "nsew", "children": [
        ("Menubutton.padding", {"sticky": "nsew", "children": [("Menubutton.label", {"sticky": "nsew"})]})]})])
    st.configure("TMenubutton", foreground="#ecfff4", font=btn, padding=(6, 3), anchor="center")
    st.map("TMenubutton", foreground=[("active", "#ffffff")])
    st.configure("TCombobox", fieldbackground=FIELD, background=RAISED, foreground=TEXT, arrowcolor=MINT,
                 bordercolor=EDGE, lightcolor=FIELD, darkcolor=FIELD)
    st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", NEON)],
           bordercolor=[("focus", MINT), ("active", MINT)])
    for opt, val in (("background", FIELD), ("foreground", TEXT), ("selectBackground", SLOT), ("font", font)):
        root.option_add(f"*TCombobox*Listbox.{opt}", val)
    st.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, bordercolor=EDGE, lightcolor=FIELD)
    st.map("TEntry", bordercolor=[("focus", MINT)])
    st.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT, rowheight=23,
                 bordercolor=LINE, lightcolor=FIELD, darkcolor=FIELD, font=font)
    st.map("Treeview", background=[("selected", SLOT)], foreground=[("selected", "#ffffff")])
    st.configure("Treeview.Heading", background=RAISED, foreground=MINT, bordercolor=LINE, lightcolor=RAISED,
                 darkcolor=RAISED, font=bold, relief="flat")
    st.map("Treeview.Heading", background=[("active", "#1a4a33")], foreground=[("active", NEON)])
    st.configure("Vertical.TScrollbar", background=RAISED, troughcolor=BG, arrowcolor=MINT, bordercolor=LINE,
                 lightcolor=RAISED, darkcolor=RAISED)
    st.map("Vertical.TScrollbar", background=[("active", "#1a4a33")])
    st.configure("Sash", sashthickness=8, gripcount=14, background=BG, lightcolor=MINT, darkcolor=LINE)
    st.configure("LCD.TLabel", background=LCD_BG, foreground=LCD_FG, font=(FAMILY, 12), padding=(10, 5))


def _neon_canvas(parent, height=9):
    """A neon divider that redraws itself to the parent's width."""
    cv = tk.Canvas(parent, height=height, bg=BG, highlightthickness=0, bd=0)

    def redraw(e):
        if e.width > 20:
            cv._img = ImageTk.PhotoImage(_neon_line(e.width, height), master=cv)
            cv.delete("all")
            cv.create_image(0, 0, image=cv._img, anchor="nw")
    cv.bind("<Configure>", redraw)
    return cv


def add_brackets(frame):
    """Corner brackets on a panel (placed over its corners, HUD targeting style)."""
    imgs = frame._brackets = []
    for corner, rx, ry, anchor in (("nw", 0, 0, "nw"), ("ne", 1, 0, "ne"), ("sw", 0, 1, "sw"), ("se", 1, 1, "se")):
        img = ImageTk.PhotoImage(_bracket(12, corner), master=frame)
        imgs.append(img)
        lbl = tk.Label(frame, image=img, bg=FIELD, bd=0, highlightthickness=0)
        lbl.place(relx=rx, rely=ry, anchor=anchor)


# -- window frame (borderless, cut corners, own title bar) -------------------------------------------------
CHAMFER = 14
EDGE_GRAB = 5
_u32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX = 0x00020000
WM_NCLBUTTONDOWN, HTCAPTION = 0x00A1, 2
SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020          # no size/move/zorder/activate, frame changed

if _u32 is not None:
    _u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.UINT]
    _u32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    _u32.GetParent.restype = wintypes.HWND
    _u32.GetParent.argtypes = [wintypes.HWND]
    _u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def _hwnd(win):
    return _u32.GetParent(win.winfo_id())


def _shape(win, w, h):
    """Clip the window to the cut-corner shape (top-left and bottom-right corners cut)."""
    c = CHAMFER
    pts = [(c, 0), (w, 0), (w, h - c), (w - c, h), (0, h), (0, c)]
    arr = (wintypes.POINT * len(pts))(*[wintypes.POINT(x, y) for x, y in pts])
    rgn = ctypes.windll.gdi32.CreatePolygonRgn(arr, len(pts), 2)
    _u32.SetWindowRgn(_hwnd(win), rgn, True)             # the system owns the region from here on


def _gem_button(parent, kind, command):
    """A small cut-corner title-bar button with a drawn glyph ('min' or 'close')."""
    cv = tk.Canvas(parent, width=34, height=22, bg=BG, highlightthickness=0, bd=0, cursor="hand2")

    def draw(hover=False):
        cv.delete("all")
        body = gem("#c8344a", 1.1, 1.0, 0.9, 0.08) if (hover and kind == "close") else (
            gem("#35cf86", 1.1, 1.0, 0.7, 0.08) if hover else gem("#1d8f5a", 1.1, 1.0, 0.6, 0.08))
        cv.create_polygon(5, 1, 33, 1, 33, 17, 28, 21, 1, 21, 1, 5, fill=body, outline=EDGE)
        cv.create_line(5, 2, 32, 2, fill=gem("#ffffff", 1, 1, 0.8, 0.2))                     # soft top gloss
        if kind == "close":
            cv.create_line(12, 6, 22, 16, 12, 16, 22, 6, fill="#f3fff8", width=2)
        else:
            cv.create_line(12, 15, 22, 15, fill="#f3fff8", width=2)
    draw()
    cv.bind("<Enter>", lambda _e: draw(True))
    cv.bind("<Leave>", lambda _e: draw(False))
    cv.bind("<Button-1>", lambda _e: command())
    return cv


def set_icon(win):
    """Give the window (and its taskbar button) the tech icon. Done with WM_SETICON because the frame change
    above drops the icon Tk set, and the taskbar then shows Tk's feather."""
    ico = ASSETS / "icon.ico"
    if _u32 is None or not ico.exists():
        return
    _u32.LoadImageW.restype = wintypes.HANDLE
    _u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
    _u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    hwnd = _hwnd(win)
    win._ntc_icons = []
    for kind, size in ((1, 32), (0, 16)):                                   # ICON_BIG, ICON_SMALL
        h = _u32.LoadImageW(None, str(ico), 1, size, size, 0x10)             # IMAGE_ICON, LR_LOADFROMFILE
        if h:
            win._ntc_icons.append(h)
            _u32.SendMessageW(hwnd, 0x80, kind, h)                           # WM_SETICON


class Frame:
    """The custom frame of one window. `body` is where the window's own widgets go."""

    def __init__(self, win, title, big, minimizable, minsize):
        self.win, self.big, self.minsize = win, big, minsize
        win.update_idletasks()
        explicit = win.geometry().split("+")[0] if win.wm_geometry() and not win.geometry().startswith("1x1") else ""
        h = _hwnd(win)
        style_bits = _u32.GetWindowLongPtrW(h, GWL_STYLE)
        _u32.SetWindowLongPtrW(h, GWL_STYLE, (style_bits & ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU)) | WS_MINIMIZEBOX)
        _u32.SetWindowPos(h, None, 0, 0, 0, 0, SWP_FLAGS)
        # Tk still adds the old frame's width to every size it sets: measure that once and cancel it
        win.geometry("300x300")
        win.update_idletasks()
        self.dw, self.dh = win.winfo_width() - 300, win.winfo_height() - 300
        win.minsize(max(1, minsize[0] - self.dw), max(1, minsize[1] - self.dh))
        if explicit:
            W, H = (int(v) for v in explicit.split("x"))
            win.geometry(f"{W - self.dw}x{H - self.dh}")
        else:
            win.geometry("")
        win.configure(bg=EDGE)
        self.outer = tk.Frame(win, bg=EDGE)
        self.outer.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.outer, bg=BG)
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._title_bar(title, minimizable)
        self.body = tk.Frame(self.inner, bg=BG)
        self.body.pack(fill="both", expand=True)
        self._grips()
        self._corners()
        win.bind("<Configure>", self._on_configure, add="+")
        self._last = None
        win._ntc_frame = self
        set_icon(win)

    # title bar: icon + title + buttons; dragging it moves the window
    def _title_bar(self, title, minimizable):
        h = 64 if self.big else 34
        self.bar = tk.Canvas(self.inner, height=h, bg=BG, highlightthickness=0, bd=0)
        self.bar.pack(fill="x")
        self.bar.bind("<Configure>", lambda e: self._draw_bar(e.width, title))
        self.bar.bind("<Button-1>", self._drag)
        self.btns = tk.Frame(self.bar, bg=BG)
        if minimizable:
            _gem_button(self.btns, "min", self._minimize).pack(side="left", padx=(0, 4))
        _gem_button(self.btns, "close", self._close).pack(side="left")
        self.btns.place(relx=1.0, x=-CHAMFER + 4, y=8, anchor="ne")

    def _draw_bar(self, width, title):
        if width < 60:
            return
        if self.big:
            img = _header(width, 64)
        else:
            img = _title_strip(width, 34, title)
            ico = ASSETS / "icon.png"
            if ico.exists():
                small = Image.open(ico).convert("RGBA").resize((22, 22), Image.LANCZOS)
                img.alpha_composite(small, (10, 5))
        self.bar._img = ImageTk.PhotoImage(img, master=self.bar)
        self.bar.delete("all")
        self.bar.create_image(0, 0, image=self.bar._img, anchor="nw")

    def _drag(self, _e):
        _u32.ReleaseCapture()
        _u32.SendMessageW(_hwnd(self.win), WM_NCLBUTTONDOWN, HTCAPTION, 0)

    def _minimize(self):
        self.win.iconify()

    def _close(self):
        cmd = self.win.protocol("WM_DELETE_WINDOW")
        if cmd:
            self.win.tk.call(cmd)
        else:
            self.win.destroy()

    # the cut corners get a diagonal edge line, and the shape is clipped to match
    def _corners(self):
        c = CHAMFER
        for corner in ("nw", "se"):
            cv = tk.Canvas(self.win, width=c + 1, height=c + 1, bg=BG, highlightthickness=0, bd=0)
            if corner == "nw":
                cv.create_line(0, c, c, 0, fill=EDGE, width=3)
                cv.place(x=0, y=0)
            else:
                cv.create_line(0, c, c, 0, fill=EDGE, width=3)
                cv.place(relx=1.0, rely=1.0, anchor="se")
            cv.configure(cursor="arrow")

    def _on_configure(self, e):
        if e.widget is not self.win or (e.width, e.height) == self._last:
            return
        self._last = (e.width, e.height)
        _shape(self.win, e.width, e.height)

    # resizing: thin grab strips on the left, right and bottom edges, plus the corner grip
    def _grips(self):
        spec = (("e", "right_side", dict(relx=1.0, rely=0.0, anchor="ne", width=EDGE_GRAB, relheight=1.0, y=CHAMFER)),
                ("w", "left_side", dict(relx=0.0, rely=0.0, anchor="nw", width=EDGE_GRAB, relheight=1.0, y=CHAMFER)),
                ("s", "bottom_side", dict(relx=0.0, rely=1.0, anchor="sw", height=EDGE_GRAB, relwidth=1.0)),
                ("se", "bottom_right_corner", dict(relx=1.0, rely=1.0, anchor="se", width=22, height=22)))
        for edge, cursor, place in spec:
            w = tk.Frame(self.win, bg=BG if edge == "se" else EDGE, cursor=cursor)
            w.place(**place)
            if edge == "se":
                w.configure(bg=BG)
                g = tk.Canvas(w, width=22, height=22, bg=BG, highlightthickness=0, bd=0, cursor=cursor)
                g.pack()
                for k in (5, 10, 15):
                    g.create_line(21, 21 - k, 21 - k, 21, fill=gem("#2fd081", 1.2, 1.0, 0.8, 0.1), width=2)
                for target in (w, g):
                    target.bind("<Button-1>", lambda e, ed=edge: self._start_resize(e, ed))
                    target.bind("<B1-Motion>", self._resize)
            else:
                w.bind("<Button-1>", lambda e, ed=edge: self._start_resize(e, ed))
                w.bind("<B1-Motion>", self._resize)
        self._rs = None

    def _start_resize(self, e, edge):
        w = self.win
        self._rs = (edge, e.x_root, e.y_root, w.winfo_width(), w.winfo_height(), w.winfo_x(), w.winfo_y())

    def _resize(self, e):
        if not self._rs:
            return
        edge, x0, y0, w0, h0, wx, wy = self._rs
        dx, dy = e.x_root - x0, e.y_root - y0
        mw, mh = self.minsize
        w, h, x = w0, h0, wx
        if "e" in edge:
            w = max(mw, w0 + dx)
        if "w" in edge:
            w = max(mw, w0 - dx)
            x = wx + (w0 - w)
        if "s" in edge:
            h = max(mh, h0 + dy)
        self.win.geometry(f"{w - self.dw}x{h - self.dh}+{x}+{wy}")


def fit(win):
    """Size a framed window to its content (after its widgets are built)."""
    fr = getattr(win, "_ntc_frame", None)
    if fr:
        win.update_idletasks()
        w, h = max(win.winfo_reqwidth(), fr.minsize[0]), max(win.winfo_reqheight(), fr.minsize[1])
        win.geometry(f"{w - fr.dw}x{h - fr.dh}")


def frame(win, title, big=False, minimizable=True, minsize=(360, 240)):
    """Give `win` the custom frame and return the Frame to put widgets into (`.body`).
    Returns None (and leaves the native frame) if it cannot be installed."""
    if _u32 is None:
        return None
    try:
        return Frame(win, title, big, minimizable, minsize)
    except Exception:                      # cosmetic only: never stop the app over the frame
        return None


# -- apply ------------------------------------------------------------------------------------------------
def apply(app):
    """Skin the widgets of the main window (the frame itself is installed by `frame` before they are built)."""
    root, body = app.root, app.body
    style(root)
    # status line becomes an LCD readout with a soft frame
    for w in body.pack_slaves():
        if isinstance(w, ttk.Label) and str(w.cget("textvariable")) == str(app.status):
            lcd_frame = tk.Frame(body, bg=LCD_BG, highlightthickness=1, highlightbackground=EDGE,
                                 highlightcolor=EDGE)
            lcd_frame.pack(fill="x", padx=8, pady=(4, 2), before=w)
            w.pack_forget()
            ttk.Label(lcd_frame, textvariable=app.status, style="LCD.TLabel", wraplength=w.cget("wraplength")).pack(
                fill="x")
            break
    for w in body.pack_slaves():                    # a divider just above the footer
        if isinstance(w, ttk.Label) and str(w.cget("textvariable")) == str(app.footer):
            _neon_canvas(body).pack(fill="x", side="bottom", after=w)
            break
    for pane in app.paned.panes():
        add_brackets(root.nametowidget(pane))
    app.tree.tag_configure("flag", **TAGS["flag"])
    ico = ASSETS / "icon.ico"
    if ico.exists():
        try:
            root.iconbitmap(default=str(ico))
        except tk.TclError:
            pass


def apply_toplevel(win):
    """For extra windows built without the frame."""
    win.configure(bg=BG)


TAGS = {"done": {"background": DONE_BG, "foreground": "#ffffff"},
        "near": {"background": WARN_BG, "foreground": AMBER},
        "flag": {"background": WARN_BG, "foreground": AMBER}}
