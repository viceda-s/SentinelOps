from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(slots=True)
class TimelineEntry:
    occurred_at: datetime
    kind: Literal["event", "remediation_attempt"]
    sort_key: tuple[datetime, int, int]
    payload: dict[str, Any]


def build_timeline(conn, incident_id: int) -> list[TimelineEntry]:
    """
    Build a merged, deterministically ordered timeline for an incident.

    Ordering rules:
    1. occurred_at ascending
    2. incident_events before remediation_attempt when timestamps are equal
    3. Within incident_events, sequence ascending
    4. Within remediation_attempt, attempt_number ascending
    """

    timeline: list[TimelineEntry] = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                sequence,
                occurred_at,
                actor,
                event_type,
                from_status,
                to_status,
                message,
                payload
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY occurred_at, sequence
            """,
            (incident_id,),
        )

        for row in cur.fetchall():
            timeline.append(
                TimelineEntry(
                    occurred_at=row["occurred_at"],
                    kind="event",
                    sort_key=(
                        row["occurred_at"],
                        0,  # events sort before remediation attempts
                        row["sequence"],
                    ),
                    payload=row,
                )
            )

        cur.execute(
            """
            SELECT
                playbook,
                attempt_number,
                started_at,
                finished_at,
                result,
                diagnostics_path
            FROM remediation_attempts
            WHERE incident_id = %s
            ORDER BY started_at, attempt_number
            """,
            (incident_id,),
        )

        for row in cur.fetchall():
            timeline.append(
                TimelineEntry(
                    occurred_at=row["started_at"],
                    kind="remediation_attempt",
                    sort_key=(
                        row["started_at"],
                        1,  # remediation attempts sort after events
                        row["attempt_number"],
                    ),
                    payload=row,
                )
            )

    timeline.sort(key=lambda entry: entry.sort_key)

    return timeline
