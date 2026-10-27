"""Code-drawn, nine-slice Tk chrome. No image libraries or game input."""

import tkinter as tk
from copy import deepcopy

TREATMENTS={
    "rpos":{"caption":("Lucida Console",9,"bold"),"button":("Tahoma",10,"bold"),"padding":(8,6),"tabs":(14,5),"kind":"angular"},
    "cronamp":{"caption":("Tahoma",9,"bold"),"button":("Tahoma",9,"bold"),"padding":(9,5),"tabs":(11,4),"kind":"brushed"},
    "clinic":{"caption":("Segoe UI",10),"button":("Segoe UI",10),"padding":(10,7),"tabs":(15,6),"kind":"enamel"},
    "iron":{"caption":("Consolas",10,"bold"),"button":("Consolas",10),"padding":(9,5),"tabs":(10,5),"kind":"circuit"},
    "forge":{"caption":("Franklin Gothic Medium",11),"button":("Tahoma",10,"bold"),"padding":(10,7),"tabs":(14,6),"kind":"riveted"},
    "rain":{"caption":("Trebuchet MS",10,"bold"),"button":("Trebuchet MS",10),"padding":(10,6),"tabs":(14,5),"kind":"neon"},
    "psi":{"caption":("Georgia",10,"bold"),"button":("Segoe UI",10),"padding":(10,6),"tabs":(13,5),"kind":"geometric"},
    "dome":{"caption":("Consolas",10,"bold"),"button":("Consolas",10,"bold"),"padding":(8,5),"tabs":(10,4),"kind":"segmented"},
}


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
        p.box(w-16,4,w-11,5,accent)
    elif kind=="brushed":
        for inset,color in ((1,high),(2,dark),(3,edge)):
            p.rect(inset,inset,w-inset-1,h-inset-1,color)
        for y in (4,6,8):p.line(6,y,w-7,y,blend(edge,face,.3+(y%3)*.13))
        if role!="field":
            for y in (h-9,h-7,h-5):p.line(w-16,y,w-7,y,high)
    elif kind=="enamel":
        p.rect(2,2,w-3,h-3,blend(bg,edge,.45));p.rect(4,4,w-5,h-5,blend(bg,"#ffffff",.65))
        p.line(6,h-3,w-7,h-3,accent)
        for x in (6,w-7):p.line(x,6,x,10,edge)
    elif kind=="circuit":
        p.rect(2,2,w-3,h-3,dark);p.line(4,6,4,h-7,accent)
        p.line(7,5,19,5,edge);p.line(19,5,23,9,edge);p.line(23,9,w-10,9,edge)
        p.line(w-6,h-6,w-22,h-6,accent);p.line(w-22,h-6,w-26,h-10,accent)
        for x,y in ((4,8),(4,h-9),(w-7,h-6)):p.box(x-1,y-1,x+1,y+1,accent)
    elif kind=="riveted":
        p.rect(1,1,w-2,h-2,high);p.rect(3,3,w-4,h-4,dark);p.rect(4,4,w-5,h-5,edge)
        for x in (5,w-6):
            for y in (5,h-6):
                p.box(x-2,y-2,x+2,y+2,dark);p.box(x-1,y-1,x+1,y+1,high);p.dot(x,y,dark)
        if role=="button":
            for y in range(9,h-8,3):p.line(8,y,w-9,y,blend(face,edge,.12))
    elif kind=="neon":
        p.rect(1,1,w-2,h-2,blend(bg,accent,.25));p.rect(3,3,w-4,h-4,accent)
        p.line(8,5,w-9,5,blend(accent,"#ffffff",.25));p.line(8,h-5,w-9,h-5,blend(bg,accent,.5))
        p.box(4,0,12,2,bg);p.box(w-13,h-3,w-5,h-1,bg)
    elif kind=="geometric":
        p.rect(2,2,w-3,h-3,edge);p.rect(5,5,w-6,h-6,blend(edge,face,.5))
        for x,y in ((5,5),(w-6,h-6)):
            for a,b,c,d in ((x,y-3,x+3,y),(x+3,y,x,y+3),(x,y+3,x-3,y),(x-3,y,x,y-3)):p.line(a,b,c,d,accent)
        p.line(12,h-5,w-13,h-5,accent)
    elif kind=="segmented":
        p.rect(2,2,w-3,h-3,dark);p.line(5,8,5,h-5,edge);p.line(7,8,7,h-5,edge)
        for x in (12,24,36):p.box(x,3,x+7,5,accent if x==12 else edge)
        p.line(12,h-5,w-7,h-5,edge);p.line(w-6,10,w-6,h-9,accent)
    if state in ("selected","pressed"):
        p.line(12,h-3,w-13,h-3,accent)
    return p.image(root)


def badge(root,skin,kind):
    bg,accent,edge=(skin[k] for k in ("bg","accent","edge"))
    p=Pixels(34,25,bg)
    if kind=="brushed":
        p.rect(1,2,27,22,edge)
        for x,height in ((6,8),(11,14),(16,10),(21,18)):p.box(x,22-height,x+2,19,accent)
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
    elif kind=="neon":
        for i,height in enumerate((6,12,19,10,5)):p.box(3+i*5,22-height,5+i*5,20,accent if i%2 else edge)
    elif kind=="geometric":
        for radius in (6,10):
            points=[(15,12-radius),(15+radius,12),(15,12+radius),(15-radius,12),(15,12-radius)]
            for a,b in zip(points,points[1:]):p.line(*a,*b,accent if radius==6 else edge)
    elif kind=="segmented":
        for x in (3,11,19):
            for y in (5,14):p.rect(x,y,x+5,y+5,accent if x==3 else edge)
    else:
        for a,b,c,d in ((2,8,8,2),(8,2,24,2),(24,2,29,7),(29,7,29,19),(29,19,24,23),(24,23,7,23),(7,23,2,18)):
            p.line(a,b,c,d,accent)
        p.line(8,12,23,12,edge);p.line(15,6,15,19,edge)
    return p.image(root)


def replaced(layout,old,new):
    result=deepcopy(layout)
    for i,(name,options) in enumerate(result):
        if name==old:result[i]=(new,options)
        if "children" in options:options["children"]=replaced(options["children"],old,new)
    return result


def apply_chrome(root,style,key,skin,heading):
    names=("TLabelframe","TButton","TEntry","TCombobox","TNotebook.Tab")
    if not hasattr(root,"_original_skin_layouts"):
        root._original_skin_layouts={name:style.layout(name) for name in names}
        root._skin_image_cache={}
    for name,layout in root._original_skin_layouts.items():style.layout(name,layout)
    if heading is not None:heading.configure(image="",compound="none")
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
            style.element_create(element,"image",images[role+"_normal"],*state_images,border=(10,9,10,8),sticky="nsew")
        style.layout(style_name,replaced(root._original_skin_layouts[style_name],old,element))
    style.configure("TLabelframe.Label",font=treatment["caption"])
    style.configure("TButton",font=treatment["button"],padding=treatment["padding"])
    style.configure("TNotebook.Tab",padding=treatment["tabs"])
    style.configure("Start.TButton",font=(*treatment["button"][:2],"bold"),foreground=skin["accent"])
    if heading is not None:heading.configure(image=images["badge"],compound="left")
