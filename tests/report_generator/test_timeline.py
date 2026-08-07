from __future__ import annotations

from datetime import datetime, timedelta, timezone

from automation.report_generator.timeline import build_timeline


def test_build_timeline_merges_in_chronological_order(
    db_connection,
    make_incident,
):
    incident = make_incident(status="IN_PROGRESS")
    base = datetime.now(timezone.utc)

    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_events (
                incident_id,
                sequence,
                occurred_at,
                actor,
                event_type,
                message,
                payload
            )
            VALUES (%s, 1, %s, 'alertmanager', 'CREATED',
                    'Incident created', '{}')
            """,
            (incident["id"], base),
        )

        cur.execute(
            """
            INSERT INTO remediation_attempts (
                incident_id,
                playbook,
                attempt_number,
                started_at,
                finished_at,
                result
            )
            VALUES (%s, 'restart_service', 1, %s, %s, 'success')
            """,
            (
                incident["id"],
                base + timedelta(minutes=1),
                base + timedelta(minutes=1, seconds=30),
            ),
        )

        cur.execute(
            """
            INSERT INTO incident_events (
                incident_id,
                sequence,
                occurred_at,
                actor,
                event_type,
                to_status,
                message,
                payload
            )
            VALUES (%s, 2, %s, 'worker', 'STATE_CHANGE',
                    'RESOLVED', 'Resolved', '{}')
            """,
            (incident["id"], base + timedelta(minutes=2)),
        )

    timeline = build_timeline(db_connection, incident["id"])

    assert [entry.kind for entry in timeline] == [
        "event",
        "remediation_attempt",
        "event",
    ]


def test_build_timeline_breaks_simultaneous_tie_events_before_attempts(
    db_connection,
    make_incident,
):
    incident = make_incident(status="IN_PROGRESS")
    same_instant = datetime.now(timezone.utc)

    # Insert the remediation attempt first on purpose. If build_timeline()
    # merely preserves insertion order instead of applying the documented
    # tie-break, this test will fail.
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
            (incident["id"], same_instant),
        )

        cur.execute(
            """
            INSERT INTO incident_events (
                incident_id,
                sequence,
                occurred_at,
                actor,
                event_type,
                message,
                payload
            )
            VALUES (%s, 1, %s, 'worker',
                    'NOTE', 'Simultaneous event', '{}')
            """,
            (incident["id"], same_instant),
        )

    timeline = build_timeline(db_connection, incident["id"])

    assert [entry.kind for entry in timeline] == [
        "event",
        "remediation_attempt",
    ]

    assert timeline[0].payload["sequence"] == 1
    assert timeline[1].payload["attempt_number"] == 1


def test_build_timeline_breaks_tie_among_events_by_sequence(
    db_connection,
    make_incident,
):
    incident = make_incident(status="IN_PROGRESS")
    same_instant = datetime.now(timezone.utc)

    # Insert sequence=2 first so ordering must come from the explicit
    # tie-break rather than insertion order.
    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_events (
                incident_id,
                sequence,
                occurred_at,
                actor,
                event_type,
                message,
                payload
            )
            VALUES (%s, 2, %s, 'worker', 'NOTE', 'Second', '{}')
            """,
            (incident["id"], same_instant),
        )

        cur.execute(
            """
            INSERT INTO incident_events (
                incident_id,
                sequence,
                occurred_at,
                actor,
                event_type,
                message,
                payload
            )
            VALUES (%s, 1, %s, 'worker', 'NOTE', 'First', '{}')
            """,
            (incident["id"], same_instant),
        )

    timeline = build_timeline(db_connection, incident["id"])

    assert [entry.payload["sequence"] for entry in timeline] == [1, 2]


def test_build_timeline_breaks_tie_among_attempts_by_attempt_number(
    db_connection,
    make_incident,
):
    incident = make_incident(status="IN_PROGRESS")
    same_instant = datetime.now(timezone.utc)

    # Insert attempt_number=2 first so ordering must come from the explicit
    # tie-break rather than insertion order.
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
            VALUES (%s, 'restart_service', 2, %s, 'success')
            """,
            (incident["id"], same_instant),
        )

        cur.execute(
            """
            INSERT INTO remediation_attempts (
                incident_id,
                playbook,
                attempt_number,
                started_at,
                result
            )
            VALUES (%s, 'restart_service', 1, %s, 'failure')
            """,
            (incident["id"], same_instant),
        )

    timeline = build_timeline(db_connection, incident["id"])

    assert [entry.payload["attempt_number"] for entry in timeline] == [1, 2]


def test_build_timeline_empty_for_incident_with_no_activity(
    db_connection,
    make_incident,
):
    incident = make_incident(status="NEW")

    assert build_timeline(db_connection, incident["id"]) == []
