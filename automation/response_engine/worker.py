from __future__ import annotations

import logging
import os
import time

import docker
import psycopg2
import psycopg2.extras
import yaml

from .claim import claim_incident
from .logging_config import configure_logging
from .remediation import (
    collect_diagnostics,
    restart_service,
)
from .state_machine import transition

POLL_INTERVAL = 5

logger = logging.getLogger(__name__)


def get_connection():
    """
    Create a PostgreSQL connection.

    The worker owns the connection for its lifetime.
    """

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.getenv("POSTGRES_DB", "postgres"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def load_cmdb() -> dict:
    """Load the CMDB."""

    with open("/app/cmdb/services.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def dispatch(conn, client, incident: dict, cmdb: dict) -> None:
    """Execute the playbook associated with an incident."""

    playbook = incident["playbook"]

    if playbook == "restart_service":
        restart_service(
            conn,
            client,
            incident,
            cmdb,
        )

    elif playbook == "collect_diagnostics":
        collect_diagnostics(
            conn,
            client,
            incident,
            cmdb,
        )

    elif playbook == "none":
        logger.error(
            "Incident reached worker without a configured playbook.",
            extra={"incident_reference": incident["reference"]},
        )

        transition(
            conn,
            incident,
            "ESCALATED",
            "worker",
            "No playbook configured.",
        )
        return

    else:
        raise RuntimeError(
            f"Unknown playbook '{playbook}' for incident {incident['reference']}."
        )


def main() -> None:
    configure_logging()

    cmdb = load_cmdb()
    client = docker.from_env()
    conn = get_connection()

    logger.info("Remediation worker started.")

    while True:

        incident = None

        try:
            incident = claim_incident(conn)

            if incident is None:
                conn.commit()
                time.sleep(POLL_INTERVAL)
                continue

            logger.info(
                "Claimed incident %s (%s)",
                incident["reference"],
                incident["playbook"],
                extra={
                    "incident_reference": incident["reference"],
                },
            )

            dispatch(
                conn,
                client,
                incident,
                cmdb,
            )

            conn.commit()

        #
        # Infrastructure failures.
        #
        # restart_service()/collect_diagnostics() already recorded
        # the failed remediation attempt.
        #

        except docker.errors.APIError as exc:
            if (
                incident is not None
                and incident["status"] not in ("ESCALATED", "RESOLVED", "CLOSED")
            ):
                transition(
                    conn,
                    incident,
                    "ESCALATED",
                    "worker",
                    f"Docker API failure: {exc}",
                )

            conn.commit()

            logger.exception(
                "Docker Engine communication failed.",
                extra={
                    "incident_reference": (
                        incident["reference"]
                        if incident is not None
                        else None
                    ),
                },
            )

            time.sleep(POLL_INTERVAL)

        #
        # Unexpected programming/configuration errors.
        #
        # Roll back so the incident returns to NEW.
        #

        except Exception:
            conn.rollback()

            logger.exception(
                "Worker iteration failed.",
                extra={
                    "incident_reference": (
                        incident["reference"]
                        if incident is not None
                        else None
                    ),
                },
            )

            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
