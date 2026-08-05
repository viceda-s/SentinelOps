# ADR-003: Use PostgreSQL as the system of record

**Status:** Accepted

## Context

Separating webhook ingestion from remediation creates a coordination problem: the webhook handler must acknowledge Alertmanager immediately, while the remediation worker may process an incident seconds or minutes later.

The system therefore requires durable shared state that survives process crashes, supports concurrent access, records the complete incident lifecycle, and prevents multiple workers from claiming the same incident.

Introducing a dedicated message broker (for example Redis or RabbitMQ) would add another piece of infrastructure while still requiring a database to store incident history, remediation attempts, and audit events.

## Decision

Use PostgreSQL as the single system of record for the response engine.

All persistent operational state is stored in PostgreSQL, including:

- incidents
- incident events
- remediation attempts
- CMDB-backed incident metadata

The `webhook-handler` persists incidents and returns an HTTP response without waiting for remediation.

The worker claims actionable incidents from PostgreSQL, performs remediation, records the outcome, and transitions the incident through its lifecycle.

Incident claiming uses row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`) so multiple worker replicas can safely process the same incident queue without double-claiming work.

PostgreSQL is the only coordination mechanism between the webhook handler and the remediation worker. No direct process-to-process communication or external message queue is used.

## Alternatives considered

- **SQLite.** Rejected because it does not provide the concurrency model needed for multiple workers and is unsuitable as the long-term coordination point for the system.

- **Redis or RabbitMQ plus PostgreSQL.** Rejected because it introduces an additional service while PostgreSQL already provides durable storage, transactions, and safe work claiming. A separate queue would duplicate infrastructure without providing sufficient benefit for Phase 1.

- **In-memory queue.** Rejected because queued work would be lost on process restart and webhook ingestion could no longer be decoupled safely from remediation.

## Consequences

- Incident processing survives worker and webhook-handler restarts.
- Every state transition, remediation attempt, and audit event is stored durably.
- Multiple worker replicas can safely share the incident queue through row-level locking.
- The database becomes critical infrastructure for the response engine; if PostgreSQL is unavailable, new incidents cannot be accepted and existing incidents cannot progress.
- The architecture remains simple: one database provides persistence, coordination, and auditing instead of introducing a separate message broker.
