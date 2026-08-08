from __future__ import annotations

import logging

from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from .cmdb import load_cmdb
from .db import get_connection
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
# CMDB is loaded once at import time; Gunicorn workers do not reload it.
#

cmdb = load_cmdb()


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
