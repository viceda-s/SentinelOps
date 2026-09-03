from __future__ import annotations

import json
import os
import subprocess

import psycopg2
import pytest
import requests
from psycopg2.extras import RealDictCursor


def verify_stack_ready() -> bool:
    """
    Verify that required Docker Compose services are running and infrastructure endpoints respond.
    Services with a Docker healthcheck must report 'healthy'; services without a healthcheck
    are accepted when state is 'running'.
    """
    try:
        host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
        port = int(os.environ.get("POSTGRES_PORT", "5432"))
        dbname = os.environ.get("POSTGRES_DB")
        user = os.environ.get("POSTGRES_USER")
        password = os.environ.get("POSTGRES_PASSWORD")

        if not dbname or not user or not password:
            return False

        # Inspect running Compose services explicitly
        res = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return False

        services = []
        for line in res.stdout.strip().splitlines():
            try:
                services.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        required_services = {"postgres", "prometheus", "webhook-handler", "worker"}
        running_services = set()

        for s in services:
            service_name = s.get("Service", "")
            state = s.get("State", "").lower()
            health = s.get("Health", "").lower()

            if state == "running" and (not health or health == "healthy"):
                running_services.add(service_name)

        if not required_services.issubset(running_services):
            return False

        # Check Prometheus API
        p_res = requests.get("http://localhost:9090/-/healthy", timeout=5)
        if p_res.status_code != 200:
            return False

        # Check Webhook Handler Health/Metrics
        w_res = requests.get("http://localhost:5002/metrics", timeout=5)
        if w_res.status_code != 200:
            return False

        # Check DB connection
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=5,
            cursor_factory=RealDictCursor,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001 -- any failure here means "not ready"
        return False


@pytest.fixture(autouse=True)
def chaos_teardown(request):
    """Guaranteed teardown fixture running reset and stack readiness check for E2E scenarios."""
    if "e2e" not in request.node.keywords:
        yield
        return

    if not verify_stack_ready():
        pytest.skip(
            "Docker Compose stack not running or unhealthy; run bootstrap.sh first"
        )

    yield

    # Ensure chaos reset and stopped Compose services are restored
    reset_res = subprocess.run(
        ["./automation/scripts/chaos.sh", "reset"],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["docker", "compose", "start", "api"],
        capture_output=True,
        text=True,
        check=False,
    )

    if reset_res.returncode != 0:
        pytest.fail(f"Teardown failure: chaos.sh reset failed: {reset_res.stderr}")

    if not verify_stack_ready():
        pytest.fail(
            "Teardown failure: Stack failed to return to healthy baseline after chaos.sh reset"
        )
