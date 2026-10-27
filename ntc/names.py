"""Name normalisation against known_items.json (SPEC 6.5)."""
import difflib
import json
import re

from .config import ROOT

PATH = ROOT / "known_items.json"
SEED_PART_TYPES = ["Component", "Hull", "Additional Technology", "Technology", "Core", "Frame"]
# Pairs of characters the OCR can swap (the game font's "g" and "y" lose their tails, "I" looks like "1" or "l").
CONFUSABLE = {("g", "a"), ("g", "v"), ("y", "v"), ("g", "q"), ("0", "o"), ("1", "l"), ("1", "i"), ("i", "l"),
              ("5", "s"), ("8", "b"), ("u", "v"), ("c", "e"), ("rn", "m")}
CONFUSABLE = {p for p in CONFUSABLE if len(p[0]) == 1 and len(p[1]) == 1}
PART_RE = re.compile(r"^(?P<part>.+?) Part Of (?P<rest>.+)$", re.I)


class Names:
    def __init__(self, path=PATH):
        self.path = path
        self.data = {"part_types": list(SEED_PART_TYPES), "names": [], "aliases": {}}
        if path.exists():
            self.data.update(json.loads(path.read_text(encoding="utf-8")))

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    @staticmethod
    def _ratio(a, b):
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _fix_part_type(self, raw):
        m = PART_RE.match(raw)
        if not m:
            return raw
        best = max(self.data["part_types"], key=lambda p: self._ratio(m["part"], p), default=None)
        if best and self._ratio(m["part"], best) >= 0.8:
            return f"{best} Part Of {m['rest']}"
        return raw

    @staticmethod
    def _equivalent(a, b):
        """True if a and b differ only by characters OCR commonly mixes up (I/1, O/0, g/a...). Names that differ
        in a digit or a letter that is not a look-alike ("51/ 56" vs "51/ 58", "II" vs "III") never merge."""
        if len(a) != len(b):
            return False
        for x, y in zip(a.lower(), b.lower()):
            if x != y and (x, y) not in CONFUSABLE and (y, x) not in CONFUSABLE:
                return False
        return True

    def _match_known(self, name):
        """Merge OCR noise into an already-known name. Names with different part types never merge."""
        m = PART_RE.match(name)
        for known in self.data["names"]:
            k = PART_RE.match(known)
            if m and k:
                if m["part"].lower() == k["part"].lower() and self._equivalent(m["rest"], k["rest"]):
                    return known
            elif not m and not k and self._equivalent(name, known):
                return known
        return None

    def is_tech(self, name):
        """A tech is a '<Part> Part Of <weapon>' item whose part is Component, Hull, Additional Technology,
        Technology, Core or Frame."""
        m = PART_RE.match(name or "")
        return bool(m) and m["part"].lower() in {p.lower() for p in self.data["part_types"]}

    def normalize(self, raw, techs_only=False):
        """Return (name, flags). With techs_only, an item that is not a tech comes back flagged SKIP and is not
        remembered, so the known-items list stays free of everything the user chose not to log."""
        raw = " ".join((raw or "").split())
        if not raw:
            return "?", ["NAME_UNREAD"]
        for k, v in self.data["aliases"].items():
            if k.lower() == raw.lower():
                return (v, ["SKIP"]) if techs_only and not self.is_tech(v) else (v, [])
        fixed = self._fix_part_type(raw)
        if techs_only and not self.is_tech(fixed):
            return fixed, ["SKIP"]
        known = self._match_known(fixed)
        if known:
            return known, []
        self.data["names"].append(fixed)
        return fixed, ["NEW_NAME"]

    def teach(self, raw, corrected):
        """Record a user correction: raw OCR text -> corrected name."""
        if raw and raw != corrected:
            self.data["aliases"][raw] = corrected
        if corrected not in self.data["names"]:
            self.data["names"].append(corrected)
        self.save()
