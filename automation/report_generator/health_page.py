from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

SEVERITY_RANK = {
    "critical": 0,
    "warning": 1,
}

# Unknown severities rank after all known values so the health page degrades gracefully instead of failing.
UNKNOWN_SEVERITY_RANK = len(SEVERITY_RANK)


@dataclass
class HealthPageModel:
    services: list[dict]
    open_incidents: list[dict]
    counts_by_severity: dict[str, int]


_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


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
        counts[incident["severity"]] += 1

        service = service_index.get(incident["service"])
        if service is None:
            continue

        if service["severity"] is None:
            service["status"] = incident["status"]
            service["severity"] = incident["severity"]
            continue

        current_rank = SEVERITY_RANK.get(service["severity"], UNKNOWN_SEVERITY_RANK)
        new_rank = SEVERITY_RANK.get(incident["severity"], UNKNOWN_SEVERITY_RANK)

        if new_rank < current_rank:
            service["status"] = incident["status"]
            service["severity"] = incident["severity"]

    return HealthPageModel(
        services=services,
        open_incidents=open_incidents,
        counts_by_severity=dict(counts),
    )


def render_health_page(model: HealthPageModel) -> str:
    """
    Render the health page as HTML.
    """
    template = _TEMPLATE_ENV.get_template("health.html.j2")
    return template.render(model=model)
