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


@dataclass
class HealthPageModel:
    services: list[dict]
    open_incidents: list[dict]
    counts_by_severity: dict[str, int]
    active_maintenance_windows: list[dict] = field(default_factory=list)


_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def severity_rank(severity: str) -> int:
    try:
        return SEVERITY_RANK[severity]
    except KeyError as exc:
        raise ValueError(f"Unknown incident severity: {severity!r}") from exc


def query_health_state(conn, cmdb: dict) -> HealthPageModel:
    """
    Build the health page model from the CMDB and current open incidents.
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
        incident_rank = severity_rank(incident["severity"])
        counts[incident["severity"]] += 1

        service = service_index.get(incident["service"])
        if service is None:
            continue

        if service["severity"] is None:
            service["status"] = incident["status"]
            service["severity"] = incident["severity"]
            continue

        current_rank = severity_rank(service["severity"])

        if incident_rank < current_rank:
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
