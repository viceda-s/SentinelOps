import os
import threading
import time
from unittest.mock import patch

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from automation.response_engine.events import (
    IncidentAcknowledged,
    IncidentCreated,
    StateChanged,
    get_next_sequence,
    record_event,
)
from tests.conftest import required_env


def _connect_test_db():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=required_env("POSTGRES_DB"),
        user=required_env("POSTGRES_USER"),
        password=required_env("POSTGRES_PASSWORD"),
        options="-c statement_timeout=5000",
        cursor_factory=RealDictCursor,
    )


def test_get_next_sequence_empty_history(db_connection, make_incident):
    """Verify that get_next_sequence returns 1 for an incident with no events."""
    incident = make_incident()
    seq = get_next_sequence(db_connection, incident["id"])
    assert seq == 1


def test_get_next_sequence_existing_history(db_connection, make_incident):
    """Verify that get_next_sequence returns MAX(sequence) + 1 for an incident with events."""
    incident = make_incident()

    with db_connection.cursor() as cur:
        for s in (1, 2, 3):
            cur.execute(
                """
                INSERT INTO incident_events (
                    incident_id, sequence, occurred_at, actor, event_type, message, payload
                )
                VALUES (%s, %s, NOW(), 'test', 'NOTE', 'test note', '{}')
                """,
                (incident["id"], s),
            )

    seq = get_next_sequence(db_connection, incident["id"])
    assert seq == 4


def test_get_next_sequence_missing_incident(db_connection):
    """Verify that get_next_sequence raises ValueError when incident does not exist."""
    with pytest.raises(ValueError, match="Incident 999999 does not exist"):
        get_next_sequence(db_connection, 999999)


def test_record_event_persists_typed_event(db_connection, make_incident):
    """Verify that record_event() inserts a row matching the typed event's fields."""
    incident = make_incident()
    event = IncidentCreated(
        actor="webhook",
        message="ServiceDown received",
        payload={"foo": "bar"},
    )

    record_event(db_connection, incident["id"], event)

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT * FROM incident_events WHERE incident_id = %s",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert row["sequence"] == 1
    assert row["actor"] == "webhook"
    assert row["event_type"] == "CREATED"
    assert row["message"] == "ServiceDown received"
    assert row["payload"] == {"foo": "bar"}
    assert row["from_status"] is None
    assert row["to_status"] is None


def test_record_event_persists_state_changed_with_statuses(
    db_connection, make_incident
):
    """Verify that record_event() persists from_status/to_status for StateChanged."""
    incident = make_incident()
    event = StateChanged(
        actor="worker",
        message="Escalating",
        from_status="IN_PROGRESS",
        to_status="ESCALATED",
    )

    record_event(db_connection, incident["id"], event)

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT * FROM incident_events WHERE incident_id = %s",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert row["event_type"] == "STATE_CHANGE"
    assert row["from_status"] == "IN_PROGRESS"
    assert row["to_status"] == "ESCALATED"


def test_incident_acknowledged_event_type_is_state_changed(
    db_connection, make_incident
):
    """Verify that IncidentAcknowledged persists as event_type STATE_CHANGE for compatibility."""
    incident = make_incident()
    event = IncidentAcknowledged(
        actor="operator",
        message="Ack'd",
        from_status="NEW",
        to_status="ACKNOWLEDGED",
    )

    record_event(db_connection, incident["id"], event)

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT * FROM incident_events WHERE incident_id = %s",
            (incident["id"],),
        )
        row = cur.fetchone()

    assert row["event_type"] == "STATE_CHANGE"
    assert row["to_status"] == "ACKNOWLEDGED"


def test_concurrent_event_sequence_generation(
    db_connection, make_incident, committed_incident_cleanup
):
    """Verify that concurrent event allocation produces unique sequential events while Thread A holds the incident row lock."""
    incident = make_incident(status="NEW")
    db_connection.commit()
    committed_incident_cleanup.append(incident["id"])
    incident_id = incident["id"]

    allocated_sequences = []
    errors = []

    thread_a_locked = threading.Event()
    release_thread_a = threading.Event()

    def thread_a_worker():
        conn = _connect_test_db()
        try:
            seq = get_next_sequence(conn, incident_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO incident_events (
                        incident_id, sequence, occurred_at, actor, event_type, message, payload
                    ) VALUES (%s, %s, NOW(), 'worker_a', 'NOTE', 'event A', '{}')
                    """,
                    (incident_id, seq),
                )
            thread_a_locked.set()
            release_thread_a.wait(timeout=5.0)
            conn.commit()
            allocated_sequences.append(seq)
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            errors.append(e)
        finally:
            conn.close()

    def thread_b_worker():
        conn = _connect_test_db()
        try:
            thread_a_locked.wait(timeout=5.0)
            seq = get_next_sequence(conn, incident_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO incident_events (
                        incident_id, sequence, occurred_at, actor, event_type, message, payload
                    ) VALUES (%s, %s, NOW(), 'worker_b', 'NOTE', 'event B', '{}')
                    """,
                    (incident_id, seq),
                )
            conn.commit()
            allocated_sequences.append(seq)
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            errors.append(e)
        finally:
            conn.close()

    t_a = threading.Thread(target=thread_a_worker)
    t_b = threading.Thread(target=thread_b_worker)

    t_a.start()
    t_b.start()

    assert thread_a_locked.wait(timeout=5.0), (
        "Thread A failed to acquire the incident lock"
    )
    time.sleep(0.1)

    release_thread_a.set()

    t_a.join(timeout=5.0)
    t_b.join(timeout=5.0)

    assert not t_a.is_alive(), "Thread A did not complete in time"
    assert not t_b.is_alive(), "Thread B did not complete in time"

    assert len(errors) == 0
    assert sorted(allocated_sequences) == [1, 2]


def test_callers_delegate_to_get_next_sequence(
    db_connection, make_incident, committed_incident_cleanup
):
    """Verify state_machine, handlers, and sla delegate sequence calculation to get_next_sequence using separate incidents."""
    from automation.response_engine import handlers, sla, state_machine

    incident_sm = make_incident(status="NEW")
    incident_h = make_incident(status="NEW")
    incident_sla = make_incident(
        status="NEW",
        sla_response_minutes=-1,
    )
    db_connection.commit()
    committed_incident_cleanup.extend(
        [incident_sm["id"], incident_h["id"], incident_sla["id"]]
    )

    with patch(
        "automation.response_engine.state_machine.record_event",
    ) as mock_sm:
        state_machine.transition(
            db_connection, incident_sm, "ACKNOWLEDGED", "worker", "test"
        )
        mock_sm.assert_called_once()
        call_args = mock_sm.call_args.args
        assert call_args[0] is db_connection
        assert call_args[1] == incident_sm["id"]

    with patch(
        "automation.response_engine.handlers.get_next_sequence", return_value=2
    ) as mock_h:
        handlers.record_note_event(
            db_connection, incident_h, actor="test", message="test note"
        )
        mock_h.assert_called_once_with(db_connection, incident_h["id"])

    with patch(
        "automation.response_engine.sla.record_event",
    ) as mock_sla:
        sla._check_one(
            db_connection,
            sla._RESPONSE_BREACH_SQL,
            "response",
            "SLA response time breached",
        )
        assert mock_sla.call_count >= 1
        call_args_list = [c.args for c in mock_sla.call_args_list]
        assert any(args[1] == incident_sla["id"] for args in call_args_list)

    db_connection.rollback()
