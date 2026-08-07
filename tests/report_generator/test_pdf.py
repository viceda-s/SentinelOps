from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from automation.report_generator.pdf import (
    build_timeline,
    render_pdf,
    write_pdf_and_record,
)
from automation.report_generator.report_model import build_report_model


def test_render_pdf_returns_nonempty_pdf_bytes(db_connection, make_incident):
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=("RCA text."),
    )

    model = build_report_model(db_connection, incident["id"])

    pdf_bytes = render_pdf(model)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_render_pdf_renders_timeline_with_events_and_attempts(
    db_connection, make_incident
):
    # Exercises both branches of render_pdf()'s timeline loop -- an empty
    # timeline (the other render test) never runs this code at all, which
    # let two real bugs (accidental tuples passed to Paragraph()) ship
    # despite the "nonempty PDF bytes" test passing.
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=("RCA text."),
    )
    now = datetime.now(timezone.utc)

    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_events
                (incident_id, sequence, occurred_at, actor, event_type, message, payload)
            VALUES (%s, 1, %s, 'alertmanager', 'CREATED', 'Incident created', '{}')
            """,
            (incident["id"], now),
        )
        cur.execute(
            """
            INSERT INTO remediation_attempts
                (incident_id, playbook, attempt_number, started_at, result)
            VALUES (%s, 'restart_service', 1, %s, 'success')
            """,
            (incident["id"], now),
        )

    model = build_report_model(db_connection, incident["id"])
    assert len(model.timeline) == 2  # sanity: both branches will run

    pdf_bytes = render_pdf(model)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000

    # A valid PDF only proves ReportLab serialized the document. Timeline content is verified by inspecting the flowables produced by build_timeline(), which catches regressions before rendering (for example, accidentally skipping the iteration over model.timeline).
    flowables = build_timeline(model)

    heading_text = " ".join(
        flowable.text for flowable in flowables if hasattr(flowable, "text")
    )
    table_cells = [
        cell
        for flowable in flowables
        if hasattr(flowable, "_cellvalues")
        for row in flowable._cellvalues
        for cell in row
    ]
    rendered_text = heading_text + " " + " ".join(table_cells)

    assert "CREATED" in rendered_text or "Incident created" in rendered_text
    assert "restart_service" in rendered_text
    assert "success" in rendered_text


def test_write_pdf_and_record_writes_file_and_insert_row(
    db_connection, make_incident, tmp_path
):
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=("RCA text."),
    )

    model = build_report_model(db_connection, incident["id"])

    write_pdf_and_record(db_connection, model, tmp_path)

    report_path = tmp_path / f"{incident['reference']}.pdf"
    tmp_path_marker = report_path.with_suffix(".pdf.tmp")

    assert report_path.exists()
    assert report_path.name == f"{incident['reference']}.pdf"
    assert not tmp_path_marker.exists()

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incident_reports
            WHERE incident_id = %s
            """,
            (incident["id"],),
        )

        row = cur.fetchone()

    assert row is not None
    assert row["path"] == str(report_path)
    assert row["generated_at"] is not None

    actual_checksum = hashlib.sha256(report_path.read_bytes()).hexdigest()

    assert row["checksum"] == actual_checksum
