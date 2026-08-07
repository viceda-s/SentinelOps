from __future__ import annotations

from unittest.mock import patch

import pytest

from automation.report_generator.health_page import (
    query_health_state,
    render_health_page,
)

CMDB = {
    "services": {
        "api": {
            "container_name": "sentinelops-api",
        },
        "postgres": {
            "container_name": "sentinelops-postgres",
        },
    }
}


def _fake_silences_response(silences: list[dict]):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return silences

    return FakeResponse()


def test_query_health_state_marks_service_with_open_incident(
    db_connection, make_incident
):
    make_incident(
        service="api",
        status="IN_PROGRESS",
        severity="critical",
    )

    with patch(
        "automation.report_generator.health_page.requests.get",
        return_value=_fake_silences_response([]),
    ):
        model = query_health_state(db_connection, CMDB)

    api_entry = next(s for s in model.services if s["name"] == "api")
    postgres_entry = next(s for s in model.services if s["name"] == "postgres")

    assert api_entry["status"] == "IN_PROGRESS"
    assert api_entry["severity"] == "critical"

    assert postgres_entry["status"] == "healthy"
    assert postgres_entry["severity"] is None


def test_query_health_state_shows_most_severe_incident_status(
    db_connection, make_incident
):
    # The health page reflects the most severe open incident affecting a service, not whichever incident happens to be returned first.
    make_incident(
        service="api",
        status="ACKNOWLEDGED",
        severity="warning",
    )
    make_incident(
        service="api",
        status="IN_PROGRESS",
        severity="critical",
    )

    with patch(
        "automation.report_generator.health_page.requests.get",
        return_value=_fake_silences_response([]),
    ):
        model = query_health_state(db_connection, CMDB)

    api_entry = next(s for s in model.services if s["name"] == "api")

    assert api_entry["status"] == "IN_PROGRESS"
    assert api_entry["severity"] == "critical"


def test_query_health_state_counts_by_severity(db_connection, make_incident):
    make_incident(
        service="api",
        status="NEW",
        severity="critical",
    )
    make_incident(
        service="postgres",
        status="NEW",
        severity="warning",
    )

    with patch(
        "automation.report_generator.health_page.requests.get",
        return_value=_fake_silences_response([]),
    ):
        model = query_health_state(db_connection, CMDB)

    assert model.counts_by_severity["critical"] == 1
    assert model.counts_by_severity["warning"] == 1


def test_query_health_state_excludes_resolved_incidents(db_connection, make_incident):
    make_incident(
        service="api",
        status="RESOLVED",
        severity="critical",
    )

    with patch(
        "automation.report_generator.health_page.requests.get",
        return_value=_fake_silences_response([]),
    ):
        model = query_health_state(db_connection, CMDB)

    api_entry = next(s for s in model.services if s["name"] == "api")

    assert api_entry["status"] == "healthy"
    assert api_entry["severity"] is None
    assert model.open_incidents == []


def test_query_health_state_page_produces_html(db_connection):
    with patch(
        "automation.report_generator.health_page.requests.get",
        return_value=_fake_silences_response([]),
    ):
        model = query_health_state(db_connection, CMDB)

    html = render_health_page(model)

    assert "<html" in html.lower()
    assert "api" in html
    assert "None active" in html


def test_query_health_state_rejects_unknown_severity(db_connection, make_incident):
    make_incident(
        service="api",
        status="NEW",
        severity="info",
    )

    with (
        patch(
            "automation.report_generator.health_page.requests.get",
            return_value=_fake_silences_response([]),
        ),
        pytest.raises(ValueError, match="info"),
    ):
        query_health_state(db_connection, CMDB)


def test_query_health_state_includes_active_maintenance_windows(db_connection):
    active_silence = {
        "id": "silence-1",
        "status": {"state": "active"},
        "matchers": [
            {"name": "job", "value": "api", "isEqual": True, "isRegex": False}
        ],
        "startsAt": "2026-01-01T00:00:00.000Z",
        "endsAt": "2026-01-01T12:00:00.000Z",
        "createdBy": "maintenance.sh",
        "comment": "Scheduled maintenance",
    }
    expired_silence = {
        "id": "silence-2",
        "status": {"state": "expired"},
        "matchers": [
            {"name": "job", "value": "postgres", "isEqual": True, "isRegex": False}
        ],
        "startsAt": "2025-01-01T00:00:00.000Z",
        "endsAt": "2025-01-01T12:00:00.000Z",
        "createdBy": "maintenance.sh",
        "comment": "Scheduled maintenance",
    }

    with patch(
        "automation.report_generator.health_page.requests.get",
        return_value=_fake_silences_response([active_silence, expired_silence]),
    ):
        model = query_health_state(db_connection, CMDB)

    assert len(model.active_maintenance_windows) == 1
    assert model.active_maintenance_windows[0]["service"] == "api"
    assert model.active_maintenance_windows[0]["ends_at"] == "2026-01-01T12:00:00.000Z"


def test_query_health_state_handles_alertmanager_unreachable(db_connection):
    import requests

    with patch(
        "automation.report_generator.health_page.requests.get",
        side_effect=requests.exceptions.ConnectionError("unreachable"),
    ):
        model = query_health_state(db_connection, CMDB)

    assert model.active_maintenance_windows == []
