"""Exporters (SPEC 9). Each returns text; the app handles the clipboard / file dialogs.

`where` maps an item name to [(cabinet label, qty), ...]. When given, every export says which cabinet(s) hold
each item, e.g. "Cabinet 1 (2), Cabinet 3 (1)", or just "Cabinet 4" when an item is in one place.
"""
import csv
import io
import json
from datetime import datetime


def default_filename(ext):
    return f"cabinet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"


def total_qty(result):
    return sum(result.totals.values())


def where_text(where, item):
    """'Cabinet 4' when the item is in one place (the Qty column already gives the number), otherwise the split:
    'Cabinet 3 (2), Inventory 1 (1)'."""
    places = (where or {}).get(item, [])
    if len(places) == 1:
        return places[0][0]
    return ", ".join(f"{label} ({qty})" for label, qty in places)


def to_clipboard(result, where=None):
    head = "Item\tQty" + ("\tWhere" if where is not None else "")
    lines = [head] if where is not None else []
    for name, qty in result.totals.items():
        lines.append(f"{name}\t{qty}" + (f"\t{where_text(where, name)}" if where is not None else ""))
    lines.append(f"TOTAL\t{total_qty(result)}")
    return "\n".join(lines)


def to_csv(result, where=None):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["scan_time", "item", "qty"] + (["cabinets"] if where is not None else []))
    for name, qty in result.totals.items():
        w.writerow([result.started_at, name, qty] + ([where_text(where, name)] if where is not None else []))
    return buf.getvalue()


def to_txt(result, where=None):
    width = max([len(n) for n in result.totals] + [len("TOTAL")])
    lines = []
    for name, qty in result.totals.items():
        line = f"{name.ljust(width)}  {qty:>4}"
        if where is not None:
            line += f"   {where_text(where, name)}"
        lines.append(line)
    lines.append("-" * (width + 6))
    lines.append(f"{'TOTAL'.ljust(width)}  {total_qty(result):>4}")
    return "\n".join(lines)


def to_json(result, where=None):
    data = result.to_dict()
    if where is not None:
        data["where"] = {item: [{"cabinet": label, "qty": qty} for label, qty in where.get(item, [])]
                         for item in result.totals}
    return json.dumps(data, indent=2)


def to_csv_by_cabinet(store, list_name=None):
    from .lists import entry_totals
    list_name = list_name or store.active
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["list", "cabinet", "scan_time", "item", "qty"])
    for e in store.entries(list_name):
        for item, qty in entry_totals(e).items():
            w.writerow([list_name, e["label"], e["time"], item, qty])
    return buf.getvalue()


def to_json_list(store, list_name=None):
    list_name = list_name or store.active
    data = json.loads(to_json(store.to_result(list_name), store.locations(list_name)))
    data["list"] = list_name
    data["entries"] = store.entries(list_name)
    return json.dumps(data, indent=2)


FORMATS = {"csv": to_csv, "txt": to_txt, "json": to_json}
