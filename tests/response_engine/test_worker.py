from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from automation.response_engine.worker import dispatch


def test_dispatch_restart_service_playbook(monkeypatch, docker_client):
    mock_restart = MagicMock()
    monkeypatch.setattr(
        "automation.response_engine.worker.restart_service", mock_restart
    )

    conn = MagicMock()
    incident = {"playbook": "restart_service"}
    cmdb = {"service": "cmdb"}

    dispatch(conn, docker_client, incident, cmdb)

    mock_restart.assert_called_once_with(conn, docker_client, incident, cmdb)


def test_dispatch_collect_diagnostics_playbook(monkeypatch, docker_client):
    mock_collect = MagicMock()
    monkeypatch.setattr(
        "automation.response_engine.worker.collect_diagnostics", mock_collect
    )

    conn = MagicMock()
    incident = {"playbook": "collect_diagnostics"}
    cmdb = {"service": "cmdb"}

    dispatch(conn, docker_client, incident, cmdb)

    mock_collect.assert_called_once_with(conn, docker_client, incident, cmdb)


def test_dispatch_disk_cleanup_playbook(monkeypatch, docker_client):
    mock_cleanup = MagicMock()
    monkeypatch.setattr("automation.response_engine.worker.disk_cleanup", mock_cleanup)

    conn = MagicMock()
    incident = {"playbook": "disk_cleanup"}
    cmdb = {"service": "cmdb"}

    dispatch(conn, docker_client, incident, cmdb)

    mock_cleanup.assert_called_once_with(conn, docker_client, incident, cmdb)


def test_dispatch_none_playbook_escalates_incident(monkeypatch, docker_client):
    mock_transition = MagicMock()
    monkeypatch.setattr("automation.response_engine.worker.transition", mock_transition)

    conn = MagicMock()
    incident = {"playbook": "none", "reference": "INC-1"}
    cmdb = {"service": "cmdb"}

    result = dispatch(conn, docker_client, incident, cmdb)

    assert result is None
    mock_transition.assert_called_once_with(
        conn, incident, "ESCALATED", "worker", "No playbook configured."
    )


def test_dispatch_unknown_playbook_raises_runtime_error(docker_client):
    conn = MagicMock()
    incident = {"playbook": "bogus", "reference": "INC-2"}
    cmdb = {"service": "cmdb"}

    with pytest.raises(
        RuntimeError, match="Unknown playbook 'bogus' for incident INC-2"
    ):
        dispatch(conn, docker_client, incident, cmdb)
