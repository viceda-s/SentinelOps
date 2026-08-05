# ADR-001: Separate webhook ingestion from the remediation worker

**Status:** Accepted

## Context

Alertmanager delivers alerts synchronously via an HTTP webhook (`webhook_configs` in `alertmanager.yml`). The receiving process must acknowledge requests quickly; otherwise Alertmanager treats the delivery as failed and retries it.

Remediation is fundamentally different. Restarting a service requires talking to the Docker Engine, waiting for recovery verification (`VERIFY_TIMEOUT` in `remediation.py`), and may legitimately take tens of seconds before an incident can be resolved or escalated.

Combining webhook ingestion and remediation in a single process would make incoming webhook latency depend on the duration of the slowest remediation currently in progress, reducing throughput during incidents and coupling two unrelated responsibilities.

## Decision

Split the response engine into two independent services:

- `webhook-handler` (`automation/response_engine/webhook_handler.py`) is a Flask application run by Gunicorn. Its responsibility is to receive Alertmanager webhooks, validate and parse the payload, enrich it from the CMDB, persist the resulting incident and event records to PostgreSQL, and return an HTTP response. It never interacts with the Docker Engine and never waits for remediation to complete.
- `worker` (`automation/response_engine/worker.py`) is a separate process that continuously polls PostgreSQL for actionable incidents. Incident claiming is implemented by `claim_incident()` in `automation/response_engine/claim.py`, which uses `SELECT ... FOR UPDATE SKIP LOCKED` so multiple worker replicas can safely share the same work queue without double-claiming incidents. Claimed incidents are then dispatched to the appropriate remediation implementation in `automation/response_engine/remediation.py`. The worker is the only component granted access to the Docker Engine through `/var/run/docker.sock`.


The two services communicate only through durable state stored in PostgreSQL. Neither process invokes the other directly.

## Alternatives considered

- **Single process with background threads.** Rejected because webhook handling and remediation would still share the same process, resource limits, and failure domain. It would also require exposing the Docker socket to the webhook-facing process.
- **Single process using `asyncio`.** Rejected because it preserves the same architectural coupling while introducing unnecessary complexity, including replacing the synchronous PostgreSQL access layer with an asynchronous one, without providing meaningful benefit for Phase 1.

## Consequences

- Webhook acknowledgement is decoupled from remediation duration, so Alertmanager receives a response immediately after the incident has been persisted.
- Only the remediation worker requires access to the Docker Engine, reducing the privileges of the externally reachable webhook service.
- The two services can be restarted, scaled, or deployed independently.
- Durable coordination between the two processes becomes a requirement, making PostgreSQL the system of record for incident processing.
