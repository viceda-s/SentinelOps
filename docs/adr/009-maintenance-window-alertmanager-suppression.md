# ADR-009: Maintenance Window Alertmanager Suppression

**Status:** Accepted

## Context

Phase 2 required supporting scheduled maintenance windows for monitored services. During maintenance, scheduled interventions (upgrades, configuration changes, or restarts) trigger alerts like `ServiceDown` or `HighCPU`. These alerts must not trigger active notifications, dispatch remediation playbooks, or escalate to human operators.

At the same time, suppressed alerts must not be discarded completely: operators require visibility into all firing alerts, and maintenance events must be recorded in the system of record (`incidents`) for auditing and SLA calculations.

## Decision

Maintenance windows are managed via dynamic Alertmanager silences synchronized with a dedicated PostgreSQL incident state (`SUPPRESSED_MAINTENANCE`).

1. **Alertmanager Silence Integration**:
   - `automation/scripts/maintenance.sh` interacts directly with Alertmanager's `/api/v2/silences` API to create or expire silences during maintenance windows.
2. **Maintenance Monitor Service**:
   - A dedicated `maintenance-monitor` process polls Alertmanager (`/api/v2/alerts?silenced=true&active=true`) every 30 seconds.
   - Silenced alerts are ingested and immediately transitioned to the `SUPPRESSED_MAINTENANCE` state rather than `NEW` or `IN_PROGRESS`.
3. **Actionable Incident Reconciliation**:
   - If a silenced alert matches an existing open actionable incident (`NEW`, `ACKNOWLEDGED`, `IN_PROGRESS`, `ESCALATED`) created before the maintenance window began, the incident state is left unchanged and a reconciliation `NOTE` event is appended referencing the silence ID (`silence_id`).
4. **Note Event Deduplication**:
   - A partial unique index (`incident_events_maintenance_silence_idx`) on `(incident_id, silence_id)` enforces note event deduplication across polling iterations.

## Alternatives considered

* **Suppress alerts at the Prometheus query level.** Rejected because modifying Prometheus alert expressions during maintenance windows removes alert visibility entirely and leaves no audit trail in PostgreSQL.
* **Filter alerts in the webhook handler.** Rejected because discarding webhooks at ingestion prevents recording maintenance suppressed events in `incidents` and `incident_events`.
* **Dispatch playbooks but skip notifications.** Rejected because running restart or diagnostic playbooks during active operator maintenance could disrupt maintenance operations.

## Consequences

* Maintenance suppression is fully non-destructive and auditable: alerts occurring during maintenance create `SUPPRESSED_MAINTENANCE` incidents without triggering automated restarts or notifications.
* Actionable incidents created prior to maintenance windows are preserved and enriched with maintenance reconciliation notes rather than being forcefully overwritten.
* Partial unique indexing prevents repeated 30-second polling iterations from producing duplicate note events for the same silence.
* The maintenance monitor relies on Alertmanager's availability; if Alertmanager is unreachable, heartbeat metrics (`sentinelops_maintenance_heartbeat_timestamp`) flag the failure.
