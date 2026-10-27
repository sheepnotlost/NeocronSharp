import csv
import io
import json

from ntc import export
from ntc.models import CellRead, ScanResult


def sample():
    r = ScanResult(started_at="2026-10-06T12:00:00")
    r.cells = [CellRead(0, 0, "Hull Part Of HOLY ABSORPTION", "x", 1),
               CellRead(0, 1, "Core Part Of HOLY DEFLECTION", "x", 5),
               CellRead(0, 2, "Core Part Of HOLY DEFLECTION", "x", 2)]
    r.recompute()
    return r


def test_totals_merge_and_sort():
    assert sample().totals == {"Core Part Of HOLY DEFLECTION": 7, "Hull Part Of HOLY ABSORPTION": 1}


def test_clipboard_is_tab_separated_with_total():
    assert export.to_clipboard(sample()).split("\n") == [
        "Core Part Of HOLY DEFLECTION\t7", "Hull Part Of HOLY ABSORPTION\t1", "TOTAL\t8"]


def test_csv_header_and_rows():
    rows = list(csv.reader(io.StringIO(export.to_csv(sample()))))
    assert rows[0] == ["scan_time", "item", "qty"]
    assert rows[1] == ["2026-10-06T12:00:00", "Core Part Of HOLY DEFLECTION", "7"]


def test_txt_has_total_line():
    assert export.to_txt(sample()).splitlines()[-1].split() == ["TOTAL", "8"]


def test_json_round_trip_has_cells_and_flags():
    data = json.loads(export.to_json(sample()))
    assert data["totals"]["Core Part Of HOLY DEFLECTION"] == 7
    assert len(data["cells"]) == 3 and "flags" in data["cells"][0]


def test_default_filename():
    assert export.default_filename("csv").startswith("cabinet_") and export.default_filename("csv").endswith(".csv")
