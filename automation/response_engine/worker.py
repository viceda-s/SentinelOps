from __future__ import annotations

import logging
import time

from prometheus_client import REGISTRY, start_http_server

import docker

from .claim import claim_incident
from .cmdb import load_cmdb
from .collectors import (
    IncidentsCollector,
    QueueDepthCollector,
)
from .db import get_connection
from .logging_config import configure_logging
from .metrics import WORKER_HEARTBEAT_TIMESTAMP
from .remediation import (
    collect_diagnostics,
    disk_cleanup,
    restart_service,
)
from .sla import check_sla_breaches
from .state_machine import transition

POLL_INTERVAL_SECONDS = 5

logger = logging.getLogger(__name__)


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

    elif playbook == "disk_cleanup":
        disk_cleanup(
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
        # Should be unreachable: validate_cmdb.py rejects any playbook name in cmdb/services.yaml that isn't in IMPLEMENTED_PLAYBOOKS or "none".
        # Unlike the "none" branch above, this raises rather than escalates -- an unrecognized playbook string means the CMDB and the worker have drifted, which is a deploy-time bug worth surfacing loudly (retry + rollback) rather than quietly escalating the incident.
        raise RuntimeError(
            f"Unknown playbook '{playbook}' for incident {incident['reference']}."
        )


def main() -> None:
    configure_logging()

    REGISTRY.register(IncidentsCollector(get_connection))

    REGISTRY.register(QueueDepthCollector(get_connection))

    start_http_server(8000)

    cmdb = load_cmdb()
    client = docker.from_env()
    conn = get_connection()

    logger.info("Remediation worker started.")

    while True:
        incident = None

        try:
            WORKER_HEARTBEAT_TIMESTAMP.set_to_current_time()

            check_sla_breaches(conn)
            conn.commit()

            incident = claim_incident(conn)

            if incident is None:
                conn.commit()
                time.sleep(POLL_INTERVAL_SECONDS)
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
            if incident is not None and incident["status"] not in (
                "ESCALATED",
                "RESOLVED",
                "CLOSED",
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
                        incident["reference"] if incident is not None else None
                    ),
                },
            )

            time.sleep(POLL_INTERVAL_SECONDS)

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
                        incident["reference"] if incident is not None else None
                    ),
                },
            )

            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
