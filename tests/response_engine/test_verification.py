from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from automation.response_engine.verification import verify_recovery


def test_running_check_returns_true_when_container_running(docker_client):
    container = docker_client.containers.get.return_value
    container.status = "running"

    result = verify_recovery(docker_client, "api", {"type": "running"})

    assert result is True
    container.reload.assert_called_once()


def test_running_check_returns_false_when_container_not_running(docker_client):
    container = docker_client.containers.get.return_value
    container.status = "exited"

    result = verify_recovery(docker_client, "api", {"type": "running"})

    assert result is False


def test_docker_health_check_returns_true_when_healthy(docker_client):
    container = docker_client.containers.get.return_value
    container.attrs = {"State": {"Health": {"Status": "healthy"}}}

    result = verify_recovery(docker_client, "api", {"type": "docker-health"})

    assert result is True


def test_docker_health_check_returns_false_when_unhealthy(docker_client):
    container = docker_client.containers.get.return_value
    container.attrs = {"State": {"Health": {"Status": "unhealthy"}}}

    result = verify_recovery(docker_client, "api", {"type": "docker-health"})

    assert result is False


def test_docker_health_check_returns_false_when_no_healthcheck_configured(
    docker_client,
):
    container = docker_client.containers.get.return_value
    container.attrs = {"State": {}}

    result = verify_recovery(docker_client, "api", {"type": "docker-health"})

    assert result is False


def test_http_check_returns_true_on_200(docker_client, monkeypatch):
    response = MagicMock(status_code=200)
    monkeypatch.setattr(requests, "get", MagicMock(return_value=response))

    result = verify_recovery(
        docker_client, "api", {"type": "http", "url": "http://apiL8080/health"}
    )

    assert result is True


def test_http_check_returns_false_on_non_200(docker_client, monkeypatch):
    response = MagicMock(status_code=503)
    monkeypatch.setattr(requests, "get", MagicMock(return_value=response))

    result = verify_recovery(
        docker_client, "api", {"type": "http", "url": "http://apiL8080/health"}
    )

    assert result is False


def test_http_check_returns_false_on_request_exception(docker_client, monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        MagicMock(side_effect=requests.exceptions.ConnectionError()),
    )

    result = verify_recovery(
        docker_client, "api", {"type": "http", "url": "http://apiL8080/health"}
    )

    assert result is False


def test_unknown_verification_type_raises(docker_client):
    with pytest.raises(ValueError, match="Unknown verification type"):
        verify_recovery(docker_client, "api", {"type": "bogus"})
