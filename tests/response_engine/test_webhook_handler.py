from unittest.mock import patch

from prometheus_client import CONTENT_TYPE_LATEST

from automation.response_engine.webhook_handler import app


def test_metrics_endpoint():
    """Verify that metrics endpoint."""
    client = app.test_client()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == CONTENT_TYPE_LATEST

    body = response.get_data(as_text=True)

    assert "sentinelops_incidents_created_total" in body


def test_alerts_route_generates_a_correlation_id_and_passes_it_to_handle_alert():
    """POST /alerts generates one correlation_id and passes it through to handle_alert."""
    client = app.test_client()

    payload = {
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "fp-webhook-test-1",
                "startsAt": "2026-09-06T00:00:00Z",
                "labels": {
                    "alertname": "ServiceDown",
                    "job": "api",
                    "severity": "critical",
                },
                "annotations": {},
            }
        ]
    }

    with (
        patch(
            "automation.response_engine.webhook_handler.handle_alert"
        ) as mock_handle_alert,
        patch("automation.response_engine.webhook_handler.get_connection"),
    ):
        response = client.post("/alerts", json=payload)

    assert response.status_code == 200
    assert mock_handle_alert.call_count == 1

    _, kwargs = mock_handle_alert.call_args
    assert "correlation_id" in kwargs
    assert isinstance(kwargs["correlation_id"], str)
    assert len(kwargs["correlation_id"]) > 0


def test_alerts_route_reuses_one_correlation_id_for_every_alert_in_the_batch():
    """A single POST /alerts with multiple alerts shares one correlation_id across all of them -- the id identifies the request, not an individual alert."""
    client = app.test_client()

    payload = {
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "fp-webhook-test-batch-1",
                "startsAt": "2026-09-06T00:00:00Z",
                "labels": {
                    "alertname": "ServiceDown",
                    "job": "api",
                    "severity": "critical",
                },
                "annotations": {},
            },
            {
                "status": "firing",
                "fingerprint": "fp-webhook-test-batch-2",
                "startsAt": "2026-09-06T00:00:00Z",
                "labels": {
                    "alertname": "DiskPressure",
                    "job": "api",
                    "severity": "warning",
                },
                "annotations": {},
            },
        ]
    }

    with (
        patch(
            "automation.response_engine.webhook_handler.handle_alert"
        ) as mock_handle_alert,
        patch("automation.response_engine.webhook_handler.get_connection"),
    ):
        response = client.post("/alerts", json=payload)

    assert response.status_code == 200
    assert mock_handle_alert.call_count == 2

    first_kwargs = mock_handle_alert.call_args_list[0].kwargs
    second_kwargs = mock_handle_alert.call_args_list[1].kwargs

    assert first_kwargs["correlation_id"] == second_kwargs["correlation_id"]
