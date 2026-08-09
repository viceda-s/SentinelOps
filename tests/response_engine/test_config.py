import os
from pathlib import Path
from unittest.mock import patch

import pytest

from automation.response_engine.config import (
    AlertmanagerSettings,
    CMDBSettings,
    DatabaseSettings,
    DiagnosticsSettings,
    PrometheusSettings,
)


def test_database_settings_from_env():
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5433",
        "POSTGRES_DB": "test_db",
        "RESPONSE_ENGINE_DB_USER": "resp_user",
        "RESPONSE_ENGINE_DB_PASSWORD": "resp_password",
    }
    with patch.dict(os.environ, env):
        db_s = DatabaseSettings.from_env()
        assert db_s.host == "localhost"
        assert db_s.port == 5433
        assert db_s.dbname == "test_db"
        assert db_s.user == "resp_user"
        assert db_s.password == "resp_password"


def test_database_settings_requires_response_engine_credentials():
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "test_db",
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(KeyError):
        DatabaseSettings.from_env()


def test_prometheus_settings_from_env():
    env = {
        "PROMETHEUS_URL": "http://custom-prom:9090",
        "DISK_PRESSURE_FREE_PERCENT": "20.5",
    }
    with patch.dict(os.environ, env):
        prom_s = PrometheusSettings.from_env()
        assert prom_s.url == "http://custom-prom:9090"
        assert prom_s.disk_pressure_free_percent == 20.5


def test_diagnostics_settings_from_env():
    env = {
        "DIAGNOSTICS_DIR": "/custom/diagnostics",
        "DIAGNOSTICS_RETENTION_DAYS": "30",
    }
    with patch.dict(os.environ, env):
        diag_s = DiagnosticsSettings.from_env()
        assert diag_s.dir_path == Path("/custom/diagnostics")
        assert diag_s.retention_days == 30


def test_cmdb_settings_from_env():
    env = {"CMDB_PATH": "/custom/cmdb.yaml"}
    with patch.dict(os.environ, env):
        cmdb_s = CMDBSettings.from_env()
        assert cmdb_s.path == "/custom/cmdb.yaml"


def test_alertmanager_settings_from_env():
    env = {"ALERTMANAGER_URL": "http://custom-am:9093"}
    with patch.dict(os.environ, env):
        am_s = AlertmanagerSettings.from_env()
        assert am_s.url == "http://custom-am:9093"
