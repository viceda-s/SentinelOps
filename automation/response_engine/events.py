"""
Incident event persistence and sequence management for SentinelOps.
"""

from __future__ import annotations


def get_next_sequence(conn, incident_id: int) -> int:
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
