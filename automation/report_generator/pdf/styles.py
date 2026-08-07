"""
Shared ReportLab styles and layout constants for incident reports.

Centralizing typography, spacing, and table styles keeps the PDF renderer
visually consistent and avoids duplicating presentation details across
section builders.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import TableStyle

styles = getSampleStyleSheet()

styles.add(
    ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1a1a1a"),
        spaceAfter=2,
    )
)
styles.add(
    ParagraphStyle(
        name="ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#444444"),
    )
)
styles.add(
    ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        spaceBefore=4,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a1a"),
    )
)
styles.add(
    ParagraphStyle(
        name="SubHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        spaceBefore=6,
        spaceAfter=3,
        textColor=colors.HexColor("#333333"),
    )
)
styles.add(
    ParagraphStyle(
        name="ReportBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
    )
)
styles.add(
    ParagraphStyle(
        name="RCABody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
    )
)
styles.add(
    ParagraphStyle(
        name="LogText",
        parent=styles["Code"],
        fontSize=8.5,
        leading=11,
    )
)

# Shared style for the report's two-column label/value tables.
LABEL_VALUE_TABLE_STYLE = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f2f2")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
)

# Sized to accommodate the widest labels used in the report.
LABEL_VALUE_COL_WIDTHS = [2.0 * inch, 4.0 * inch]

# Reduced widths so nested tables fit within a parent value cell.
NESTED_LABEL_VALUE_COL_WIDTHS = [1.6 * inch, 2.2 * inch]

# Timestamp and description columns for the incident timeline.
TIMELINE_COL_WIDTHS = [1.9 * inch, 4.1 * inch]


def timeline_table_style(row_count: int) -> TableStyle:
    """Build the timeline table style with alternating row shading."""
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_index in range(row_count):
        if row_index % 2 == 1:
            commands.append(
                (
                    "BACKGROUND",
                    (0, row_index),
                    (-1, row_index),
                    colors.HexColor("#f7f7f7"),
                )
            )
    return TableStyle(commands)


SECTION_SPACER_HEIGHT = 10
