"""
Remediation playbooks and attempt recording module for SentinelOps.

Implements autonomous recovery playbooks (`restart_service`, `collect_diagnostics`,
`disk_cleanup`), records attempt start and finish timestamps using wall-clock precision
(`clock_timestamp()`), and queries Prometheus for disk pressure verification.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from psycopg2.extensions import connection

import docker

from .config import DiagnosticsSettings, PrometheusSettings
from .metrics import REMEDIATION_ATTEMPTS_TOTAL
from .state_machine import transition
from .verification import verify_recovery

VERIFY_TIMEOUT = 30
VERIFY_INTERVAL = 1
RESTART_COOLDOWN = 5
MAX_RESTART_ATTEMPTS = 2

# Margin added to a container's own HEALTHCHECK interval + timeout when computing its docker-health verify deadline, to absorb scheduling jitter.
HEALTHCHECK_VERIFY_MARGIN = 5

PROMETHEUS_SETTINGS = PrometheusSettings.from_env()
DIAGNOSTICS_SETTINGS = DiagnosticsSettings.from_env()

PROMETHEUS_URL = PROMETHEUS_SETTINGS.url
DISK_PRESSURE_FREE_PERCENT = PROMETHEUS_SETTINGS.disk_pressure_free_percent
DIAGNOSTICS_RETENTION_DAYS = DIAGNOSTICS_SETTINGS.retention_days
DIAGNOSTICS_DIR = DIAGNOSTICS_SETTINGS.dir_path


def record_attempt_start(conn: connection, incident: dict, playbook: str) -> int:
    """Create a remediation_attempts row for a new remediation attempt.

    Returns:
        The allocated attempt_number.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
    """

    with conn.cursor() as cur:
        # Allocate the next attempt number for this incident.
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

        # Record the start of the attempt.

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
    conn: connection,
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

        # Defensive check: caller should only finish an attempt that exists.

        if cur.rowcount != 1:
            raise RuntimeError(
                f"Attempt {attempt_number} does not exist for incident {incident['reference']}"
            )

        REMEDIATION_ATTEMPTS_TOTAL.labels(
            playbook=playbook,
            result=result,
        ).inc()


def _verify_timeout_for(container, verification: dict) -> float:
    """docker-health's deadline must cover the container's own first post-restart healthcheck probe, not just VERIFY_TIMEOUT."""

    if verification["type"] != "docker-health":
        return VERIFY_TIMEOUT

    healthcheck = container.attrs.get("Config", {}).get("Healthcheck") or {}
    interval_ns = healthcheck.get("Interval") or 0
    timeout_ns = healthcheck.get("Timeout") or 0

    first_probe_seconds = (interval_ns + timeout_ns) / 1_000_000_000
    return max(VERIFY_TIMEOUT, first_probe_seconds + HEALTHCHECK_VERIFY_MARGIN)


def restart_service(
    conn: connection, client: docker.DockerClient, incident: dict, cmdb: dict
) -> None:
    """Execute the restart_service playbook.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
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
            # 1. Container must exist.

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

            # Restart the container.
            container.restart()

            # Poll until recovery or timeout.

            verify_timeout = _verify_timeout_for(container, verification)
            deadline = time.monotonic() + verify_timeout
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

            # Verification timed out.

            record_attempt_finish(
                conn,
                incident,
                attempt_number,
                playbook,
                result="timeout",
                error=(f"Verification timed out after {verify_timeout} seconds"),
            )
        # Record infrastructure failures for auditability, then propagate them.

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


def collect_diagnostics(
    conn: connection, client: docker.DockerClient, incident: dict, cmdb: dict
) -> None:
    """Execute the collect_diagnostics playbook.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
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
        # 1. Container must exist.

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

        # Collect diagnostics.

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

    # Record infrastructure failures for auditability, then propagate them.
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

    # Diagnostics could not be persisted; escalate so an operator is notified.

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


class DiskMeasurementUnavailable(Exception):
    """Raised when post-cleanup filesystem state cannot be determined.

    Covers invalid, stale, ambiguous, or unavailable Prometheus measurements.
    """


# Prometheus scrapes every 15s. The re-check window gives a fresh sample
# time to arrive; not_before remains the authoritative post-cleanup guard.
DISK_RECHECK_TIMEOUT = 20
DISK_RECHECK_INTERVAL = 5

# Allow one scrape interval plus request latency while rejecting genuinely
# stale samples. Independent of the not_before causality check.
DISK_SAMPLE_MAX_AGE_SECONDS = 30


def _promql_string(value: str) -> str:
    """
    Encode a value as a PromQL string literal.

    PromQL double-quoted string literals use the same backslash/quote escaping
    as JSON strings, so json.dumps() is a correct, dependency-free escaper --
    it turns a literal '"' or '\\' in an alert label into a properly escaped
    PromQL literal instead of a broken or injected query.
    """

    return json.dumps(value)


def get_disk_free_percent(
    instance: str,
    mountpoint: str,
    *,
    timeout: float = 5,
    not_before: float | None = None,
) -> float:
    """
    Query Prometheus for the free-space percentage of the alert's filesystem.

    The query mirrors the DiskPressure alert's node-exporter and filesystem
    selection rules. When provided, ``not_before`` rejects samples predating
    the cleanup completion timestamp, preventing stale pre-cleanup readings
    from being treated as recovery.

    Args:
        instance: Prometheus node-exporter instance label.
        mountpoint: Filesystem mountpoint label.
        timeout: Maximum HTTP request duration in seconds.
        not_before: Optional wall-clock timestamp; samples before this value
            are rejected.

    Returns:
        The validated filesystem free-space percentage.

    Raises:
        DiskMeasurementUnavailable: If no single valid, fresh, post-cleanup
            measurement can be obtained.
    """

    instance_expr = _promql_string(instance)
    mountpoint_expr = _promql_string(mountpoint)

    # Reproduce both alert rule exclusions (fstype and mountpoint patterns).
    label_matchers = (
        f'job="node-exporter",instance={instance_expr},mountpoint={mountpoint_expr},'
        'fstype!~"tmpfs|erofs|overlay|squashfs",'
        'mountpoint!~"/oldroot|/run.*"'
    )

    query = (
        f"node_filesystem_avail_bytes{{{label_matchers}}} / "
        f"node_filesystem_size_bytes{{{label_matchers}}} * 100"
    )

    url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(query)}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise DiskMeasurementUnavailable(f"Prometheus query failed: {e}") from e

    # Normalize malformed or non-success responses to DiskMeasurementUnavailable contract.

    if not isinstance(body, dict) or body.get("status") != "success":
        raise DiskMeasurementUnavailable(
            f"Prometheus returned a non-success response: {body!r}"
        )

    data = body.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise DiskMeasurementUnavailable(
            f"expected an instant vector result, got: {body!r}"
        )

    result = data.get("result")
    if not isinstance(result, list) or len(result) != 1:
        got = len(result) if isinstance(result, list) else "malformed"
        raise DiskMeasurementUnavailable(
            f"expected exactly one series (job=node-exporter, instance={instance!r}, "
            f"mountpoint={mountpoint!r}), got {got}"
        )

    try:
        sample_timestamp, raw_value = result[0]["value"]
        sample_age = time.time() - float(sample_timestamp)
        percent_free = float(raw_value)
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise DiskMeasurementUnavailable(f"malformed Prometheus result: {e}") from e

    if sample_age > DISK_SAMPLE_MAX_AGE_SECONDS:
        raise DiskMeasurementUnavailable(
            f"Prometheus measurement is stale: {sample_age:.1f}s old "
            f"(max {DISK_SAMPLE_MAX_AGE_SECONDS}s) -- node-exporter may not be "
            f"scraping this target"
        )

    # Sample-age freshness and post-cleanup causality are independent; a sample can pass
    # the age check while predating cleanup completion.

    if not_before is not None and float(sample_timestamp) < not_before:
        raise DiskMeasurementUnavailable(
            f"Prometheus sample ({sample_timestamp}) predates cleanup "
            f"completion ({not_before}) -- measurement does not yet reflect "
            f"the cleanup's effect"
        )

    # Reject non-finite (+Inf/-Inf/NaN) or out-of-range values to prevent false RESOLVED.

    if not math.isfinite(percent_free) or not (0 <= percent_free <= 100):
        raise DiskMeasurementUnavailable(f"measurement out of range: {percent_free!r}")

    return percent_free


def prune_diagnostics(retention_days: int = DIAGNOSTICS_RETENTION_DAYS) -> int:
    """
    Delete diagnostics artifacts older than retention_days.

    Returns the number of files deleted. Missing directory is not an error --
    nothing has been collected yet.
    """

    if not DIAGNOSTICS_DIR.exists():
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).timestamp()
    deleted = 0

    for artifact in DIAGNOSTICS_DIR.glob("*.json"):
        if artifact.stat().st_mtime < cutoff:
            artifact.unlink()
            deleted += 1

    return deleted


def _prune_docker_resources(client: docker.DockerClient) -> None:
    """
    Prune reclaimable Docker container, dangling image, and build cache resources.

    Volumes are deliberately NEVER pruned to protect database and metric storage.

    Args:
        client: Docker SDK client instance.
    """
    client.containers.prune()
    client.images.prune(filters={"dangling": True})
    client.api.prune_builds()


def await_disk_recovery(
    instance: str,
    mountpoint: str,
    cleanup_completed_at: float,
    timeout: float = DISK_RECHECK_TIMEOUT,
    interval: float = DISK_RECHECK_INTERVAL,
) -> tuple[float | None, str | None]:
    """
    Poll Prometheus until free disk space reaches the threshold or the re-check deadline expires.

    Args:
        instance: Prometheus node-exporter instance label.
        mountpoint: Target filesystem mountpoint label.
        cleanup_completed_at: Wall-clock Unix timestamp marking cleanup completion.
        timeout: Total re-check window in seconds (default: 20s).
        interval: Polling interval in seconds (default: 1s).

    Returns:
        tuple[float | None, str | None]:
            (percent_free: float | None, last_error: str | None)
            - percent_free is float: Query succeeded (val >= 15 or val < 15).
            - percent_free is None: Query failed or timed out (error holds description).
    """
    deadline = time.monotonic() + timeout
    percent_free: float | None = None
    last_error: str | None = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        try:
            percent_free = get_disk_free_percent(
                instance,
                mountpoint,
                timeout=min(5.0, remaining),
                not_before=cleanup_completed_at,
            )
        except DiskMeasurementUnavailable as e:
            percent_free = None
            last_error = str(e)
        else:
            last_error = None

        if percent_free is not None and percent_free >= DISK_PRESSURE_FREE_PERCENT:
            break

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        time.sleep(min(interval, remaining))

    return percent_free, last_error


def disk_cleanup(
    conn: connection, client: docker.DockerClient, incident: dict, cmdb: dict
) -> None:
    """Execute the disk_cleanup playbook.

    Prunes reclaimable Docker data and old diagnostics artifacts, then re-checks
    free space to decide whether the incident recovered.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback().
    """

    incident = transition(
        conn, incident, "IN_PROGRESS", "worker", "Starting disk_cleanup playbook"
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

    playbook = "disk_cleanup"
    attempt_number = record_attempt_start(
        conn,
        incident,
        playbook,
    )

    try:
        # Conservative prune only: never remove volumes or non-dangling images.

        _prune_docker_resources(client)

        try:
            deleted = prune_diagnostics()
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
                conn,
                incident,
                "ESCALATED",
                "worker",
                "Failed to prune diagnostics",
            )
            return

        # Mark cleanup completion so Prometheus samples predating this point are rejected.

        cleanup_completed_at = time.time()

        # Both instance and mountpoint labels are required to identify the target filesystem.

        instance = incident["labels"].get("instance")
        mountpoint = incident["labels"].get("mountpoint")

        if not instance or not mountpoint:
            record_attempt_finish(
                conn,
                incident,
                attempt_number,
                playbook,
                result="failure",
                error=(
                    "Alert did not carry instance/mountpoint labels; "
                    "cannot verify recovery"
                ),
            )
            transition(
                conn,
                incident,
                "ESCALATED",
                "worker",
                "Unable to verify disk pressure after cleanup",
            )
            return

        percent_free, last_error = await_disk_recovery(
            instance,
            mountpoint,
            cleanup_completed_at,
        )

        if percent_free is None:
            record_attempt_finish(
                conn,
                incident,
                attempt_number,
                playbook,
                result="failure",
                error=last_error or "disk measurement unavailable",
            )
            transition(
                conn,
                incident,
                "ESCALATED",
                "worker",
                "Unable to verify disk pressure after cleanup",
            )
            return

        # Reclaiming insufficient space is an operational outcome (escalation), not a playbook failure.

        record_attempt_finish(
            conn,
            incident,
            attempt_number,
            playbook,
            result="success",
        )

        if percent_free >= DISK_PRESSURE_FREE_PERCENT:
            incident = transition(
                conn,
                incident,
                "RESOLVED",
                "worker",
                (
                    f"Disk cleanup reclaimed space "
                    f"({percent_free:.1f}% free, {deleted} diagnostics artifacts removed)."
                ),
            )
            return

        incident = transition(
            conn,
            incident,
            "ESCALATED",
            "worker",
            (
                f"Disk still low after cleanup "
                f"({percent_free:.1f}% free, {deleted} diagnostics artifacts removed)."
            ),
        )
        return

    # Record infrastructure failures for auditability, then propagate them.

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
