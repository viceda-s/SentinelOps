from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest
from psycopg2.extras import Json

import docker
from automation.response_engine.remediation import disk_cleanup

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


def _status(db_connection, incident_id: int) -> str:
    with db_connection.cursor() as cur:
        cur.execute("SELECT status FROM incidents WHERE id = %s", (incident_id,))
        return cur.fetchone()["status"]


def _attempts(db_connection, incident_id: int) -> list[dict]:
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


def test_escalates_when_disk_still_low(db_connection, make_incident, docker_client):
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
        return_value=3.0,
    ):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

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
    db_connection, make_incident, docker_client
):
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

    with (
        patch(
            "automation.response_engine.remediation.get_disk_free_percent",
            side_effect=DiskMeasurementUnavailable("Prometheus query failed: timeout"),
        ),
        patch("automation.response_engine.remediation.time.sleep"),
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
    from automation.response_engine import remediation

    with patch.object(remediation, "DIAGNOSTICS_DIR", tmp_path / "nope"):
        assert remediation.prune_diagnostics() == 0
