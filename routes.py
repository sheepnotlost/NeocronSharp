"""A growing library of walked Nav-Ray routes, and the map of areas they connect.

Every successful walk records where it started (the HUD's Location name), where it ended, how long it
took and its legs (turns and walking time). The library is saved to routes.json next to the app (your own
data: it is not part of the repository). Later walks use it as a hint, and `areas()` summarises which
areas have been reached from which.
"""
import json
import re
import time
from pathlib import Path

ROUTES_PATH = Path(__file__).parent / "routes.json"
LOCATION_BOX = (.02, .082, .105, .108)      # the HUD "Location" name, as fractions of the frame
KEEP_LEGS = 60


def normalize_area(text):
    """OCR of the Location name -> "PLAZA SEC-1" style. Junk at the edges is dropped; "SEC-I" is "SEC-1"."""
    text = " ".join((text or "").upper().split())
    text = re.sub(r"\s+[A-Z]$", "", text)                       # a stray single letter from the HUD frame
    match = re.match(r"([A-Z][A-Z ]*?)\s*(SEC-?\s*[0-9I]+)", text)
    if match:
        sector = re.sub(r"\s+", "", match.group(2)).replace("I", "1")
        sector = sector if "-" in sector else sector.replace("SEC", "SEC-")
        return f"{match.group(1).strip()} {sector}"
    return text


def read_area(gray):
    """The Location name from a grayscale frame, or "" when it cannot be read."""
    import cv2
    import pytesseract
    from ntc import ocr
    ocr.configure("")
    height, width = gray.shape[:2]
    left, top, right, bottom = LOCATION_BOX
    crop = gray[int(top*height):int(bottom*height), int(left*width):int(right*width)]
    if crop.size == 0:
        return ""
    big = cv2.resize(255 - crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=int(big.max()))
    text = pytesseract.image_to_string(
        big, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ")
    return normalize_area(text)


class RouteBook:
    def __init__(self, path=ROUTES_PATH):
        self.path = Path(path)
        self.data = {"routes": {}}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("routes"), dict):
                self.data = loaded
        except (OSError, ValueError):
            pass

    @staticmethod
    def key(start_area, destination):
        return f"{start_area or '?'} | {destination}"

    def best(self, start_area, destination):
        return self.data["routes"].get(self.key(start_area, destination))

    def record(self, start_area, destination, end_area, legs, seconds):
        """Remember a finished walk. The quickest walk of a route is kept as its best; every walk is counted."""
        key = self.key(start_area, destination)
        entry = self.data["routes"].setdefault(key, {"start": start_area, "destination": destination, "walks": 0})
        entry["walks"] += 1
        entry["end"] = end_area or entry.get("end")
        if "seconds" not in entry or seconds < entry["seconds"]:
            entry.update({"seconds": round(seconds, 1), "legs": list(legs)[:KEEP_LEGS],
                          "recorded": time.strftime("%Y-%m-%d %H:%M")})
        return entry

    def first_turn(self, start_area, destination):
        """Which way the best known walk first turned (+1 right, -1 left, 0 unknown): where to look first."""
        entry = self.best(start_area, destination)
        for leg in (entry or {}).get("legs", ()):
            if leg.get("turn"):
                return 1 if leg["turn"] > 0 else -1
        return 0

    def areas(self):
        """{area: {"leads_to": sorted areas reached from it, "routes": number of routes starting there}}."""
        found = {}
        for entry in self.data["routes"].values():
            start = entry.get("start") or "?"
            item = found.setdefault(start, {"leads_to": set(), "routes": 0})
            item["routes"] += 1
            if entry.get("end"):
                item["leads_to"].add(entry["end"])
        return {k: {"leads_to": sorted(v["leads_to"]), "routes": v["routes"]} for k, v in sorted(found.items())}

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
