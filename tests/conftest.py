from __future__ import annotations

import itertools
import os
from datetime import datetime, timezone

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor


def required_env(name: str) -> str:
    """Return the value of a required environment variable or fail fast with an helpful error."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Run tests via ./automation/scripts/test.sh or load .env first."
        )
    return value


_reference_counter = itertools.count(1)


@pytest.fixture
def db_connection():
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=required_env("POSTGRES_DB"),
        user=required_env("POSTGRES_USER"),
        password=required_env("POSTGRES_PASSWORD"),
        cursor_factory=RealDictCursor,
    )

    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def make_incident(db_connection):
    def _make_incident(**overrides):
        n = next(_reference_counter)

        values = {
            "reference": f"INC-{n:06d}",
            "fingerprint": f"fingerprint-{n}",
            "alert_name": "ServiceDown",
            "service": "api",
            "severity": "critical",
            "status": "NEW",
            "detected_at": datetime.now(timezone.utc),
            "labels": Json({}),
            "annotations": Json({}),
            # Behaviourally required defaults.
            "sla_response_minutes": 5,
            "sla_resolution_minutes": 60,
        }

        values.update(overrides)

        columns = ", ".join(values.keys())
        placeholders = ", ".join(["%s"] * len(values))

        with db_connection.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO incidents ({columns})
                VALUES ({placeholders})
                RETURNING *
                """,
                list(values.values()),
            )
            return cur.fetchone()

    return _make_incident
