"""Scan the 2 fps crops for "Entering new district" banners and Location-panel changes.

Frame n (1-based) is video time (n-1)/2 s. Writes events.json next to this script.
Make the crops first (1920x1080 recording), into banner/ and loc/ beside this script:
  ffmpeg -i REC.mp4 -filter_complex "[0:v]fps=2,split=2[a][b];[a]crop=480:72:720:530[ba];[b]crop=200:50:30:72[lo]"
         -map "[ba]" banner/%05d.png -map "[lo]" loc/%05d.png
Run with the bundled runtime: runtime\\python.exe scan.py runtime\\tesseract\\tesseract.exe
Then pair.py <traversal\\logs> lines the events up with the walk logs (edit T0 for another recording).
Known slip: a run whose name changes part way (Plaza 2 -> 3 at 1490 s) is reported under its later name.
"""
import re
from collections import Counter
import json, subprocess, sys, tempfile, os
from pathlib import Path
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TESS = Path(sys.argv[1])  # tesseract.exe
BANNER, LOC = HERE / "banner", HERE / "loc"


def green_text(im):
    b, g, r = (im[..., i].astype(int) for i in range(3))
    return (g > 170) & (g - r > 50) & (g - b > 20)


def ocr(im, scale=3):
    big = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    mask = green_text(big)
    page = np.where(mask, 0, 255).astype(np.uint8)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.png")
        cv2.imwrite(p, page)
        out = subprocess.run([str(TESS), p, "stdout", "--psm", "7", "--tessdata-dir", str(TESS.parent / "tessdata")],
                             capture_output=True, text=True).stdout
    return " ".join(out.split())


def ocr_block(im, scale=3):
    big = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    page = np.where(green_text(big), 0, 255).astype(np.uint8)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.png")
        cv2.imwrite(p, page)
        out = subprocess.run([str(TESS), p, "stdout", "--psm", "6", "--tessdata-dir", str(TESS.parent / "tessdata")],
                             capture_output=True, text=True).stdout
    return " ".join(out.split())


def place(text):
    t = text.upper().replace("SEC -", "SEC-")
    m = re.search(r"(PLAZA|PEPPER PARK|VIA ROSSO|INDUSTRIAL AREA|OUTZONE)\W*SEC\W*(\d)", t) or re.search(r"(NEOFRAG)\W*(\d)", t)
    return f"{m.group(1)} {'SEC-' if m.group(1) != 'NEOFRAG' else ''}{m.group(2)}" if m else None


frames = sorted(BANNER.glob("*.png"))
scores = []
for f in frames:
    im = cv2.imread(str(f))
    scores.append(int(green_text(im[30:58]).sum()))

# Banner runs: consecutive frames with enough green text in the text row.
events, run = [], None
for i, s in enumerate(scores):
    if s >= 300:
        run = run or [i, i]
        run[1] = i
    elif run:
        events.append(run); run = None
if run: events.append(run)
banners = []
for a, b in events:
    if b - a < 1:
        continue
    seq = []
    for i in range(a, b + 1):
        m = re.search(r"d\W*\w*str\w*\W*(.+)", ocr(cv2.imread(str(frames[i]))[28:60]))
        text = m.group(1).strip(" .,;:|}]") if m else None
        p = place(text or "")
        seq.append((i, p or text))
    # split on a change of the read name (ignoring single unreadable frames)
    cur = None
    for i, text in seq:
        if not text: continue
        if cur and text == cur["text"]:
            cur["end"] = i / 2; continue
        if cur and i / 2 - cur["end"] <= 1 and cur["n"] == 1:
            cur.update(text=text, end=i / 2); continue
        cur = {"start": i / 2, "end": i / 2, "text": text, "n": 0}
        banners.append(cur)
        cur["n"] = 1
    for c in banners: c["n"] = 2
for c in banners:
    print(f"banner {c['start']:7.1f}-{c['end']:7.1f}s  {c['text']}", flush=True)

# Location panel: OCR whenever the crop changes noticeably.
locs, last_img, last_text = [], None, None
for f in sorted(LOC.glob("*.png")):
    im = cv2.imread(str(f))
    t = (int(f.stem) - 1) / 2
    if last_img is not None and np.abs(im.astype(int) - last_img.astype(int)).mean() < 6:
        continue
    last_img = im
    text = place(ocr_block(im, 4))
    if text and text != last_text:
        locs.append({"t": t, "text": text})
        print(f"location {t:7.1f}s  {text}", flush=True)
        last_text = text

(HERE / "events.json").write_text(json.dumps({"banners": banners, "locations": locs, "scores": scores}, indent=1))
