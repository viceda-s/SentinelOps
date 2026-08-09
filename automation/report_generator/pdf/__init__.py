"""
PDF rendering package for SentinelOps incident reports.

Provides functions for rendering `ReportModel` instances to PDF byte streams using ReportLab,
atomically publishing PDF files to disk, and recording SHA-256 checksums in PostgreSQL.
"""

from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Flowable, KeepTogether, SimpleDocTemplate

from ..report_model import ReportModel
from .sections import (
    build_actions_taken,
    build_detection_details,
    build_diagnostic_evidence,
    build_header,
    build_incident_information,
    build_recovery_sla,
    build_root_cause_analysis,
    build_timeline,
)

__all__ = ["build_timeline", "render_pdf", "write_pdf_and_record"]


def render_pdf(model: ReportModel) -> bytes:
    """
    Render an incident report to PDF.

    Section builders are intentionally pure: they return flat lists of
    ReportLab flowables with no pagination policy. Pagination is applied
    here by grouping each section with KeepTogether before assembling the
    document.
    """

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
    )

    section_builders = (
        build_incident_information,
        build_detection_details,
        build_timeline,
        build_actions_taken,
        build_diagnostic_evidence,
        build_recovery_sla,
        build_root_cause_analysis,
    )

    story: list[Flowable] = []
    story.extend(build_header(model))
    for builder in section_builders:
        story.append(KeepTogether(builder(model)))

    doc.build(story)

    return buffer.getvalue()


def write_pdf_and_record(conn, model: ReportModel, reports_dir: Path) -> None:
    """
    Render, atomically write, and record an incident report.

    The caller owns the database transaction. This function never commits or
    rolls back. Reports are written crash-safely by rendering to a temporary
    file, atomically replacing the final path, then recording the report in
    incident_reports.
    """

    reports_dir.mkdir(parents=True, exist_ok=True)

    reference = model.incident["reference"]

    final_path = reports_dir / f"{reference}.pdf"
    tmp_path = reports_dir / f"{reference}.pdf.tmp"

    pdf_bytes = render_pdf(model)

    with tmp_path.open("wb") as f:
        f.write(pdf_bytes)
        f.flush()
        os.fsync(f.fileno())

    tmp_path.replace(final_path)

    checksum = hashlib.sha256(pdf_bytes).hexdigest()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_reports (
                incident_id,
                generated_at,
                path,
                checksum
            )
            VALUES (%s, NOW(), %s, %s)
            """,
            (
                model.incident["id"],
                str(final_path),
                checksum,
            ),
        )
