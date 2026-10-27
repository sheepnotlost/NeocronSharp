import csv
import io
import json

import pytest

from ntc import export, lists
from ntc.lists import ListStore
from ntc.models import CellRead, ScanResult


def scan(*items, aborted=False):
    r = ScanResult(started_at="2026-10-06T12:00:00", aborted=aborted)
    r.cells = [CellRead(i // 5, i % 5, name, name, qty) for i, (name, qty) in enumerate(items)]
    r.recompute()
    return r


@pytest.fixture
def store(tmp_path):
    return ListStore(tmp_path / "lists.json")


def test_starts_with_default_list(store):
    assert store.names() == ["Default"] and store.active == "Default"


def test_two_scans_sum_L1(store):
    store.add_scan(scan(("Core", 2), ("Hull", 1)))
    store.add_scan(scan(("Core", 3)))
    assert store.totals() == {"Core": 5, "Hull": 1}
    assert [e["label"] for e in store.entries()] == ["Cabinet 1", "Cabinet 2"]
    assert store.where_is("Core") == [("Cabinet 1", 2), ("Cabinet 2", 3)]


def test_restart_restores_everything_L2(store, tmp_path):
    store.create("Tech")
    store.add_scan(scan(("Core", 2)))
    store.set_active("Default")
    again = ListStore(tmp_path / "lists.json")
    assert again.names() == ["Default", "Tech"] and again.active == "Default"
    assert again.totals("Tech") == {"Core": 2}


def test_undo_by_deleting_entry_L3(store):
    store.add_scan(scan(("Core", 2)))
    last = store.add_scan(scan(("Core", 3)))
    store.delete_entry(last["id"])
    assert store.totals() == {"Core": 2}


def test_edit_and_delete_entry_persist_L4(store, tmp_path):
    e = store.add_scan(scan(("Core", 2), ("Hull", 1)))
    store.set_cells(e["id"], [lists.cell_dict(CellRead(None, None, "Hull", "", 4))])
    store.rename_entry(e["id"], "Safe house")
    again = ListStore(tmp_path / "lists.json")
    assert again.totals() == {"Hull": 4} and again.entries()[0]["label"] == "Safe house"
    again.delete_entry(e["id"])
    assert ListStore(tmp_path / "lists.json").totals() == {}


def test_delete_list_isolated_and_last_list_recreated_L5(store):
    store.add_scan(scan(("Core", 2)))
    store.create("Other")
    store.add_scan(scan(("Hull", 1)))
    store.delete("Other")
    assert store.names() == ["Default"] and store.active == "Default" and store.totals() == {"Core": 2}
    store.delete("Default")
    assert store.names() == ["Default"] and store.totals() == {}


def test_corrupt_file_is_kept_as_bad_L6(tmp_path):
    p = tmp_path / "lists.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s = ListStore(p)
    assert s.names() == ["Default"]
    assert (tmp_path / "lists.json.bad").read_text(encoding="utf-8") == "{ this is not json"
    assert json.loads(p.read_text(encoding="utf-8"))["active"] == "Default"


@pytest.mark.parametrize("bad", ["", "   ", "x" * 41, "default"])
def test_invalid_list_names_rejected(store, bad):
    with pytest.raises(ValueError):
        store.create(bad)


def test_rename_list_keeps_data_and_active(store):
    store.add_scan(scan(("Core", 2)))
    store.rename("Default", "Main")
    assert store.names() == ["Main"] and store.active == "Main" and store.totals() == {"Core": 2}
    with pytest.raises(ValueError):
        store.create("MAIN")


def test_partial_scan_and_empty_scan(store):
    e = store.add_scan(scan(("Core", 1), aborted=True))
    assert e["label"] == "Cabinet 1 (partial)" and e["partial"]
    with pytest.raises(ValueError):
        store.add_scan(scan())
    assert len(store.entries()) == 1


def test_cabinet_number_follows_the_highest_existing(store):
    """Regression: a counter that only counted up gave 'Cabinet 6' after deleting 'Cabinet 5' from 1, 2, 5."""
    ids = [store.add_scan(scan(("Core", 1)))["id"] for _ in range(5)]          # Cabinet 1..5
    for i in ids[2:]:                                                          # delete 3, 4, 5
        store.delete_entry(i)
    assert store.add_scan(scan(("Core", 1)))["label"] == "Cabinet 3"


def test_deleting_a_middle_cabinet_does_not_renumber_or_reuse(store):
    ids = [store.add_scan(scan(("Core", 1)))["id"] for _ in range(3)]
    store.delete_entry(ids[1])
    assert store.add_scan(scan(("Core", 1)))["label"] == "Cabinet 4"
    assert [e["label"] for e in store.entries()] == ["Cabinet 1", "Cabinet 3", "Cabinet 4"]


def test_cabinet_number_ignores_renamed_and_counts_partial(store):
    a = store.add_scan(scan(("Core", 1)))
    store.rename_entry(a["id"], "Safe house")
    assert store.add_scan(scan(("Core", 1), aborted=True))["label"] == "Cabinet 1 (partial)"
    assert store.add_scan(scan(("Core", 1)))["label"] == "Cabinet 2"
    store.add_manual("Hand count")
    assert store.add_scan(scan(("Core", 1)))["label"] == "Cabinet 3"


def test_old_lists_file_with_counter_still_loads(tmp_path):
    p = tmp_path / "lists.json"
    p.write_text(json.dumps({"active": "Default", "lists": {"Default": {"created": "x", "next_cabinet": 9, "entries": []}}}))
    assert ListStore(p).add_scan(scan(("Core", 1)))["label"] == "Cabinet 1"


def test_scan_goes_to_list_active_at_scan_start(store):
    store.create("A")
    store.add_scan(scan(("Core", 1)), list_name="Default")
    assert store.totals("Default") == {"Core": 1} and store.totals("A") == {}


def test_manual_entry(store):
    e = store.add_manual("Hand count")
    store.set_cells(e["id"], [lists.cell_dict(CellRead(None, None, "Core", "", 7))])
    assert store.totals() == {"Core": 7} and store.entries()[0]["source"] == "manual"


def test_exports_match_list_totals_L7(store):
    store.add_scan(scan(("Core", 2), ("Hull", 1)))
    store.add_scan(scan(("Core", 3)))
    r = store.to_result()
    assert export.to_clipboard(r).splitlines() == ["Core\t5", "Hull\t1", "TOTAL\t6"]
    rows = list(csv.reader(io.StringIO(export.to_csv_by_cabinet(store))))
    assert rows[0] == ["list", "cabinet", "scan_time", "item", "qty"]
    assert [(r_[1], r_[3], r_[4]) for r_ in rows[1:]] == [("Cabinet 1", "Core", "2"), ("Cabinet 1", "Hull", "1"),
                                                           ("Cabinet 2", "Core", "3")]
    data = json.loads(export.to_json_list(store))
    assert data["list"] == "Default" and data["totals"] == {"Core": 5, "Hull": 1} and len(data["entries"]) == 2


def test_inventory_and_cabinet_numbered_separately(store):
    inv = scan(("Core", 1))
    inv.kind = "inventory"
    assert store.add_scan(scan(("Core", 1)))["label"] == "Cabinet 1"
    assert store.add_scan(inv)["label"] == "Inventory 1"
    assert store.add_scan(scan(("Core", 1)))["label"] == "Cabinet 2"
    inv2 = scan(("Core", 1), aborted=True)
    inv2.kind = "inventory"
    assert store.add_scan(inv2)["label"] == "Inventory 2 (partial)"


def test_exports_say_which_cabinet_holds_each_item(store):
    store.add_scan(scan(("Core", 2), ("Hull", 1)))                       # Cabinet 1
    inv = scan(("Core", 1))
    inv.kind = "inventory"
    store.add_scan(inv)                                                  # Inventory 1
    store.add_scan(scan(("Core", 3)))                                    # Cabinet 2
    where = store.locations()
    assert where == {"Core": [("Cabinet 1", 2), ("Inventory 1", 1), ("Cabinet 2", 3)], "Hull": [("Cabinet 1", 1)]}
    r = store.to_result()
    assert export.where_text(where, "Core") == "Cabinet 1 (2), Inventory 1 (1), Cabinet 2 (3)"
    clip = export.to_clipboard(r, where).splitlines()
    assert clip == ["Item\tQty\tWhere", "Core\t6\tCabinet 1 (2), Inventory 1 (1), Cabinet 2 (3)",
                    "Hull\t1\tCabinet 1", "TOTAL\t7"]          # one place: the quantity is not repeated
    rows = list(csv.reader(io.StringIO(export.to_csv(r, where))))
    assert rows[0] == ["scan_time", "item", "qty", "cabinets"]
    assert rows[1][1:] == ["Core", "6", "Cabinet 1 (2), Inventory 1 (1), Cabinet 2 (3)"]
    assert export.to_txt(r, where).splitlines()[1].endswith("Cabinet 1")
    data = json.loads(export.to_json_list(store))
    assert data["where"]["Hull"] == [{"cabinet": "Cabinet 1", "qty": 1}]


def test_exports_without_locations_keep_the_old_format(store):
    store.add_scan(scan(("Core", 2)))
    assert export.to_clipboard(store.to_result()).splitlines() == ["Core\t2", "TOTAL\t2"]
