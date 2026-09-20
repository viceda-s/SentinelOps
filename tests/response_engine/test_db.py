from __future__ import annotations

from psycopg2.extras import RealDictCursor

from automation.response_engine.db import get_connection


def test_get_connection_uses_provided_settings(database_settings):
    conn = get_connection(database_settings)
    try:
        assert conn.cursor_factory is RealDictCursor
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS one")
            assert cur.fetchone() == {"one": 1}
    finally:
        conn.close()


def test_get_connection_defaults_to_settings_from_env(monkeypatch, database_settings):
    monkeypatch.setenv("RESPONSE_ENGINE_DB_USER", database_settings.user)
    monkeypatch.setenv("RESPONSE_ENGINE_DB_PASSWORD", database_settings.password)
    monkeypatch.setenv("POSTGRES_HOST", database_settings.host)
    monkeypatch.setenv("POSTGRES_DB", database_settings.dbname)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS one")
            assert cur.fetchone() == {"one": 1}
    finally:
        conn.close()
