"""
Incident event persistence and sequence management for SentinelOps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from psycopg2.extensions import connection
from psycopg2.extras import Json


@dataclass(frozen=True)
class DomainEvent:
    """Base for typed incident_events rows. Subclasses pin event_type."""

    event_type: ClassVar[str]

    actor: str
    message: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IncidentCreated(DomainEvent):
    event_type: ClassVar[str] = "CREATED"


@dataclass(frozen=True)
class StateChanged(DomainEvent):
    event_type: ClassVar[str] = "STATE_CHANGE"

    from_status: str = ""
    to_status: str = ""


@dataclass(frozen=True)
class IncidentAcknowledged(StateChanged):
    to_status: str = "ACKNOWLEDGED"


@dataclass(frozen=True)
class RemediationStarted(DomainEvent):
    event_type: ClassVar[str] = "REMEDIATION_STARTED"


@dataclass(frozen=True)
class RemediationCompleted(DomainEvent):
    event_type: ClassVar[str] = "REMEDIATION_COMPLETED"


@dataclass(frozen=True)
class SLABreached(DomainEvent):
    event_type: ClassVar[str] = "SLA_BREACHED"


@dataclass(frozen=True)
class ReportGenerated(DomainEvent):
    event_type: ClassVar[str] = "REPORT_GENERATED"


def get_next_sequence(conn: connection, incident_id: int) -> int:
    """
    Allocate the next sequence number for an incident's events.

    Acquires an exclusive row-level lock ('FOR UPDATE') on the target incident row,
    serializing concurrent event creation for the same incident.

    Args:
        conn: Active PostgreSQL connection (caller owns the transaction).
        incident_id: Database primary key of the target incident.

    Returns:
        int: Allocated next sequence number (>= 1).

    Raises:
        ValueError: If no incident matching incident_id exists in the database.

    Notes:
        The caller owns the transaction. This function MUST NOT call commit() or rollback().
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM incidents
            WHERE id = %s
            FOR UPDATE
            """,
            (incident_id,),
        )

        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Incident {incident_id} does not exist.")

        cur.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
            FROM incident_events
            WHERE incident_id = %s
            """,
            (incident_id,),
        )

        return cur.fetchone()["next_sequence"]


def record_event(conn: connection, incident_id: int, event: DomainEvent) -> None:
    """
    Persist a typed domain event to an incident's audit trail.

    Allocates the next sequence number and inserts one incident_events row.
    The caller owns the transaction. This function MUST NOT call commit() or rollback().
    """
    sequence = get_next_sequence(conn, incident_id)

    from_status = getattr(event, "from_status", None)
    to_status = getattr(event, "to_status", None)

    with conn.cursor() as cur:
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
                %s, %s, NOW(), %s, %s, %s, %s, %s, %s
            )
            """,
            (
                incident_id,
                sequence,
                event.actor,
                event.event_type,
                from_status,
                to_status,
                event.message,
                Json(event.payload),
            ),
        )
