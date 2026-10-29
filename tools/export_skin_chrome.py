"""Export the app's own code-drawn chrome for the offline styling gallery."""

from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from appearance import SKINS, apply_skin
from skin_chrome import TREATMENTS


def main():
    root=tk.Tk();root.withdraw();ttk.Style(root).theme_use("clam")
    heading=ttk.Label(root,text="NeocronSharp")
    folder=ROOT/"styling/native-chrome";folder.mkdir(exist_ok=True)
    rules=["/* Exported from the native app's code-drawn skins. Basic is untouched. */"]
    try:
        for key in TREATMENTS:
            apply_skin(root,key,heading)
            for name,image in root._skin_image_cache[key].items():
                image.write(str(folder/f"{key}-{name}.png"),format="png")
            prefix=f".skin-{key}"
            rules.append(f'{prefix} .module{{border:9px solid transparent;border-image:url("native-chrome/{key}-panel_normal.png") 9 10 8 10 fill;padding:4px}}')
            rules.append(f'{prefix} .control{{border:7px solid transparent;border-image:url("native-chrome/{key}-button_normal.png") 9 10 8 10 fill;padding:2px 5px}}')
            rules.append(f'{prefix} .field{{border:6px solid transparent;border-image:url("native-chrome/{key}-field_normal.png") 9 10 8 10 fill;padding:2px 4px}}')
            rules.append(f'{prefix} .tab{{border:6px solid transparent;border-image:url("native-chrome/{key}-tab_normal.png") 9 10 8 10 fill;padding:2px 7px}}')
            rules.append(f'{prefix} .tab.active{{border-image-source:url("native-chrome/{key}-tab_selected.png")}}')
            rules.append(f'{prefix} .bar::before{{content:"";display:block;flex:0 0 25px;height:22px;background:url("native-chrome/{key}-badge.png") center/contain no-repeat}}')
            rules.append(f'{prefix} .bar strong{{flex:1;margin-left:5px}}')
        rules.append('.mini .module{border-width:4px!important;padding:3px!important}.mini .control,.mini .field{border-width:3px!important;padding:2px!important}.mini .bar::before{display:none!important}.mini .bar strong{margin-left:0}')
        (ROOT/"styling/native-chrome.css").write_text("\n".join(rules)+"\n",encoding="utf8")
        print(f"Exported {len(TREATMENTS)} native chrome sets for the gallery; Basic unchanged.")
    finally:root.destroy()


if __name__=="__main__":main()
