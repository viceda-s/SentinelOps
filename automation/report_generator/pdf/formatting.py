"""
Formatting helpers shared by the PDF renderer.

These helpers encapsulate common ReportLab patterns and presentation
logic so section builders remain focused on report content.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from reportlab.platypus import Flowable, Paragraph, Table

from .styles import (
    LABEL_VALUE_COL_WIDTHS,
    LABEL_VALUE_TABLE_STYLE,
    NESTED_LABEL_VALUE_COL_WIDTHS,
    styles,
)


def display(value) -> str:
    """Render an optional primitive value for display."""
    return "-" if value is None else str(value)


def format_timestamp(value: datetime | None) -> str:
    """Format an optional timestamp for the incident report."""
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_bool(value: bool | None) -> str:
    if value is None:
        return "-"
    return "Yes" if value else "No"


def format_duration(delta: timedelta | None) -> str:
    if delta is None:
        return "-"

    total_seconds = int(delta.total_seconds())
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)

    return f"{hours:d}h {minutes:02d}m {seconds:02d}s"


def label_value_table(rows: list[list], col_widths=None) -> Table:
    """
    Build a shared two-column label/value table.

    Nested tables may supply narrower column widths so they fit within the
    parent cell without overflowing the page.
    """
    table = Table(rows, colWidths=col_widths or LABEL_VALUE_COL_WIDTHS)
    table.setStyle(LABEL_VALUE_TABLE_STYLE)
    return table


def value_flowable(value, *, nested: bool = False) -> Flowable:
    """
    Render a value for insertion into a key/value table.

    Nested dictionaries become nested tables, multiline strings preserve line
    breaks using the LogText style, and all other values are rendered as
    normal report text.
    """
    if isinstance(value, dict):
        return key_value_table(value, nested=True)

    text = str(value)

    if "\n" in text:
        html_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(html_text.replace("\n", "<br/>"), styles["LogText"])

    return Paragraph(text, styles["ReportBody"])


def key_value_table(data: dict, *, nested: bool = False) -> Table:
    """
    Render a dictionary as a two-column key/value table.

    Values are converted to flowables so long text wraps correctly and nested
    dictionaries render as nested tables rather than Python reprs.
    """
    if not data:
        rows = [["-", "-"]]
    else:
        rows = [[str(key), value_flowable(v, nested=nested)] for key, v in data.items()]

    col_widths = NESTED_LABEL_VALUE_COL_WIDTHS if nested else None
    return label_value_table(rows, col_widths=col_widths)
