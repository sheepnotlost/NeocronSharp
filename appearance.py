"""Fifteen native Tk skins, including the original Basic appearance."""

from tkinter import ttk

SKINS={
    "basic":{"name":"Basic","bg":"#f3f5f5","fg":"#192c2d","panel":"#e6eceb","input":"#ffffff","accent":"#35796a","muted":"#566c69","edge":"#a7b7b3","font":"Segoe UI","heading":22},
    "rpos":{"name":"RPOS Classic","bg":"#183c2d","fg":"#d6f6dc","panel":"#28573d","input":"#102d21","accent":"#74efaa","muted":"#a1cab0","edge":"#52ae79","font":"Tahoma","heading":18},
    "cronamp":{"name":"CronAMP 97","bg":"#777e8e","fg":"#f5f3e7","panel":"#505b70","input":"#102419","accent":"#a4f279","muted":"#ddd9c9","edge":"#bdc5ce","font":"Tahoma","heading":17},
    "amber":{"name":"Dead Sector Terminal","bg":"#292a21","fg":"#ead09a","panel":"#3d3c2d","input":"#130f06","accent":"#ffc258","muted":"#bfb18e","edge":"#8e805c","font":"Consolas","heading":17},
    "clinic":{"name":"BioLab Workstation","bg":"#dbe6df","fg":"#173d3c","panel":"#c4d6ca","input":"#f2fff5","accent":"#2d7964","muted":"#3b665d","edge":"#7fa69b","font":"Segoe UI","heading":20},
    "iron":{"name":"Fallen Circuit","bg":"#293632","fg":"#e3e8d4","panel":"#46534b","input":"#15211c","accent":"#d8df70","muted":"#b6c4ae","edge":"#85937a","font":"Tahoma","heading":17},
    "forge":{"name":"Tangent Forge","bg":"#39282d","fg":"#f2d9c5","panel":"#633c3b","input":"#200f0b","accent":"#ffc18a","muted":"#d5ab93","edge":"#a57569","font":"Tahoma","heading":18},
    "rain":{"name":"Pepper Park Signal","bg":"#29181f","fg":"#f7dce6","panel":"#4d2738","input":"#150b12","accent":"#ff83b3","muted":"#ce9dae","edge":"#a34b71","font":"Trebuchet MS","heading":18},
    "psi":{"name":"PSI Resonance","bg":"#302339","fg":"#ecdeed","panel":"#51415e","input":"#190d22","accent":"#d8b9f2","muted":"#c3a8d0","edge":"#91789f","font":"Segoe UI","heading":19},
    "dome":{"name":"Dome Control","bg":"#243541","fg":"#dae8df","panel":"#435864","input":"#0d211f","accent":"#a0dab5","muted":"#adc5c2","edge":"#7c999b","font":"Consolas","heading":17},
    # Five late-90s media-player inspired skins: LCD readouts, spectrum bars,
    # bevelled chrome, oscilloscope traces and a compact "shade" title bar.
    "lcd":{"name":"Graphite LCD","bg":"#2b2c33","fg":"#d9dccf","panel":"#3e404a","input":"#050805","accent":"#3cf06b","muted":"#9aa093","edge":"#6d717e","font":"Consolas","heading":17},
    "spectrum":{"name":"Spectrum Bars","bg":"#0d0f14","fg":"#e2e6ee","panel":"#1d2230","input":"#000000","accent":"#ffd23a","muted":"#8e97aa","edge":"#3d4a66","font":"Tahoma","heading":17},
    "chrome":{"name":"Chrome Equalizer","bg":"#9aa3ad","fg":"#11161d","panel":"#c3cad2","input":"#e9eef3","accent":"#1f5fd1","muted":"#3d4651","edge":"#6c7682","font":"Tahoma","heading":18},
    "visualizer":{"name":"Neon Visualizer","bg":"#140c24","fg":"#e6e0ff","panel":"#271a45","input":"#08040f","accent":"#2ee6e6","muted":"#9d90c4","edge":"#7b3fe4","font":"Trebuchet MS","heading":18},
    "shade":{"name":"Shade Mode","bg":"#1a2236","fg":"#d6dcf0","panel":"#2a3552","input":"#0b1020","accent":"#f29a2e","muted":"#8d97b5","edge":"#4f5f88","font":"Lucida Console","heading":16},
}


def apply_skin(root, key, heading=None):
    import tkinter as tk
    skin=SKINS[key]
    style=ttk.Style(root)
    bg,fg,panel,field,accent,edge=(skin[k] for k in ("bg","fg","panel","input","accent","edge"))
    font=(skin["font"],10)
    style.configure(".",background=bg,foreground=fg,font=font)
    style.configure("TLabel",font=font)
    for name in ("TFrame","TLabel","TLabelframe","TCheckbutton"):
        style.configure(name,background=bg,foreground=fg)
    style.configure("TLabelframe",bordercolor=edge,lightcolor=edge,darkcolor=panel)
    style.configure("TLabelframe.Label",background=bg,foreground=fg,font=(skin["font"],10,"bold"))
    style.configure("TButton",background=panel,foreground=fg,bordercolor=edge,lightcolor=edge,
                    darkcolor=field,font=font,padding=6,borderwidth=1 if key=="basic" else 2)
    style.map("TButton",background=[("active",edge),("pressed",field)],foreground=[("disabled",skin["muted"])])
    style.configure("TEntry",fieldbackground=field,foreground=fg,insertcolor=accent,bordercolor=edge)
    style.configure("TCombobox",fieldbackground=field,background=panel,foreground=fg,arrowcolor=accent,bordercolor=edge)
    style.map("TCombobox",fieldbackground=[("readonly",field)],foreground=[("readonly",fg),("disabled",skin["muted"])])
    style.map("TCheckbutton",background=[("active",bg)],foreground=[("disabled",skin["muted"])])
    style.configure("TNotebook",background=bg,bordercolor=edge)
    style.configure("TNotebook.Tab",background=panel,foreground=fg,padding=(12,5))
    style.map("TNotebook.Tab",background=[("selected",field)],foreground=[("selected",accent),("disabled",skin["muted"])])
    style.configure("Treeview",background=field,fieldbackground=field,foreground=fg,bordercolor=edge,rowheight=25)
    style.configure("Treeview.Heading",background=panel,foreground=fg,font=(skin["font"],10,"bold"))
    style.map("Treeview",background=[("selected",accent)],foreground=[("selected","#10201a")])
    style.configure("Vertical.TScrollbar",background=panel,troughcolor=bg,bordercolor=edge,arrowcolor=fg)
    root.configure(background=bg)
    root.option_add("*TCombobox*Listbox.background",field)
    root.option_add("*TCombobox*Listbox.foreground",fg)
    from skin_chrome import apply_chrome, TREATMENTS
    apply_chrome(root,style,key,skin,heading)
    def walk(widget):
        if isinstance(widget,tk.Canvas) or (isinstance(widget,tk.PanedWindow) and not isinstance(widget,ttk.PanedWindow)):
            widget.configure(background=bg)
        elif isinstance(widget,tk.Text):widget.configure(background=panel,foreground=fg,insertbackground=accent)
        elif isinstance(widget,ttk.Button) and widget.cget("text")=="Start in 3 seconds":
            widget.configure(style="Start.TButton" if key in TREATMENTS else "TButton")
        for child in widget.winfo_children():walk(child)
    walk(root)
    if heading is not None:heading.configure(font=(skin["font"],skin["heading"],"bold"))


def stop_sound(enabled):
    if not enabled:return False
    try:
        import winsound
        from pathlib import Path
        winsound.PlaySound(str(Path(__file__).parent/"assets/stopped.wav"),winsound.SND_FILENAME|winsound.SND_ASYNC)
        return True
    except (ImportError,RuntimeError,OSError):
        return False
