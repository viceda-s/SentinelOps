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


def test_transition_from_suppressed_maintenance_is_rejected(
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
