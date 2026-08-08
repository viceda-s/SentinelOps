from datetime import datetime, timedelta, timezone

from prometheus_client import Histogram

from automation.response_engine.metrics import (
    INCIDENT_RESOLUTION_SECONDS,
    INCIDENT_RESPONSE_SECONDS,
)
from automation.response_engine.state_machine import transition


def histogram_count(histogram: Histogram) -> float:
    """Retrun the histogram's current observation count."""
    metric = next(iter(histogram.collect()))

    for sample in metric.samples:
        if sample.name.endswith("_count"):
            return sample.value

    raise AssertionError("Histogram has no _count sample")


def test_transition_to_acknowledged_observes_response_histogram(
    db_connection, make_incident
):
    incident = make_incident(
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=5), status="NEW"
    )

    before = histogram_count(INCIDENT_RESPONSE_SECONDS)

    transition(
        db_connection,
        incident,
        "ACKNOWLEDGED",
        actor="worker",
        message="Claimed by worker.",
    )

    after = histogram_count(INCIDENT_RESPONSE_SECONDS)

    assert after == before + 1


def test_transition_to_resolved_observes_resolution_histogram(
    db_connection, make_incident
):
    incident = make_incident(
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        status="IN_PROGRESS",
    )

    before = histogram_count(INCIDENT_RESOLUTION_SECONDS)

    transition(
        db_connection,
        incident,
        "RESOLVED",
        actor="worker",
        message="Resolved automatically.",
    )

    after = histogram_count(INCIDENT_RESOLUTION_SECONDS)

    assert after == before + 1


def test_transition_to_in_progress_observes_no_histogram(db_connection, make_incident):
    incident = make_incident(
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        status="ACKNOWLEDGED",
    )

    response_before = histogram_count(INCIDENT_RESPONSE_SECONDS)
    resolution_before = histogram_count(INCIDENT_RESOLUTION_SECONDS)

    transition(
        db_connection,
        incident,
        "IN_PROGRESS",
        actor="worker",
        message="Beginning remediation.",
    )

    assert histogram_count(INCIDENT_RESPONSE_SECONDS) == response_before
    assert histogram_count(INCIDENT_RESOLUTION_SECONDS) == resolution_before


def test_transition_to_suppressed_maintenance(
    db_connection,
    make_incident,
):
    incident = make_incident(status="NEW")

    updated = transition(
        db_connection,
        incident,
        "SUPPRESSED_MAINTENANCE",
        actor="maintenance",
        message="Suppressed by active maintenance window.",
    )

    assert updated["status"] == "SUPPRESSED_MAINTENANCE"


def test_transition_from_suppressed_maintenance_to_in_progress_is_rejected(
    db_connection,
    make_incident,
):
    incident = make_incident(status="SUPPRESSED_MAINTENANCE")

    try:
        transition(
            db_connection,
            incident,
            "IN_PROGRESS",
            actor="worker",
            message="Beginning remediation.",
        )
    except ValueError as exc:
        assert "Invalid transition" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid state transition.")


def test_transition_from_suppressed_maintenance_to_resolved(
    db_connection,
    make_incident,
):
    incident = make_incident(status="SUPPRESSED_MAINTENANCE")

    updated = transition(
        db_connection,
        incident,
        "RESOLVED",
        actor="operator",
        message="Maintenance window ended; underlying condition recovered.",
    )

    assert updated["status"] == "RESOLVED"

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT resolved_at FROM incidents WHERE id = %s",
            (incident["id"],),
        )

        assert cur.fetchone()["resolved_at"] is not None

        cur.execute(
            """
            SELECT actor, event_type, from_status, to_status, message
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (incident["id"],),
        )

        event = cur.fetchone()

        assert event["actor"] == "operator"
        assert event["event_type"] == "STATE_CHANGE"
        assert event["from_status"] == "SUPPRESSED_MAINTENANCE"
        assert event["to_status"] == "RESOLVED"


def test_transition_from_suppressed_maintenance_through_resolved_to_closed(
    db_connection,
    make_incident,
):
    incident = make_incident(status="SUPPRESSED_MAINTENANCE")

    resolved = transition(
        db_connection,
        incident,
        "RESOLVED",
        actor="operator",
        message="Maintenance window ended; underlying condition recovered.",
    )

    closed = transition(
        db_connection,
        resolved,
        "CLOSED",
        actor="operator",
        message="Incident closed",
    )

    assert closed["status"] == "CLOSED"
