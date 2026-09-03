import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]


def _query_prometheus_sum(metric_expr: str) -> float:
    res = requests.get(
        "http://localhost:9090/api/v1/query",
        params={"query": f"sum({metric_expr})"},
        timeout=5,
    )
    res.raise_for_status()
    data = res.json()
    if data["status"] != "success":
        raise RuntimeError(f"Prometheus query failed: {data}")
    results = data["data"]["result"]
    if not results:
        return 0.0
    return float(results[0]["value"][1])


def _wait_for_metric_increment(
    metric_expr: str, baseline: float, deadline: float
) -> float:
    while time.monotonic() < deadline:
        val = _query_prometheus_sum(metric_expr)
        if val >= baseline + 1:
            return val
        time.sleep(1.5)
    return _query_prometheus_sum(metric_expr)


def _wait_for_incident(
    conn, service: str, alert_name: str, scenario_start: datetime, deadline: float
) -> dict:
    while time.monotonic() < deadline:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM incidents
                WHERE service = %s AND alert_name = %s AND detected_at >= %s
                ORDER BY id DESC LIMIT 1
                """,
                (service, alert_name, scenario_start),
            )
            inc = cur.fetchone()
            if inc:
                return inc
        time.sleep(1.5)
    raise TimeoutError(
        f"Incident for service '{service}' and alert '{alert_name}' not detected before scenario deadline"
    )


def _wait_for_incident_status(
    conn, incident_id: int, target_status: str, deadline: float
) -> dict:
    last_status = None
    while time.monotonic() < deadline:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,))
            inc = cur.fetchone()
            if inc:
                last_status = inc["status"]
                if last_status == target_status:
                    return inc
        time.sleep(1.5)
    raise TimeoutError(
        f"Incident ID {incident_id} failed to reach status '{target_status}' before scenario deadline (last observed status: '{last_status}')"
    )


@pytest.mark.e2e
@pytest.mark.chaos
def test_e2e_service_down_restart_playbook(db_connection):
    # Enforce scenario-wide 120-second monotonic deadline
    scenario_deadline = time.monotonic() + 120.0

    # 1. Scrape baseline metric using PromQL sum(...)
    before_count = _query_prometheus_sum(
        "sentinelops_incident_resolution_seconds_count"
    )

    # 2. Precondition check: no active ServiceDown incident for api
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM incidents
            WHERE service = 'api' AND alert_name = 'ServiceDown'
              AND status IN ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'ESCALATED')
            """
        )
        assert cur.fetchone() is None, (
            "Precondition failed: active ServiceDown incident already exists"
        )

    # 3. Capture timestamp immediately before fault injection
    scenario_start = datetime.now(timezone.utc)
    res = subprocess.run(
        ["./automation/scripts/chaos.sh", "stop", "api"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.returncode == 0

    # 4. Wait for incident creation then wait for RESOLVED status under scenario_deadline
    created_incident = _wait_for_incident(
        db_connection, "api", "ServiceDown", scenario_start, scenario_deadline
    )
    resolved_incident = _wait_for_incident_status(
        db_connection, created_incident["id"], "RESOLVED", scenario_deadline
    )

    # 5. Assert state machine transition sequence in chronological order
    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT event_type, from_status, to_status FROM incident_events WHERE incident_id = %s ORDER BY sequence ASC",
            (resolved_incident["id"],),
        )
        events = cur.fetchall()

    event_types = [e["event_type"] for e in events]
    assert "CREATED" in event_types
    assert "STATE_CHANGE" in event_types

    state_changes = [
        (e["from_status"], e["to_status"])
        for e in events
        if e["event_type"] == "STATE_CHANGE"
    ]
    expected_sequence = [
        ("NEW", "ACKNOWLEDGED"),
        ("ACKNOWLEDGED", "IN_PROGRESS"),
        ("IN_PROGRESS", "RESOLVED"),
    ]
    assert state_changes == expected_sequence, (
        f"Expected chronological transitions {expected_sequence}, got {state_changes}"
    )

    # 6. Assert restart_service remediation attempt
    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT * FROM remediation_attempts WHERE incident_id = %s ORDER BY attempt_number ASC",
            (resolved_incident["id"],),
        )
        attempts = cur.fetchall()

    assert len(attempts) > 0
    assert attempts[0]["playbook"] == "restart_service"
    assert attempts[0]["result"].upper() == "SUCCESS"

    # 7. Assert host API service health
    api_health = requests.get("http://localhost:5001/health", timeout=5)
    assert api_health.status_code == 200

    # 8. Assert metric increment via async polling under scenario_deadline
    #
    # Not an exact +1: this metric observes every incident resolution, not just this
    # scenario's. The ServiceDown rule (`up == 0`) is intentionally global -- on a
    # freshly-bootstrapped stack, another service can still be stabilizing when this
    # runs and resolve its own transient ServiceDown incident inside this window.
    after_count = _wait_for_metric_increment(
        "sentinelops_incident_resolution_seconds_count", before_count, scenario_deadline
    )
    assert after_count >= before_count + 1


@pytest.mark.e2e
@pytest.mark.chaos
def test_e2e_high_error_rate_diagnostics_playbook(db_connection):
    scenario_deadline = time.monotonic() + 60.0

    scenario_start = datetime.now(timezone.utc)
    target_fingerprint = f"test-diag-{int(scenario_start.timestamp())}"

    # Precondition: no active HighErrorRate incident with this fingerprint
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM incidents
            WHERE fingerprint = %s
            """,
            (target_fingerprint,),
        )
        assert cur.fetchone() is None, (
            "Precondition failed: active HighErrorRate incident already exists for fingerprint"
        )

    # Inject alert via Alertmanager webhook payload to test real CMDB enrichment (job="api", alertname="HighErrorRate")
    webhook_payload = {
        "receiver": "sentinelops-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "job": "api",
                    "severity": "warning",
                },
                "annotations": {
                    "summary": "High error rate on api",
                    "description": "5xx error ratio has exceeded 5%",
                },
                "startsAt": scenario_start.isoformat(),
                "generatorURL": "http://localhost:9090",
                "fingerprint": target_fingerprint,
            }
        ],
    }

    resp = requests.post(
        "http://localhost:5002/alerts", json=webhook_payload, timeout=5
    )
    assert resp.status_code == 200

    # Wait for incident creation by fingerprint
    created_incident = None
    while time.monotonic() < scenario_deadline:
        with db_connection.cursor() as cur:
            cur.execute(
                "SELECT * FROM incidents WHERE fingerprint = %s AND detected_at >= %s",
                (target_fingerprint, scenario_start),
            )
            created_incident = cur.fetchone()
            if created_incident:
                break
        time.sleep(1.5)

    assert created_incident is not None, (
        "HighErrorRate incident was not created before scenario deadline"
    )

    # Wait for ESCALATED status
    escalated_incident = _wait_for_incident_status(
        db_connection, created_incident["id"], "ESCALATED", scenario_deadline
    )
    assert escalated_incident["status"] == "ESCALATED"

    # Query DB for remediation attempt & diagnostics_path sorted by attempt_number
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM remediation_attempts
            WHERE incident_id = %s AND playbook = 'collect_diagnostics'
            ORDER BY attempt_number ASC
            """,
            (escalated_incident["id"],),
        )
        attempts = cur.fetchall()

    assert len(attempts) > 0
    attempt = attempts[0]
    assert attempt["result"].upper() == "SUCCESS"
    diag_path_str = attempt["diagnostics_path"]
    assert diag_path_str is not None

    # Resolve diagnostics path relative to REPO_ROOT (mapping container /app/ mount to host)
    if diag_path_str.startswith("/app/"):
        diag_file = REPO_ROOT / diag_path_str.removeprefix("/app/")
    else:
        diag_file = (
            REPO_ROOT / diag_path_str
            if not os.path.isabs(diag_path_str)
            else Path(diag_path_str)
        )
    assert diag_file.exists(), f"Diagnostics file {diag_file} missing on disk"

    # Parse JSON diagnostic artifact
    with open(diag_file, "r", encoding="utf-8") as f:
        diag_data = json.load(f)

    assert "service" in diag_data and diag_data["service"] == "api"
    assert "container" in diag_data and diag_data["container"] == "sentinelops-api"
    assert diag_data.get("logs")
    assert diag_data.get("stats")


@pytest.mark.e2e
@pytest.mark.chaos
def test_e2e_disk_pressure_cleanup_playbook(db_connection):
    # 240s covers one DiskPressure incident (a single-mountpoint Linux host, e.g. CI).
    # node-exporter can report several bind-mount views of the same underlying disk
    # (Docker Desktop's /host_mnt/* paths on macOS), fanning one real pressure event out
    # into multiple independent incidents that a single worker processes serially --
    # 400s leaves headroom for the worst case (5 mountpoints) observed locally without
    # loosening the per-incident RESOLVED wait itself.
    scenario_deadline = time.monotonic() + 400.0
    metric_query = 'sentinelops_remediation_attempts_total{playbook="disk_cleanup",result="success"}'
    before_count = _query_prometheus_sum(metric_query)

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM incidents
            WHERE alert_name = 'DiskPressure'
              AND status IN ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'ESCALATED')
            """
        )
        assert cur.fetchone() is None, (
            "Precondition failed: active DiskPressure incident already exists. "
            "DiskPressure's fingerprint is fully determined by its labels (mountpoint, "
            "instance, ...), so a prior run's incident for the same mountpoint blocks "
            "fresh detection here -- clear it (or run this scenario alone) before retrying."
        )

    scenario_start = datetime.now(timezone.utc)
    env = dict(os.environ)
    # GitHub-hosted runners have a large root filesystem with substantial free space
    # at job start (observed: ~144GB total, ~59% free), needing ~75GB to reach the
    # fill destination -- comfortable headroom above that, not sized for a laptop disk.
    env["CHAOS_FILL_MAX_MB"] = "120000"
    fill_result = subprocess.run(
        ["./automation/scripts/chaos.sh", "fill"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert fill_result.returncode == 0, (
        f"chaos.sh fill failed (exit {fill_result.returncode}):\n"
        f"stdout: {fill_result.stdout}\nstderr: {fill_result.stderr}"
    )

    # Wait for incident creation then wait for RESOLVED status under scenario_deadline
    created_incident = _wait_for_incident(
        db_connection,
        "node-exporter",
        "DiskPressure",
        scenario_start,
        scenario_deadline,
    )
    resolved_incident = _wait_for_incident_status(
        db_connection, created_incident["id"], "RESOLVED", scenario_deadline
    )
    assert resolved_incident["status"] == "RESOLVED"

    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM remediation_attempts
            WHERE incident_id = %s AND playbook = 'disk_cleanup'
            ORDER BY attempt_number ASC
            """,
            (resolved_incident["id"],),
        )
        attempts = cur.fetchall()

    assert len(attempts) > 0
    attempt = attempts[0]
    assert attempt["result"].upper() == "SUCCESS"

    # Not an exact +1: node-exporter can expose several bind-mount views of the same
    # underlying filesystem (e.g. Docker Desktop's /host_mnt/* paths on macOS), so one
    # real disk-pressure event can fan out into multiple independent DiskPressure firings,
    # each with its own successful disk_cleanup attempt.
    after_count = _wait_for_metric_increment(
        metric_query, before_count, scenario_deadline
    )
    assert after_count >= before_count + 1
