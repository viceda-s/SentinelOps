from __future__ import annotations

from .state_machine import transition


def claim_incident(conn) -> dict | None:
    """
    Claim the oldest NEW incident.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()

    Returns:
        The claimed incident (now ACKNOWLEDGED), or None if no claimable incidents exist.
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
