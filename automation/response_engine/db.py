"""
Database connection factory for the SentinelOps response engine.

Provides helper functions for instantiating PostgreSQL connections configured with
`RealDictCursor` for dictionary-style row access.
"""

from __future__ import annotations

import psycopg2
import psycopg2.extras

from .config import DatabaseSettings


def get_connection(settings: DatabaseSettings | None = None):
    """
    Create a PostgreSQL connection configured for response engine services.

    Reads database credentials from DatabaseSettings configuration object or environment.

    Returns:
        psycopg2.connection: A new PostgreSQL connection using RealDictCursor.
    """
    if settings is None:
        settings = DatabaseSettings.from_env()

    return psycopg2.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        dbname=settings.dbname,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
