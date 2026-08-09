"""
Domain configuration dataclasses for SentinelOps response engine services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL database connection configuration for response engine."""

    host: str
    port: int
    dbname: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        return cls(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.environ["RESPONSE_ENGINE_DB_USER"],
            password=os.environ["RESPONSE_ENGINE_DB_PASSWORD"],
            dbname=os.getenv("POSTGRES_DB", "postgres"),
        )


@dataclass(frozen=True)
class PrometheusSettings:
    """Prometheus metrics endpoint and threshold configuration."""

    url: str
    disk_pressure_free_percent: float

    @classmethod
    def from_env(cls) -> PrometheusSettings:
        return cls(
            url=os.getenv("PROMETHEUS_URL", "http://prometheus:9090"),
            disk_pressure_free_percent=float(
                os.getenv("DISK_PRESSURE_FREE_PERCENT", "15")
            ),
        )


@dataclass(frozen=True)
class DiagnosticsSettings:
    """Diagnostics artifact directory and retention configuration."""

    dir_path: Path
    retention_days: int

    @classmethod
    def from_env(cls) -> DiagnosticsSettings:
        return cls(
            dir_path=Path(os.getenv("DIAGNOSTICS_DIR", "/app/diagnostics")),
            retention_days=int(os.getenv("DIAGNOSTICS_RETENTION_DAYS", "14")),
        )


@dataclass(frozen=True)
class CMDBSettings:
    """CMDB configuration path settings."""

    path: str

    @classmethod
    def from_env(cls) -> CMDBSettings:
        return cls(
            path=os.getenv("CMDB_PATH", "/app/cmdb/services.yaml"),
        )


@dataclass(frozen=True)
class AlertmanagerSettings:
    """Alertmanager HTTP endpoint configuration."""

    url: str

    @classmethod
    def from_env(cls) -> AlertmanagerSettings:
        return cls(
            url=os.getenv("ALERTMANAGER_URL", "http://alertmanager:9093"),
        )
