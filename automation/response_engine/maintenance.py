from __future__ import annotations

import logging
import os
import time
from datetime import datetime

import psycopg2
import requests
from prometheus_client import start_http_server

from .cmdb import load_cmdb
from .db import get_connection
from .handlers import ingest_alert, record_note_event
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

    #
    # Parse to datetime rather than sorting the raw strings: Alertmanager's
    # Go RFC3339Nano marshaling trims trailing zero fractional digits, so
    # two alerts in the same response can have different sub-second
    # precision (e.g. "...:00Z" vs "...:00.5Z"). Lexicographic string
    # comparison of those isn't equivalent to chronological order.
    #

    alerts.sort(
        key=lambda alert: datetime.fromisoformat(
            alert["startsAt"].replace("Z", "+00:00")
        )
    )

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


def find_suppressed_incident(conn, fingerprint: str, starts_at: str) -> dict | None:
    """
    Look up the SUPPRESSED_MAINTENANCE incident for (fingerprint, starts_at),
    if one exists.

    Same predicate as suppressed_incident_exists(), returning the row
    instead of a boolean -- used to reconcile the race
    incidents_suppressed_maintenance_fingerprint_idx exists to catch.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incidents
            WHERE fingerprint = %s
              AND status = 'SUPPRESSED_MAINTENANCE'
              AND detected_at = %s
            LIMIT 1
            """,
            (fingerprint, starts_at),
        )

        return cur.fetchone()


def find_actionable_incident(conn, fingerprint: str) -> dict | None:
    """
    Look up the open, actionable incident for this fingerprint, if one
    exists -- i.e. the one guarded by incidents_active_fingerprint_idx.

    Mirrors handlers.py's handle_alert() UniqueViolation lookup: a
    suppressed alert can collide with an incident that's still being
    worked (created via the webhook before a maintenance window started
    for the same service). That incident's lifecycle stays untouched --
    see process_suppressed_alert().
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incidents
            WHERE fingerprint = %s
              AND status IN (
                  'NEW',
                  'ACKNOWLEDGED',
                  'IN_PROGRESS',
                  'ESCALATED'
              )
            """,
            (fingerprint,),
        )

        return cur.fetchone()


def process_suppressed_alert(conn, alert: dict, cmdb: dict) -> dict | None:
    """
    Process a suppressed Alertmanager alert.

    If the alert has already been recorded as a SUPPRESSED_MAINTENANCE
    incident, no new incident is created.

    A UniqueViolation on ingest_alert()'s INSERT means this fingerprint
    collided with an existing incident on one of two indexes, and which
    one determines the response:

    - incidents_active_fingerprint_idx: an actionable incident
      (NEW/ACKNOWLEDGED/IN_PROGRESS/ESCALATED) already exists for this
      fingerprint -- e.g. the webhook created it before this maintenance
      window started. That incident is already being worked; a NOTE is
      recorded on it, and its lifecycle is left untouched. It does not
      become SUPPRESSED_MAINTENANCE.
    - incidents_suppressed_maintenance_fingerprint_idx: another
      SUPPRESSED_MAINTENANCE incident already exists for this exact
      (fingerprint, startsAt) -- suppressed_incident_exists()'s
      check-then-insert lost a race (e.g. an overlapping poll). A true
      duplicate: a NOTE is recorded on the existing suppressed incident.

    If neither lookup finds a row, the UniqueViolation is unexplained --
    re-raised rather than swallowed, since that means the uniqueness
    assumptions above have drifted from the schema.

    Returns:
        The created (or reconciled) incident, or None if the alert was
        an already-recorded suppression duplicate.
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

    try:
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

    except psycopg2.errors.UniqueViolation:
        conn.rollback()

        actionable_incident = find_actionable_incident(conn, fingerprint)

        if actionable_incident is not None:
            record_note_event(
                conn,
                actionable_incident,
                actor="maintenance",
                message="Alert also matched an active maintenance window.",
                payload=alert,
            )
            return actionable_incident

        suppressed_incident = find_suppressed_incident(conn, fingerprint, starts_at)

        if suppressed_incident is not None:
            record_note_event(
                conn,
                suppressed_incident,
                actor="maintenance",
                message="Duplicate suppressed alert observed during maintenance window.",
                payload=alert,
            )
            SUPPRESSED_ALERTS_DUPLICATE_TOTAL.inc()
            return suppressed_incident

        raise RuntimeError(
            f"Cannot resolve incident: UniqueViolation for fingerprint "
            f"{fingerprint!r} matched neither an actionable incident nor "
            f"a SUPPRESSED_MAINTENANCE incident."
        )


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

                except Exception:
                    conn.rollback()

                    logger.exception(
                        "Failed to process suppressed alert.",
                        extra={
                            "fingerprint": alert.get("fingerprint"),
                        },
                    )

            logger.debug(
                "Processed %s suppressed alerts.",
                len(alerts),
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
