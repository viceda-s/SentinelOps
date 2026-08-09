# ADR-010: SLA Breach Calculation and Metrics

**Status:** Accepted

## Context

Phase 2 required introducing Service Level Agreements (SLAs) for incident response and resolution time, tracking SLA breaches, and exporting Mean Time to Resolution (MTTR) metrics for operational dashboards.

Incident lifecycles involve variable durations between detection, acknowledgment, remediation, and resolution. Relying on manual operator calculation or post-hoc database queries makes SLA enforcement unreliable and prevents real-time alerting on SLA breaches.

## Decision

SLA targets and breach tracking are implemented directly in PostgreSQL and calculated asynchronously by the remediation worker.

1. **Severity-Based Targets**:
   - SLA targets are defined in CMDB metadata (`cmdb/services.yaml`) per service and severity level:
     - `critical` (P1): Response SLA = 5 min, Resolution SLA = 60 min.
     - `warning` (P2): Response SLA = 15 min, Resolution SLA = 240 min.
   - Values are copied to `incidents.sla_response_minutes` and `incidents.sla_resolution_minutes` at ingestion.
2. **Asynchronous Breach Determination**:
   - `check_sla_breaches()` runs periodically within the remediation worker loop (`automation/response_engine/sla.py`).
   - Queries compare PostgreSQL `clock_timestamp()` against `detected_at + make_interval(mins => sla_..._minutes)` for non-terminal incidents (`NEW`, `ACKNOWLEDGED`, `IN_PROGRESS`, `ESCALATED`).
   - PostgreSQL `clock_timestamp()` is used instead of `NOW()` to ensure accurate wall-clock comparison during multi-step worker transactions.
3. **Idempotent Breach Logging and Metrics**:
   - When a breach occurs, `sla_response_breached` or `sla_resolution_breached` is set to `TRUE`, an `incident_events` `NOTE` is logged, and `sentinelops_sla_breaches_total` Prometheus metric counters are incremented.
4. **MTTR and Duration Observation**:
   - State machine transitions (`automation/response_engine/state_machine.py`) measure duration histograms:
     - `ACKNOWLEDGED`: Observes response time in `sentinelops_incident_response_seconds`.
     - `RESOLVED`: Observes total resolution duration in `sentinelops_incident_resolution_seconds`.

## Alternatives considered

* **Calculate SLA breaches in Grafana/PromQL.** Rejected because Prometheus cannot enforce state machine updates or write audit events to PostgreSQL.
* **Calculate breaches synchronously on every API request.** Rejected because webhooks and HTTP queries should be fast and decoupled from periodic SLA scanning.
* **Use PostgreSQL `NOW()` in breach detection queries.** Rejected because `NOW()` freezes at transaction start time, which produces inaccurate duration comparisons when evaluating incidents during long transactions.

## Consequences

* SLA target tracking is transparent, automated, and enforced at the database level.
* Asynchronous worker checks guarantee SLA breaches are flagged promptly without blocking webhook ingestion.
* Using `clock_timestamp()` ensures real-time wall-clock precision for SLA breach detection.
* Prometheus metrics (`sentinelops_sla_breaches_total`, `sentinelops_incident_response_seconds`, `sentinelops_incident_resolution_seconds`) provide live data for Grafana SLA and MTTR dashboards.
