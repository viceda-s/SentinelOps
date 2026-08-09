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
    make_incident(
        status="NEW",
        service="collector-svc-1",
        severity="critical",
    )
    make_incident(
        status="NEW",
        service="collector-svc-1",
        severity="critical",
    )
    make_incident(
        status="ACKNOWLEDGED",
        service="collector-svc-2",
        severity="warning",
    )

    def connect():
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

    assert samples[("collector-svc-1", "critical", "NEW")] == 2
    assert samples[("collector-svc-2", "warning", "ACKNOWLEDGED")] == 1


def test_queue_depth_collector_counts_only_new(
    db_connection,
    make_incident,
):
    def connect():
        return db_connection

    collector = QueueDepthCollector(connect)
    initial_families = list(collector.collect())
    initial_depth = initial_families[0].samples[0].value if initial_families else 0

    make_incident(status="NEW")
    make_incident(status="NEW")
    make_incident(status="ACKNOWLEDGED")

    families = list(collector.collect())

    assert len(families) == 1
    assert families[0].name == "sentinelops_queue_depth"
    assert families[0].samples[0].value - initial_depth == 2


def test_incidents_collector_omits_metric_on_query_failure(caplog):
    def connect():
        raise RuntimeError("database unavailable")

    collector = IncidentsCollector(connect)

    with caplog.at_level(logging.ERROR):
        families = list(collector.collect())

    assert families == []

    assert (
        "Failed to collect sentinelops_incidents; omitting from this scrape."
        in caplog.text
    )
