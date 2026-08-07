from __future__ import annotations

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


def test_query_health_state_marks_service_with_open_incident(
    db_connection, make_incident
):
    make_incident(
        service="api",
        status="IN_PROGRESS",
        severity="critical",
    )

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

    model = query_health_state(db_connection, CMDB)

    assert model.counts_by_severity["critical"] == 1
    assert model.counts_by_severity["warning"] == 1


def test_query_health_state_excludes_resolved_incidents(db_connection, make_incident):
    make_incident(
        service="api",
        status="RESOLVED",
        severity="critical",
    )

    model = query_health_state(db_connection, CMDB)

    api_entry = next(s for s in model.services if s["name"] == "api")

    assert api_entry["status"] == "healthy"
    assert api_entry["severity"] is None
    assert model.open_incidents == []


def test_query_health_state_page_produces_html(db_connection):
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

    with pytest.raises(ValueError, match="info"):
        query_health_state(db_connection, CMDB)
