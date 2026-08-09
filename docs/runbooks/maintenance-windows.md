# Maintenance Windows

## Symptom

Services undergoing scheduled maintenance trigger alerts that must not produce active notifications or operator escalations.

## Detection

Alert: Any alert fired during an active Alertmanager silence.

Trigger condition:

- Alert matches an active Alertmanager silence rule created by `automation/scripts/maintenance.sh`.

Severity:

- Suppressed (`SUPPRESSED_MAINTENANCE` status in SentinelOps database).

## Automated response

Playbook: `maintenance-suppression`

The maintenance monitor service (`docker/maintenance-monitor/`) continuously polls Alertmanager (`/api/v2/alerts?silenced=true&active=true`):

1. Fetches active alerts matching silence rules in chronological order of `startsAt`.
2. Checks whether a `SUPPRESSED_MAINTENANCE` incident already exists for the alert's fingerprint and detection timestamp.
3. If no incident exists, ingests the alert and transitions the state machine to `SUPPRESSED_MAINTENANCE`.
4. If an active actionable incident (`NEW`, `ACKNOWLEDGED`, `IN_PROGRESS`, `ESCALATED`) already exists for the alert fingerprint, records a reconciliation `NOTE` event referencing the silence ID (`silence_id`).
5. Deduplicates repeated polling notes using the `incident_events_maintenance_silence_idx` partial unique constraint.

## Manual verification

To schedule, view, or end maintenance windows manually:

1. **Schedule a maintenance window**:
   ```bash
   ./automation/scripts/maintenance.sh start --service api --duration 60m --comment "Scheduled API maintenance"
   ```
2. **View active maintenance windows**:
   ```bash
   ./automation/scripts/maintenance.sh status
   ```
3. **Verify Alertmanager silences**:
   Access Alertmanager UI at `http://localhost:9093/#/silences` or query silence API:
   ```bash
   curl -s http://localhost:9093/api/v2/silences?filter=status.state=active
   ```
4. **End a maintenance window early**:
   ```bash
   ./automation/scripts/maintenance.sh end --silence-id <SILENCE_ID>
   ```

## Escalation

Escalate if:

- Alertmanager fails to accept silence rules during window setup.
- The `maintenance-monitor` container fails or its Prometheus heartbeat (`sentinelops_maintenance_heartbeat_timestamp`) stops advancing.
- Alerts during a maintenance window trigger active notifications or invalid state transitions.
