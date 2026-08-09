from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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

#
# disk_cleanup configuration.
#
# The recovery re-check queries Prometheus directly, scoped to the exact
# job/instance/mountpoint the firing DiskPressure alert carries, rather than
# reading a filesystem path inside the worker container. An earlier design
# used a read-only /:/hostfs:ro bind mount and shutil.disk_usage(): a
# deployed review found that on Docker Desktop /hostfs resolves to the
# worker's own bind-mount overlay (verified at 0.83GB total, 99.94% free --
# essentially incapable of ever reading below the 15% threshold) rather than
# the real host disk, causing disk_cleanup to mark genuinely full disks
# RESOLVED. The mount was also a credential-disclosure risk disproportionate
# to the feature: it let the worker read host SSH keys and .env secrets to
# support one shutil.disk_usage() call. See the "Re-check" section of
# .superpowers/specs/2026-08-08-operational-tooling-design.md for the full
# writeup, including why a fixed path can't be trusted even on native Linux
# hosts with multiple mounted filesystems.
#
# This is a deliberate, narrow exception to "the response engine never calls
# Prometheus": one read-only query, using labels the incident already
# carries (Alertmanager attaches instance/mountpoint automatically; the
# webhook handler already persists the complete raw label set verbatim into
# incidents.labels), inside disk_cleanup's post-cleanup verification only.
#
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")

# Matches the DiskPressure expression in docker/prometheus/rules/alerts.yml
# rather than inventing a second recovery threshold.
DISK_PRESSURE_FREE_PERCENT = float(os.environ.get("DISK_PRESSURE_FREE_PERCENT", "15"))

# Diagnostics artifacts accumulate at a rate driven by incident volume, so
# retention is age-based rather than count-based.
DIAGNOSTICS_RETENTION_DAYS = int(os.environ.get("DIAGNOSTICS_RETENTION_DAYS", "14"))


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


class DiskMeasurementUnavailable(Exception):
    """
    Raised when the post-cleanup filesystem state cannot be determined.

    Covers a missing/ambiguous Prometheus response (zero or more than one
    matching series) as well as request failures (timeout, connection error,
    non-2xx status). All are treated identically by the caller: the playbook
    could not verify recovery, so it must not claim one.
    """


# Bounded re-check window. Prometheus's scrape_interval is 15s
# (docker/prometheus/prometheus.yml), so a query fired immediately after
# cleanup can read a sample taken before cleanup finished (a scrape from
# moments earlier that is nonetheless still within DISK_SAMPLE_MAX_AGE_SECONDS
# once cleanup completes a few seconds later). Polling for up to
# DISK_RECHECK_TIMEOUT at DISK_RECHECK_INTERVAL spans at least one scrape, so
# a genuine post-cleanup reading becomes available within the window. Note
# that the retry loop alone does not GUARANTEE a post-cleanup sample -- that
# guarantee comes from get_disk_free_percent()'s not_before parameter (see
# below), which this loop always passes as cleanup_completed_at. The loop
# only provides the time for a fresh scrape to arrive; not_before is what
# rejects a sample that arrives but still predates cleanup. This can only
# make a genuine recovery resolve once a valid post-cleanup sample exists --
# it can never turn a persistently low reading into a false RESOLVED, and a
# persistent measurement failure still escalates once the window elapses.
DISK_RECHECK_TIMEOUT = 20
DISK_RECHECK_INTERVAL = 5

# A returned sample must be no older than this to be trusted. Guards against
# a specific, dangerous failure: if node-exporter stops scraping (crashed,
# network partition) while its LAST successful sample happened to read above
# the threshold, Prometheus keeps serving that same stale value forever --
# the retry loop above does not help, because every retry gets the identical
# stale sample. Sized to comfortably exceed one scrape_interval (15s) plus
# request latency, without being so loose it accepts genuinely old data.
# Independent of, and does not substitute for, the not_before causality
# check below -- a sample can pass this check and still predate cleanup.
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
    Query Prometheus for the free-space percentage of the exact filesystem
    identified by instance and mountpoint -- the same labels the firing
    DiskPressure alert carries.

    Mirrors the alert rule's own selection semantics EXACTLY
    (docker/prometheus/rules/alerts.yml:5): job=node-exporter, the same
    fstype exclusion, AND the same mountpoint exclusion
    (mountpoint!~"/oldroot|/run.*") -- omitting the mountpoint exclusion
    would let a query with an unexpectedly broad label set match an
    unintended series that the alert itself would never fire on.

    timeout bounds the HTTP request. The caller is expected to pass the time
    remaining in its own bounded re-check window, so a request started near
    the end of that window cannot itself blow past it.

    not_before, if given, is a time.time()-comparable timestamp (worker wall
    clock and Prometheus sample timestamps share the same clock domain,
    confirmed within ~13ms in this environment). A sample timestamped BEFORE
    not_before is rejected even if it is within DISK_SAMPLE_MAX_AGE_SECONDS --
    freshness alone does not prove the sample reflects the state AFTER
    cleanup ran. Without this check, a sample taken moments before cleanup
    started could still read "fresh" once cleanup finishes a few seconds
    later, and a disk that was already above threshold before any cleanup
    happened would resolve the incident without cleanup having verified
    anything.

    Raises:
        DiskMeasurementUnavailable: any failure to obtain a valid, fresh,
            finite, in-range, post-cleanup single numeric measurement -- the
            request failed, the response wasn't well-formed JSON, Prometheus
            reported status != "success", the result wasn't a vector, the
            query did not return exactly one matching series, the value
            wasn't a finite number in [0, 100], the sample is older than
            DISK_SAMPLE_MAX_AGE_SECONDS, or the sample predates not_before.
    """

    instance_expr = _promql_string(instance)
    mountpoint_expr = _promql_string(mountpoint)

    #
    # fstype!~"tmpfs|erofs|overlay|squashfs" AND mountpoint!~"/oldroot|/run.*"
    # -- both exclusions from the alert rule, not just the first. A query
    # that reproduces only part of the alert's selection isn't reproducing
    # the alert's selection.
    #
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

    #
    # Validate the response shape before trusting it. A malformed or
    # non-success response must become DiskMeasurementUnavailable, not a raw
    # KeyError/TypeError/IndexError leaking an implementation detail past the
    # function's declared contract. Prometheus's API declares resultType
    # explicitly (vector/matrix/scalar/string) -- an instant query always
    # returns "vector"; anything else means the query itself was malformed.
    #

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

    #
    # Freshness (checked above) and post-cleanup causality (checked here) are
    # independent conditions. A sample can be well within
    # DISK_SAMPLE_MAX_AGE_SECONDS and still predate cleanup -- e.g. cleanup
    # takes 5s and the scrape interval is 15s, so a sample from just before
    # cleanup started can still look "fresh" once cleanup finishes. Only
    # not_before proves the sample reflects state the cleanup could actually
    # have influenced.
    #

    if not_before is not None and float(sample_timestamp) < not_before:
        raise DiskMeasurementUnavailable(
            f"Prometheus sample ({sample_timestamp}) predates cleanup "
            f"completion ({not_before}) -- measurement does not yet reflect "
            f"the cleanup's effect"
        )

    #
    # Reject non-finite or out-of-range values. Prometheus can serialize
    # +Inf/-Inf/NaN as JSON strings; float("+Inf") parses successfully and
    # would otherwise compare >= any threshold, producing a false RESOLVED
    # from a value that was never a real percentage.
    #

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


def disk_cleanup(conn, client, incident: dict, cmdb: dict) -> None:
    """
    Execute the disk_cleanup playbook.

    Prunes reclaimable Docker data and old diagnostics artifacts, then re-checks
    free space to decide whether the incident recovered.

    The caller owns the transaction.
    This function MUST NOT call commit() or rollback()
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
        #
        # Conservative prune only.
        #
        # Volumes are NEVER pruned: postgres_data holds every incident in the
        # system, and DiskPressure is a warning-severity alert. Unused-but-tagged
        # images are also left alone -- deleting an image the estate needs turns
        # a disk warning into a failed restart_service during the next outage.
        #

        client.containers.prune()
        client.images.prune(filters={"dangling": True})
        client.api.prune_builds()

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
            transition(
                conn,
                incident,
                "ESCALATED",
                "worker",
                "Failed to prune diagnostics",
            )
            return

        #
        # Recorded immediately after the Docker prune and diagnostics prune
        # above have both succeeded -- this is the instant cleanup actually
        # finished. Any Prometheus sample timestamped before this point
        # cannot reflect the cleanup's effect, no matter how "fresh" it looks
        # by DISK_SAMPLE_MAX_AGE_SECONDS alone.
        #

        cleanup_completed_at = time.time()

        #
        # Re-check the exact filesystem the firing alert named, via
        # Prometheus, to decide the operational outcome. instance/mountpoint
        # come from the incident's own labels -- Alertmanager attaches both
        # automatically, and the webhook handler already persists the
        # complete raw label set verbatim (see ingest_alert()/handle_alert()
        # in handlers.py). Missing either is treated the same as a failed
        # query: the playbook cannot identify which filesystem to verify.
        #

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

        deadline = time.monotonic() + DISK_RECHECK_TIMEOUT
        percent_free = None
        last_error = None

        while True:
            #
            # The query's own HTTP timeout is bounded by whatever's left in
            # the re-check window, not a fixed 5s -- otherwise a request
            # starting near the deadline could still push the total past
            # DISK_RECHECK_TIMEOUT, making "bounded 20s re-check" untrue.
            #
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            try:
                percent_free = get_disk_free_percent(
                    instance,
                    mountpoint,
                    timeout=min(5, remaining),
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

            time.sleep(min(DISK_RECHECK_INTERVAL, remaining))

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

        #
        # The cleanup itself succeeded either way. Whether it reclaimed *enough*
        # is an operational outcome carried by the incident state, not an
        # execution failure -- recording it as a failure would fire
        # RemediationFailureRateHigh when the playbook worked as designed.
        #

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
