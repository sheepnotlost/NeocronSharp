"""Which rares can be completed from the parts in a list (SPEC 15). Pure logic, no UI."""
import csv
import io
import json
import re
from dataclasses import dataclass, field

from .config import RES

DATA = RES / "data" / "tech_sets.json"
PART_RE = re.compile(r"^(?P<part>.+?) Part Of (?P<item>.+)$", re.I)
ABBREV = {"Technology": "Tech", "Hull": "Hull", "Frame": "Frame", "Core": "Core", "Component": "Comp",
          "Additional Technology": "Add.Tech"}


def key(name):
    """Match key: lowercase, dots and apostrophes removed, other punctuation as a space."""
    s = name.lower().replace("'", "").replace("’", "").replace(".", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def load(path=DATA):
    return json.loads(path.read_text(encoding="utf-8"))["items"]


@dataclass
class SetStatus:
    name: str
    group: str
    tech_level: str
    needs: list
    have: dict = field(default_factory=dict)         # part -> quantity held
    where: dict = field(default_factory=dict)        # part -> [(cabinet label, qty)]

    @property
    def missing(self):
        return [p for p in self.needs if self.have.get(p, 0) < 1]

    @property
    def held(self):
        return [p for p in self.needs if self.have.get(p, 0) >= 1]

    @property
    def complete_sets(self):
        return 0 if self.missing else min(self.have[p] for p in self.needs)

    @property
    def status(self):
        if not self.missing:
            return f"COMPLETE x{self.complete_sets}"
        return f"missing {len(self.missing)}"

    @property
    def have_text(self):
        return f"{len(self.held)}/{len(self.needs)}"

    def where_text(self):
        places = {}
        for p in self.needs:
            for label, qty in self.where.get(p, []):
                places.setdefault(label, []).append(ABBREV[p])
        return "; ".join(f"{label}: {', '.join(parts)}" for label, parts in places.items())


def analyze(locations, items=None):
    """locations = {tech name: [(cabinet label, qty), ...]} (see ListStore.locations).
    Returns (statuses for every rare in the database, names of held parts no rare matches)."""
    items = items if items is not None else load()
    by_key = {i["key"]: SetStatus(i["name"], i["group"], i["tech_level"], list(i["needs"])) for i in items}
    unknown = []
    for name, places in locations.items():
        m = PART_RE.match(name)
        st = by_key.get(key(m["item"])) if m else None
        if st is None:
            unknown.append(name)
            continue
        part = next((p for p in ABBREV if p.lower() == m["part"].lower()), None)
        if part is None or part not in st.needs:
            continue                                  # a part type this rare does not need is ignored
        st.have[part] = st.have.get(part, 0) + sum(q for _, q in places)
        st.where.setdefault(part, []).extend(places)
    return sorted(by_key.values(), key=lambda s: (len(s.missing), s.name.lower())), sorted(unknown)


FILTERS = {
    "in progress": lambda s: bool(s.held),
    "complete": lambda s: not s.missing,
    "missing 1": lambda s: len(s.missing) == 1 and bool(s.held),
    "missing 2 or fewer": lambda s: len(s.missing) <= 2 and bool(s.held),
    "all": lambda s: True,
}


def select(statuses, show="in progress", search=""):
    f, q = FILTERS[show], search.strip().lower()
    return [s for s in statuses if f(s) and q in s.name.lower()]


def rows(statuses):
    return [[s.name, s.group, s.status, s.have_text, ", ".join(ABBREV[p] for p in s.missing), s.where_text()]
            for s in statuses]


HEADER = ["Item", "Category", "Status", "Have", "Missing", "Where"]


def to_clipboard(statuses):
    return "\n".join("\t".join(r) for r in [HEADER] + rows(statuses))


def to_csv(statuses):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(rows(statuses))
    return buf.getvalue()


def detail(status):
    """Part-by-part lines: a check or cross per needed part, and where it is held."""
    lines = [f"{status.name}  ({status.group}, TL {status.tech_level})", f"{status.status}   have {status.have_text}", ""]
    for p in status.needs:
        q = status.have.get(p, 0)
        if q:
            places = ", ".join(f"{label} ({n})" if len(status.where[p]) > 1 else label for label, n in status.where[p])
            lines.append(f"  [x] {p}: {q}   {places}")
        else:
            lines.append(f"  [ ] {p}: MISSING")
    return "\n".join(lines)
