"""Persistent named lists of scanned cabinets (SPEC 13)."""
import json
import os
import re
import uuid
from datetime import datetime

from .config import ROOT
from .models import CellRead, ScanResult

PATH = ROOT / "lists.json"
DEFAULT_NAME = "Default"
MAX_NAME = 40
LABEL_PREFIX = {"cabinet": "Cabinet", "inventory": "Inventory"}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _new_list():
    return {"created": _now(), "entries": []}


def cell_dict(c):
    return {"row": c.row, "col": c.col, "name": c.name, "raw_ocr": c.raw_ocr, "qty": c.qty, "flags": list(c.flags)}


def entry_totals(entry):
    totals = {}
    for c in entry["cells"]:
        totals[c["name"]] = totals.get(c["name"], 0) + c["qty"]
    return dict(sorted(totals.items()))


class ListStore:
    def __init__(self, path=PATH):
        self.path = path
        self.data = {"active": DEFAULT_NAME, "lists": {DEFAULT_NAME: _new_list()}}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            lists = data["lists"]
            assert isinstance(lists, dict) and lists
            for lst in lists.values():
                assert isinstance(lst["entries"], list)
                lst.setdefault("created", _now())
                for e in lst["entries"]:
                    assert isinstance(e["cells"], list) and "id" in e and "label" in e
            if data.get("active") not in lists:
                data["active"] = next(iter(lists))
            self.data = data
        except Exception:
            try:
                os.replace(self.path, self.path.with_name(self.path.name + ".bad"))
            except OSError:
                pass
            self.save()

    def save(self):
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- lists -------------------------------------------------------------
    @property
    def active(self):
        return self.data["active"]

    def names(self):
        return list(self.data["lists"])

    def _clean_name(self, name, ignore=None):
        name = " ".join((name or "").split())
        if not name:
            raise ValueError("The list needs a name.")
        if len(name) > MAX_NAME:
            raise ValueError(f"List names are at most {MAX_NAME} characters.")
        if any(n.lower() == name.lower() for n in self.data["lists"] if n != ignore):
            raise ValueError(f"A list named '{name}' already exists.")
        return name

    def set_active(self, name):
        if name not in self.data["lists"]:
            raise KeyError(name)
        self.data["active"] = name
        self.save()

    def create(self, name):
        name = self._clean_name(name)
        self.data["lists"][name] = _new_list()
        self.data["active"] = name
        self.save()
        return name

    def rename(self, old, new):
        new = self._clean_name(new, ignore=old)
        if new != old:
            self.data["lists"] = {(new if k == old else k): v for k, v in self.data["lists"].items()}
            if self.data["active"] == old:
                self.data["active"] = new
            self.save()
        return new

    def delete(self, name):
        del self.data["lists"][name]
        if not self.data["lists"]:
            self.data["lists"][DEFAULT_NAME] = _new_list()
        if self.data["active"] not in self.data["lists"]:
            self.data["active"] = next(iter(self.data["lists"]))
        self.save()

    # -- entries -----------------------------------------------------------
    def _list(self, name=None):
        return self.data["lists"][name or self.active]

    def entries(self, name=None):
        return self._list(name)["entries"]

    def find_entry(self, entry_id):
        for lname, lst in self.data["lists"].items():
            for e in lst["entries"]:
                if e["id"] == entry_id:
                    return lname, e
        raise KeyError(entry_id)

    @staticmethod
    def _next_number(lst, prefix):
        """One more than the highest '<prefix> N' already in the list (1 if none). Renamed entries are ignored."""
        pat = re.compile(re.escape(prefix) + r" (\d+)\b")
        nums = [int(m[1]) for e in lst["entries"] if (m := pat.match(e["label"]))]
        return max(nums, default=0) + 1

    def add_scan(self, result, list_name=None):
        """Add a ScanResult as a new 'Cabinet N' entry. Raises ValueError if it has no cells."""
        if not result.cells:
            raise ValueError("Nothing to add: the scan found no items.")
        if list_name not in self.data["lists"]:
            list_name = self.active
        lst = self._list(list_name)
        prefix = LABEL_PREFIX.get(getattr(result, "kind", "cabinet"), "Cabinet")
        label = f"{prefix} {self._next_number(lst, prefix)}" + (" (partial)" if result.aborted else "")
        entry = {"id": uuid.uuid4().hex[:8], "label": label, "source": "scan", "time": result.started_at,
                 "partial": bool(result.aborted), "cells": [cell_dict(c) for c in result.cells]}
        lst["entries"].append(entry)
        self.save()
        return entry

    def add_manual(self, label="Manual"):
        entry = {"id": uuid.uuid4().hex[:8], "label": label, "source": "manual", "time": _now(),
                 "partial": False, "cells": []}
        self._list()["entries"].append(entry)
        self.save()
        return entry

    def delete_entry(self, entry_id):
        lname, entry = self.find_entry(entry_id)
        self.data["lists"][lname]["entries"].remove(entry)
        self.save()

    def rename_entry(self, entry_id, label):
        label = " ".join((label or "").split())
        if not label:
            raise ValueError("The entry needs a label.")
        self.find_entry(entry_id)[1]["label"] = label[:MAX_NAME]
        self.save()

    def set_cells(self, entry_id, cells):
        """Replace an entry's cells (list of dicts as produced by cell_dict)."""
        self.find_entry(entry_id)[1]["cells"] = cells
        self.save()

    # -- totals / export ---------------------------------------------------
    def totals(self, name=None):
        totals = {}
        for e in self.entries(name):
            for item, qty in entry_totals(e).items():
                totals[item] = totals.get(item, 0) + qty
        return dict(sorted(totals.items()))

    def slot_count(self, name=None):
        return sum(len(e["cells"]) for e in self.entries(name))

    def where_is(self, item, name=None):
        """[(entry label, qty)] for every entry that contains the item."""
        out = []
        for e in self.entries(name):
            q = entry_totals(e).get(item)
            if q:
                out.append((e["label"], q))
        return out

    def locations(self, name=None):
        """{item: [(entry label, qty), ...]} for every item in the list: which cabinet holds what."""
        out = {}
        for e in self.entries(name):
            for item, qty in entry_totals(e).items():
                out.setdefault(item, []).append((e["label"], qty))
        return out

    def to_result(self, name=None):
        """The active list as one ScanResult, so the existing exporters work unchanged."""
        r = ScanResult(started_at=_now())
        for e in self.entries(name):
            for c in e["cells"]:
                r.cells.append(CellRead(c.get("row"), c.get("col"), c["name"], c.get("raw_ocr", ""),
                                        c["qty"], list(c.get("flags", []))))
        r.recompute()
        return r
