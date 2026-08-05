from pathlib import Path

import pytest

from automation.scripts import validate_cmdb
from automation.scripts.validate_cmdb import validate


@pytest.fixture(autouse=True)
def isolate_repository_checks(monkeypatch):
    """Disable repository-wide validation checks unrelated to these tests."""
    missing = Path("/definitely/does/not/exist")

    monkeypatch.setattr(validate_cmdb, "PROMETHEUS_CONFIG", missing)
    monkeypatch.setattr(validate_cmdb, "COMPOSE_PATH", missing)


def make_service(playbook: str) -> dict:
    return {
        "container_name": "api",
        "owner": "platform-team",
        "tier": "prod",
        "criticality": "high",
        "runbook": "docs/runbooks/service-down.md",
        "verification": {
            "type": "running",
        },
        "sla": {
            "response_minutes": 5,
            "resolution_minutes": 30,
        },
        "playbooks": {
            "ServiceDown": playbook,
        },
    }


def test_validate_accepts_none_playbook():
    cmdb = {
        "services": {
            "api": make_service("none"),
        }
    }

    errors = validate(cmdb)

    assert errors == []


def test_validate_rejects_unknown_playbook():
    cmdb = {
        "services": {
            "api": make_service("definitely_not_a_real_playbook"),
        }
    }

    errors = validate(cmdb)

    assert len(errors) == 1
    assert "unknown playbook" in errors[0]
