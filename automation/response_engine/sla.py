from __future__ import annotations

from psycopg2.extras import Json

from .metrics import SLA_BREACHES_TOTAL

_RESPONSE_BREACH_SQL = """
UPDATE incidents
SET sla_response_breached = TRUE
WHERE
    status IN ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'ESCALATED')
    AND sla_response_breached = FALSE
    AND clock_timestamp () >
        detected_at + make_interval(mins => sla_response_minutes)
RETURNING id;
"""

_RESOLUTION_BREACH_SQL = """
UPDATE incidents
SET sla_resolution_breached = TRUE
WHERE
    status IN ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'ESCALATED')
    AND sla_resolution_breached = FALSE
    AND clock_timestamp () >
        detected_at + make_interval(mins => sla_resolution_minutes)
RETURNING id;
"""


def _check_one(conn, sql: str, breach_type: str, message: str) -> None:
    """
    Execute one SLA breach check (response or resolution).

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        breached = cur.fetchall()
        for incident in breached:
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
                VALUES(
                    %s,
                    %s,
                    NOW(),
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    incident["id"],
                    sequence,
                    "worker",
                    "NOTE",
                    message,
                    Json({}),
                ),
            )

            SLA_BREACHES_TOTAL.labels(type=breach_type).inc()


def check_sla_breaches(conn) -> None:
    """
    Flag incidents whose response or resolution SLA has expired.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
    """
    _check_one(conn, _RESPONSE_BREACH_SQL, "response", "Response SLA breached.")

    _check_one(conn, _RESOLUTION_BREACH_SQL, "resolution", "Resolution SLA breached.")
