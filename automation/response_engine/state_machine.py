"""
Incident state machine implementation for SentinelOps.

Enforces valid lifecycle state transitions, updates database timestamp columns,
appends audit records to `incident_events`, and records Prometheus duration metrics.
"""

import json
import logging
from datetime import datetime, timezone

from psycopg2.extensions import connection

from .events import get_next_sequence
from .metrics import (
    INCIDENT_RESOLUTION_SECONDS,
    INCIDENT_RESPONSE_SECONDS,
)

logger = logging.getLogger(__name__)

# NEW -> ESCALATED allows unknown services (not in CMDB) to escalate during enrichment before worker claim.

ALLOWED_TRANSITIONS = {
    "NEW": {"ACKNOWLEDGED", "SUPPRESSED_MAINTENANCE", "ESCALATED"},
    "ACKNOWLEDGED": {"IN_PROGRESS", "ESCALATED"},
    "ESCALATED": {"IN_PROGRESS", "RESOLVED"},
    "IN_PROGRESS": {"RESOLVED", "ESCALATED"},
    "SUPPRESSED_MAINTENANCE": {"RESOLVED"},
    "RESOLVED": {"CLOSED"},
}

STATUS_TIMESTAMPS = {
    "ACKNOWLEDGED": "acknowledged_at",
    "RESOLVED": "resolved_at",
    "CLOSED": "closed_at",
}


def transition(
    conn: connection, incident: dict, to_status: str, actor: str, message: str
) -> dict:
    """Perform a validated incident state transition.

    Args:
        conn: Active PostgreSQL connection (caller manages transactions).
            Must be opened with cursor_factory=psycopg2.extras.RealDictCursor.
        incident: Incident record dictionary.
        to_status: Target status name string.
        actor: Identity of actor triggering transition (e.g. 'worker', 'operator').
        message: Audit log description for the transition.

    Returns:
        Updated in-memory incident dictionary.

    Raises:
        ValueError: If requested state transition is not allowed.

    Notes:
        The caller owns the transaction. This function MUST NOT call commit() or rollback().
    """

    current_status = incident["status"]

    allowed = ALLOWED_TRANSITIONS.get(current_status, set())

    if to_status not in allowed:
        logger.warning(
            "Rejected transition",
            extra={
                "incident_reference": incident["reference"],
                "from_status": current_status,
                "to_status": to_status,
                "actor": actor,
            },
        )
        raise ValueError(f"Invalid transition: {current_status} -> {to_status}")

    with conn.cursor() as cur:
        # Update incident.
        timestamp_column = STATUS_TIMESTAMPS.get(to_status)

        if timestamp_column:
            cur.execute(
                f"""
                UPDATE incidents
                SET
                    status = %s,
                    {timestamp_column} = NOW()
                WHERE id = %s
                """,
                (
                    to_status,
                    incident["id"],
                ),
            )
        else:
            cur.execute(
                """
                UPDATE incidents
                SET status = %s
                WHERE id = %s
                """,
                (
                    to_status,
                    incident["id"],
                ),
            )

        # Allocate next audit sequence number.
        sequence = get_next_sequence(conn, incident["id"])

        # Insert audit event.
        cur.execute(
            """
            INSERT INTO incident_events (
                incident_id,
                sequence,
                occurred_at,
                actor,
                event_type,
                from_status,
                to_status,
                message,
                payload
            )
            VALUES (
                %s, %s, NOW(), %s, %s,
                %s, %s, %s, %s
            )
            """,
            (
                incident["id"],
                sequence,
                actor,
                "STATE_CHANGE",
                current_status,
                to_status,
                message,
                json.dumps({}),
            ),
        )

    # Keep in-memory incident dictionary in sync.

    now = datetime.now(timezone.utc)

    incident["status"] = to_status

    if to_status in STATUS_TIMESTAMPS:
        incident[STATUS_TIMESTAMPS[to_status]] = now

    if to_status == "ACKNOWLEDGED":
        INCIDENT_RESPONSE_SECONDS.observe(
            (now - incident["detected_at"]).total_seconds()
        )
    elif to_status == "RESOLVED":
        INCIDENT_RESOLUTION_SECONDS.observe(
            (now - incident["detected_at"]).total_seconds()
        )

    return incident
