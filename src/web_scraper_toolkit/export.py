"""Exporters: CSV, JSON and formatted XLSX."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

FORMATS = ("csv", "json", "xlsx")
_LIST_SEPARATOR = " | "
_MAX_COLUMN_WIDTH = 60


def infer_format(path: str | Path) -> str:
    """Derive the export format from a file extension."""
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix not in FORMATS:
        raise ValueError(f"cannot infer format from {path!s}; use one of: {', '.join(FORMATS)}")
    return suffix


def export_records(
    records: Iterable[dict[str, Any]],
    path: str | Path,
    columns: Sequence[str],
    fmt: str | None = None,
) -> Path:
    """Write ``records`` to ``path`` in the given (or inferred) format."""
    fmt = fmt or infer_format(path)
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; use one of: {', '.join(FORMATS)}")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = list(records)
    if fmt == "csv":
        write_csv(rows, out, columns)
    elif fmt == "json":
        write_json(rows, out, columns)
    else:
        write_xlsx(rows, out, columns)
    return out


def write_csv(records: Sequence[dict[str, Any]], path: Path, columns: Sequence[str]) -> None:
    """UTF-8 CSV with a header row; list values are joined with ``" | "``."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({col: flatten_cell(record.get(col)) for col in columns})


def write_json(records: Sequence[dict[str, Any]], path: Path, columns: Sequence[str]) -> None:
    """Pretty-printed JSON array; lists stay lists."""
    ordered = [{col: record.get(col) for col in columns} for record in records]
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_xlsx(records: Sequence[dict[str, Any]], path: Path, columns: Sequence[str]) -> None:
    """Excel workbook: bold header, frozen first row, autofilter, sized columns."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "data"
    sheet.append(list(columns))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for record in records:
        sheet.append([_xlsx_cell(record.get(col)) for col in columns])

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for index, column in enumerate(columns, start=1):
        longest = len(str(column))
        for record in records:
            longest = max(longest, len(str(flatten_cell(record.get(column)) or "")))
        sheet.column_dimensions[get_column_letter(index)].width = min(longest, _MAX_COLUMN_WIDTH) + 2
    workbook.save(path)


def flatten_cell(value: Any) -> Any:
    """Turn list values into a single string for flat formats."""
    if isinstance(value, (list, tuple)):
        return _LIST_SEPARATOR.join("" if v is None else str(v) for v in value)
    return value


def _xlsx_cell(value: Any) -> Any:
    value = flatten_cell(value)
    if value is None or isinstance(value, (int, float, str)):
        return value
    return str(value)
