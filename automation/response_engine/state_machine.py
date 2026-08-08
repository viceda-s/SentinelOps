import json
import logging
from datetime import datetime, timezone

from .metrics import (
    INCIDENT_RESOLUTION_SECONDS,
    INCIDENT_RESPONSE_SECONDS,
)

logger = logging.getLogger(__name__)

# NEW -> ESCALATED (in addition to DESIGN.md v1.0's NEW -> ACKNOWLEDGED | SUPPRESSED_MAINTENANCE) is a deliberate deviation from the frozen design, not an oversight. An unknown service (not in the CMDB) has to escalate straight out of enrichment, before any worker has claimed it -- see implementation-findings.md. Faking an ACKNOWLEDGED event to satisfy the original table would misrepresent the audit trail, since ACKNOWLEDGED specifically means "claimed by a worker."

#
# SUPPRESSED_MAINTENANCE is reserved for the Phase 2 maintenance-window feature.
# No Phase 1 code path currently enters this state.
#
# SUPPRESSED_MAINTENANCE -> RESOLVED is its only legal exit. Nothing currently calls it automatically -- no code path observes an Alertmanager alert recovering and resolves the matching incident. Until that exists, an incident that enters this state stays here until an operator resolves it by hand.
#
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


def transition(conn, incident, to_status, actor, message):
    """
    Perform a validated incident state transition.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().

    conn must be opened with cursor_factory=psycopg2.extras.RealDictCursor —
    incident is expected to support dict-style access (incident["status"]),
    and this function's own queries rely on the same convention.
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
        #
        # Update incident
        #

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

        #
        # Next sequence number
        #

        cur.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
            FROM incident_events
            WHERE incident_id = %s
            """,
            (incident["id"],),
        )

        sequence = cur.fetchone()["next_sequence"]

        #
        # Insert audit event
        #

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

    #
    # Keep the in-memory object in sync
    #

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
