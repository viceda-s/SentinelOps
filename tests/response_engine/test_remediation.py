from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest
from psycopg2.extras import Json

import docker
from automation.response_engine.metrics import WORKER_HEARTBEAT_TIMESTAMP
from automation.response_engine.remediation import (
    _verify_timeout_for,
    disk_cleanup,
    restart_service,
)

CMDB = {
    "services": {
        "api": {
            "container_name": "sentinelops-api",
            "verification": {"type": "http", "url": "http://api:5000/health"},
        },
    },
}


@pytest.fixture
def docker_client():
    """A Docker client whose prune calls all succeed and record their arguments."""
    return MagicMock()


@pytest.fixture
def fake_clock():
    """
    A monotonic clock that only advances when code calls time.sleep(), so
    disk_cleanup's real-time retry loop (deadline = time.monotonic() + N)
    can be exercised without the test actually waiting N seconds. Patches
    both time.monotonic and time.sleep on the remediation module -- patching
    sleep alone does nothing, since the loop's deadline check reads
    monotonic() directly and the loop otherwise busy-spins in real time.
    """
    clock = [1_000_000.0]

    def fake_monotonic():
        """Verify that fake monotonic."""
        return clock[0]

    def fake_sleep(seconds):
        """Verify that fake sleep."""
        clock[0] += seconds

    with (
        patch(
            "automation.response_engine.remediation.time.monotonic",
            side_effect=fake_monotonic,
        ),
        patch(
            "automation.response_engine.remediation.time.sleep",
            side_effect=fake_sleep,
        ),
    ):
        yield clock


def _status(db_connection, incident_id: int) -> str:
    """Verify that status."""
    with db_connection.cursor() as cur:
        cur.execute("SELECT status FROM incidents WHERE id = %s", (incident_id,))
        return cur.fetchone()["status"]


def _attempts(db_connection, incident_id: int) -> list[dict]:
    """Verify that attempts."""
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT playbook, attempt_number, result, error
            FROM remediation_attempts
            WHERE incident_id = %s
            ORDER BY attempt_number
            """,
            (incident_id,),
        )
        return cur.fetchall()


def test_resolves_when_cleanup_frees_enough_space(
    db_connection, make_incident, docker_client
):
    """Verify that resolves when cleanup frees enough space."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(
            {"instance": "node-exporter:9100", "mountpoint": "/var/lib/docker"}
        ),
    )

    with patch(
        "automation.response_engine.remediation.get_disk_free_percent",
        return_value=42.0,
    ):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    assert _status(db_connection, incident["id"]) == "RESOLVED"

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    assert attempts[0]["playbook"] == "disk_cleanup"
    assert attempts[0]["result"] == "success"


def test_escalates_when_disk_still_low(
    db_connection, make_incident, docker_client, fake_clock
):
    """Verify that escalates when disk still low."""
    from automation.response_engine.remediation import DISK_RECHECK_TIMEOUT

    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(
            {"instance": "node-exporter:9100", "mountpoint": "/var/lib/docker"}
        ),
    )

    start = fake_clock[0]

    with patch(
        "automation.response_engine.remediation.get_disk_free_percent",
        return_value=3.0,
    ) as mock_get_disk_free_percent:
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    #
    # The fake clock only advances via time.sleep(), so these two assertions
    # together prove the retry loop actually ran to its bound rather than
    # exiting after a single measurement -- a future change that accidentally
    # dropped the retry loop (e.g. checking once and escalating immediately)
    # would still satisfy every other assertion in this test.
    #
    assert mock_get_disk_free_percent.call_count > 1
    assert fake_clock[0] == pytest.approx(start + DISK_RECHECK_TIMEOUT)

    assert _status(db_connection, incident["id"]) == "ESCALATED"

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    #
    # The cleanup executed correctly; it simply could not reclaim enough.
    # Recording this as a failure would contaminate the remediation failure
    # rate metric and fire RemediationFailureRateHigh on correct behaviour.
    #
    assert attempts[0]["result"] == "success"


def test_never_prunes_volumes(db_connection, make_incident, docker_client):
    """Verify that never prunes volumes."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(
            {"instance": "node-exporter:9100", "mountpoint": "/var/lib/docker"}
        ),
    )

    with patch(
        "automation.response_engine.remediation.get_disk_free_percent",
        return_value=42.0,
    ):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    #
    # postgres_data holds every incident in the system. This assertion is the
    # guard against a future edit quietly adding volume pruning.
    #
    docker_client.volumes.prune.assert_not_called()


def test_prunes_exactly_the_three_intended_surfaces(
    db_connection, make_incident, docker_client
):
    """Verify that prunes exactly the three intended surfaces."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(
            {"instance": "node-exporter:9100", "mountpoint": "/var/lib/docker"}
        ),
    )

    with patch(
        "automation.response_engine.remediation.get_disk_free_percent",
        return_value=42.0,
    ):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    #
    # The conservative scope, asserted positively so a future edit that drops
    # one of these is caught, not just one that adds volume pruning.
    #
    docker_client.containers.prune.assert_called_once()
    docker_client.images.prune.assert_called_once_with(filters={"dangling": True})
    docker_client.api.prune_builds.assert_called_once()


def test_records_failure_and_reraises_on_docker_api_error(
    db_connection, make_incident, docker_client
):
    """Verify that records failure and reraises on docker api error."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(
            {"instance": "node-exporter:9100", "mountpoint": "/var/lib/docker"}
        ),
    )

    docker_client.containers.prune.side_effect = docker.errors.APIError("boom")

    with pytest.raises(docker.errors.APIError):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    assert attempts[0]["result"] == "failure"
    assert "boom" in attempts[0]["error"]


def test_records_failure_and_escalates_when_diagnostics_pruning_fails(
    db_connection, make_incident, docker_client
):
    """Verify that records failure and escalates when diagnostics pruning fails."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(
            {"instance": "node-exporter:9100", "mountpoint": "/var/lib/docker"}
        ),
    )

    #
    # Docker cleanup succeeded but pruning old diagnostics artifacts did not,
    # so the playbook did NOT fully execute. This is a genuine execution
    # failure, distinct from the filesystem re-check failing below, and is
    # recorded as one with its own escalation message.
    #
    with patch(
        "automation.response_engine.remediation.prune_diagnostics",
        side_effect=OSError("permission denied"),
    ):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    assert _status(db_connection, incident["id"]) == "ESCALATED"

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    assert attempts[0]["result"] == "failure"
    assert "permission denied" in attempts[0]["error"]

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT message FROM incident_events WHERE incident_id = %s ORDER BY sequence",
            (incident["id"],),
        )
        messages = [row["message"] for row in cur.fetchall()]
    assert "Failed to prune diagnostics" in messages


def test_records_failure_and_escalates_when_filesystem_recheck_fails(
    db_connection, make_incident, docker_client, fake_clock
):
    """Verify that records failure and escalates when filesystem recheck fails."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(
            {"instance": "node-exporter:9100", "mountpoint": "/var/lib/docker"}
        ),
    )

    #
    # Docker cleanup and diagnostics pruning both succeeded, but the
    # post-cleanup Prometheus re-check could not be performed (e.g. the
    # request failed) at every poll within the bounded re-check window. This
    # is a distinct failure mode from the diagnostics-pruning failure above --
    # the playbook cannot even tell whether the incident recovered -- and
    # carries its own escalation message.
    #
    from automation.response_engine.remediation import DiskMeasurementUnavailable

    with patch(
        "automation.response_engine.remediation.get_disk_free_percent",
        side_effect=DiskMeasurementUnavailable("Prometheus query failed: timeout"),
    ):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    assert _status(db_connection, incident["id"]) == "ESCALATED"

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    assert attempts[0]["result"] == "failure"
    assert "Prometheus query failed" in attempts[0]["error"]

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT message FROM incident_events WHERE incident_id = %s ORDER BY sequence",
            (incident["id"],),
        )
        messages = [row["message"] for row in cur.fetchall()]
    assert "Unable to verify disk pressure after cleanup" in messages


@pytest.mark.parametrize(
    "labels",
    [
        {},
        {"instance": "node-exporter:9100"},
        {"mountpoint": "/var/lib/docker"},
    ],
    ids=["both-missing", "mountpoint-missing", "instance-missing"],
)
def test_records_failure_and_escalates_when_alert_missing_disk_labels(
    db_connection, make_incident, docker_client, labels
):
    """Verify that records failure and escalates when alert missing disk labels."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        labels=Json(labels),
    )

    #
    # Alertmanager always attaches instance/mountpoint for a real
    # DiskPressure alert, but a malformed or synthetic one might not. The
    # playbook must not guess which filesystem to verify -- treat this the
    # same as any other measurement failure: failure + ESCALATED, never
    # RESOLVED. Each of the three parametrized cases must independently
    # trigger this path, not just the case where both labels are absent.
    #
    disk_cleanup(db_connection, docker_client, incident, CMDB)

    assert _status(db_connection, incident["id"]) == "ESCALATED"

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    assert attempts[0]["result"] == "failure"
    assert "instance/mountpoint" in attempts[0]["error"]

    #
    # No Prometheus query was even attempted -- the label check happens
    # first.
    #
    docker_client.containers.prune.assert_called_once()


def test_get_disk_free_percent_raises_on_zero_or_multiple_series():
    """Verify that get disk free percent raises on zero or multiple series."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    now = time.time()
    zero_series_body = (
        b'{"status": "success", "data": {"resultType": "vector", "result": []}}'
    )
    two_series_body = (
        f'{{"status": "success", "data": {{"resultType": "vector", "result": ['
        f'{{"metric": {{}}, "value": [{now}, "50"]}}, '
        f'{{"metric": {{}}, "value": [{now}, "60"]}}'
        f"]}}}}"
    ).encode()

    for body in (zero_series_body, two_series_body):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = body

        with (
            patch(
                "automation.response_engine.remediation.urllib.request.urlopen",
                return_value=mock_resp,
            ),
            pytest.raises(DiskMeasurementUnavailable),
        ):
            get_disk_free_percent("node-exporter:9100", "/var/lib/docker")


def test_get_disk_free_percent_raises_on_non_success_status():
    """Verify that get disk free percent raises on non success status."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    #
    # A malformed or error response must not reach the series-count check at
    # all -- it fails on the status field first, with a message that says so
    # rather than a generic "got 0 series".
    #
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = b'{"status": "error", "error": "bad query"}'

    with (
        patch(
            "automation.response_engine.remediation.urllib.request.urlopen",
            return_value=mock_resp,
        ),
        pytest.raises(DiskMeasurementUnavailable, match="non-success"),
    ):
        get_disk_free_percent("node-exporter:9100", "/var/lib/docker")


def test_get_disk_free_percent_raises_on_non_vector_result_type():
    """Verify that get disk free percent raises on non vector result type."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    #
    # An instant query always returns resultType "vector". Anything else
    # (e.g. "matrix", from a malformed range-style query) means the query
    # itself was wrong and the response must not be trusted.
    #
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = (
        b'{"status": "success", "data": {"resultType": "matrix", "result": []}}'
    )

    with (
        patch(
            "automation.response_engine.remediation.urllib.request.urlopen",
            return_value=mock_resp,
        ),
        pytest.raises(DiskMeasurementUnavailable, match="instant vector"),
    ):
        get_disk_free_percent("node-exporter:9100", "/var/lib/docker")


def test_get_disk_free_percent_wraps_request_failures():
    """Verify that get disk free percent wraps request failures."""
    import urllib.error

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    #
    # Proves urllib failures actually reach DiskMeasurementUnavailable rather
    # than propagating as a raw URLError -- the disk_cleanup-level test only
    # proves the caller handles DiskMeasurementUnavailable correctly, not that
    # the HTTP layer produces it.
    #
    with (
        patch(
            "automation.response_engine.remediation.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ),
        pytest.raises(DiskMeasurementUnavailable, match="connection refused"),
    ):
        get_disk_free_percent("node-exporter:9100", "/var/lib/docker")


def test_get_disk_free_percent_wraps_http_errors():
    """Verify that get disk free percent wraps http errors."""
    import urllib.error

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    #
    # HTTPError is a distinct failure mode from a connection-level URLError
    # (e.g. Prometheus itself returning 503) and deserves its own test, even
    # though HTTPError is a URLError subclass and the existing except clause
    # already catches it correctly.
    #
    with (
        patch(
            "automation.response_engine.remediation.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://prometheus:9090/api/v1/query",
                503,
                "Service Unavailable",
                {},
                None,
            ),
        ),
        pytest.raises(DiskMeasurementUnavailable, match="Prometheus query failed"),
    ):
        get_disk_free_percent("node-exporter:9100", "/var/lib/docker")


def test_get_disk_free_percent_raises_on_stale_sample():
    """Verify that get disk free percent raises on stale sample."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import (
        DISK_SAMPLE_MAX_AGE_SECONDS,
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    #
    # The most dangerous Prometheus-specific failure mode this redesign must
    # guard against: node-exporter stops scraping while its last sample read
    # comfortably above the threshold, and Prometheus keeps serving that
    # stale value forever. A retry loop alone does not catch this, since
    # every retry gets the identical stale sample -- only a freshness check
    # on the sample's own timestamp does.
    #
    stale_timestamp = time.time() - (DISK_SAMPLE_MAX_AGE_SECONDS + 30)
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = (
        f'{{"status": "success", "data": {{"resultType": "vector", "result": '
        f'[{{"metric": {{}}, "value": [{stale_timestamp}, "50"]}}]}}}}'
    ).encode()

    with (
        patch(
            "automation.response_engine.remediation.urllib.request.urlopen",
            return_value=mock_resp,
        ),
        pytest.raises(DiskMeasurementUnavailable, match="stale"),
    ):
        get_disk_free_percent("node-exporter:9100", "/var/lib/docker")


def test_get_disk_free_percent_accepts_a_fresh_sample():
    """Verify that get disk free percent accepts a fresh sample."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import get_disk_free_percent

    #
    # The counterpart to the staleness test above: a sample well within
    # DISK_SAMPLE_MAX_AGE_SECONDS must be accepted normally.
    #
    fresh_timestamp = time.time() - 5
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = (
        f'{{"status": "success", "data": {{"resultType": "vector", "result": '
        f'[{{"metric": {{}}, "value": [{fresh_timestamp}, "50"]}}]}}}}'
    ).encode()

    with patch(
        "automation.response_engine.remediation.urllib.request.urlopen",
        return_value=mock_resp,
    ):
        assert get_disk_free_percent("node-exporter:9100", "/var/lib/docker") == 50.0


def test_get_disk_free_percent_rejects_sample_that_predates_cleanup():
    """Verify that get disk free percent rejects sample that predates cleanup."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    #
    # A sample can be well within DISK_SAMPLE_MAX_AGE_SECONDS and still have
    # been taken before cleanup finished -- freshness alone does not prove
    # the measurement reflects the cleanup's effect. Simulate: cleanup
    # finished 2s ago, but the available Prometheus sample is from 5s ago
    # (before cleanup completed), well within the 30s staleness window but
    # still the wrong sample to trust.
    #
    cleanup_completed_at = time.time() - 2
    pre_cleanup_sample_timestamp = time.time() - 5

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = (
        f'{{"status": "success", "data": {{"resultType": "vector", "result": '
        f'[{{"metric": {{}}, "value": [{pre_cleanup_sample_timestamp}, "50"]}}]}}}}'
    ).encode()

    with (
        patch(
            "automation.response_engine.remediation.urllib.request.urlopen",
            return_value=mock_resp,
        ),
        pytest.raises(DiskMeasurementUnavailable, match="predates cleanup"),
    ):
        get_disk_free_percent(
            "node-exporter:9100",
            "/var/lib/docker",
            not_before=cleanup_completed_at,
        )


def test_get_disk_free_percent_accepts_sample_taken_after_cleanup():
    """Verify that get disk free percent accepts sample taken after cleanup."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import get_disk_free_percent

    #
    # The counterpart to the test above: a sample timestamped after
    # cleanup_completed_at must be accepted, proving not_before doesn't
    # reject valid post-cleanup measurements.
    #
    cleanup_completed_at = time.time() - 5
    post_cleanup_sample_timestamp = time.time() - 1

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = (
        f'{{"status": "success", "data": {{"resultType": "vector", "result": '
        f'[{{"metric": {{}}, "value": [{post_cleanup_sample_timestamp}, "42"]}}]}}}}'
    ).encode()

    with patch(
        "automation.response_engine.remediation.urllib.request.urlopen",
        return_value=mock_resp,
    ):
        result = get_disk_free_percent(
            "node-exporter:9100",
            "/var/lib/docker",
            not_before=cleanup_completed_at,
        )

    assert result == 42.0


def test_get_disk_free_percent_rejects_non_finite_and_out_of_range_values():
    """Verify that get disk free percent rejects non finite and out of range values."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        get_disk_free_percent,
    )

    #
    # Prometheus can serialize +Inf/-Inf/NaN as JSON strings, and
    # float("+Inf") parses without error -- an unvalidated value like that
    # would satisfy `>= threshold` and produce a false RESOLVED from a value
    # that was never a real percentage. Also reject an in-range-looking but
    # impossible percentage (150) as a defensive bound.
    #
    now = time.time()
    for bad_value in ("+Inf", "-Inf", "NaN", "150"):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = (
            f'{{"status": "success", "data": {{"resultType": "vector", "result": '
            f'[{{"metric": {{}}, "value": [{now}, "{bad_value}"]}}]}}}}'
        ).encode()

        with (
            patch(
                "automation.response_engine.remediation.urllib.request.urlopen",
                return_value=mock_resp,
            ),
            pytest.raises(DiskMeasurementUnavailable),
        ):
            get_disk_free_percent("node-exporter:9100", "/var/lib/docker")


def test_get_disk_free_percent_query_matches_alert_selection_semantics():
    """Verify that get disk free percent query matches alert selection semantics."""
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import get_disk_free_percent

    now = time.time()
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = (
        f'{{"status": "success", "data": {{"resultType": "vector", "result": '
        f'[{{"metric": {{}}, "value": [{now}, "42.5"]}}]}}}}'
    ).encode()

    captured_url = {}

    def _fake_urlopen(url, timeout=None):
        """Verify that fake urlopen."""
        captured_url["url"] = url
        return mock_resp

    with patch(
        "automation.response_engine.remediation.urllib.request.urlopen",
        side_effect=_fake_urlopen,
    ):
        result = get_disk_free_percent("node-exporter:9100", "/var/lib/docker")

    assert result == 42.5

    #
    # The query, url-decoded, must reproduce the alert rule's own selection
    # semantics EXACTLY (docker/prometheus/rules/alerts.yml:5) -- BOTH
    # exclusions, not just fstype. This is the regression guard for the
    # redesign's central correctness claim: the re-check measures exactly
    # the filesystem the alert fired on.
    #
    decoded_query = urllib.parse.unquote(captured_url["url"])
    assert 'job="node-exporter"' in decoded_query
    assert 'instance="node-exporter:9100"' in decoded_query
    assert 'mountpoint="/var/lib/docker"' in decoded_query
    assert 'fstype!~"tmpfs|erofs|overlay|squashfs"' in decoded_query
    assert 'mountpoint!~"/oldroot|/run.*"' in decoded_query


def test_promql_string_escapes_special_characters():
    """Verify that promql string escapes special characters."""
    from automation.response_engine.remediation import _promql_string

    #
    # A label containing a quote or backslash must produce a query PromQL can
    # still parse correctly, not a broken or injected string literal.
    #
    assert _promql_string('weird"quote') == '"weird\\"quote"'
    assert _promql_string("back\\slash") == '"back\\\\slash"'


def test_escalates_when_service_missing_from_cmdb(
    db_connection, make_incident, docker_client
):
    """Verify that escalates when service missing from cmdb."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="DiskPressure",
        playbook="disk_cleanup",
        service="deleted-service",
    )

    disk_cleanup(db_connection, docker_client, incident, CMDB)

    assert _status(db_connection, incident["id"]) == "ESCALATED"
    #
    # The CMDB check happens before any attempt is recorded, so no cleanup ran.
    #
    assert _attempts(db_connection, incident["id"]) == []
    docker_client.containers.prune.assert_not_called()


def test_prune_diagnostics_deletes_only_old_artifacts(tmp_path):
    """Verify that prune diagnostics deletes only old artifacts."""
    from automation.response_engine import remediation

    old = tmp_path / "INC-000001-attempt-1.json"
    recent = tmp_path / "INC-000002-attempt-1.json"
    old.write_text("{}")
    recent.write_text("{}")

    thirty_days_ago = time.time() - 30 * 86400
    os.utime(old, (thirty_days_ago, thirty_days_ago))

    with patch.object(remediation, "DIAGNOSTICS_DIR", tmp_path):
        deleted = remediation.prune_diagnostics(retention_days=14)

    assert deleted == 1
    assert not old.exists()
    assert recent.exists()


def test_prune_diagnostics_tolerates_missing_directory(tmp_path):
    """Verify that prune diagnostics tolerates missing directory."""
    from automation.response_engine import remediation

    with patch.object(remediation, "DIAGNOSTICS_DIR", tmp_path / "nope"):
        assert remediation.prune_diagnostics() == 0


def test_prune_docker_resources_calls_prune_surfaces():
    """
    Verify that _prune_docker_resources calls containers, images, and build cache prunes.
    """
    from unittest.mock import MagicMock

    from automation.response_engine.remediation import _prune_docker_resources

    client = MagicMock()
    _prune_docker_resources(client)

    client.containers.prune.assert_called_once()
    client.images.prune.assert_called_once_with(filters={"dangling": True})
    client.api.prune_builds.assert_called_once()
    client.volumes.prune.assert_not_called()


def test_await_disk_recovery_success():
    """
    Verify that await_disk_recovery returns (20.0, None) when disk recovers above threshold.
    """
    from automation.response_engine.remediation import await_disk_recovery

    with (
        patch(
            "automation.response_engine.remediation.get_disk_free_percent",
            return_value=20.0,
        ),
        patch("time.sleep"),
    ):
        pct, err = await_disk_recovery(
            "node-1", "/", cleanup_completed_at=100.0, timeout=20.0
        )

    assert pct == 20.0
    assert err is None


def test_await_disk_recovery_forwards_not_before():
    """
    Verify that await_disk_recovery explicitly passes cleanup_completed_at as not_before to get_disk_free_percent.
    """
    from automation.response_engine.remediation import await_disk_recovery

    cleanup_ts = 1723200000.5
    with (
        patch(
            "automation.response_engine.remediation.get_disk_free_percent",
            return_value=20.0,
        ) as mock_get,
        patch("time.sleep"),
    ):
        await_disk_recovery(
            "node-1", "/", cleanup_completed_at=cleanup_ts, timeout=20.0
        )

    mock_get.assert_called_once_with("node-1", "/", timeout=5.0, not_before=cleanup_ts)


def test_await_disk_recovery_below_threshold():
    """
    Verify that await_disk_recovery returns valid measurement even if below threshold when deadline expires.
    """
    from automation.response_engine.remediation import await_disk_recovery

    with (
        patch(
            "automation.response_engine.remediation.get_disk_free_percent",
            return_value=10.0,
        ),
        patch("time.monotonic", side_effect=[100.0, 105.0, 125.0]),
        patch("time.sleep"),
    ):
        pct, err = await_disk_recovery(
            "node-1", "/", cleanup_completed_at=100.0, timeout=20.0
        )

    assert pct == 10.0
    assert err is None


def test_await_disk_recovery_timeout_unavailable():
    """
    Verify that await_disk_recovery returns (None, error) when measurement is unavailable.
    """
    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        await_disk_recovery,
    )

    with (
        patch(
            "automation.response_engine.remediation.get_disk_free_percent",
            side_effect=DiskMeasurementUnavailable("Disk query failed"),
        ),
        patch("time.monotonic", side_effect=[100.0, 101.0, 125.0]),
        patch("time.sleep"),
    ):
        pct, err = await_disk_recovery(
            "node-1", "/", cleanup_completed_at=100.0, timeout=20.0
        )

    assert pct is None
    assert err is not None
    assert "Disk query failed" in err


def test_await_disk_recovery_sleep_bounded():
    """
    Verify that loop sleep uses min(interval, remaining).
    """
    import pytest

    from automation.response_engine.remediation import (
        DiskMeasurementUnavailable,
        await_disk_recovery,
    )

    with (
        patch(
            "automation.response_engine.remediation.get_disk_free_percent",
            side_effect=DiskMeasurementUnavailable("Disk low"),
        ),
        patch("time.monotonic", side_effect=[100.0, 101.0, 119.8, 120.0]),
        patch("time.sleep") as mock_sleep,
    ):
        await_disk_recovery(
            "node-1",
            "/",
            cleanup_completed_at=100.0,
            timeout=20.0,
            interval=5.0,
        )

    # 119.8 -> remaining 0.2s, so sleep must be approx 0.2, not 5.0
    actual_sleep = mock_sleep.call_args[0][0]
    assert actual_sleep == pytest.approx(0.2)


def test_await_disk_recovery_query_timeout_bounded():
    """
    Verify that get_disk_free_percent receives min(5.0, remaining) as timeout when near deadline.
    """
    import pytest

    from automation.response_engine.remediation import await_disk_recovery

    with (
        patch(
            "automation.response_engine.remediation.get_disk_free_percent",
            return_value=20.0,
        ) as mock_get,
        patch("time.monotonic", side_effect=[100.0, 119.8, 120.0]),
        patch("time.sleep"),
    ):
        await_disk_recovery("node-1", "/", cleanup_completed_at=100.0, timeout=20.0)

    # 119.8 -> remaining 0.2s, so timeout must be approx 0.2
    actual_timeout = mock_get.call_args.kwargs["timeout"]
    assert actual_timeout == pytest.approx(0.2)


# Regression test for issue #59: docker-health services can lose the race against a fixed VERIFY_TIMEOUT.
CADVISOR_CMDB = {
    "services": {
        "cadvisor": {
            "container_name": "sentinelops-cadvisor",
            "verification": {"type": "docker-health"},
        },
    },
}


def _fake_cadvisor_container(healthy_at_seconds: float, fake_clock):
    """A container whose health flips "starting" -> "healthy" `healthy_at_seconds` after each restart()."""
    container = MagicMock()
    restarted_at = []
    container.restart.side_effect = lambda: restarted_at.append(fake_clock[0])

    def _attrs():
        elapsed = fake_clock[0] - restarted_at[-1]
        is_healthy = elapsed >= healthy_at_seconds
        return {
            "Config": {
                "Healthcheck": {
                    "Test": ["CMD-SHELL", "wget --quiet --tries=1 --spider $URL"],
                    "Interval": 30_000_000_000,
                    "Timeout": 3_000_000_000,
                },
            },
            "State": {
                "Health": {
                    "Status": "healthy" if is_healthy else "starting",
                    "FailingStreak": 0,
                },
            },
        }

    # attrs is re-read after each reload() in verify_recovery, so use a property.
    type(container).attrs = property(lambda self: _attrs())
    return container


def test_resolves_docker_health_service_whose_first_probe_lands_at_the_computed_deadline(
    db_connection, make_incident, docker_client, fake_clock
):
    """Last poll tick for a 38s deadline is t=37 (while t < deadline) -- must still resolve there, not escalate."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="ServiceDown",
        playbook="restart_service",
        service="cadvisor",
    )

    container = _fake_cadvisor_container(healthy_at_seconds=37.0, fake_clock=fake_clock)
    docker_client.containers.get.return_value = container

    restart_service(db_connection, docker_client, incident, CADVISOR_CMDB)

    assert _status(db_connection, incident["id"]) == "RESOLVED"

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    assert attempts[0]["result"] == "success"
    assert attempts[0]["attempt_number"] == 1


def test_escalates_docker_health_service_whose_first_probe_lands_past_the_computed_deadline(
    db_connection, make_incident, docker_client, fake_clock
):
    """One tick past the last poll (t=38) is genuinely past the budget -- must escalate, proving the boundary test above isn't just loose."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="ServiceDown",
        playbook="restart_service",
        service="cadvisor",
    )

    container = _fake_cadvisor_container(healthy_at_seconds=38.0, fake_clock=fake_clock)
    docker_client.containers.get.return_value = container

    restart_service(db_connection, docker_client, incident, CADVISOR_CMDB)

    assert _status(db_connection, incident["id"]) == "ESCALATED"


def _heartbeat_value() -> float:
    return next(iter(WORKER_HEARTBEAT_TIMESTAMP.collect())).samples[0].value


def test_restart_service_refreshes_heartbeat_during_a_long_verify_loop(
    db_connection, make_incident, docker_client, fake_clock
):
    """A long docker-health verify budget must keep refreshing the worker heartbeat, or ResponseEngineDown (no `for:` grace period) would false-page during normal remediation."""
    incident = make_incident(
        status="ACKNOWLEDGED",
        alert_name="ServiceDown",
        playbook="restart_service",
        service="cadvisor",
    )

    WORKER_HEARTBEAT_TIMESTAMP.set(0)
    container = _fake_cadvisor_container(healthy_at_seconds=37.0, fake_clock=fake_clock)
    docker_client.containers.get.return_value = container
    before = time.time()

    restart_service(db_connection, docker_client, incident, CADVISOR_CMDB)

    # set_to_current_time() uses real time.time(), unaffected by fake_clock (which only patches monotonic/sleep).
    assert _heartbeat_value() >= before


def test_verify_timeout_for_extends_past_healthcheck_interval():
    """A 30s-interval healthcheck (like cadvisor's) needs more than VERIFY_TIMEOUT."""
    container = MagicMock()
    container.attrs = {
        "Config": {
            "Healthcheck": {"Interval": 30_000_000_000, "Timeout": 3_000_000_000}
        }
    }

    result = _verify_timeout_for(container, {"type": "docker-health"})

    assert result == 30 + 3 + 5  # interval + timeout + HEALTHCHECK_VERIFY_MARGIN


def test_verify_timeout_for_uses_default_when_healthcheck_interval_is_short():
    """A fast healthcheck shouldn't shrink the verify budget below VERIFY_TIMEOUT."""
    container = MagicMock()
    container.attrs = {
        "Config": {"Healthcheck": {"Interval": 5_000_000_000, "Timeout": 1_000_000_000}}
    }

    result = _verify_timeout_for(container, {"type": "docker-health"})

    assert result == 30


def test_verify_timeout_for_uses_docker_defaults_when_no_healthcheck_configured():
    """CMDB says docker-health but the image has no HEALTHCHECK -- don't crash, assume Docker's 30s/30s defaults."""
    container = MagicMock()
    container.attrs = {"Config": {"Healthcheck": None}}

    result = _verify_timeout_for(container, {"type": "docker-health"})

    assert result == 60  # capped at HEALTHCHECK_VERIFY_MAX; 30+30+5=65 uncapped


def test_verify_timeout_for_treats_missing_interval_as_docker_default_not_zero():
    """A HEALTHCHECK with no explicit --interval/--timeout (like api's Dockerfile) reports no Interval/Timeout keys at all -- must not be treated as 0s."""
    container = MagicMock()
    container.attrs = {"Config": {"Healthcheck": {"Test": ["CMD-SHELL", "curl -f x"]}}}

    result = _verify_timeout_for(container, {"type": "docker-health"})

    assert result == 60  # same as the no-healthcheck case: 30+30+5=65, capped at 60


def test_verify_timeout_for_caps_very_long_healthcheck_intervals():
    """A container with a multi-minute healthcheck interval must not hold the deadline open indefinitely."""
    container = MagicMock()
    container.attrs = {
        "Config": {
            "Healthcheck": {"Interval": 300_000_000_000, "Timeout": 3_000_000_000}
        }
    }

    result = _verify_timeout_for(container, {"type": "docker-health"})

    assert result == 60


def test_verify_timeout_for_accounts_for_start_period():
    """StartPeriod delays the first probe too -- a container with a long start_period must not time out before it's even eligible to report healthy."""
    container = MagicMock()
    container.attrs = {
        "Config": {
            "Healthcheck": {
                "Interval": 10_000_000_000,
                "Timeout": 3_000_000_000,
                "StartPeriod": 45_000_000_000,
            }
        }
    }

    result = _verify_timeout_for(container, {"type": "docker-health"})

    assert (
        result == 60
    )  # start_period(45) + interval(10) + timeout(3) + margin(5) = 63, capped at 60


def test_verify_timeout_for_does_not_crash_on_null_config():
    """Docker inspect can report "Config": null -- must fall back to defaults, not raise."""
    container = MagicMock()
    container.attrs = {"Config": None}

    result = _verify_timeout_for(container, {"type": "docker-health"})

    assert result == 60


def test_verify_timeout_for_does_not_crash_on_missing_verification_type():
    """A verification dict without a "type" key must fall back to VERIFY_TIMEOUT, not raise KeyError."""
    container = MagicMock()
    container.attrs = {"Config": {"Healthcheck": {"Interval": 300_000_000_000}}}

    result = _verify_timeout_for(container, {})

    assert result == 30


def test_verify_timeout_for_ignores_healthcheck_for_http_verification():
    """http verification isn't racing a container-owned polling cadence."""
    container = MagicMock()
    container.attrs = {
        "Config": {
            "Healthcheck": {"Interval": 300_000_000_000, "Timeout": 3_000_000_000}
        }
    }

    result = _verify_timeout_for(
        container, {"type": "http", "url": "http://api:5000/health"}
    )

    assert result == 30
