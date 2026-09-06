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
    """Verify that new incident increments created counter."""
    alert = _firing_alert()

    before = counter_value(
        INCIDENTS_CREATED_TOTAL,
        service="api",
        severity="critical",
    )

    handle_alert(db_connection, alert, CMDB, correlation_id="test-correlation-id")

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
    """Verify that duplicate alert does not increment created counter."""
    alert = _firing_alert()

    handle_alert(db_connection, alert, CMDB, correlation_id="test-correlation-id")

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

    handle_alert(db_connection, alert, CMDB, correlation_id="test-correlation-id")

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
    """Verify that ingest alert creates new incident."""
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
    """Verify that ingest alert is policy free."""
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
    """Verify that record note event appends without changing status."""
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
    """Verify that record note event defaults payload to empty dict."""
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


def test_ingest_alert_persists_correlation_id_in_created_event_payload(
    db_connection,
    committed_incident_cleanup,
):
    """ingest_alert writes correlation_id into the CREATED event's payload when given one."""
    alert = _firing_alert()

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="webhook_handler",
        correlation_id="corr-abc-123",
    )
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT payload FROM incident_events WHERE incident_id = %s AND event_type = 'CREATED'",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert row["payload"]["correlation_id"] == "corr-abc-123"


def test_ingest_alert_omits_correlation_id_from_payload_when_not_given(
    db_connection,
    committed_incident_cleanup,
):
    """ingest_alert called without correlation_id (e.g. from maintenance.py) doesn't add the key at all."""
    alert = _firing_alert()

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="maintenance",
    )
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT payload FROM incident_events WHERE incident_id = %s AND event_type = 'CREATED'",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert "correlation_id" not in row["payload"]


def test_record_note_event_persists_correlation_id_when_given(
    db_connection, make_incident
):
    """record_note_event writes correlation_id into the NOTE event's payload when given one."""
    incident = make_incident(status="NEW")

    record_note_event(
        db_connection,
        incident,
        actor="webhook_handler",
        message="Duplicate delivery",
        payload={"detail": "example"},
        correlation_id="corr-def-456",
    )

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT payload FROM incident_events WHERE incident_id = %s AND event_type = 'NOTE'",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert row["payload"]["correlation_id"] == "corr-def-456"
    assert row["payload"]["detail"] == "example"  # original payload keys preserved


def test_record_note_event_omits_correlation_id_from_payload_when_not_given(
    db_connection, make_incident
):
    """record_note_event called without correlation_id (e.g. from maintenance.py) doesn't add the key."""
    incident = make_incident(status="NEW")

    record_note_event(
        db_connection,
        incident,
        actor="maintenance",
        message="Silence reconciliation note",
        payload={"detail": "example"},
    )

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT payload FROM incident_events WHERE incident_id = %s AND event_type = 'NOTE'",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert "correlation_id" not in row["payload"]


def test_correlation_id_is_queryable_via_its_expression_index(
    db_connection, committed_incident_cleanup
):
    """A CREATED event can be found directly by its correlation_id via incident_events_correlation_id_idx."""
    alert = _firing_alert()

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="webhook_handler",
        correlation_id="corr-findme-789",
    )
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT incident_id FROM incident_events WHERE payload ->> 'correlation_id' = %s",
            ("corr-findme-789",),
        )
        rows = cur.fetchall()

    assert len(rows) == 1
    assert rows[0]["incident_id"] == incident["id"]


def test_duplicate_delivery_records_its_own_correlation_id_without_touching_the_original(
    db_connection, committed_incident_cleanup
):
    """A second webhook delivery for the same open incident's fingerprint gets its own correlation_id on the NOTE event; the CREATED event's original correlation_id is untouched."""
    from automation.response_engine.handlers import _reconcile_duplicate_alert

    alert = _firing_alert()

    incident = ingest_alert(
        db_connection,
        alert,
        CMDB,
        source="webhook_handler",
        correlation_id="corr-original-111",
    )
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])

    _reconcile_duplicate_alert(
        db_connection, alert, alert["fingerprint"], correlation_id="corr-retry-222"
    )
    # No db_connection.commit() here -- _reconcile_duplicate_alert manages its own transaction (rollback at start, commit at end).

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, payload
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence
            """,
            (incident["id"],),
        )
        events = cur.fetchall()

    assert len(events) == 2
    assert events[0]["event_type"] == "CREATED"
    assert events[0]["payload"]["correlation_id"] == "corr-original-111"
    assert events[1]["event_type"] == "NOTE"
    assert events[1]["payload"]["correlation_id"] == "corr-retry-222"


def test_record_note_event_persists_silence_id(db_connection, make_incident):
    """Verify that record note event persists silence id."""
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
    """Verify that record note event defaults silence id to null."""
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
    """Verify that record note event rejects duplicate silence id."""
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


def test_reconcile_duplicate_alert_raises_when_no_active_incident_exists(
    db_connection,
):
    """Verify that _reconcile_duplicate_alert raises RuntimeError when no active incident exists."""
    from automation.response_engine.handlers import _reconcile_duplicate_alert

    alert = _firing_alert()
    alert["fingerprint"] = "non-existent-fingerprint-12345"

    with pytest.raises(
        RuntimeError, match="Cannot resolve incident: no active incident exists"
    ):
        _reconcile_duplicate_alert(
            db_connection,
            alert,
            alert["fingerprint"],
            correlation_id="test-correlation-id",
        )


def test_reconcile_duplicate_alert_appends_note_with_webhook_actor(
    db_connection, committed_incident_cleanup, make_incident
):
    """Verify that _reconcile_duplicate_alert Appends NOTE event using actor 'webhook_handler'."""
    from automation.response_engine.handlers import _reconcile_duplicate_alert

    alert = _firing_alert()
    incident = make_incident(
        fingerprint=alert["fingerprint"],
        status="NEW",
    )
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])

    _reconcile_duplicate_alert(
        db_connection, alert, alert["fingerprint"], correlation_id="test-correlation-id"
    )

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT actor, event_type, message
            FROM incident_events
            WHERE incident_id = %s
            """,
            (incident["id"],),
        )
        events = cur.fetchall()

    assert len(events) == 1
    assert events[0]["actor"] == "webhook_handler"
    assert events[0]["event_type"] == "NOTE"
    assert events[0]["message"] == "Duplicate Alertmanager notification received"
