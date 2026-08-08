from __future__ import annotations

import os

import psycopg2
import psycopg2.extras


def get_connection():
    """
    Create a PostgreSQL connection.

    Returns:
        A new PostgreSQL connection using the response engine database credentials.
    """

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.environ["RESPONSE_ENGINE_DB_USER"],
        password=os.environ["RESPONSE_ENGINE_DB_PASSWORD"],
        dbname=os.getenv("POSTGRES_DB", "postgres"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
