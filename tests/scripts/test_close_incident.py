from datetime import datetime, timezone

import pytest

from automation.scripts.close_incident import close_incident


def test_close_incident_success(db_connection, make_incident):
    incident = make_incident(
        status="RESOLVED",
        resolved_at=datetime.now(timezone.utc),
    )

    updated = close_incident(
        db_connection,
        incident["reference"],
        "Root cause analysis",
    )

    assert updated["status"] == "CLOSED"
    assert updated["root_cause_analysis"] == "Root cause analysis"

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, to_status, actor, message
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (incident["id"],),
        )

        event = cur.fetchone()

    assert event["event_type"] == "STATE_CHANGE"
    assert event["to_status"] == "CLOSED"
    assert event["actor"] == "operator"
    assert event["message"] == "Incident closed"


def test_close_incident_unknown_reference(db_connection, make_incident):
    with pytest.raises(ValueError, match="INC-DOES-NOT-EXIST"):
        close_incident(db_connection, "INC-DOES-NOT-EXIST", "RCA")


def test_close_incident_requires_resolved_state(db_connection, make_incident):
    incident = make_incident(status="NEW")

    with pytest.raises(ValueError, match="NEW"):
        close_incident(db_connection, incident["reference"], "RCA")

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT status, root_cause_analysis FROM incidents WHERE id = %s",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert row["status"] == "NEW"
    assert row["root_cause_analysis"] is None


def test_close_incident_does_not_commit_transaction(db_connection, make_incident):
    incident = make_incident(
        status="RESOLVED",
        resolved_at=datetime.now(timezone.utc),
    )

    # Commit the fixture's insert so it survives this test's rollback().
    # This test verifies that close_incident() does not commit its own transaction, so it needs a durable "before" state to roll back to.
    db_connection.commit()

    close_incident(
        db_connection,
        incident["reference"],
        "Root cause analysis",
    )

    db_connection.rollback()

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT status, root_cause_analysis
            FROM incidents
            WHERE id = %s
            """,
            (incident["id"],),
        )

        row = cur.fetchone()

    assert row["status"] == "RESOLVED"
    assert row["root_cause_analysis"] is None

    # This test commits its setup row so it survives the rollback under test.
    # Because the fixture's teardown rollback can no longer remove it, clean it up explicitly so the test remains repeatable.
    with db_connection.cursor() as cur:
        cur.execute("DELETE FROM incidents WHERE id = %s", (incident["id"],))
    db_connection.commit()
