import pytest
from prometheus_client import Counter, Gauge, Histogram

from automation.response_engine.metrics import (
    INCIDENT_RESOLUTION_SECONDS,
    INCIDENT_RESPONSE_SECONDS,
    INCIDENTS_CREATED_TOTAL,
    REMEDIATION_ATTEMPTS_TOTAL,
    SLA_BREACHES_TOTAL,
    WORKER_HEARTBEAT_TIMESTAMP,
)


def test_metric_types():
    assert isinstance(INCIDENTS_CREATED_TOTAL, Counter)
    assert isinstance(REMEDIATION_ATTEMPTS_TOTAL, Counter)
    assert isinstance(SLA_BREACHES_TOTAL, Counter)

    assert isinstance(WORKER_HEARTBEAT_TIMESTAMP, Gauge)

    assert isinstance(INCIDENT_RESPONSE_SECONDS, Histogram)
    assert isinstance(INCIDENT_RESOLUTION_SECONDS, Histogram)


def test_incident_created_total_labels():
    INCIDENTS_CREATED_TOTAL.labels(
        service="api",
        severity="critical",
    )

    with pytest.raises(ValueError):
        INCIDENTS_CREATED_TOTAL.labels(service="api")

    with pytest.raises(ValueError):
        INCIDENTS_CREATED_TOTAL.labels(service="api", severity="critical", status="NEW")


def test_remediation_attempt_total_labels():
    REMEDIATION_ATTEMPTS_TOTAL.labels(
        playbook="restart_service",
        result="success",
    )

    with pytest.raises(ValueError):
        REMEDIATION_ATTEMPTS_TOTAL.labels(playbook="restart_service")

    with pytest.raises(ValueError):
        REMEDIATION_ATTEMPTS_TOTAL.labels(
            playbook="restart_service",
            result="success",
            service="api",
        )


def test_sla_breaches_total_labels():
    SLA_BREACHES_TOTAL.labels(type="response")

    with pytest.raises(ValueError):
        SLA_BREACHES_TOTAL.labels()

    with pytest.raises(ValueError):
        SLA_BREACHES_TOTAL.labels(
            type="response",
            service="api",
        )


def test_worker_heartbeat_timestamp_has_no_labels():
    WORKER_HEARTBEAT_TIMESTAMP.set_to_current_time()

    with pytest.raises(ValueError):
        WORKER_HEARTBEAT_TIMESTAMP.labels(worker_id="1")
