"""
Alert and incident ingestion handlers for SentinelOps.

Handles parsing Alertmanager webhook payloads, CMDB enrichment, incident reference allocation,
timeline note event recording, and initial lifecycle transitions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json

from .metrics import INCIDENTS_CREATED_TOTAL
from .state_machine import transition

logger = logging.getLogger(__name__)

TERMINAL_STATES = (
    "CLOSED",
    "SUPPRESSED_MAINTENANCE",
)


def record_note_event(
    conn,
    incident: dict,
    *,
    actor: str,
    message: str,
    payload: dict | None = None,
    silence_id: str | None = None,
) -> None:
    """
    Append a NOTE event to an incident's timeline.

    Args:
        conn: Active PostgreSQL connection (caller manages transactions).
        incident: Incident dictionary record.
        actor: Identity string of the actor creating the note.
        message: Descriptive message string for the note event.
        payload: Optional dictionary payload attached to the note.
        silence_id: Optional Alertmanager silence ID. When provided, the
            `incident_events_maintenance_silence_idx` partial unique constraint
            guarantees at most one note per (incident, silence).

    Raises:
        psycopg2.errors.UniqueViolation: If silence_id is specified and a note for
            that silence_id has already been recorded on this incident.

    Notes:
        The caller owns the transaction. This function MUST NOT call commit() or rollback().
    """

    if payload is None:
        payload = {}

    with conn.cursor() as cur:
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
                payload,
                silence_id
            )
            VALUES (
                %s,
                %s,
                NOW(),
                %s,
                'NOTE',
                %s,
                %s,
                %s
            )
            """,
            (
                incident["id"],
                sequence,
                actor,
                message,
                Json(payload),
                silence_id,
            ),
        )


def ingest_alert(
    conn,
    alert: dict,
    cmdb: dict,
    source: str,
) -> dict:
    """
    Create a NEW incident from an Alertmanager alert.

    Responsibilities:
        - extract Alertmanager fields
        - resolve service metadata from the CMDB
        - resolve the playbook
        - generate an incident reference
        - insert the incident
        - record the initial CREATED event
        - increment incident creation metrics

    Deliberately policy-free:
        - does not decide the incident lifecycle
        - callers decide whether to leave the incident NEW,
          ESCALATE it, SUPPRESS it, etc. via transition()

    Transaction ownership:
        - the caller owns the transaction
        - this function MUST NOT call commit() or rollback()

    Returns:
        The newly created incident row.
    """

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
        _,
    ) = resolve_cmdb_entry(
        cmdb,
        service,
        alert_name,
    )

    reference = generate_reference(conn)

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

        #
        # Best-effort telemetry: Prometheus metrics are not transactionally coupled to PostgreSQL, so this may diverge if the transaction later rolls back.
        #

        INCIDENTS_CREATED_TOTAL.labels(
            service=incident["service"],
            severity=incident["severity"],
        ).inc()

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
                %s,
                'CREATED',
                %s,
                %s
            )
            """,
            (
                incident["id"],
                1,
                source,
                f"{alert_name} received",
                Json(alert),
            ),
        )

    return incident


def handle_alert(conn, alert: dict, cmdb: dict) -> None:
    """
    Process a single Alertmanager alert.

    Responsibilities:
        - process firing alerts only
        - validate Alertmanager metadata against the CMDB
        - create or retrieve the incident
        - apply webhook-specific lifecycle policy
        - deduplicate duplicate Alertmanager notifications
    """

    #
    # The webhook handler only processes firing alerts; non-firing notifications are ignored.
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

    alert_name = labels["alertname"]
    service = labels["job"]
    fingerprint = alert["fingerprint"]

    #
    # Alertmanager carries a playbook too.
    # The CMDB is authoritative; mismatches are logged.
    #
    (
        _owner,
        _tier,
        _criticality,
        playbook,
        _sla_response,
        _sla_resolution,
        known_service,
    ) = resolve_cmdb_entry(
        cmdb,
        service,
        alert_name,
    )

    alertmanager_playbook = labels.get("playbook")

    if alertmanager_playbook is not None and alertmanager_playbook != playbook:
        logger.warning(
            "Playbook mismatch",
            extra={
                "service": service,
                "alert": alert_name,
                "cmdb_playbook": playbook,
                "alertmanager_playbook": alertmanager_playbook,
            },
        )

    try:
        incident = ingest_alert(
            conn,
            alert,
            cmdb,
            source="webhook_handler",
        )

        #
        # Webhook-specific lifecycle policy.
        #
        # Incidents that cannot be remediated automatically
        # escalate immediately after creation.
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

    #
    # Duplicate Alertmanager notifications are expected.
    #
    # The active-incident unique constraint guarantees only one
    # actionable incident exists per fingerprint. Later notifications
    # are recorded as NOTE events on the existing incident.
    #

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
                (fingerprint,),
            )

            incident = cur.fetchone()

        if incident is None:
            raise RuntimeError(
                f"Cannot resolve incident: no active incident exists for fingerprint {fingerprint!r}"
            )

        record_note_event(
            conn,
            incident,
            actor="webhook_handler",
            message="Duplicate Alertmanager notification received",
            payload=alert,
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
    playbook = entry.get(
        "playbooks",
        {},
    ).get(alert_name, "none")

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

    The counter update participates in the caller's transaction, so a rollback also rolls back the allocated reference number. This also means the current year's counter row stays locked for the duration of the caller's transaction -- concurrent handle_alert() calls serialize on this row rather than allocating independently.
    """

    year = datetime.now(timezone.utc).year

    with conn.cursor() as cur:
        cur.execute(
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
            (year,),
        )

        counter = cur.fetchone()["next_value"]

    return f"INC-{year}-{counter:04d}"
