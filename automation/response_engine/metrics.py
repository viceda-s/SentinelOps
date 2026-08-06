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

#
# Liveness metrics
#

WORKER_HEARTBEAT_TIMESTAMP = Gauge(
    "sentinelops_worker_heartbeat_timestamp",
    "Unix timestamp of the worker's most recent poll loop iteration.",
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
