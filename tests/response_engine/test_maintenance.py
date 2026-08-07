from unittest.mock import Mock, patch

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
    counter_value,
)


@patch("automation.response_engine.maintenance.requests.get")
def test_fetch_suppressed_alerts_sorts_by_starts_at(mock_get):
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
def test_fetch_suppressed_alerts_propagates_request_failures(mock_get):
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
