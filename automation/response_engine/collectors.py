from __future__ import annotations

import logging
from collections.abc import Callable

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)


class IncidentsCollector(Collector):
    """
    State metric: current incident distribution by (service, severity, status).

    Computed fresh from PostgreSQL on every scrape -- never cached in process memory, so this can never disagree with the database or with any other process reading the same table.
    """

    def __init__(self, connect: Callable[[], object]):
        self._connect = connect

    def collect(self):
        family = GaugeMetricFamily(
            "sentinelops_incidents",
            "Current incidents by service, severity, and status",
            labels=["service", "severity", "status"],
        )

        try:
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

    def __init__(self, connect: Callable[[], object]):
        self._connect = connect

    def collect(self):
        family = GaugeMetricFamily(
            "sentinelops_queue_depth",
            "Incidents currently eligible to be claimed by a worker",
        )

        try:
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
                "Failed to collect sentinelops_depth_queue; omitting from this scrape."
            )
            return

        yield family
