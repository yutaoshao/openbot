"""Telegram-friendly Markdown table rendering."""

from __future__ import annotations

import re
from html import escape as html_escape
from typing import TYPE_CHECKING
from unicodedata import east_asian_width

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Table separator row (e.g. |---|---|)
TABLE_SEPARATOR = re.compile(r"^\|[\s:]*-{2,}[\s:]*(\|[\s:]*-{2,}[\s:]*)*\|?\s*$")

PRE_COLUMN_GAP = "  "
PRE_TABLE_MAX_WIDTH = 56
PRE_CELL_MAX_WIDTH = 24
DOUBLE_WIDTH_CATEGORIES = frozenset({"F", "W"})

# Markdown formatting markers to strip in <pre> table cells.
MD_MARKERS = re.compile(r"\*\*|~~|__")


def render_markdown_table(
    rows: Sequence[str],
    inline_renderer: Callable[[str], str],
) -> str:
    """Render Markdown table rows using a Telegram-compatible layout."""
    parsed = _parse_table(rows)
    if not parsed:
        return ""

    if _fits_pre_block(parsed):
        return _render_pre_table(parsed)

    return _render_field_list(parsed, inline_renderer)


def _parse_table(rows: Sequence[str]) -> list[list[str]]:
    parsed: list[list[str]] = []
    for row in rows:
        if TABLE_SEPARATOR.match(row):
            continue
        parsed.append(_parse_table_row(row))
    return parsed


def _parse_table_row(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _fits_pre_block(rows: Sequence[Sequence[str]]) -> bool:
    col_widths = _column_widths(rows)
    total_width = sum(col_widths) + len(PRE_COLUMN_GAP) * max(0, len(col_widths) - 1)
    if total_width > PRE_TABLE_MAX_WIDTH:
        return False
    return all(_display_width(cell) <= PRE_CELL_MAX_WIDTH for row in rows for cell in row)


def _render_pre_table(rows: Sequence[Sequence[str]]) -> str:
    clean_rows = [[MD_MARKERS.sub("", cell) for cell in row] for row in rows]
    col_widths = _column_widths(clean_rows)
    rendered: list[str] = []
    for idx, row_cells in enumerate(clean_rows):
        rendered.append(_render_pre_row(row_cells, col_widths))
        if idx == 0 and len(clean_rows) > 1:
            rendered.append(PRE_COLUMN_GAP.join("-" * width for width in col_widths))
    escaped = html_escape("\n".join(rendered))
    return f"<pre>{escaped}</pre>"


def _render_pre_row(row_cells: Sequence[str], col_widths: Sequence[int]) -> str:
    parts = []
    for index, width in enumerate(col_widths):
        cell = row_cells[index] if index < len(row_cells) else ""
        padding = width - _display_width(cell)
        parts.append(cell + " " * max(0, padding))
    return PRE_COLUMN_GAP.join(parts)


def _render_field_list(
    rows: Sequence[Sequence[str]],
    inline_renderer: Callable[[str], str],
) -> str:
    headers = rows[0]
    items = [_render_field_item(headers, row, inline_renderer) for row in rows[1:]]
    return "\n\n".join(item for item in items if item)


def _render_field_item(
    headers: Sequence[str],
    row: Sequence[str],
    inline_renderer: Callable[[str], str],
) -> str:
    if not row:
        return ""

    lines: list[str] = []
    title = _render_inline_cell(row[0], inline_renderer)
    if title:
        lines.append(f"<b>{title}</b>")

    for index, cell in enumerate(row[1:], start=1):
        label = _header_label(headers, index, inline_renderer)
        value = _render_inline_cell(cell, inline_renderer)
        lines.append(f"{label}：{value}")
    return "\n".join(lines)


def _header_label(
    headers: Sequence[str],
    index: int,
    inline_renderer: Callable[[str], str],
) -> str:
    if index < len(headers):
        return _render_inline_cell(headers[index], inline_renderer)
    return f"Column {index + 1}"


def _render_inline_cell(cell: str, inline_renderer: Callable[[str], str]) -> str:
    return inline_renderer(html_escape(cell))


def _column_widths(rows: Sequence[Sequence[str]]) -> list[int]:
    n_cols = max(len(row) for row in rows)
    col_widths = [0] * n_cols
    for row in rows:
        for index, cell in enumerate(row):
            col_widths[index] = max(col_widths[index], _display_width(cell))
    return col_widths


def _display_width(text: str) -> int:
    """Approximate display width accounting for CJK double-width chars."""
    width = 0
    for ch in text:
        if east_asian_width(ch) in DOUBLE_WIDTH_CATEGORIES:
            width += 2
        else:
            width += 1
    return width
