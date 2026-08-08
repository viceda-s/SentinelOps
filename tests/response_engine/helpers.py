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


def _suppressed_alert(*silence_ids: str) -> dict:
    """
    Build an alert shaped like a GET /api/v2/alerts response.

    Differs from _firing_alert() in one important way: the v2 API returns status as an object, not the string the webhook payload carries. The maintenance path reads status.silencedBy, so its fixtures must match.

    silencedBy is a list -- an alert can be covered by several silences at once, and each is deduplicated independently.
    """
    alert = _firing_alert()

    alert["status"] = {
        "state": "suppressed",
        "silencedBy": list(silence_ids),
        "inhibitedBy": [],
        "mutedBy": [],
    }

    return alert


def counter_value(counter: Counter, **labels) -> float:
    """Return the current value of a labeled Counter"""
    metric = next(iter(counter.collect()))

    for sample in metric.samples:
        if sample.name.endswith("_total") and sample.labels == labels:
            return sample.value

    return 0.0
