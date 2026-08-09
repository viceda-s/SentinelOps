"""
Maintenance window monitor for SentinelOps.

Polls Alertmanager for silenced alerts, ingests suppressed alerts into PostgreSQL under
the `SUPPRESSED_MAINTENANCE` state, and reconciles collisions with active incidents.
"""

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
    Fetch active alerts currently suppressed by Alertmanager silences.

    Alerts are returned in chronological order by ``startsAt`` so that processing order is deterministic.

    Raises:
        requests.exceptions.RequestException:
            If the Alertmanager request fails.
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

    # Parse timestamps before sorting to ensure chronological ordering.

    alerts.sort(
        key=lambda alert: datetime.fromisoformat(
            alert["startsAt"].replace("Z", "+00:00")
        )
    )

    return alerts


def suppressed_incident_exists(conn, fingerprint: str, starts_at: str) -> bool:
    """
    Check whether this Alertmanager firing has already been recorded as a SUPPRESSED_MAINTENANCE incident.

    The fingerprint identifies the alert identity; ``startsAt`` distinguishes a later firing of the same alert after it has resolved.
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
    Return the existing SUPPRESSED_MAINTENANCE incident for this firing, if any.

    This uses the same identity as ``suppressed_incident_exists()`` and is used when the database reports a concurrent duplicate during ingestion.
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
    Return the open actionable incident for this fingerprint, if one exists.

    This is the incident protected by ``incidents_active_fingerprint_idx``.
    A maintenance-suppressed alert may collide with it when the incident was created before the maintenance window began. Its lifecycle remains unchanged; the maintenance path only records reconciliation notes.
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
    Record an active Alertmanager-suppressed alert as a maintenance incident.

    A previously recorded SUPPRESSED_MAINTENANCE incident is treated as a duplicate and does not create another incident.

    If ingestion conflicts with an existing actionable incident, that incident remains unchanged and receives at most one reconciliation NOTE per active Alertmanager silence.

    If ingestion conflicts with an existing SUPPRESSED_MAINTENANCE incident, the existing incident receives a duplicate NOTE.

    Unexpected uniqueness violations are re-raised rather than silently reconciled.

    Returns:
        The created or reconciled incident, or None for an already-recorded maintenance suppression.
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
            # Reconcile each silence independently. Partial unique index prevents duplicate notes.
            for silence_id in alert["status"]["silencedBy"]:
                with conn.cursor() as cur:
                    cur.execute("SAVEPOINT maintenance_note")

                    try:
                        record_note_event(
                            conn,
                            actionable_incident,
                            actor="maintenance",
                            message=(
                                "Alert also matched an active maintenance "
                                f"window (silence {silence_id})."
                            ),
                            payload=alert,
                            silence_id=silence_id,
                        )

                    except psycopg2.errors.UniqueViolation as exc:
                        # Ignore unique violation only for maintenance-silence index; re-raise others.
                        if (
                            exc.diag.constraint_name
                            != "incident_events_maintenance_silence_idx"
                        ):
                            raise

                        cur.execute("ROLLBACK TO SAVEPOINT maintenance_note")
                        cur.execute("RELEASE SAVEPOINT maintenance_note")

                        logger.debug(
                            "Reconciliation NOTE already recorded for silence.",
                            extra={
                                "incident_id": actionable_incident["id"],
                                "silence_id": silence_id,
                            },
                        )

                    else:
                        cur.execute("RELEASE SAVEPOINT maintenance_note")

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

    Poll Alertmanager continuously and record active silenced alerts as SUPPRESSED_MAINTENANCE incidents.

    The process continues after individual alert, Alertmanager, and unexpected iteration failures. The heartbeat advances only after an entire poll completes successfully.
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

            # Heartbeat advances only after a successful poll iteration completes.

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
