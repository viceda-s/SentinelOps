from unittest.mock import Mock, patch

import psycopg2
import pytest
import requests

from automation.response_engine.maintenance import (
    fetch_suppressed_alerts,
    process_suppressed_alert,
)
from automation.response_engine.metrics import (
    SUPPRESSED_INCIDENTS_CREATED_TOTAL,
)
from tests.response_engine.helpers import (
    CMDB,
    _firing_alert,
    _suppressed_alert,
    counter_value,
)


@patch("automation.response_engine.maintenance.requests.get")
def test_fetch_suppressed_alerts_sorts_by_starts_at(mock_get):
    """Verify that fetch suppressed alerts sorts by starts at."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {
            "fingerprint": "b",
            "startsAt": "2026-08-07T10:00:00Z",
        },
        {
            "fingerprint": "a",
            "startsAt": "2026-08-07T09:00:00Z",
        },
    ]

    mock_get.return_value = response

    alerts = fetch_suppressed_alerts("http://alertmanager")

    assert [alert["fingerprint"] for alert in alerts] == [
        "a",
        "b",
    ]


@patch("automation.response_engine.maintenance.requests.get")
def test_fetch_suppressed_alerts_sorts_chronologically_not_lexicographically(mock_get):
    # Regression test: Alertmanager's Go RFC3339Nano marshaling trims
    # trailing zero fractional digits, so alerts in the same response can
    # have different sub-second precision. "10:00:00.5Z" is chronologically
    # after "10:00:00Z", but sorts before it as a raw string, since "." is
    # less than "Z" in ASCII.
    """Verify that fetch suppressed alerts sorts chronologically not lexicographically."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {
            "fingerprint": "later",
            "startsAt": "2026-08-07T10:00:00.5Z",
        },
        {
            "fingerprint": "earlier",
            "startsAt": "2026-08-07T10:00:00Z",
        },
    ]

    mock_get.return_value = response

    alerts = fetch_suppressed_alerts("http://alertmanager")

    assert [alert["fingerprint"] for alert in alerts] == [
        "earlier",
        "later",
    ]


@patch("automation.response_engine.maintenance.requests.get")
def test_fetch_suppressed_alerts_propagates_request_failures(mock_get):
    """Verify that fetch suppressed alerts propagates request failures."""
    mock_get.side_effect = requests.exceptions.RequestException("boom")

    try:
        fetch_suppressed_alerts("http://alertmanager")
    except requests.exceptions.RequestException:
        pass
    else:
        raise AssertionError("Expected RequestException to propagate.")


def test_process_suppressed_alert_creates_suppressed_incident(
    db_connection,
    committed_incident_cleanup,
):
    """Verify that process suppressed alert creates suppressed incident."""
    alert = _firing_alert()

    before = counter_value(SUPPRESSED_INCIDENTS_CREATED_TOTAL)

    incident = process_suppressed_alert(
        db_connection,
        alert,
        CMDB,
    )

    db_connection.commit()

    committed_incident_cleanup.append(incident["id"])

    after = counter_value(SUPPRESSED_INCIDENTS_CREATED_TOTAL)

    assert incident["status"] == "SUPPRESSED_MAINTENANCE"
    assert after == before + 1


def test_process_suppressed_alert_deduplicates(
    db_connection,
    committed_incident_cleanup,
):
    """Verify that process suppressed alert deduplicates."""
    alert = _firing_alert()

    first = process_suppressed_alert(
        db_connection,
        alert,
        CMDB,
    )

    db_connection.commit()

    committed_incident_cleanup.append(first["id"])

    second = process_suppressed_alert(
        db_connection,
        alert,
        CMDB,
    )

    db_connection.commit()

    assert second is None

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incidents
            WHERE fingerprint = %s
              AND status = 'SUPPRESSED_MAINTENANCE'
            """,
            (alert["fingerprint"],),
        )

        row = cur.fetchone()

    assert row["count"] == 1


def test_process_suppressed_alert_records_created_event_from_maintenance(
    db_connection,
    committed_incident_cleanup,
):
    """Verify that process suppressed alert records created event from maintenance."""
    alert = _firing_alert()

    incident = process_suppressed_alert(
        db_connection,
        alert,
        CMDB,
    )

    db_connection.commit()

    committed_incident_cleanup.append(incident["id"])

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT actor
            FROM incident_events
            WHERE incident_id = %s
              AND event_type = 'CREATED'
            """,
            (incident["id"],),
        )

        event = cur.fetchone()

    assert event["actor"] == "maintenance"


def test_process_suppressed_alert_notes_existing_actionable_incident_without_suppressing_it(
    db_connection,
    make_incident,
    committed_incident_cleanup,
):
    # Regression test: an alert that's already an active incident (created
    # via the webhook, e.g. IN_PROGRESS under active remediation) collides
    # with incidents_active_fingerprint_idx when the same fingerprint shows
    # up suppressed. Before this fix, ingest_alert()'s UniqueViolation
    # propagated uncaught out of process_suppressed_alert() every poll,
    # forever, and the incident was never touched at all.
    """Verify that process suppressed alert notes existing actionable incident without suppressing it."""
    alert = _suppressed_alert("sil-test")

    actionable_incident = make_incident(
        fingerprint=alert["fingerprint"],
        status="IN_PROGRESS",
    )
    db_connection.commit()
    committed_incident_cleanup.append(actionable_incident["id"])

    result = process_suppressed_alert(
        db_connection,
        alert,
        CMDB,
    )
    db_connection.commit()

    # The actionable incident is returned and reconciled, not suppressed.
    assert result["id"] == actionable_incident["id"]

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT status FROM incidents WHERE id = %s",
            (actionable_incident["id"],),
        )
        assert cur.fetchone()["status"] == "IN_PROGRESS"

        cur.execute(
            """
            SELECT actor, event_type, message, silence_id
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (actionable_incident["id"],),
        )
        event = cur.fetchone()

    assert event["event_type"] == "NOTE"
    assert event["actor"] == "maintenance"
    assert "maintenance window" in event["message"]
    assert event["silence_id"] == "sil-test"

    # No orphaned SUPPRESSED_MAINTENANCE row was created for this fingerprint.
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incidents
            WHERE fingerprint = %s
              AND status = 'SUPPRESSED_MAINTENANCE'
            """,
            (alert["fingerprint"],),
        )
        assert cur.fetchone()["count"] == 0


def test_process_suppressed_alert_still_dedups_after_intervening_event(
    db_connection,
    make_incident,
    committed_incident_cleanup,
):
    # The decisive test: a "skip if the last event is identical" guard was
    # rejected because any intervening event re-enables it. Dedup keys on the
    # silence identity, not timeline position, so an unrelated event landing
    # in between must not produce a second NOTE.
    """Verify that process suppressed alert still dedups after intervening event."""
    alert = _suppressed_alert("sil-test")

    actionable_incident = make_incident(
        fingerprint=alert["fingerprint"],
        status="IN_PROGRESS",
    )
    db_connection.commit()
    committed_incident_cleanup.append(actionable_incident["id"])

    process_suppressed_alert(db_connection, alert, CMDB)
    db_connection.commit()

    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incident_events (
                incident_id, sequence, occurred_at, actor,
                event_type, message, payload
            )
            SELECT %s, COALESCE(MAX(sequence), 0) + 1, NOW(), 'operator',
                   'STATE_CHANGE', 'Escalated by operator.', '{}'
            FROM incident_events WHERE incident_id = %s
            """,
            (actionable_incident["id"], actionable_incident["id"]),
        )
    db_connection.commit()

    process_suppressed_alert(db_connection, alert, CMDB)
    db_connection.commit()

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incident_events
            WHERE incident_id = %s
              AND event_type = 'NOTE'
            """,
            (actionable_incident["id"],),
        )
        assert cur.fetchone()["count"] == 1


def test_process_suppressed_alert_notes_new_silence_for_same_service(
    db_connection,
    make_incident,
    committed_incident_cleanup,
):
    # Ending and restarting a maintenance window produces a new Alertmanager
    # silence id, which is a new operator action and gets its own NOTE.
    """Verify that process suppressed alert notes new silence for same service."""
    first_alert = _suppressed_alert("sil-first")

    actionable_incident = make_incident(
        fingerprint=first_alert["fingerprint"],
        status="IN_PROGRESS",
    )
    db_connection.commit()
    committed_incident_cleanup.append(actionable_incident["id"])

    process_suppressed_alert(db_connection, first_alert, CMDB)
    db_connection.commit()

    second_alert = dict(first_alert)
    second_alert["status"] = {
        "state": "suppressed",
        "silencedBy": ["sil-second"],
        "inhibitedBy": [],
        "mutedBy": [],
    }

    process_suppressed_alert(db_connection, second_alert, CMDB)
    db_connection.commit()

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT silence_id
            FROM incident_events
            WHERE incident_id = %s
              AND event_type = 'NOTE'
            ORDER BY sequence
            """,
            (actionable_incident["id"],),
        )
        rows = cur.fetchall()

    assert [row["silence_id"] for row in rows] == ["sil-first", "sil-second"]


def test_process_suppressed_alert_notes_each_silence_once(
    db_connection,
    make_incident,
    committed_incident_cleanup,
):
    # An alert can be covered by several silences at once (status.silencedBy is
    # a list). Each silence is an independent operator action and gets its own
    # NOTE, deduplicated independently.
    """Verify that process suppressed alert notes each silence once."""
    alert = _suppressed_alert("sil-a", "sil-b")

    actionable_incident = make_incident(
        fingerprint=alert["fingerprint"],
        status="IN_PROGRESS",
    )
    db_connection.commit()
    committed_incident_cleanup.append(actionable_incident["id"])

    process_suppressed_alert(db_connection, alert, CMDB)
    db_connection.commit()

    process_suppressed_alert(db_connection, alert, CMDB)
    db_connection.commit()

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT silence_id
            FROM incident_events
            WHERE incident_id = %s
              AND event_type = 'NOTE'
            ORDER BY silence_id
            """,
            (actionable_incident["id"],),
        )
        rows = cur.fetchall()

    assert [row["silence_id"] for row in rows] == ["sil-a", "sil-b"]


def test_process_suppressed_alert_skips_note_when_silenced_by_empty(
    db_connection,
    make_incident,
    committed_incident_cleanup,
):
    # A silence can expire between Alertmanager evaluating the alert and this
    # poll reading it, leaving silencedBy empty. With no silence id there is no
    # identity to deduplicate on, so recording a NOTE would reintroduce
    # unbounded per-poll noise. Treated as a transient race: skip, don't crash.
    """Verify that process suppressed alert skips note when silenced by empty."""
    alert = _suppressed_alert()

    actionable_incident = make_incident(
        fingerprint=alert["fingerprint"],
        status="IN_PROGRESS",
    )
    db_connection.commit()
    committed_incident_cleanup.append(actionable_incident["id"])

    result = process_suppressed_alert(db_connection, alert, CMDB)
    db_connection.commit()

    assert result["id"] == actionable_incident["id"]

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incident_events
            WHERE incident_id = %s
              AND event_type = 'NOTE'
            """,
            (actionable_incident["id"],),
        )
        assert cur.fetchone()["count"] == 0

        cur.execute(
            "SELECT status FROM incidents WHERE id = %s",
            (actionable_incident["id"],),
        )
        assert cur.fetchone()["status"] == "IN_PROGRESS"


def test_process_suppressed_alert_reconciles_duplicate_suppressed_incident_race(
    db_connection,
    committed_incident_cleanup,
):
    # Regression test for the TOCTOU race incidents_suppressed_maintenance_fingerprint_idx
    # exists to catch: two overlapping process_suppressed_alert() calls for
    # the same (fingerprint, startsAt) can both see suppressed_incident_exists()
    # return False before either commits. Simulated here by patching
    # suppressed_incident_exists() to always return False, forcing a second
    # call to attempt the INSERT despite a SUPPRESSED_MAINTENANCE row for
    # this exact (fingerprint, startsAt) already existing -- exactly what
    # the "loser" of a real race would observe. It must reconcile via
    # find_suppressed_incident() rather than letting UniqueViolation
    # propagate uncaught.
    """Verify that process suppressed alert reconciles duplicate suppressed incident race."""
    alert = _firing_alert()

    winner = process_suppressed_alert(db_connection, alert, CMDB)
    db_connection.commit()
    committed_incident_cleanup.append(winner["id"])

    with patch(
        "automation.response_engine.maintenance.suppressed_incident_exists",
        return_value=False,
    ):
        loser_result = process_suppressed_alert(db_connection, alert, CMDB)
        db_connection.commit()

    assert loser_result["id"] == winner["id"]

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incidents
            WHERE fingerprint = %s
              AND status = 'SUPPRESSED_MAINTENANCE'
            """,
            (alert["fingerprint"],),
        )
        assert cur.fetchone()["count"] == 1

        cur.execute(
            """
            SELECT actor, event_type, message
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (winner["id"],),
        )
        event = cur.fetchone()

    assert event["event_type"] == "NOTE"
    assert event["actor"] == "maintenance"
    assert "duplicate" in event["message"].lower()


def test_process_suppressed_alert_raises_when_unique_violation_is_unexplained(
    db_connection,
):
    # If a UniqueViolation happens but neither an actionable nor a
    # SUPPRESSED_MAINTENANCE incident can be found for the fingerprint
    # (both lookups race-losing against a rollback, or a genuinely
    # different constraint fires), that's not a case to silently swallow --
    # it means the uniqueness assumptions have drifted from the schema.
    """Verify that process suppressed alert raises when unique violation is unexplained."""
    alert = _firing_alert()

    with (
        patch(
            "automation.response_engine.maintenance.suppressed_incident_exists",
            return_value=False,
        ),
        patch(
            "automation.response_engine.maintenance.ingest_alert",
            side_effect=psycopg2.errors.UniqueViolation("simulated"),
        ),
        patch(
            "automation.response_engine.maintenance.find_actionable_incident",
            return_value=None,
        ),
        patch(
            "automation.response_engine.maintenance.find_suppressed_incident",
            return_value=None,
        ),
    ):
        try:
            process_suppressed_alert(db_connection, alert, CMDB)
        except RuntimeError as exc:
            assert "UniqueViolation" in str(exc)
        else:
            raise AssertionError(
                "Expected RuntimeError for an unexplained UniqueViolation."
            )


def test_process_suppressed_alert_propagates_non_silence_unique_violations(
    db_connection,
    make_incident,
    committed_incident_cleanup,
):
    # Only the silence index means "already recorded". record_note_event()
    # computes its sequence with a racy COALESCE(MAX(sequence), 0) + 1, so
    # incident_events_incident_id_sequence_key can genuinely fire here.
    # Swallowing it would silently discard a NOTE and report success.
    """Verify that process suppressed alert propagates non silence unique violations."""
    alert = _suppressed_alert("sil-abc")

    actionable_incident = make_incident(
        fingerprint=alert["fingerprint"],
        status="IN_PROGRESS",
    )
    db_connection.commit()
    committed_incident_cleanup.append(actionable_incident["id"])

    class _FakeDiag:
        constraint_name = "incident_events_incident_id_sequence_key"

    sequence_violation = psycopg2.errors.UniqueViolation()

    with patch.object(
        type(sequence_violation), "diag", property(lambda self: _FakeDiag())
    ):
        with (
            patch(
                "automation.response_engine.maintenance.record_note_event",
                side_effect=sequence_violation,
            ),
            pytest.raises(psycopg2.errors.UniqueViolation) as excinfo,
        ):
            process_suppressed_alert(db_connection, alert, CMDB)

        assert (
            excinfo.value.diag.constraint_name
            == "incident_events_incident_id_sequence_key"
        )
