from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from reportlab.platypus import Paragraph, Table

from automation.report_generator.pdf import (
    build_timeline,
    render_pdf,
    write_pdf_and_record,
)
from automation.report_generator.pdf.formatting import key_value_table
from automation.report_generator.pdf.sections import build_actions_taken, build_header
from automation.report_generator.report_model import build_report_model


def test_render_pdf_returns_nonempty_pdf_bytes(
    db_connection,
    make_incident,
):
    """
    Verify that render_pdf returns valid non-empty PDF byte content starting with PDF header.
    """
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis="RCA text.",
    )

    model = build_report_model(db_connection, incident["id"])

    pdf_bytes = render_pdf(model)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_render_pdf_escapes_special_characters_in_root_cause_analysis(
    db_connection,
    make_incident,
):
    """
    Regression test for ReportLab Paragraph escaping.

    Tag-like input is interpreted as markup by ReportLab. The PDF renderer
    must escape operator-authored text before embedding it in a Paragraph.
    An unclosed tag such as "<script>" makes ReportLab's parser raise, so
    this input only passes if the renderer escapes it first -- unlike a
    closed tag pair, which ReportLab silently consumes without erroring.
    """
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis=(
            "Restarted <script>alert(1) after latency exceeded 500ms. "
            "Root cause: cache & backend both degraded when load > threshold."
        ),
    )

    model = build_report_model(db_connection, incident["id"])

    pdf_bytes = render_pdf(model)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_render_pdf_escapes_special_characters_in_alert_name(
    db_connection,
    make_incident,
):
    """
    Alert metadata is also rendered inside Paragraph flowables and must be
    escaped before rendering.
    """
    incident = make_incident(
        status="CLOSED",
        alert_name="Disk <script>alert(1) usage high",
        root_cause_analysis="RCA text.",
    )

    model = build_report_model(db_connection, incident["id"])

    pdf_bytes = render_pdf(model)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_pdf_sections_escape_markup_and_display_unfinished_remediation(
    db_connection,
    make_incident,
):
    """
    Parser-triggering <script> markup proves escaping is retained.

    Arbitrary angle-bracket text can be harmlessly consumed by ReportLab,
    whereas an unclosed tag makes Paragraph rendering fail when escaping is
    removed.
    """
    incident = make_incident(
        reference="INC-<script>",
        status="CLOSED",
        root_cause_analysis="RCA text.",
    )
    now = datetime.now(timezone.utc)

    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_events
                (incident_id, sequence, occurred_at, actor, event_type, message, payload)
            VALUES (%s, 1, %s, 'operator', 'NOTE', 'Incident <script>', '{}')
            """,
            (incident["id"], now),
        )
        cur.execute(
            """
            INSERT INTO remediation_attempts
                (incident_id, playbook, attempt_number, started_at, result)
            VALUES (%s, 'restart <script>', 1, %s, NULL)
            """,
            (incident["id"], now),
        )

    model = build_report_model(db_connection, incident["id"])

    header = build_header(model)
    assert header[2].text == "Reference: INC-&lt;script&gt;"

    key_table = key_value_table({"label<script>": "value & more"})
    assert isinstance(key_table._cellvalues[0][0], Paragraph)
    assert key_table._cellvalues[0][0].text == "label&lt;script&gt;"

    timeline = build_timeline(model)
    timeline_table = next(
        flowable for flowable in timeline if isinstance(flowable, Table)
    )
    assert isinstance(timeline_table._cellvalues[0][1], Paragraph)
    assert timeline_table._cellvalues[0][1].text == "Incident &lt;script&gt;"
    assert timeline_table._cellvalues[1][1].text == (
        "Ran restart &lt;script&gt; (result: -)"
    )

    actions = build_actions_taken(model)
    action_paragraph = actions[2]._flowables[0]._flowables[0]
    assert action_paragraph.text == "restart &lt;script&gt; (attempt 1) → -"


def test_render_pdf_renders_timeline_events_and_attempts(
    db_connection,
    make_incident,
):
    """
    Exercise both timeline entry types.

    A valid PDF only proves ReportLab serialized the document. Timeline
    content is verified by inspecting the flowables produced before
    rendering.
    """
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis="RCA text.",
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

    assert len(model.timeline) == 2

    pdf_bytes = render_pdf(model)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000

    flowables = build_timeline(model)

    paragraphs_text = " ".join(
        flowable.text for flowable in flowables if hasattr(flowable, "text")
    )

    table_text = [
        cell.text if hasattr(cell, "text") else cell
        for flowable in flowables
        if hasattr(flowable, "_cellvalues")
        for row in flowable._cellvalues
        for cell in row
    ]

    rendered_text = " ".join(
        [
            paragraphs_text,
            *table_text,
        ]
    )

    assert "CREATED" in rendered_text or "Incident created" in rendered_text
    assert "restart_service" in rendered_text
    assert "success" in rendered_text


def test_write_pdf_and_record_writes_file_and_inserts_row(
    db_connection,
    make_incident,
    tmp_path,
):
    """
    Verify that write_pdf_and_record writes PDF file to disk and inserts database report metadata.
    """
    incident = make_incident(
        status="CLOSED",
        root_cause_analysis="RCA text.",
    )

    model = build_report_model(db_connection, incident["id"])

    write_pdf_and_record(db_connection, model, tmp_path)

    report_path = tmp_path / f"{incident['reference']}.pdf"
    tmp_report_path = report_path.with_suffix(".pdf.tmp")

    assert report_path.exists()
    assert report_path.name == f"{incident['reference']}.pdf"
    assert not tmp_report_path.exists()

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
