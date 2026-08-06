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
    incident: dict[str, Any]
    timeline: list[TimelineEntry]
    diagnostics: dict[str, Any] | None
    diagnostics_unavailable_reason: str | None


def _find_diagnostics_path(conn, incident_id: int) -> str | None:
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
