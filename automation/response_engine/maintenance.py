from __future__ import annotations

import logging
import os
import time

import requests
from prometheus_client import start_http_server

from .cmdb import load_cmdb
from .db import get_connection
from .handlers import ingest_alert
from .logging_config import configure_logging
from .metrics import (
    ALERTMANAGER_REQUEST_FAILURES_TOTAL,
    MAINTENANCE_HEARTBEAT_TIMESTAMP,
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


def main() -> None:
    """
    Run the maintenance monitor.

    Poll Alertmanager for active silenced alerts and record them as SUPPRESSED_MAINTENANCE incidents.

    The process runs indefinitely until terminated.
    """

    configure_logging()

    start_http_server(8000)

    cmdb = load_cmdb()
    conn = get_connection()

    logger.info("Maintenance monitor started.")

    while True:
        try:
            alerts = fetch_suppressed_alerts(
                os.getenv(
                    "ALERTMANAGER_URL",
                    "http://alertmanager:9093",
                )
            )

            for alert in alerts:
                try:
                    process_suppressed_alert(
                        conn,
                        alert,
                        cmdb,
                    )

                    conn.commit()

                    logger.debug(
                        "Processed %s suppressed alerts.",
                        len(alerts),
                    )

                except Exception:
                    conn.rollback()

                    logger.exception(
                        "Failed to process suppressed alert.",
                        extra={
                            "fingerprint": alert.get("fingerprint"),
                        },
                    )

            #
            # The heartbeat only advances after a successful poll iteration completes.
            #

            MAINTENANCE_HEARTBEAT_TIMESTAMP.set_to_current_time()

        except requests.exceptions.RequestException:
            conn.rollback()

            ALERTMANAGER_REQUEST_FAILURES_TOTAL.inc()

            logger.exception("Failed to query Alertmanager.")

        except Exception:
            conn.rollback()

            logger.exception("Maintenance monitor iteration failed.")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
