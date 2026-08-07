from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg2
import yaml
from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from psycopg2.extras import RealDictCursor
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from .handlers import handle_alert
from .logging_config import configure_logging

#
# Gunicorn imports this module rather than executing __main__,
# so logging must be configured at import time.
#

configure_logging()

logger = logging.getLogger(__name__)

app = Flask(__name__)

#
# CMDB
#

CMDB_PATH = Path(
    os.environ.get(
        "CMDB_PATH",
        "/app/cmdb/services.yaml",
    )
)

with CMDB_PATH.open("r", encoding="utf-8") as f:
    cmdb = yaml.safe_load(f)


def get_connection():
    """
    Return a new PostgreSQL connection.

    Connections are request-scoped.
    """

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.environ["RESPONSE_ENGINE_DB_USER"],
        password=os.environ["RESPONSE_ENGINE_DB_PASSWORD"],
        dbname=os.getenv("POSTGRES_DB", "postgres"),
        cursor_factory=RealDictCursor,
    )


@app.post("/alerts")
def alerts():
    """
    Receive Alertmanager webhooks.

    Response codes:

        200  Alert(s) successfully persisted.
        400  Malformed payload.
        500  Internal error (Alertmanager should retry).
    """

    try:
        payload = request.get_json()

        if not isinstance(payload, dict):
            return jsonify(
                error="Payload must be a JSON object.",
            ), 400

        alerts = payload["alerts"]

        if not isinstance(alerts, list):
            return jsonify(
                error="'alerts' must be a list.",
            ), 400

        with get_connection() as conn:
            for alert in alerts:
                handle_alert(
                    conn,
                    alert,
                    cmdb,
                )

        return "", 200

    except (
        KeyError,
        TypeError,
        BadRequest,
        UnsupportedMediaType,
    ):
        logger.warning(
            "Malformed Alertmanager payload.",
            exc_info=True,
        )

        return jsonify(
            error="Malformed Alertmanager payload.",
        ), 400

    except Exception:
        logger.exception(
            "Failed to process Alertmanager webhook.",
        )

        return jsonify(
            error="Internal server error.",
        ), 500


@app.get("/metrics")
def metrics():
    """Expose Prometheus metrics."""

    return Response(
        generate_latest(),
        content_type=CONTENT_TYPE_LATEST,
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
    )
