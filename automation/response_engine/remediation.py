from __future__ import annotations

import time

import docker

from .state_machine import transition
from .verification import verify_recovery

VERIFY_TIMEOUT = 30
VERIFY_INTERVAL = 1
RESTART_COOLDOWN = 5
MAX_RESTART_ATTEMPTS = 2

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
                NOW()
            )
            """,
            (
                incident["id"],
                playbook,
                attempt_number,
            ),
        )

    return attempt_number

def record_attempt_finish(conn, incident: dict, attempt_number: int, result: str, *, diagnostics_path: str | None = None, error: str | None = None) -> None:
    """
    Complete an existing remediation attempt

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE remediation_attempts
            SET
                finished_at = NOW(),
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
                attempt_number
            ),
        )

        #
        # Defensive check: the caller should only finish an attempt that actually exists.
        #

        if cur.rowcount != 1:
            raise RuntimeError(f"Attempt {attempt_number} does not exist for incident {incident['reference']}")

def restart_service(conn, client, incident: dict, cmdb: dict) -> None:
    """
    Execute the restart_service playbook

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()
    """

    incident = transition(conn, incident, "IN_PROGRESS", "worker", "Starting restart_service playbook")
    service = cmdb["services"][incident["service"]]
    container_name = service["container_name"]
    verification = service["verification"]

    for attempt in range(1, MAX_RESTART_ATTEMPTS + 1):
        attempt_number = record_attempt_start(
            conn,
            incident,
            "restart_service",
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
                    result="failure",
                    error=str(e),
                )
                transition(
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

            deadline = (time.monotonic() + VERIFY_TIMEOUT)
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
                result="timeout",
                error=(f"Verification timed out after {VERIFY_TIMEOUT} seconds"),
            )
        #
        # Docker Engine failures are infrastructure failures.
        # Record the failed attempt, then propagate the error.
        #

        except docker.errors.APIError as e:
            record_attempt_finish(
                conn,
                incident,
                attempt_number,
                result="failure",
                error=str(e),
            )
            raise

        if attempt < MAX_RESTART_ATTEMPTS:
            time.sleep(RESTART_COOLDOWN)

    transition(
        conn,
        incident,
        "ESCALATED",
        "worker",
        f"Service did not recover after {MAX_RESTART_ATTEMPTS} restart attempts."
    )
