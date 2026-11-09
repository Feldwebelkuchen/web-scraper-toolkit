import csv
import json

import pytest
from openpyxl import load_workbook

from web_scraper_toolkit.export import export_records, infer_format
from web_scraper_toolkit.table import render_table

RECORDS = [
    {"title": "Alpha", "price": 10.0, "tags": ["a", "b"], "upc": None},
    {"title": "Beta, with comma", "price": 20.5, "tags": [], "upc": "X1"},
]
COLUMNS = ["title", "price", "tags", "upc"]


def test_infer_format():
    assert infer_format("out.CSV") == "csv"
    assert infer_format("data/out.xlsx") == "xlsx"
    with pytest.raises(ValueError):
        infer_format("out.txt")


def test_csv_export(tmp_path):
    path = export_records(RECORDS, tmp_path / "out.csv", COLUMNS)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0] == {"title": "Alpha", "price": "10.0", "tags": "a | b", "upc": ""}
    assert rows[1]["title"] == "Beta, with comma"


def test_json_export_keeps_lists_and_nulls(tmp_path):
    path = export_records(RECORDS, tmp_path / "out.json", COLUMNS)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["tags"] == ["a", "b"] and data[0]["upc"] is None
    assert list(data[1]) == COLUMNS


def test_xlsx_export_formatting(tmp_path):
    path = export_records(RECORDS, tmp_path / "out.xlsx", COLUMNS)
    sheet = load_workbook(path).active
    assert sheet.title == "data"
    assert [c.value for c in sheet[1]] == COLUMNS
    assert all(c.font.bold for c in sheet[1])
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:D3"
    assert sheet["A3"].value == "Beta, with comma"
    assert sheet["B2"].value == 10.0
    assert sheet["C2"].value == "a | b"
    assert sheet.column_dimensions["A"].width == len("Beta, with comma") + 2


def test_explicit_format_overrides_extension(tmp_path):
    path = export_records(RECORDS, tmp_path / "out.dat", COLUMNS, fmt="json")
    assert json.loads(path.read_text(encoding="utf-8"))[0]["title"] == "Alpha"
    with pytest.raises(ValueError):
        export_records(RECORDS, tmp_path / "out.dat", COLUMNS, fmt="parquet")


def test_render_table_truncates_and_aligns():
    text = render_table(RECORDS, COLUMNS, max_width=8)
    lines = text.splitlines()
    assert lines[0].startswith("| title")
    assert "Beta, w…" in lines[3]
    assert len({len(line) for line in lines}) == 1  # all lines equally wide
    assert "(no records)" in render_table([], COLUMNS)
