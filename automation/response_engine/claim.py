"""
Incident claiming logic for SentinelOps remediation workers.

Acquires available `NEW` incidents using PostgreSQL row locking (`FOR UPDATE SKIP LOCKED`)
to ensure concurrency safety across worker instances.
"""

from __future__ import annotations

from .state_machine import transition


def claim_incident(conn) -> dict | None:
    """
    Claim the oldest unhandled `NEW` incident for remediation.

    Uses `FOR UPDATE SKIP LOCKED` to safely select and lock an unclaimed incident row,
    preventing race conditions when multiple worker processes execute concurrently.

    Args:
        conn: Active PostgreSQL connection (caller manages transactions).

    Returns:
        The claimed incident dictionary (now transitioned to `ACKNOWLEDGED`),
        or None if no claimable `NEW` incidents exist.

    Notes:
        The caller owns the transaction. This function MUST NOT call commit() or rollback().
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM incidents
            WHERE status = 'NEW'
            ORDER BY detected_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )

        incident = cur.fetchone()

        if incident is None:
            return None

        incident = transition(
            conn,
            incident,
            "ACKNOWLEDGED",
            "worker",
            "Incident claimed by worker",
        )

        return incident
