import psycopg2
import pytest

from automation.response_engine.handlers import (
    handle_alert,
    ingest_alert,
    record_note_event,
)
from automation.response_engine.metrics import INCIDENTS_CREATED_TOTAL
from tests.response_engine.helpers import (
    CMDB,
    _firing_alert,
    counter_value,
)


def test_new_incident_increments_created_counter(
    db_connection, committed_incident_cleanup
):
    alert = _firing_alert()

    before = counter_value(
        INCIDENTS_CREATED_TOTAL,
        service="api",
        severity="critical",
    )

    handle_alert(db_connection, alert, CMDB)

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT id FROM incidents WHERE fingerprint = %s",
            (alert["fingerprint"],),
        )
        committed_incident_cleanup.append(cur.fetchone()["id"])

    after = counter_value(
        INCIDENTS_CREATED_TOTAL,
        service="api",
        severity="critical",
    )

    assert after == before + 1

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incidents
            WHERE fingerprint = %s
            """,
            (alert["fingerprint"],),
        )

        assert cur.fetchone()["count"] == 1


def test_duplicate_alert_does_not_increment_created_counter(
    db_connection, committed_incident_cleanup
):
    alert = _firing_alert()

    handle_alert(db_connection, alert, CMDB)

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT id FROM incidents WHERE fingerprint = %s",
            (alert["fingerprint"],),
        )
        committed_incident_cleanup.append(cur.fetchone()["id"])

    before = counter_value(
        INCIDENTS_CREATED_TOTAL,
        service="api",
        severity="critical",
    )

    handle_alert(db_connection, alert, CMDB)

    after = counter_value(
        INCIDENTS_CREATED_TOTAL,
        service="api",
        severity="critical",
    )

    assert after == before

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM incidents
            WHERE fingerprint = %s
            """,
            (alert["fingerprint"],),
        )

        incident = cur.fetchone()

        assert incident is not None

        cur.execute(
            """
            SELECT actor, event_type
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence
            """,
            (incident["id"],),
        )

        events = cur.fetchall()

        assert len(events) == 2

        # Regression test: both the CREATED event and the duplicate-
        # notification NOTE event must agree on which component recorded
        # them. Before this fix, CREATED used the caller-supplied source
        # ("webhook_handler") while the NOTE branch hardcoded the literal
        # "alertmanager", so one incident's timeline could show two
        # different actors for events written by the same process.
        assert events[0]["actor"] == "webhook_handler"
        assert events[1]["actor"] == "webhook_handler"


def test_ingest_alert_creates_new_incident(
    db_connection,
    committed_incident_cleanup,
):
    alert = _firing_alert()

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="maintenance",
    )

    db_connection.commit()

    committed_incident_cleanup.append(incident["id"])

    assert incident["status"] == "NEW"

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence
            """,
            (incident["id"],),
        )

        events = cur.fetchall()

    assert len(events) == 1
    assert events[0]["event_type"] == "CREATED"
    assert events[0]["actor"] == "maintenance"


def test_ingest_alert_is_policy_free(
    db_connection,
    committed_incident_cleanup,
):
    alert = _firing_alert()

    alert["labels"]["job"] = "unknown-service"

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="maintenance",
    )

    db_connection.commit()

    committed_incident_cleanup.append(incident["id"])

    assert incident["status"] == "NEW"


def test_record_note_event_appends_without_changing_status(
    db_connection,
    committed_incident_cleanup,
):
    alert = _firing_alert()

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="webhook_handler",
    )
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])

    record_note_event(
        db_connection,
        incident,
        actor="worker",
        message="Some informational note.",
        payload={"detail": "example"},
    )
    db_connection.commit()

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT status FROM incidents WHERE id = %s",
            (incident["id"],),
        )
        assert cur.fetchone()["status"] == "NEW"

        cur.execute(
            """
            SELECT sequence, actor, event_type, message
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence
            """,
            (incident["id"],),
        )
        events = cur.fetchall()

    assert len(events) == 2
    assert events[0]["event_type"] == "CREATED"
    assert events[1]["event_type"] == "NOTE"
    assert events[1]["sequence"] == 2
    assert events[1]["actor"] == "worker"
    assert events[1]["message"] == "Some informational note."


def test_record_note_event_defaults_payload_to_empty_dict(
    db_connection,
    committed_incident_cleanup,
):
    alert = _firing_alert()

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="webhook_handler",
    )
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])

    record_note_event(
        db_connection,
        incident,
        actor="worker",
        message="No payload supplied.",
    )
    db_connection.commit()

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT payload
            FROM incident_events
            WHERE incident_id = %s
              AND event_type = 'NOTE'
            """,
            (incident["id"],),
        )
        assert cur.fetchone()["payload"] == {}


def test_record_note_event_persists_silence_id(db_connection, make_incident):
    incident = make_incident(status="IN_PROGRESS")

    record_note_event(
        db_connection,
        incident,
        actor="maintenance",
        message="Alert also matched an active maintenance window (silence sil-abc).",
        payload={"fingerprint": "abc"},
        silence_id="sil-abc",
    )

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT silence_id, event_type, actor
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (incident["id"],),
        )
        event = cur.fetchone()

    assert event["silence_id"] == "sil-abc"
    assert event["event_type"] == "NOTE"
    assert event["actor"] == "maintenance"


def test_record_note_event_defaults_silence_id_to_null(db_connection, make_incident):
    # The webhook duplicate-notification path passes no silence_id. Those rows
    # must stay outside the partial unique index so that path keeps recording a
    # NOTE per duplicate notification.
    incident = make_incident(status="IN_PROGRESS")

    record_note_event(
        db_connection,
        incident,
        actor="webhook_handler",
        message="Duplicate Alertmanager notification received",
    )

    record_note_event(
        db_connection,
        incident,
        actor="webhook_handler",
        message="Duplicate Alertmanager notification received",
    )

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incident_events
            WHERE incident_id = %s
              AND event_type = 'NOTE'
              AND silence_id IS NULL
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["count"] == 2


def test_record_note_event_rejects_duplicate_silence_id(db_connection, make_incident):
    # The database, not application logic, is what makes the invariant true.
    incident = make_incident(status="IN_PROGRESS")

    record_note_event(
        db_connection,
        incident,
        actor="maintenance",
        message="Alert also matched an active maintenance window (silence sil-dup).",
        silence_id="sil-dup",
    )

    with pytest.raises(psycopg2.errors.UniqueViolation) as excinfo:
        record_note_event(
            db_connection,
            incident,
            actor="maintenance",
            message="Alert also matched an active maintenance window (silence sil-dup).",
            silence_id="sil-dup",
        )

    assert (
        excinfo.value.diag.constraint_name == "incident_events_maintenance_silence_idx"
    )
