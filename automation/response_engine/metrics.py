"""
Prometheus metrics definitions for SentinelOps.

Defines counters, gauges, and histograms for tracking incident creation, remediation
attempts, SLA breaches, maintenance suppression, heartbeats, and MTTR durations.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

#
# Event metrics
#

INCIDENTS_CREATED_TOTAL = Counter(
    "sentinelops_incidents_created_total",
    "Total incidents created.",
    ("service", "severity"),
)

REMEDIATION_ATTEMPTS_TOTAL = Counter(
    "sentinelops_remediation_attempts_total",
    "Total remediation attempts.",
    ("playbook", "result"),
)

SLA_BREACHES_TOTAL = Counter(
    "sentinelops_sla_breaches_total",
    "Total SLA breaches.",
    ("type",),
)

SUPPRESSED_ALERTS_DISCOVERED_TOTAL = Counter(
    "sentinelops_suppressed_alerts_discovered_total",
    "Total suppressed alerts discovered during polling.",
)

SUPPRESSED_INCIDENTS_CREATED_TOTAL = Counter(
    "sentinelops_suppressed_incidents_created_total",
    "Total SUPPRESSED_MAINTENANCE incidents created.",
)

SUPPRESSED_ALERTS_DUPLICATE_TOTAL = Counter(
    "sentinelops_suppressed_alerts_duplicate_total",
    "Total suppressed alerts skipped because an incident already exists.",
)

ALERTMANAGER_REQUEST_FAILURES_TOTAL = Counter(
    "sentinelops_alertmanager_request_failures_total",
    "Total failed requests to the Alertmanager API.",
)

#
# Liveness metrics
#

WORKER_HEARTBEAT_TIMESTAMP = Gauge(
    "sentinelops_worker_heartbeat_timestamp",
    "Unix timestamp of the worker's most recent poll loop iteration.",
)

MAINTENANCE_HEARTBEAT_TIMESTAMP = Gauge(
    "sentinelops_maintenance_heartbeat_timestamp",
    "Unix timestamp of the maintenance monitor's most recent successful poll.",
)

#
# Duration metrics
#

INCIDENT_RESPONSE_SECONDS = Histogram(
    "sentinelops_incident_response_seconds",
    "Time from incident detection to acknowledgement.",
)

INCIDENT_RESOLUTION_SECONDS = Histogram(
    "sentinelops_incident_resolution_seconds",
    "Time from incident detection to resolution.",
)
