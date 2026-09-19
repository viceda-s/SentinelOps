from __future__ import annotations

from datetime import datetime, timedelta, timezone

from automation.response_engine.claim import claim_incident


def test_claim_incident_returns_none_when_no_new_incidents(db_connection):
    claimed = claim_incident(db_connection)

    assert claimed is None


def test_claim_incident_claims_oldest_new_incident(db_connection, make_incident):
    older = make_incident(
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=10), status="NEW"
    )
    make_incident(
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=5), status="NEW"
    )

    claimed = claim_incident(db_connection)

    assert claimed["id"] == older["id"]
    assert claimed["status"] == "ACKNOWLEDGED"


def test_claim_incident_ignores_non_new_incidents(db_connection, make_incident):
    make_incident(status="ACKNOWLEDGED")

    claimed = claim_incident(db_connection)

    assert claimed is None


def test_claim_incident_records_transition_event(db_connection, make_incident):
    incident = make_incident(status="NEW")

    claim_incident(db_connection)

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT actor, event_type, from_status, to_status
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (incident["id"],),
        )
        event = cur.fetchone()

    assert event["actor"] == "worker"
    assert event["event_type"] == "STATE_CHANGE"
    assert event["from_status"] == "NEW"
    assert event["to_status"] == "ACKNOWLEDGED"
