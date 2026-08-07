from datetime import datetime, timezone
from uuid import uuid4

from prometheus_client import Counter

CMDB = {
    "services": {
        "api": {
            "owner": "platform-team",
            "tier": "prod",
            "criticality": "high",
            "playbooks": {
                "ServiceDown": "restart_service",
            },
            "sla": {
                "response_minutes": 5,
                "resolution_minutes": 30,
            },
        },
    },
}


def _firing_alert() -> dict:
    return {
        "status": "firing",
        "fingerprint": str(uuid4()),
        "startsAt": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "labels": {
            "alertname": "ServiceDown",
            "job": "api",
            "severity": "critical",
            "playbook": "restart_service",
        },
        "annotations": {},
    }


def counter_value(counter: Counter, **labels) -> float:
    """Return the current value of a labeled Counter"""
    metric = next(iter(counter.collect()))

    for sample in metric.samples:
        if sample.name.endswith("_total") and sample.labels == labels:
            return sample.value

    return 0.0
