from datetime import datetime, timezone
from uuid import uuid4

from prometheus_client import Counter

from automation.response_engine.handlers import handle_alert, ingest_alert
from automation.response_engine.metrics import INCIDENTS_CREATED_TOTAL

CMDB = {
    "services": {
        "api": {
            "owner": "platform-team",
            "tier": "prod",
            "criticality": "high",
            "playbooks": {
                "ServiceDown": "restart_service",
            },
            "sla": {
                "response_minutes": 5,
                "resolution_minutes": 30,
            },
        },
    },
}


def _firing_alert() -> dict:
    return {
        "status": "firing",
        "fingerprint": str(uuid4()),
        "startsAt": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "labels": {
            "alertname": "ServiceDown",
            "job": "api",
            "severity": "critical",
            "playbook": "restart_service",
        },
        "annotations": {},
    }


def counter_value(counter: Counter, **labels) -> float:
    """Return the current value of a labeled Counter"""
    metric = next(iter(counter.collect()))

    for sample in metric.samples:
        if sample.name.endswith("_total") and sample.labels == labels:
            return sample.value

    return 0.0


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
            SELECT COUNT(*) AS count
            FROM incident_events
            WHERE incident_id = %s
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["count"] == 2


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
