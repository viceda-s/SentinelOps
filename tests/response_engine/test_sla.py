from datetime import datetime, timedelta, timezone

from prometheus_client import Counter

from automation.response_engine.metrics import SLA_BREACHES_TOTAL
from automation.response_engine.sla import check_sla_breaches


def counter_value(counter: Counter, **labels) -> float:
    """Return the current value of a labeled Counter."""
    metric = next(iter(counter.collect()))

    for sample in metric.samples:
        if sample.name.endswith("_total") and sample.labels == labels:
            return sample.value

    return 0.0


def test_response_sla_breached(db_connection, make_incident):
    incident = make_incident(
        status="NEW",
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        sla_response_minutes=5,
    )

    before = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    check_sla_breaches(db_connection)

    after = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    assert after == before + 1

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT sla_response_breached
            FROM incidents
            WHERE id = %s
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["sla_response_breached"] is True

        cur.execute(
            """
            SELECT actor, event_type, message
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (incident["id"],),
        )

        event = cur.fetchone()

        assert event["actor"] == "worker"
        assert event["event_type"] == "NOTE"
        assert event["message"] == "Response SLA breached."


def test_response_sla_not_breached(db_connection, make_incident):
    incident = make_incident(
        status="NEW",
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        sla_response_minutes=5,
    )

    before = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    check_sla_breaches(db_connection)

    after = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    assert after == before

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT sla_response_breached
            FROM incidents
            WHERE id = %s
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["sla_response_breached"] is False

        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incident_events
            WHERE incident_id = %s
              AND message = 'Response SLA breached.'
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["count"] == 0


def test_resolution_sla_breached(db_connection, make_incident):
    incident = make_incident(
        status="IN_PROGRESS",
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=90),
        sla_resolution_minutes=60,
    )

    before = counter_value(
        SLA_BREACHES_TOTAL,
        type="resolution",
    )

    check_sla_breaches(db_connection)

    after = counter_value(
        SLA_BREACHES_TOTAL,
        type="resolution",
    )

    assert after == before + 1

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT sla_resolution_breached
            FROM incidents
            WHERE id = %s
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["sla_resolution_breached"] is True

        cur.execute(
            """
            SELECT actor, event_type, message
            FROM incident_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (incident["id"],),
        )

        event = cur.fetchone()

        assert event["actor"] == "worker"
        assert event["event_type"] == "NOTE"
        assert event["message"] == "Resolution SLA breached."


def test_sla_breach_is_idempotent(db_connection, make_incident):
    incident = make_incident(
        status="NEW",
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        sla_response_minutes=5,
    )

    before = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    check_sla_breaches(db_connection)
    check_sla_breaches(db_connection)

    after = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    assert after == before + 1

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incident_events
            WHERE incident_id = %s
              AND message = 'Response SLA breached.'
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["count"] == 1


def test_terminal_incident_is_ignored(db_connection, make_incident):
    incident = make_incident(
        status="CLOSED",
        detected_at=datetime.now(timezone.utc) - timedelta(days=1),
        sla_response_minutes=5,
        sla_resolution_minutes=60,
    )

    before = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    check_sla_breaches(db_connection)

    after = counter_value(
        SLA_BREACHES_TOTAL,
        type="response",
    )

    assert after == before

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT
              sla_response_breached,
              sla_resolution_breached
            FROM incidents
            WHERE id = %s
            """,
            (incident["id"],),
        )

        row = cur.fetchone()

        assert row["sla_response_breached"] is False
        assert row["sla_resolution_breached"] is False

        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM incident_events
            WHERE incident_id = %s
              AND actor = 'worker'
              AND event_type = 'NOTE'
            """,
            (incident["id"],),
        )

        assert cur.fetchone()["count"] == 0
