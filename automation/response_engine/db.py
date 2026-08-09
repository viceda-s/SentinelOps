"""
Database connection factory for the SentinelOps response engine.

Provides helper functions for instantiating PostgreSQL connections configured with
`RealDictCursor` for dictionary-style row access.
"""

from __future__ import annotations

import os

import psycopg2
import psycopg2.extras


def get_connection():
    """
    Create a PostgreSQL connection configured for response engine services.

    Reads database credentials from environment variables (`RESPONSE_ENGINE_DB_USER`,
    `RESPONSE_ENGINE_DB_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`).

    Returns:
        psycopg2.connection: A new PostgreSQL connection using RealDictCursor.
    """

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.environ["RESPONSE_ENGINE_DB_USER"],
        password=os.environ["RESPONSE_ENGINE_DB_PASSWORD"],
        dbname=os.getenv("POSTGRES_DB", "postgres"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
