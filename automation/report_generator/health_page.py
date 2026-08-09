"""
Health page model builder and Jinja2 renderer for SentinelOps.

Queries PostgreSQL for open incidents and Alertmanager for active maintenance windows,
summarizes service health states, and renders HTML dashboard pages.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

SEVERITY_RANK = {
    "critical": 0,
    "warning": 1,
}

STATUS_RANK = {
    "IN_PROGRESS": 0,
    "ACKNOWLEDGED": 1,
    "ESCALATED": 2,
    "NEW": 3,
}


@dataclass
class HealthPageModel:
    """
    Data model representing system health state for HTML dashboard rendering.

    Attributes:
        services: List of service status dictionaries.
        open_incidents: List of non-terminal open incident row dictionaries.
        counts_by_severity: Dictionary mapping severity names to active incident counts.
        active_maintenance_windows: List of active Alertmanager silence dictionaries.
    """

    services: list[dict]
    open_incidents: list[dict]
    counts_by_severity: dict[str, int]
    active_maintenance_windows: list[dict] = field(default_factory=list)


_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def severity_rank(severity: str) -> int:
    """
    Return numerical priority rank for severity strings.

    Args:
        severity: Severity string ('critical' or 'warning').

    Returns:
        int: Lower integer value represents higher priority.

    Raises:
        ValueError: If severity string is not recognized.
    """
    try:
        return SEVERITY_RANK[severity]
    except KeyError as exc:
        raise ValueError(f"Unknown incident severity: {severity!r}") from exc


def status_rank(status: str) -> int:
    """
    Return numerical priority rank for incident status strings.

    Args:
        status: Incident status string.

    Returns:
        int: Lower integer value represents higher priority.
    """
    return STATUS_RANK.get(status, 99)


def query_health_state(conn, cmdb: dict) -> HealthPageModel:
    """
    Build the `HealthPageModel` from CMDB metadata, database incidents, and Alertmanager silences.

    Args:
        conn: Active PostgreSQL connection with RealDictCursor.
        cmdb: CMDB configuration dictionary.

    Returns:
        HealthPageModel: Assembled system health model.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incidents
            WHERE status IN (
                'NEW',
                'ACKNOWLEDGED',
                'IN_PROGRESS',
                'ESCALATED'
            )
            ORDER BY id ASC
            """
        )
        open_incidents = cur.fetchall()

    services = [
        {
            "name": service_name,
            "status": "healthy",
            "severity": None,
        }
        for service_name in cmdb["services"]
    ]

    service_index = {service["name"]: service for service in services}

    counts = Counter()

    for incident in open_incidents:
        incident_sev_rank = severity_rank(incident["severity"])
        incident_stat_rank = status_rank(incident["status"])
        counts[incident["severity"]] += 1

        service = service_index.get(incident["service"])
        if service is None:
            continue

        if service["severity"] is None:
            service["status"] = incident["status"]
            service["severity"] = incident["severity"]
            continue

        current_sev_rank = severity_rank(service["severity"])
        current_stat_rank = status_rank(service["status"])

        if incident_sev_rank < current_sev_rank or (
            incident_sev_rank == current_sev_rank
            and incident_stat_rank < current_stat_rank
        ):
            service["status"] = incident["status"]
            service["severity"] = incident["severity"]

    return HealthPageModel(
        services=services,
        open_incidents=open_incidents,
        counts_by_severity=dict(counts),
        active_maintenance_windows=query_active_maintenance_windows(),
    )


def render_health_page(model: HealthPageModel) -> str:
    """
    Render the health page as HTML.
    """
    template = _TEMPLATE_ENV.get_template("health.html.j2")
    return template.render(model=model)


def query_active_maintenance_windows() -> list[dict]:
    """
    Query Alertmanager for active maintenance windows.

    Returns an empty list if Alertmanager cannot be reached.
    """

    alertmanager_url = os.getenv(
        "ALERTMANAGER_URL",
        "http://alertmanager:9093",
    )

    try:
        response = requests.get(
            f"{alertmanager_url}/api/v2/silences",
            timeout=5,
        )
        response.raise_for_status()

    except requests.RequestException:
        return []

    windows = []

    for silence in response.json():
        if silence["status"]["state"] != "active":
            continue

        service = None

        for matcher in silence["matchers"]:
            if matcher["name"] == "job" and not matcher.get("isRegex", False):
                service = matcher["value"]
                break

        if service is None:
            continue

        windows.append(
            {
                "id": silence["id"],
                "service": service,
                "starts_at": silence["startsAt"],
                "ends_at": silence["endsAt"],
                "created_by": silence["createdBy"],
                "comment": silence["comment"],
            }
        )

    return windows
