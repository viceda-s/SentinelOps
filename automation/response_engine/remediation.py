from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import docker

from .metrics import REMEDIATION_ATTEMPTS_TOTAL
from .state_machine import transition
from .verification import verify_recovery

VERIFY_TIMEOUT = 30
VERIFY_INTERVAL = 1
RESTART_COOLDOWN = 5
MAX_RESTART_ATTEMPTS = 2
DIAGNOSTICS_DIR = Path("/app/diagnostics")


def record_attempt_start(conn, incident: dict, playbook: str) -> int:
    """
    Create a remediation_attempts row for a new remediation attempt.


    Returns:
        The allocated attempt_number.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()
    """

    with conn.cursor() as cur:
        #
        # Allocate the next attempt number for this incident
        #

        cur.execute(
            """
            SELECT COALESCE(MAX(attempt_number), 0) + 1
            AS next_attempt
            FROM remediation_attempts
            WHERE incident_id = %s
            """,
            (incident["id"],),
        )

        attempt_number = cur.fetchone()["next_attempt"]

        #
        # Record the start of the attempt
        #

        cur.execute(
            """
            INSERT INTO remediation_attempts (
                incident_id,
                playbook,
                attempt_number,
                started_at
            )
            VALUES (
                %s,
                %s,
                %s,
                clock_timestamp()
            )
            """,
            (
                incident["id"],
                playbook,
                attempt_number,
            ),
        )

    return attempt_number


def record_attempt_finish(
    conn,
    incident: dict,
    attempt_number: int,
    playbook: str,
    result: str,
    *,
    diagnostics_path: str | None = None,
    error: str | None = None,
) -> None:
    """
    Record the completion of a remediation attempt.

    playbook must be the same playbook name that was passed to
    record_attempt_start() for this attempt.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_attempts
            SET
                finished_at = clock_timestamp(),
                result = %s,
                diagnostics_path = %s,
                error = %s
            WHERE incident_id = %s
              AND attempt_number = %s
            """,
            (
                result,
                diagnostics_path,
                error,
                incident["id"],
                attempt_number,
            ),
        )

        #
        # Defensive check: the caller should only finish an attempt that
        # actually exists.
        #

        if cur.rowcount != 1:
            raise RuntimeError(
                f"Attempt {attempt_number} does not exist for incident {incident['reference']}"
            )

        REMEDIATION_ATTEMPTS_TOTAL.labels(
            playbook=playbook,
            result=result,
        ).inc()


def restart_service(conn, client, incident: dict, cmdb: dict) -> None:
    """
    Execute the restart_service playbook

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()
    """

    incident = transition(
        conn, incident, "IN_PROGRESS", "worker", "Starting restart_service playbook"
    )

    if incident["service"] not in cmdb["services"]:
        incident = transition(
            conn,
            incident,
            "ESCALATED",
            "worker",
            "Service no longer exists in the CMDB.",
        )
        return

    playbook = "restart_service"
    service = cmdb["services"][incident["service"]]
    container_name = service["container_name"]
    verification = service["verification"]

    for attempt in range(1, MAX_RESTART_ATTEMPTS + 1):
        attempt_number = record_attempt_start(
            conn,
            incident,
            playbook,
        )
        try:
            #
            # 1. Container must exist
            #

            try:
                container = client.containers.get(container_name)

            except docker.errors.NotFound as e:
                record_attempt_finish(
                    conn,
                    incident,
                    attempt_number,
                    playbook,
                    result="failure",
                    error=str(e),
                )
                incident = transition(
                    conn,
                    incident,
                    "ESCALATED",
                    "worker",
                    "Container not found",
                )
                return

            #
            # Restart the container.
            #

            container.restart()

            #
            # Poll until recovery or timeout
            #

            deadline = time.monotonic() + VERIFY_TIMEOUT
            while time.monotonic() < deadline:
                if verify_recovery(
                    client,
                    container_name,
                    verification,
                ):
                    record_attempt_finish(
                        conn,
                        incident,
                        attempt_number,
                        playbook,
                        result="success",
                    )

                    incident = transition(
                        conn,
                        incident,
                        "RESOLVED",
                        "worker",
                        "Service recovered after restart",
                    )

                    return
                time.sleep(VERIFY_INTERVAL)

            #
            # Verification timed out.
            #

            record_attempt_finish(
                conn,
                incident,
                attempt_number,
                playbook,
                result="timeout",
                error=(f"Verification timed out after {VERIFY_TIMEOUT} seconds"),
            )
        #
        # Docker Engine failures are infrastructure failures, not remediation outcomes. Record the failed attempt so the audit trail stays complete, then propagate the exception to the worker.
        #

        except docker.errors.APIError as e:
            record_attempt_finish(
                conn,
                incident,
                attempt_number,
                playbook,
                result="failure",
                error=str(e),
            )
            raise

        if attempt < MAX_RESTART_ATTEMPTS:
            time.sleep(RESTART_COOLDOWN)

    incident = transition(
        conn,
        incident,
        "ESCALATED",
        "worker",
        f"Service did not recover after {MAX_RESTART_ATTEMPTS} restart attempts.",
    )


def collect_diagnostics(conn, client, incident: dict, cmdb: dict) -> None:
    """
    Execute the collect_diagnostics playbook

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()
    """

    incident = transition(
        conn, incident, "IN_PROGRESS", "worker", "Starting collect_diagnostics playbook"
    )

    if incident["service"] not in cmdb["services"]:
        incident = transition(
            conn,
            incident,
            "ESCALATED",
            "worker",
            "Service no longer exists in the CMDB.",
        )
        return

    playbook = "collect_diagnostics"
    service = cmdb["services"][incident["service"]]
    container_name = service["container_name"]
    attempt_number = record_attempt_start(
        conn,
        incident,
        playbook,
    )

    try:
        #
        # 1. Container must exist
        #

        try:
            container = client.containers.get(container_name)

        except docker.errors.NotFound as e:
            record_attempt_finish(
                conn,
                incident,
                attempt_number,
                playbook,
                result="failure",
                error=str(e),
            )
            incident = transition(
                conn,
                incident,
                "ESCALATED",
                "worker",
                "Container not found during diagnostics collection",
            )
            return

        #
        # Collect diagnostics.
        #

        logs = container.logs(tail=100).decode("utf-8", errors="replace")

        stats = container.stats(stream=False)

        diagnostics = {
            "incident": incident["reference"],
            "service": incident["service"],
            "container": container_name,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "logs": logs,
            "stats": stats,
        }

        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)

        diagnostics_path = (
            DIAGNOSTICS_DIR / f"{incident['reference']}-attempt-{attempt_number}.json"
        )
        with diagnostics_path.open("w", encoding="utf-8") as f:
            json.dump(diagnostics, f, indent=2)

        record_attempt_finish(
            conn,
            incident,
            attempt_number,
            playbook,
            result="success",
            diagnostics_path=str(diagnostics_path),
        )
        incident = transition(
            conn,
            incident,
            "ESCALATED",
            "worker",
            "Diagnostics collected.",
        )
        return

    #
    # Docker Engine failures are infrastructure failures, not remediation outcomes. Record the failed attempt so the audit trail stays complete, then propagate the exception to the worker.
    #

    except docker.errors.APIError as e:
        record_attempt_finish(
            conn,
            incident,
            attempt_number,
            playbook,
            result="failure",
            error=str(e),
        )
        raise

    #
    # Diagnostics could not be persisted.
    # Escalate anyway so an operator is notified.
    #

    except OSError as e:
        record_attempt_finish(
            conn,
            incident,
            attempt_number,
            playbook,
            result="failure",
            error=str(e),
        )

        incident = transition(
            conn, incident, "ESCALATED", "worker", "Failed to persist diagnostics"
        )
