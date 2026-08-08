from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

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
    )

    with patch(
        "automation.response_engine.remediation.free_percent",
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
    )

    with patch(
        "automation.response_engine.remediation.free_percent",
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
    )

    with patch(
        "automation.response_engine.remediation.free_percent",
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
    )

    with patch(
        "automation.response_engine.remediation.free_percent",
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
    )

    #
    # Docker cleanup and diagnostics pruning both succeeded, but the
    # post-cleanup filesystem re-check could not be performed. This is a
    # distinct failure mode from the diagnostics-pruning failure above -- the
    # playbook cannot even tell whether the incident recovered -- and carries
    # its own escalation message.
    #
    with patch(
        "automation.response_engine.remediation.free_percent",
        side_effect=OSError("no such file or directory"),
    ):
        disk_cleanup(db_connection, docker_client, incident, CMDB)

    assert _status(db_connection, incident["id"]) == "ESCALATED"

    attempts = _attempts(db_connection, incident["id"])
    assert len(attempts) == 1
    assert attempts[0]["result"] == "failure"
    assert "no such file or directory" in attempts[0]["error"]

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT message FROM incident_events WHERE incident_id = %s ORDER BY sequence",
            (incident["id"],),
        )
        messages = [row["message"] for row in cur.fetchall()]
    assert "Unable to verify disk pressure after cleanup" in messages


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
