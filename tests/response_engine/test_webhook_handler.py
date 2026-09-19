from unittest.mock import ANY, MagicMock

import pytest
from prometheus_client import CONTENT_TYPE_LATEST

from automation.response_engine.webhook_handler import app


@pytest.fixture
def mock_connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(
        "automation.response_engine.webhook_handler.get_connection",
        MagicMock(return_value=conn),
    )
    return conn


def test_metrics_endpoint():
    """Verify that metrics endpoint."""
    client = app.test_client()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == CONTENT_TYPE_LATEST

    body = response.get_data(as_text=True)

    assert "sentinelops_incidents_created_total" in body


def test_alerts_returns_400_when_payload_is_not_a_dict():
    client = app.test_client()

    response = client.post("/alerts", json=["not", "a", "dict"])

    assert response.status_code == 400
    assert response.get_json()["error"] == "Payload must be a JSON object."


def test_alerts_returns_400_when_alerts_is_not_a_list():
    client = app.test_client()

    response = client.post("/alerts", json={"alerts": "not-a-list"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "'alerts' must be a list."


def test_alerts_returns_400_on_missing_alerts_key():
    client = app.test_client()

    response = client.post("/alerts", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Malformed Alertmanager payload."


def test_alerts_processes_each_alert_and_returns_200(monkeypatch, mock_connection):
    mock_handle_alert = MagicMock()
    monkeypatch.setattr(
        "automation.response_engine.webhook_handler.handle_alert", mock_handle_alert
    )

    client = app.test_client()
    alert_a = {"fingerprint": "a"}
    alert_b = {"fingerprint": "b"}

    response = client.post("/alerts", json={"alerts": [alert_a, alert_b]})

    assert response.status_code == 200
    mock_handle_alert.assert_any_call(mock_connection, alert_a, ANY)
    mock_handle_alert.assert_any_call(mock_connection, alert_b, ANY)
    assert mock_handle_alert.call_count == 2


def test_alerts_returns_500_on_unexpected_error(monkeypatch, mock_connection):
    monkeypatch.setattr(
        "automation.response_engine.webhook_handler.handle_alert",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    client = app.test_client()

    response = client.post("/alerts", json={"alerts": [{"fingerprint": "a"}]})

    assert response.status_code == 500
    assert response.get_json()["error"] == "Internal server error."
