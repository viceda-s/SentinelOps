"""
SLA breach detection module for SentinelOps.

Asynchronously monitors open incidents against target response and resolution windows
using PostgreSQL `clock_timestamp()` duration checks, updates breach flags, and records
audit note events and Prometheus metrics.
"""

from __future__ import annotations

import logging

from psycopg2.extensions import connection
from psycopg2.extras import Json

from .events import get_next_sequence
from .metrics import SLA_BREACHES_TOTAL

_RESPONSE_BREACH_SQL = """
UPDATE incidents
SET sla_response_breached = TRUE
WHERE
    status IN ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'ESCALATED')
    AND sla_response_breached = FALSE
    AND clock_timestamp () >
        detected_at + make_interval(mins => sla_response_minutes)
RETURNING id, reference;
"""

_RESOLUTION_BREACH_SQL = """
UPDATE incidents
SET sla_resolution_breached = TRUE
WHERE
    status IN ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'ESCALATED')
    AND sla_resolution_breached = FALSE
    AND clock_timestamp () >
        detected_at + make_interval(mins => sla_resolution_minutes)
RETURNING id, reference;
"""

logger = logging.getLogger(__name__)


def _check_one(conn: connection, sql: str, breach_type: str, message: str) -> None:
    """
    Execute one SLA breach check (response or resolution).

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        breached = cur.fetchall()
        for incident in breached:
            sequence = get_next_sequence(conn, incident["id"])

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

            logger.info(
                message,
                extra={
                    "incident_reference": incident["reference"],
                },
            )


def check_sla_breaches(conn: connection) -> None:
    """
    Flag incidents whose response or resolution SLA has expired.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
    """
    _check_one(conn, _RESPONSE_BREACH_SQL, "response", "Response SLA breached.")

    _check_one(conn, _RESOLUTION_BREACH_SQL, "resolution", "Resolution SLA breached.")
