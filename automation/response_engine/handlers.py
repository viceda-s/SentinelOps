from __future__ import annotations

import logging
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json

from .state_machine import transition

logger = logging.getLogger(__name__)

TERMINAL_STATES = (
    "CLOSED",
    "SUPPRESSED_MAINTENANCE",
)

def handle_alert(conn, alert: dict, cmdb: dict) -> None:
    """
    Process a single Alertmanager alert.

    Responsibilities:
        - extract Alertmanager fields
        - enrich from the CMDB
        - resolve the playbook
        - create a NEW incident
        - create the initial CREATED event
        - deduplicate using the database unique constraint
        - immediately escalate unknown services
    """

    #
    # Phase 1 only processes firing alerts
    #

    if alert.get("status") != "firing":
        logger.info(
            "Ignoring non-firing alert",
            extra={
                "status": alert.get("status"),
                "fingerprint": alert.get("fingerprint"),
            },
        )
        return

    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}

    fingerprint = alert["fingerprint"]
    alert_name = labels["alertname"]
    service = labels["job"]
    severity = labels["severity"]
    detected_at = alert["startsAt"]

    (
        owner,
        tier,
        criticality,
        playbook,
        sla_response,
        sla_resolution,
        known_service,
    ) = resolve_cmdb_entry(
        cmdb,
        service,
        alert_name,
    )

    #
    # Alertmanager carries a playbook too.
    # The CMDB is authoritative; mismatches are logged.
    #

    alertmanager_playbook = labels.get("playbook")

    if (alertmanager_playbook is not None and alertmanager_playbook != playbook):
        logger.warning(
            "Playbook mismatch",
            extra={
                "service": service,
                "alert": alert_name,
                "cmdb_playbook": playbook,
                "alertmanager_playbook": alertmanager_playbook,
            },
        )

    reference = generate_reference(conn)

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO incidents (
                    reference,
                    fingerprint,
                    alert_name,
                    service,
                    severity,
                    status,
                    owner,
                    tier,
                    criticality,
                    playbook,
                    detected_at,
                    sla_response_minutes,
                    sla_resolution_minutes,
                    labels,
                    annotations
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'NEW',
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                RETURNING *
                """,
                (
                    reference,
                    fingerprint,
                    alert_name,
                    service,
                    severity,
                    owner,
                    tier,
                    criticality,
                    playbook,
                    detected_at,
                    sla_response,
                    sla_resolution,
                    Json(labels),
                    Json(annotations),
                ),
            )

            incident = cur.fetchone()

            cur.execute(
                """
                INSERT INTO incident_events (
                    incident_id,
                    sequence,
                    occurred_at,
                    actor,
                    event_type,
                    message,
                    payload
                )
                VALUES (
                    %s,
                    %s,
                    NOW(),
                    'alertmanager',
                    'CREATED',
                    %s,
                    %s
                )
                """,
                (
                    incident["id"],
                    1,
                    f"{alert_name} received",
                    Json(alert),
                ),
                )

            #
            # Incidents that cannot be remediated automatically escalate immediately.
            #

            if not known_service:
                transition(
                    conn,
                    incident,
                    "ESCALATED",
                    "webhook_handler",
                    "Unknown service in CMDB",
                )

            elif playbook == "none":
                transition(
                    conn,
                    incident,
                    "ESCALATED",
                    "webhook_handler",
                    f"No playbook configured for alert {alert_name!r}",
                )

        conn.commit()

    except psycopg2.errors.UniqueViolation:

        conn.rollback()

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
                (fingerprint,)
            )

            incident = cur.fetchone()

            if incident is None:
                raise RuntimeError(f"Cannot resolve incident: no active incident exists for fingerprint {fingerprint!r}")

            cur.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1
                AS next_sequence
                FROM incident_events
                WHERE incident_id = %s
                """,
                (incident["id"],),
            )

            sequence = cur.fetchone()["next_sequence"]

            cur.execute(
                """
                INSERT INTO incident_events (
                    incident_id,
                    sequence,
                    occurred_at,
                    actor,
                    event_type,
                    message,
                    payload
                )
                VALUES (
                    %s,
                    %s,
                    NOW(),
                    'alertmanager',
                    'NOTE',
                    %s,
                    %s
                )
                """,
                (
                    incident["id"],
                    sequence,
                    "Duplicate Alertmanager notification received",
                    Json(alert),
                ),
            )

        conn.commit()


def resolve_cmdb_entry(cmdb: dict, service: str, alert_name: str):
    """
    Resolve service metadata from the CMDB.

    Unknown services deliberately fallback to unassigned/unknown/none and are escalated immediately after creation.
    """

    services = cmdb["services"]

    if service not in services:
        return (
            "unassigned",
            "unknown",
            "unknown",
            "none",
            0,
            0,
            False,
        )

    entry = services[service]

    # "none" is an internal sentinel meaning this alert has no configured playbook. It is not a valid playbook name in the CMDB itself.
    playbook = entry.get("playbooks", {},).get(alert_name,"none")

    sla = entry["sla"]

    return (
        entry["owner"],
        entry["tier"],
        entry["criticality"],
        playbook,
        sla["response_minutes"],
        sla["resolution_minutes"],
        True,
    )


def generate_reference(conn) -> str:
    """
    Allocate a unique incident reference

    References are sequential per UTC calendar year and are allocated atomically using PostgreSQL row-level locking.

    The counter update participates in the caller's transaction, so a rollback also rolls back the allocated reference number.
    """

    year = datetime.now(timezone.utc).year

    with conn.cursor() as cur:

        cur.execute (
            """
            INSERT INTO incident_reference_counters (
                year,
                next_value
            )
            VALUES (
                %s,
                1
            )
            ON CONFLICT (year)
            DO UPDATE
            SET next_value = incident_reference_counters.next_value + 1
            RETURNING next_value
            """,
            (year,)
        )

        counter = cur.fetchone()["next_value"]

    return f"INC-{year}-{counter:04d}"

