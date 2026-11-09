"""Minimal plain-text table renderer for terminal previews."""

from __future__ import annotations

from typing import Any, Sequence

from .export import flatten_cell


def render_table(records: Sequence[dict[str, Any]], columns: Sequence[str], max_width: int = 32) -> str:
    """Render records as an aligned text table, truncating long cells."""
    if not columns:
        return "(no columns)"
    rows = [[_cell(record.get(col), max_width) for col in columns] for record in records]
    widths = [len(col) for col in columns]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells: Sequence[str]) -> str:
        return "| " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)) + " |"

    separator = "|-" + "-|-".join("-" * w for w in widths) + "-|"
    out = [line(list(columns)), separator]
    out.extend(line(row) for row in rows)
    if not rows:
        out.append("| " + "(no records)".ljust(sum(widths) + 3 * (len(widths) - 1)) + " |")
    return "\n".join(out)


def _cell(value: Any, max_width: int) -> str:
    text = "" if value is None else str(flatten_cell(value))
    text = " ".join(text.split())
    if len(text) > max_width:
        return text[: max_width - 1] + "…"
    return text
