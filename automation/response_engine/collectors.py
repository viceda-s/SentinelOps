"""
Custom Prometheus metric collectors for SentinelOps.

Queries PostgreSQL state dynamically during scrapes to expose live incident counts
by service/severity/status (`sentinelops_incidents`) and worker queue depth (`sentinelops_queue_depth`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)


class IncidentsCollector(Collector):
    """
    Custom Prometheus collector for incident distribution metrics.

    Dynamically queries PostgreSQL on every scrape to report current incident counts
    grouped by (service, severity, status).
    """

    def __init__(self, connect: Callable[[], object]) -> None:
        """
        Initialize collector with a database connection factory.

        Args:
            connect: Callable returning an active PostgreSQL connection object.
        """
        self._connect = connect

    def collect(self) -> Generator[GaugeMetricFamily, None, None]:
        """
        Collect sentinelops_incidents gauge metric family.

        Yields:
            GaugeMetricFamily: Incident metrics with service, severity, and status labels.
        """
        family = GaugeMetricFamily(
            "sentinelops_incidents",
            "Current incidents by service, severity, and status",
            labels=["service", "severity", "status"],
        )

        try:
            #
            # The connection is owned by the injected connect() callable, not by the
            # collector. Production passes get_connection(); tests may deliberately
            # return a fixture-owned connection so the collector can observe
            # uncommitted rows. Do not close() the connection here.
            #
            conn = self._connect()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT service, severity, status, COUNT(*) AS n
                    FROM incidents
                    GROUP BY service, severity, status
                    """
                )

                for row in cur.fetchall():
                    family.add_metric(
                        [row["service"], row["severity"], row["status"]],
                        row["n"],
                    )

            #
            # Read-only query: release the implicit transaction without commiting anything.
            #
            conn.rollback()

        except Exception:
            logger.exception(
                "Failed to collect sentinelops_incidents; omitting from this scrape."
            )
            return

        yield family


class QueueDepthCollector(Collector):
    """
    State metric: incidents eligible to be claimed (status = NEW)

    Computed fresh from PostgreSQL on every scrape, same rationale as IncidentsCollector.
    """

    def __init__(self, connect: Callable[[], object]) -> None:
        """
        Initialize QueueDepthCollector with a database connection factory.

        Args:
            connect: Callable returning an active PostgreSQL connection object.
        """
        self._connect = connect

    def collect(self) -> Generator[GaugeMetricFamily, None, None]:
        """
        Collect sentinelops_queue_depth gauge metric family.

        Yields:
            GaugeMetricFamily: Queue depth metrics.
        """
        family = GaugeMetricFamily(
            "sentinelops_queue_depth",
            "Incidents currently eligible to be claimed by a worker",
        )

        try:
            #
            # The connection is owned by the injected connect() callable, not by the
            # collector. Production passes get_connection(); tests may deliberately
            # return a fixture-owned connection so the collector can observe
            # uncommitted rows. Do not close() the connection here.
            #
            conn = self._connect()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM incidents
                    WHERE status = 'NEW'
                    """
                )

                family.add_metric([], cur.fetchone()["n"])

            conn.rollback()

        except Exception:
            logger.exception(
                "Failed to collect sentinelops_queue_depth; omitting from this scrape."
            )
            return

        yield family
