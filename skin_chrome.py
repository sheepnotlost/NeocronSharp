"""Code-drawn, nine-slice Tk chrome and a Winamp-style title bar. No image libraries or game input."""

import tkinter as tk
from copy import deepcopy
from pathlib import Path

TREATMENTS={
    "rpos":{"caption":("Lucida Console",9,"bold"),"button":("Tahoma",10,"bold"),"padding":(8,6),"tabs":(3,3),"kind":"angular"},
    "cronamp":{"caption":("Tahoma",9,"bold"),"button":("Tahoma",9,"bold"),"padding":(9,5),"tabs":(3,3),"kind":"brushed"},
    "amber":{"caption":("Consolas",10,"bold"),"button":("Consolas",10,"bold"),"padding":(8,5),"tabs":(3,3),"kind":"terminal"},
    "clinic":{"caption":("Segoe UI",10),"button":("Segoe UI",10),"padding":(10,7),"tabs":(3,3),"kind":"enamel"},
    "iron":{"caption":("Consolas",10,"bold"),"button":("Consolas",10),"padding":(9,5),"tabs":(3,3),"kind":"circuit"},
    "forge":{"caption":("Franklin Gothic Medium",11),"button":("Tahoma",10,"bold"),"padding":(10,7),"tabs":(3,3),"kind":"riveted"},
    "rain":{"caption":("Trebuchet MS",10,"bold"),"button":("Trebuchet MS",10,"bold"),"padding":(10,6),"tabs":(3,3),"kind":"redlight"},
    "psi":{"caption":("Georgia",10,"bold"),"button":("Segoe UI",10),"padding":(10,6),"tabs":(3,3),"kind":"geometric"},
    "dome":{"caption":("Consolas",10,"bold"),"button":("Consolas",10,"bold"),"padding":(8,5),"tabs":(3,3),"kind":"segmented"},
    "lcd":{"caption":("Consolas",10,"bold"),"button":("Tahoma",9,"bold"),"padding":(9,5),"tabs":(3,3),"kind":"lcd"},
    "spectrum":{"caption":("Tahoma",9,"bold"),"button":("Tahoma",9,"bold"),"padding":(9,5),"tabs":(3,3),"kind":"spectrum"},
    "chrome":{"caption":("Tahoma",10,"bold"),"button":("Tahoma",10),"padding":(10,6),"tabs":(3,3),"kind":"bevel"},
    "visualizer":{"caption":("Trebuchet MS",10,"bold"),"button":("Trebuchet MS",10),"padding":(10,6),"tabs":(3,3),"kind":"scope"},
    "shade":{"caption":("Lucida Console",9,"bold"),"button":("Lucida Console",9),"padding":(8,4),"tabs":(3,3),"kind":"shade",
              "tabfont":("Lucida Console",8)},                     # a wide font: smaller, so all nine tabs fit
}

BORDER=(10,9,10,8)        # left, top, right, bottom: the fixed corners of every nine-slice image
TAB_PADDING=(4,4,4,3)     # tabs sit inside less than the full border, so all nine still fit across the window
# The Pepper Park billboard shows a picture kept on this PC only (it is game artwork and the repository is public):
# assets/local/pepper_park_billboard.png. Without it a drawn billboard is shown.
BILLBOARD=Path(__file__).resolve().parent/"assets"/"local"/"pepper_park_billboard.png"


def blend(a,b,t):
    return "#"+"".join(f"{round(int(a[i:i+2],16)*(1-t)+int(b[i:i+2],16)*t):02x}" for i in (1,3,5))


class Pixels:
    def __init__(self,w,h,color):self.w=w;self.h=h;self.rows=[[color]*w for _ in range(h)]
    def dot(self,x,y,color):
        if 0<=x<self.w and 0<=y<self.h:self.rows[y][x]=color
    def box(self,x0,y0,x1,y1,color):
        for y in range(max(0,y0),min(self.h,y1+1)):
            for x in range(max(0,x0),min(self.w,x1+1)):self.rows[y][x]=color
    def line(self,x0,y0,x1,y1,color):
        steps=max(abs(x1-x0),abs(y1-y0),1)
        for i in range(steps+1):self.dot(round(x0+(x1-x0)*i/steps),round(y0+(y1-y0)*i/steps),color)
    def rect(self,x0,y0,x1,y1,color):
        for a,b,c,d in ((x0,y0,x1,y0),(x1,y0,x1,y1),(x1,y1,x0,y1),(x0,y1,x0,y0)):self.line(a,b,c,d,color)
    def tileable(self,face):
        """Tk repeats the middle of each edge and the centre to fill a control. Anything drawn there that is not
        the same all along turns into a row of stray marks, so make every edge strip uniform along its length
        (copied from its middle) and the centre plain. Only the corners keep their own detail."""
        left,top,right,bottom=BORDER
        for y in range(self.h):
            if y<top or y>=self.h-bottom:
                middle=self.rows[y][self.w//2]
                for x in range(left,self.w-right):self.rows[y][x]=middle
        for x in list(range(left))+list(range(self.w-right,self.w)):
            middle=self.rows[self.h//2][x]
            for y in range(top,self.h-bottom):self.rows[y][x]=middle
        self.box(left,top,self.w-right-1,self.h-bottom-1,face)
    def image(self,root):
        image=tk.PhotoImage(master=root,width=self.w,height=self.h)
        image.put(" ".join("{"+" ".join(row)+"}" for row in self.rows))
        return image


def surface(root,skin,kind,role,state="normal"):
    w,h=(96,64) if role=="panel" else (100,32)
    bg,panel,field,accent,edge=(skin[k] for k in ("bg","panel","input","accent","edge"))
    face=bg if role=="panel" else field if role=="field" or state in ("pressed","selected") else panel
    if state=="active":face=blend(panel,accent,.14)
    p=Pixels(w,h,bg);p.box(2,2,w-3,h-3,face)
    high=blend(edge,"#ffffff",.30);dark=blend(field,"#000000",.42)
    p.rect(1,1,w-2,h-2,edge)
    if kind=="angular":
        p.box(0,0,w-1,7,bg)
        points=[(1,8),(8,1),(w-10,1),(w-2,9),(w-2,h-9),(w-10,h-2),(1,h-2),(1,8)]
        for a,b in zip(points,points[1:]):p.line(*a,*b,accent)
        p.line(5,10,5,h-7,edge);p.line(9,h-5,w-13,h-5,edge)
    elif kind=="brushed":
        # Winamp's base skin: a light top/left bevel, a dark bottom/right one, and fine brushed lines along the top.
        p.line(1,1,w-2,1,high);p.line(1,1,1,h-2,high)
        p.line(w-2,2,w-2,h-2,dark);p.line(2,h-2,w-2,h-2,dark)
        p.rect(3,3,w-4,h-4,blend(edge,face,.4))
        for y in (5,7):p.line(5,y,w-6,y,blend(edge,face,.55))
    elif kind=="terminal":
        # A CRT terminal: a thin double rule with bright corner brackets.
        p.rect(3,3,w-4,h-4,blend(edge,face,.5))
        for x,y,dx,dy in ((1,1,1,1),(w-2,1,-1,1),(1,h-2,1,-1),(w-2,h-2,-1,-1)):
            p.line(x,y,x+5*dx,y,accent);p.line(x,y,x,y+4*dy,accent)
    elif kind=="enamel":
        p.rect(2,2,w-3,h-3,blend(bg,edge,.45));p.rect(4,4,w-5,h-5,blend(bg,"#ffffff",.65))
        p.line(6,h-3,w-7,h-3,accent)
    elif kind=="circuit":
        p.rect(2,2,w-3,h-3,dark);p.line(4,6,4,h-7,accent);p.line(6,5,w-7,5,edge)
        for x,y in ((4,4),(4,h-5)):p.box(x-1,y-1,x+1,y+1,accent)
    elif kind=="riveted":
        p.rect(1,1,w-2,h-2,high);p.rect(3,3,w-4,h-4,dark);p.rect(4,4,w-5,h-5,edge)
        for x in (5,w-6):
            for y in (5,h-6):
                p.box(x-2,y-2,x+2,y+2,dark);p.box(x-1,y-1,x+1,y+1,high);p.dot(x,y,dark)
    elif kind=="redlight":
        # Pepper Park: dark brick framed by a red neon tube, with a lamp in each corner.
        mortar=blend(face,"#000000",.45)
        p.rect(1,1,w-2,h-2,blend(bg,accent,.35));p.rect(2,2,w-3,h-3,blend(accent,"#ffffff",.15))
        p.rect(3,3,w-4,h-4,blend(bg,accent,.45));p.rect(4,4,w-5,h-5,mortar)
        for x,y in ((5,5),(w-6,5),(5,h-6),(w-6,h-6)):p.dot(x,y,blend(accent,"#ffffff",.55))
    elif kind=="geometric":
        p.rect(2,2,w-3,h-3,edge);p.rect(5,5,w-6,h-6,blend(edge,face,.5))
        for x,y in ((5,5),(w-6,h-6)):
            for a,b,c,d in ((x,y-3,x+3,y),(x+3,y,x,y+3),(x,y+3,x-3,y),(x-3,y,x,y-3)):p.line(a,b,c,d,accent)
    elif kind=="segmented":
        p.rect(2,2,w-3,h-3,dark);p.line(5,8,5,h-5,edge)
        p.box(3,3,8,5,accent)
        if role=="panel":p.line(w-6,10,w-6,h-9,accent)         # beside a tab's text it read like a cursor
    elif kind=="lcd":
        # Dark inset readout with a lit pixel strip along the bottom.
        p.rect(2,2,w-3,h-3,dark);p.rect(3,3,w-4,h-4,high)
        p.line(6,h-6,w-7,h-6,blend(face,accent,.35))
    elif kind=="spectrum":
        # Thin frame; the analyser bars live in the corners, a gradient rule along the bottom.
        p.rect(2,2,w-3,h-3,dark)
        for i,(x,height) in enumerate(((3,3),(5,5),(7,2),(w-8,4),(w-6,2),(w-4,5))):
            p.box(x,h-3-height,x+1,h-3,blend(accent,"#ff4a2a",i/6))
        p.line(10,h-3,w-11,h-3,blend(accent,"#ff4a2a",.5))
    elif kind=="bevel":
        # Raised chrome: bright top/left, dark bottom/right, double edge.
        p.line(1,1,w-2,1,"#ffffff");p.line(1,1,1,h-2,"#ffffff")
        p.line(w-2,1,w-2,h-2,dark);p.line(1,h-2,w-2,h-2,dark)
        p.rect(3,3,w-4,h-4,blend(edge,"#ffffff",.45))
    elif kind=="scope":
        # Glowing frame; a scope trace in the top border (it repeats cleanly: one wave per four pixels).
        p.rect(2,2,w-3,h-3,edge);p.rect(3,3,w-4,h-4,blend(bg,accent,.3))
        for x in range(4,w-4):
            p.dot(x,5+(0,-1,0,1)[x%4],accent)
    elif kind=="shade":
        # Compact title-bar look: two rules along the top, slim body.
        p.rect(2,2,w-3,h-3,dark)
        for y in (4,6):p.line(4,y,w-5,y,edge)
    if state in ("selected","pressed"):
        p.line(4,h-3,w-5,h-3,accent)
    p.tileable(face)
    return p.image(root)


def badge(root,skin,kind):
    bg,accent,edge=(skin[k] for k in ("panel","accent","edge"))
    p=Pixels(34,25,bg)
    if kind=="brushed":
        p.rect(1,2,27,22,edge)
        for x,height in ((6,8),(11,14),(16,10),(21,18)):p.box(x,22-height,x+2,19,accent)
    elif kind=="terminal":
        p.rect(1,2,30,22,edge);p.line(6,8,11,12,accent);p.line(11,12,6,16,accent);p.box(14,16,22,17,accent)
    elif kind=="enamel":
        p.rect(2,3,24,21,edge);p.line(13,7,13,17,accent);p.line(8,12,18,12,accent)
    elif kind=="circuit":
        for y in (5,12,19):p.line(3,y,12,y,accent);p.line(12,y,20,12,edge);p.box(1,y-1,4,y+1,accent)
        p.rect(20,8,27,16,accent)
    elif kind=="riveted":
        p.rect(3,3,25,21,edge);p.rect(6,6,22,18,accent)
        for x in (4,24):
            for y in (4,20):p.dot(x,y,accent)
        p.line(11,8,17,16,edge);p.line(17,8,11,16,edge)
    elif kind=="redlight":
        # The pedestrian-traffic arrow from Pepper Park's street signs, as a neon tube.
        for a,b,c,d in ((3,12,22,12),(22,12,15,5),(22,12,15,19)):p.line(a,b,c,d,accent)
        for a,b,c,d in ((3,13,22,13),(21,12,14,5),(21,12,14,19)):p.line(a,b,c,d,blend(accent,"#ffffff",.4))
        p.rect(0,1,30,23,edge)
    elif kind=="geometric":
        for radius in (6,10):
            points=[(15,12-radius),(15+radius,12),(15,12+radius),(15-radius,12),(15,12-radius)]
            for a,b in zip(points,points[1:]):p.line(*a,*b,accent if radius==6 else edge)
    elif kind=="segmented":
        for x in (3,11,19):
            for y in (5,14):p.rect(x,y,x+5,y+5,accent if x==3 else edge)
    elif kind=="lcd":
        p.box(1,4,30,20,"#050805");p.rect(1,4,30,20,edge)
        for x in (4,10,16,22):p.box(x,8,x+3,16,accent)
    elif kind=="spectrum":
        for i,height in enumerate((5,11,17,8,14,19)):p.box(2+i*5,22-height,4+i*5,22,blend(accent,"#ff4a2a",i/6))
    elif kind=="bevel":
        p.rect(2,3,28,21,edge);p.line(3,4,27,4,"#ffffff");p.line(3,4,3,20,"#ffffff")
        for x in (8,14,20):p.line(x,7,x,18,accent);p.box(x-2,12-(x%3)*2,x+2,13-(x%3)*2,accent)
    elif kind=="scope":
        p.rect(1,2,30,22,edge);previous=None
        for x in range(3,29,2):
            y=12+round(6*((x//2)%4-1.5)/1.5)
            if previous:p.line(*previous,x,y,accent)
            previous=(x,y)
    elif kind=="shade":
        p.box(1,8,30,16,edge);p.box(24,9,29,15,accent)
        for x in range(3,21,3):p.line(x,10,x,14,blend(edge,"#ffffff",.4))
    else:
        for a,b,c,d in ((2,8,8,2),(8,2,24,2),(24,2,29,7),(29,7,29,19),(29,19,24,23),(24,23,7,23),(7,23,2,18)):
            p.line(a,b,c,d,accent)
        p.line(8,12,23,12,edge);p.line(15,6,15,19,edge)
    return p.image(root)


def replaced(layout,old,new):
    result=deepcopy(layout)
    for i,(name,options) in enumerate(result):
        if name==old:
            # A "border" node is drawn after its children; an image there would paint over the button's text.
            options.pop("border",None)
            result[i]=(new,options)
        if "children" in options:options["children"]=replaced(options["children"],old,new)
    return result


# ---- the Winamp title bar: ribbed strips either side of the caps title, badge left, LCD readout right ----

TITLE_HEIGHT=34
STREET_HEIGHT=136          # Pepper Park's taller bar: a brick street with a billboard


def billboard_photo(root,height):
    """The local billboard picture scaled to `height` pixels, or None. Pictures are cached per height."""
    cache=root.__dict__.setdefault("_billboard_cache",{})
    if height not in cache:
        cache[height]=None
        if BILLBOARD.exists():
            try:
                photo=tk.PhotoImage(master=root,file=str(BILLBOARD))
                factor=max(1,-(-photo.height()//height))          # never taller than the frame
                cache[height]=photo.subsample(factor) if factor>1 else photo
            except tk.TclError:
                cache[height]=None
    return cache[height]


def draw_ribs(canvas,x0,x1,middle,skin):
    if x1-x0<12:return
    high=blend(skin["edge"],"#ffffff",.35);low=blend(skin["edge"],skin["accent"],.35)
    dark=blend(skin["input"],"#000000",.4)
    for y in (middle-5,middle-1,middle+3):
        canvas.create_line(x0,y,x1,y,fill=high);canvas.create_line(x0,y+1,x1,y+1,fill=low)
        canvas.create_line(x0,y+2,x1,y+2,fill=dark)


def draw_street(canvas,w,h,skin):
    """Pepper Park behind the title: dark brick lit red from below, and a billboard on the right."""
    brick=skin["panel"];mortar=blend(skin["input"],"#000000",.3);glow=skin["accent"]
    canvas.create_rectangle(0,0,w,h,fill=mortar,outline="")
    for row,y in enumerate(range(0,h,12)):
        shade=blend(brick,glow,.06+.22*y/h)
        for x in range(-(row%2)*14,w,28):canvas.create_rectangle(x+1,y+1,x+26,y+10,fill=shade,outline="")
    canvas.create_rectangle(0,h-3,w,h,fill=glow,outline="")                         # the neon strip at street level
    canvas.create_rectangle(0,h-6,w,h-3,fill=blend(glow,mortar,.5),outline="")
    height=h-30
    photo=billboard_photo(canvas.winfo_toplevel(),height)
    if photo is not None and photo.width()>w//3:photo=None              # too wide for this window: the drawn one
    if photo is not None:height=photo.height()
    width=photo.width() if photo is not None else round(height*2.3)
    right=w-14;left=right-width
    # Frame, two lamps on the top rail, legs down to the street.
    for x in (left+width//4,right-width//4):canvas.create_rectangle(x-2,h-14,x+2,h-6,fill=blend(skin["edge"],"#000000",.4),outline="")
    canvas.create_rectangle(left-5,9,right+5,15+height,fill=blend(skin["edge"],"#000000",.5),outline=skin["edge"])
    if photo is not None:
        canvas.create_image(left,12,image=photo,anchor="nw")
    else:
        canvas.create_rectangle(left,12,right,12+height,fill=skin["input"],outline="")
        canvas.create_text((left+right)//2,12+height//2-10,text="NEOCRON",fill=glow,font=("Trebuchet MS",17,"bold"))
        canvas.create_text((left+right)//2,12+height//2+14,text="PEPPER PARK",fill=blend(glow,"#ffffff",.45),
                           font=("Trebuchet MS",10,"bold"))
    for x in (left+12,right-12):
        canvas.create_polygon(x-4,4,x+4,4,x+12,11,x-12,11,fill=blend(glow,"#ffffff",.5),outline="")
    canvas.create_rectangle(left,12,right,12+height,outline=blend(glow,"#ffffff",.3))
    return left-16


def draw_titlebar(canvas):
    key,skin,images,treatment=canvas._spec
    w=max(canvas.winfo_width(),300)
    street=treatment["kind"]=="redlight"
    h=STREET_HEIGHT if street else TITLE_HEIGHT
    if int(canvas.cget("height"))!=h:canvas.configure(height=h)
    canvas.delete("all")
    panel,edge,accent,field,fg=(skin[k] for k in ("panel","edge","accent","input","fg"))
    high=blend(edge,"#ffffff",.35);dark=blend(field,"#000000",.4)
    end=w-8
    if street:
        end=draw_street(canvas,w,h,skin)
        middle=h//2-4
    else:
        canvas.create_rectangle(0,0,w-1,h-1,fill=panel,outline=dark)
        canvas.create_line(1,1,w-2,1,fill=high);canvas.create_line(1,1,1,h-2,fill=high)
        middle=h//2
    canvas.create_image(8,middle,image=images["badge"],anchor="w")
    font=(treatment["caption"][0],13 if street else 11,"bold")
    title="N E O C R O N S H A R P"
    if street:                                          # a neon sign: a dark red halo, then the bright tube
        for dx,dy in ((-2,0),(2,0),(0,-2),(0,2)):
            canvas.create_text(46+dx,middle+dy,text=title,anchor="w",fill=blend(accent,"#000000",.45),font=font)
        text=canvas.create_text(46,middle,text=title,anchor="w",fill=blend(accent,"#ffffff",.35),font=font)
        x0,_,x1,_=canvas.bbox(text)
        draw_ribs(canvas,x1+12,end,middle,skin)
        return
    text=canvas.create_text(w//2,middle,text=title,fill=fg,font=font)
    x0,_,x1,_=canvas.bbox(text)
    readout=skin["name"].upper()
    label=canvas.create_text(end-8,middle,text=readout,anchor="e",fill=accent,font=("Consolas",9,"bold"))
    lx0,ly0,lx1,ly1=canvas.bbox(label)
    canvas.create_rectangle(lx0-6,ly0-3,lx1+6,ly1+3,fill=field,outline=edge)
    canvas.tag_raise(label)
    draw_ribs(canvas,44,x0-12,middle,skin)
    draw_ribs(canvas,x1+12,lx0-14,middle,skin)


def show_titlebar(heading,key,skin,images,treatment):
    canvas=getattr(heading,"_titlebar",None)
    if canvas is None:
        info=heading.grid_info()
        canvas=tk.Canvas(heading.master,highlightthickness=0,borderwidth=0,height=TITLE_HEIGHT)
        canvas._titlebar_canvas=True                     # apply_skin repaints canvases; this one paints itself
        canvas.grid(row=info["row"],column=info["column"],sticky="ew",pady=(0,4))
        canvas.bind("<Configure>",lambda event:draw_titlebar(canvas))
        heading._titlebar=canvas
    canvas._spec=(key,skin,images,treatment)
    canvas.configure(background=skin["bg"])
    canvas.grid();heading.grid_remove()
    draw_titlebar(canvas)


def hide_titlebar(heading):
    canvas=getattr(heading,"_titlebar",None)
    if canvas is not None:canvas.grid_remove()
    heading.grid()


def apply_chrome(root,style,key,skin,heading):
    names=("TLabelframe","TButton","TEntry","TCombobox","TNotebook.Tab")
    if not hasattr(root,"_original_skin_layouts"):
        root._original_skin_layouts={name:style.layout(name) for name in names}
        root._skin_image_cache={}
    for name,layout in root._original_skin_layouts.items():style.layout(name,layout)
    if heading is not None:
        heading.configure(image="",compound="none")
        if heading.winfo_manager() or getattr(heading,"_titlebar",None) is not None:hide_titlebar(heading)
    if key not in TREATMENTS:return
    treatment=TREATMENTS[key];kind=treatment["kind"]
    if key not in root._skin_image_cache:
        images={}
        for role in ("panel","button","field","tab"):
            states=("normal","active","pressed") if role=="button" else ("normal","selected","active") if role=="tab" else ("normal",)
            for state in states:images[role+"_"+state]=surface(root,skin,kind,role,state)
        images["badge"]=badge(root,skin,kind);root._skin_image_cache[key]=images
    images=root._skin_image_cache[key]
    for role,style_name,old in (("panel","TLabelframe","Labelframe.border"),("button","TButton","Button.border"),
                               ("field","TEntry","Entry.field"),("field","TCombobox","Combobox.field"),
                               ("tab","TNotebook.Tab","Notebook.tab")):
        element=f"Macro.{key}.{role}"
        if element not in style.element_names():
            state_images=[(s,images[role+"_"+s]) for s in ("pressed","selected","active") if role+"_"+s in images]
            # An image element is never smaller than its picture (100 px wide) unless told: every tab was 100 px,
            # so long names were cut while short ones had room to spare.
            extra={"tab":{"padding":TAB_PADDING,"width":24,"height":20},"button":{"width":40,"height":24}}.get(role,{})
            style.element_create(element,"image",images[role+"_normal"],*state_images,border=BORDER,sticky="nsew",**extra)
        style.layout(style_name,replaced(root._original_skin_layouts[style_name],old,element))
    style.configure("TLabelframe.Label",font=treatment["caption"])
    style.configure("TButton",font=treatment["button"],padding=treatment["padding"])
    # All nine tabs fit across the narrowest window (960 px) in every font.
    style.configure("TNotebook.Tab",padding=treatment["tabs"],
                    font=treatment.get("tabfont",(treatment["button"][0],min(9,treatment["button"][1]))))
    style.configure("Start.TButton",font=(*treatment["button"][:2],"bold"),foreground=skin["accent"])
    if heading is not None:
        heading.configure(image=images["badge"],compound="left")
        if heading.winfo_manager() or getattr(heading,"_titlebar",None) is not None:
            show_titlebar(heading,key,skin,images,treatment)
