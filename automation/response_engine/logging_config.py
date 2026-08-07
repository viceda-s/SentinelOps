from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    """
    Format every log record as one JSON object per line.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "incident_reference": getattr(
                record,
                "incident_reference",
                None,
            ),
            "exception": None,
        }

        if record.exc_info:
            payload["exception"] = self.formatException(
                record.exc_info,
            )

        context = {
            key: value
            for key, value in record.__dict__.items()
            if (key not in STANDARD_LOG_RECORD_FIELDS and key != "incident_reference")
        }

        if context:
            payload["context"] = context

        return json.dumps(
            payload,
            ensure_ascii=False,
        )


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure process-wide JSON logging.

    Safe to call multiple times: repeated calls replace only the handler
    this function previously installed, leaving handlers added by anything
    else (e.g. pytest's caplog, or a WSGI server's own logging setup) intact.
    """

    root = logging.getLogger()

    for existing in list(root.handlers):
        if getattr(existing, "_sentinelops_json_handler", False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._sentinelops_json_handler = True

    root.addHandler(handler)
    root.setLevel(level)
