import csv
import io

from ntc import sets
from ntc.lists import ListStore
from ntc.models import CellRead, ScanResult

ALL = ["Technology", "Hull", "Frame", "Core", "Component", "Additional Technology"]


def db():
    return [
        {"name": "Terminator", "key": "terminator", "group": "Rifles (Low-Tech)", "tech_level": "87",
         "needs": ALL[:5]},                                                    # a five-part rare
        {"name": "Desperado", "key": "desperado", "group": "Rifles (Low-Tech)", "tech_level": "103", "needs": ALL},
        {"name": "Steiner F.P 1.0", "key": sets.key("Steiner F.P 1.0"), "group": "Pistols", "tech_level": "50", "needs": ALL},
    ]


def locs(**parts):
    """locs(Terminator={"Hull": [("Cabinet 1", 1)]}) -> the locations dict of a list."""
    out = {}
    for item, byp in parts.items():
        for part, places in byp.items():
            out[f"{part} Part Of {item}"] = places
    return out


def status(results, name):
    return next(s for s in results[0] if s.name == name)


def test_complete_set():
    L = locs(Terminator={p: [("Cabinet 1", 1)] for p in ALL[:5]})
    s = status(sets.analyze(L, db()), "Terminator")
    assert s.complete_sets == 1 and s.missing == [] and s.status == "COMPLETE x1" and s.have_text == "5/5"


def test_one_part_short_names_the_missing_part():
    parts = {p: [("Cabinet 1", 1)] for p in ALL if p != "Frame"}
    s = status(sets.analyze(locs(Desperado=parts), db()), "Desperado")
    assert s.missing == ["Frame"] and s.status == "missing 1" and s.complete_sets == 0 and s.have_text == "5/6"


def test_two_copies_of_every_part_give_two_sets_and_the_smallest_quantity_rules():
    L = locs(Terminator={p: [("Cabinet 1", 2)] for p in ALL[:5]})
    assert status(sets.analyze(L, db()), "Terminator").complete_sets == 2
    L["Core Part Of Terminator"] = [("Cabinet 1", 1)]
    assert status(sets.analyze(L, db()), "Terminator").complete_sets == 1


def test_parts_in_different_cabinets_add_up_and_are_located():
    L = locs(Terminator={"Hull": [("Cabinet 1", 1), ("Inventory 1", 2)], "Tech": []})
    s = status(sets.analyze(L, db()), "Terminator")
    assert s.have["Hull"] == 3
    assert "Cabinet 1: Hull" in s.where_text() and "Inventory 1: Hull" in s.where_text()


def test_a_part_type_the_rare_does_not_need_is_ignored():
    L = locs(Terminator={"Additional Technology": [("Cabinet 1", 1)]})
    s = status(sets.analyze(L, db()), "Terminator")
    assert "Additional Technology" not in s.have and s.held == []


def test_punctuation_differences_still_match():
    L = locs(**{"STEINER FP 1.0": {"Core": [("Cabinet 6", 1)]}})
    assert status(sets.analyze(L, db()), "Steiner F.P 1.0").held == ["Core"]


def test_parts_of_unknown_rares_are_reported_not_dropped():
    L = locs(Mystery={"Core": [("Cabinet 1", 1)]})
    _, unknown = sets.analyze(L, db())
    assert unknown == ["Core Part Of Mystery"]


def test_sorted_closest_to_complete_first_and_filters():
    L = locs(Terminator={p: [("Cabinet 1", 1)] for p in ALL[:5]},
             Desperado={p: [("Cabinet 1", 1)] for p in ALL[:4]})            # missing 2
    results, _ = sets.analyze(L, db())
    assert [s.name for s in results][:2] == ["Terminator", "Desperado"]
    assert [s.name for s in sets.select(results, "complete")] == ["Terminator"]
    assert [s.name for s in sets.select(results, "missing 2 or fewer")] == ["Terminator", "Desperado"]
    assert [s.name for s in sets.select(results, "in progress")] == ["Terminator", "Desperado"]
    assert len(sets.select(results, "all")) == 3 and sets.select(results, "all", "steiner")[0].name == "Steiner F.P 1.0"


def test_exports_and_detail():
    L = locs(Desperado={p: [("Cabinet 1", 1)] for p in ALL if p != "Frame"})
    results, _ = sets.analyze(L, db())
    shown = sets.select(results, "in progress")
    assert sets.to_clipboard(shown).splitlines()[0] == "Item\tCategory\tStatus\tHave\tMissing\tWhere"
    rows = list(csv.reader(io.StringIO(sets.to_csv(shown))))
    assert rows[1][:5] == ["Desperado", "Rifles (Low-Tech)", "missing 1", "5/6", "Frame"]
    text = sets.detail(shown[0])
    assert "[ ] Frame: MISSING" in text and "[x] Hull: 1" in text


def test_bundled_data_is_sound():
    items = sets.load()
    assert len(items) == 86 and len({i["key"] for i in items}) == 86
    assert all(set(i["needs"]) <= set(ALL) and len(i["needs"]) in (5, 6) for i in items)
    assert all(sets.key(i["name"]) == i["key"] for i in items)


def test_works_with_a_real_list_store(tmp_path):
    store = ListStore(tmp_path / "l.json")
    r = ScanResult(started_at="2026-10-06T12:00:00")
    r.cells = [CellRead(0, i, f"{p} Part Of Terminator", "", 1) for i, p in enumerate(ALL[:5])]
    r.recompute()
    store.add_scan(r)
    s = status(sets.analyze(store.locations()), "Terminator")
    assert s.complete_sets == 1 and s.where_text() == "Cabinet 1: Tech, Hull, Frame, Core, Comp"
