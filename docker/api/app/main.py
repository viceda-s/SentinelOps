import os
import time

from flask import Flask, jsonify, request
import psycopg2
from psycopg2 import OperationalError
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST
)

app = Flask(__name__)

#
# Prometheus metrics
#

API_REQUESTS_TOTAL = Counter(
    "api_requests_total",
    "Total number of API Requests",
    ["methods", "endpoint", "status"],
)

API_ERRORS_TOTAL = Counter(
    "api_errors_total",
    "Total number of server errors (5xx)",
    ["endpoint"],
)

API_REQUEST_LATENCY_SECONDS = Histogram(
    "api_request_latency_seconds",
    "API request latency in seconds",
    ["endpoint"],
)

def get_db_connection():
    """
    Create a new PostgreSQL connection using environment variables.

    Connection is created lazily per request so the application can start even if PostgreSQL is not yet accepting connections.
    """
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.getenv("POSTGRES_DB", "postgres"),
    )

def record_metrics(endpoint: str, status_code: int, start_time: float):
    """
    Record latency, request count and server errors.
    """
    elapsed = time.perf_counter() - start_time

    API_REQUEST_LATENCY_SECONDS.labels(endpoint=endpoint).observe(elapsed)

    API_REQUESTS_TOTAL.labels(
        methods=request.method,
        endpoint=endpoint,
        status=str(status_code),
    ).inc()

    if status_code >= 500:
        API_ERRORS_TOTAL.labels(endpoint=endpoint).inc()


@app.route("/health")
def health():
    start = time.perf_counter()

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        finally:
            conn.close()

        status = 200
        response = jsonify(
            {
                "status": "healthy",
                "database": "up",
            }
        )

    except OperationalError as exc:
        # Postgres unreachable, refusing connections, auth failure, etc.
        # This is the failure mode chaos.sh dependency is meant to trigger.
        status = 503
        response = jsonify(
            {
                "status": "unhealthy",
                "database": "down",
                "error": str(exc),
            }
        )

    record_metrics("/health", status, start)
    return response, status


@app.route("/items")
def items():
    start = time.perf_counter()

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # Placeholder table expected to exist.
                cur.execute("SELECT * FROM items;")

                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()

                result = [
                    dict(zip(columns, row))
                    for row in rows
                ]
        finally:
            conn.close()

        status = 200
        response = jsonify(result)

    except OperationalError as exc:
        # Postgres unreachable: the dependency is down, not our code.
        status = 503
        response = jsonify(
            {
                "error": "Database unavailable",
                "details": str(exc),
            }
        )

    except psycopg2.Error as exc:
        # Postgres unreachable: the dependency is down, not our code.
        status = 500
        response = jsonify(
            {
                "error": "Database query failed",
                "details": str(exc),
            }
        )

    record_metrics("/items", status, start)
    return response, status

@app.route("/metrics")
def metrics():
    return (
        generate_latest(),
        200,
        {"Content-Type": CONTENT_TYPE_LATEST},
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
