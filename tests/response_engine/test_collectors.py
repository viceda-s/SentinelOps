from __future__ import annotations

import logging

from prometheus_client.core import GaugeMetricFamily

from automation.response_engine.collectors import (
    IncidentsCollector,
    QueueDepthCollector,
)


def test_incidents_collector_reflects_current_status_counts(
    db_connection,
    make_incident,
):
    """Verify that incidents collector reflects current status counts."""
    make_incident(
        status="NEW",
        service="api",
        severity="critical",
    )
    make_incident(
        status="NEW",
        service="api",
        severity="critical",
    )
    make_incident(
        status="ACKNOWLEDGED",
        service="nginx",
        severity="warning",
    )

    def connect():
        """Verify that connect."""
        return db_connection

    collector = IncidentsCollector(connect)

    families = list(collector.collect())

    assert len(families) == 1

    family = families[0]

    assert isinstance(family, GaugeMetricFamily)
    assert family.name == "sentinelops_incidents"

    samples = {
        (
            sample.labels["service"],
            sample.labels["severity"],
            sample.labels["status"],
        ): sample.value
        for sample in family.samples
    }

    assert samples[("api", "critical", "NEW")] == 2
    assert samples[("nginx", "warning", "ACKNOWLEDGED")] == 1


def test_queue_depth_collector_counts_only_new(
    db_connection,
    make_incident,
):
    """Verify that queue depth collector counts only new."""
    make_incident(status="NEW")
    make_incident(status="NEW")
    make_incident(status="ACKNOWLEDGED")

    def connect():
        """Verify that connect."""
        return db_connection

    collector = QueueDepthCollector(connect)

    families = list(collector.collect())

    assert len(families) == 1
    assert families[0].name == "sentinelops_queue_depth"
    assert families[0].samples[0].value == 2


def test_incidents_collector_omits_metric_on_query_failure(caplog):
    """Verify that incidents collector omits metric on query failure."""

    def connect():
        """Verify that connect."""
        raise RuntimeError("database unavailable")

    collector = IncidentsCollector(connect)

    with caplog.at_level(logging.ERROR):
        families = list(collector.collect())

    assert families == []

    assert (
        "Failed to collect sentinelops_incidents; omitting from this scrape."
        in caplog.text
    )
