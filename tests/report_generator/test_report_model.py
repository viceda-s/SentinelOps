from __future__ import annotations

import json
from datetime import datetime, timezone

from automation.report_generator.report_model import (
    DIAGNOSTICS_FILE_MISSING_REASON,
    DIAGNOSTICS_UNAVAILABLE_REASON,
    build_report_model,
)


def test_build_report_model_diagnostics_unavailable_when_not_collected(
    db_connection, make_incident
):
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=("Log rotation misconfiguration."),
    )

    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO remediation_attempts (
                incident_id,
                playbook,
                attempt_number,
                started_at,
                result
            )
            VALUES (%s, 'restart_service', 1, %s, 'success')
            """,
            (incident["id"], datetime.now(timezone.utc)),
        )

    model = build_report_model(db_connection, incident["id"])

    assert model.diagnostics is None
    assert model.diagnostics_unavailable_reason == DIAGNOSTICS_UNAVAILABLE_REASON


def test_build_report_model_diagnostics_file_missing_on_disk(
    db_connection, make_incident, tmp_path
):
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=("Disk pressure."),
    )

    diagnostics_path = tmp_path / f"{incident['reference']}-attempt-1.json"
    # Deliberately never written -- the DB references a path with nothing
    # on disk at it, simulating the file being deleted/moved after
    # collection.

    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO remediation_attempts (
                incident_id,
                playbook,
                attempt_number,
                started_at,
                result,
                diagnostics_path
            )
            VALUES (
                %s,
                'collect_diagnostics',
                1,
                %s,
                'success',
                %s
            )
            """,
            (
                incident["id"],
                datetime.now(timezone.utc),
                str(diagnostics_path),
            ),
        )

    model = build_report_model(db_connection, incident["id"])

    assert model.diagnostics is None
    assert model.diagnostics_unavailable_reason == DIAGNOSTICS_FILE_MISSING_REASON


def test_build_report_model_includes_diagnostics_when_collected(
    db_connection, make_incident, tmp_path
):
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=("Disk pressure."),
    )

    diagnostics_path = tmp_path / f"{incident['reference']}-attempt-1.json"
    diagnostics_path.write_text(
        json.dumps(
            {
                "logs": "some log lines",
                "stats": {"cpu": 0.5},
            }
        ),
        encoding="utf-8",
    )

    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO remediation_attempts (
                incident_id,
                playbook,
                attempt_number,
                started_at,
                result,
                diagnostics_path
            )
            VALUES (
                %s,
                'collect_diagnostics',
                1,
                %s,
                'success',
                %s
            )
            """,
            (
                incident["id"],
                datetime.now(timezone.utc),
                str(diagnostics_path),
            ),
        )

    model = build_report_model(db_connection, incident["id"])

    assert model.diagnostics == {"logs": "some log lines", "stats": {"cpu": 0.5}}
    assert model.diagnostics_unavailable_reason is None


def test_build_report_model_includes_timeline(db_connection, make_incident):
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=("RCA text."),
    )

    model = build_report_model(db_connection, incident["id"])

    # Timeline ordering is covered by Task 4. Here we only verify that build_report_model() delegates and exposes the resulting timeline.
    assert model.timeline == []
    assert model.incident["reference"] == incident["reference"]


def test_build_report_model_pending_rca_when_null(db_connection, make_incident):
    incident = make_incident(status="RESOLVED")

    with db_connection.cursor() as cur:
        cur.execute(
            """
                UPDATE incidents
                SET status = 'CLOSED'
                WHERE id = %s
                """,
            (incident["id"],),
        )

    model = build_report_model(db_connection, incident["id"])

    assert model.incident["root_cause_analysis"] is None
