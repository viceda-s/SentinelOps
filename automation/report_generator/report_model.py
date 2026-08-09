"""
Report model data structures and builders for SentinelOps incident reports.

Assembles incident metadata, chronological timeline entries, and diagnostic JSON payloads
into structured `ReportModel` instances for PDF generation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from automation.report_generator.timeline import (
    TimelineEntry,
    build_timeline,
)

DIAGNOSTICS_FILE_MISSING_REASON = (
    "Diagnostics were collected but the file could not be read."
)
DIAGNOSTICS_UNAVAILABLE_REASON = (
    "No diagnostics playbook was executed for this incident."
)


@dataclass(slots=True)
class ReportModel:
    """
    Data model representing a complete incident report for PDF generation.

    Attributes:
        incident: Incident row dictionary from database.
        timeline: List of chronological `TimelineEntry` objects.
        diagnostics: Parsed diagnostics JSON dictionary, or None if unavailable.
        diagnostics_unavailable_reason: Human-readable reason string if diagnostics is None.
    """

    incident: dict[str, Any]
    timeline: list[TimelineEntry]
    diagnostics: dict[str, Any] | None
    diagnostics_unavailable_reason: str | None


def _find_diagnostics_path(conn, incident_id: int) -> str | None:
    """
    Query database for the most recent diagnostics_path for an incident.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT diagnostics_path
            FROM remediation_attempts
            WHERE incident_id = %s
                AND diagnostics_path IS NOT NULL
            ORDER BY attempt_number DESC
            LIMIT 1
            """,
            (incident_id,),
        )

        row = cur.fetchone()

    return None if row is None else row["diagnostics_path"]


def build_report_model(conn, incident_id: int) -> ReportModel:
    """
    Build a complete `ReportModel` instance for a given incident ID.

    Queries incident details, constructs the unified timeline from `incident_events` and
    `remediation_attempts`, and loads diagnostic JSON payloads if available.

    Args:
        conn: Active PostgreSQL connection with RealDictCursor.
        incident_id: Database integer primary key of the incident.

    Returns:
        ReportModel: Assembled report model dataclass.

    Raises:
        ValueError: If no incident matching incident_id exists in the database.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incidents
            WHERE id = %s
            """,
            (incident_id,),
        )

        incident = cur.fetchone()

    if incident is None:
        raise ValueError(f"Incident {incident_id} not found.")

    timeline = build_timeline(conn, incident_id)

    diagnostics_path = _find_diagnostics_path(conn, incident_id)

    diagnostics: dict[str, Any] | None
    diagnostics_unavailable_reason: str | None

    if diagnostics_path is None:
        diagnostics = None
        diagnostics_unavailable_reason = DIAGNOSTICS_UNAVAILABLE_REASON
    else:
        try:
            with open(diagnostics_path, encoding="utf-8") as f:
                diagnostics = json.load(f)

            diagnostics_unavailable_reason = None

        except FileNotFoundError:
            diagnostics = None
            diagnostics_unavailable_reason = DIAGNOSTICS_FILE_MISSING_REASON

    return ReportModel(
        incident=incident,
        timeline=timeline,
        diagnostics=diagnostics,
        diagnostics_unavailable_reason=diagnostics_unavailable_reason,
    )
