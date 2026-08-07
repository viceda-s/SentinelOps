from __future__ import annotations

import logging

import requests

from .handlers import ingest_alert
from .metrics import (
    SUPPRESSED_ALERTS_DISCOVERED_TOTAL,
    SUPPRESSED_ALERTS_DUPLICATE_TOTAL,
    SUPPRESSED_INCIDENTS_CREATED_TOTAL,
)
from .state_machine import transition

POLL_INTERVAL_SECONDS = 30

logger = logging.getLogger(__name__)


def fetch_suppressed_alerts(alertmanager_url: str) -> list[dict]:
    """
    Fetch all active, silenced alerts from Alertmanager

    Alerts are returned ordered by their start time (oldest first) to provide deterministic processing order.

    Raises:
        requests.exceptions.RequestException:
            If the Alertmanager API request fails.
    """

    response = requests.get(
        f"{alertmanager_url}/api/v2/alerts",
        params={
            "silenced": "true",
            "active": "true",
        },
        timeout=5,
    )

    response.raise_for_status()

    alerts = response.json()

    alerts.sort(key=lambda alert: alert["startsAt"])

    return alerts


def suppressed_incident_exists(conn, fingerprint: str, starts_at: str) -> bool:
    """
    Check whether a suppressed maintenance incident already exists.

    Deduplication uses the Alertmanager fingerprint together with the alert's original startsAt timestamp so that an alert which resolves and later re-fires during the same maintenance window is treated as a new incident.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM incidents
            WHERE fingerprint = %s
              AND status = 'SUPPRESSED_MAINTENANCE'
              AND detected_at = %s
            LIMIT 1
            """,
            (fingerprint, starts_at),
        )

        return cur.fetchone() is not None


def process_suppressed_alert(conn, alert: dict, cmdb: dict) -> dict | None:
    """
    Process a suppressed Alertmanager alert.

    If the alert has already been recorded as a SUPRESSED_MAINTENANCE incident, no new incident is created.

    Returns:
        The created incident, or None if the alert was a duplicate.
    """

    SUPPRESSED_ALERTS_DISCOVERED_TOTAL.inc()

    fingerprint = alert["fingerprint"]
    starts_at = alert["startsAt"]

    if suppressed_incident_exists(
        conn,
        fingerprint,
        starts_at,
    ):
        SUPPRESSED_ALERTS_DUPLICATE_TOTAL.inc()
        return None

    incident = ingest_alert(
        conn,
        alert,
        cmdb,
        source="maintenance",
    )

    incident = transition(
        conn,
        incident,
        "SUPPRESSED_MAINTENANCE",
        actor="maintenance",
        message="Suppressed by active maintenance window.",
    )

    SUPPRESSED_INCIDENTS_CREATED_TOTAL.inc()

    return incident
