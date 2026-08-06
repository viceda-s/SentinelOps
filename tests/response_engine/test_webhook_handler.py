from prometheus_client import CONTENT_TYPE_LATEST

from automation.response_engine.webhook_handler import app


def test_metrics_endpoint():
    client = app.test_client()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == CONTENT_TYPE_LATEST

    body = response.get_data(as_text=True)

    assert "sentinelops_incidents_created_total" in body
