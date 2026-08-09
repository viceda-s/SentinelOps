# Incident Closure and Reports

## Symptom

An incident has reached `RESOLVED` status after automated or manual remediation and requires formal administrative closure, Root Cause Analysis (RCA) recording, and PDF report generation.

## Detection

Status: `RESOLVED`

Trigger condition:

- Service recovery verified after remediation playbook completion or manual operator intervention.

Severity:

- Operational administrative task.

## Automated response

Playbook: `incident-closure`

Closing an incident initiates the following automated pipeline:

1. **CLI Execution**: The operator invokes `automation/scripts/close_incident.sh <INCIDENT_REF> <RCA_FILE>`.
2. **State Transition**: `close_incident.py` acquires a row lock (`FOR UPDATE`), verifies the incident is in `RESOLVED` state, writes the `root_cause_analysis` text, and transitions status from `RESOLVED` to `CLOSED`.
3. **PDF Generation**: The `report-generator` background service scans PostgreSQL for `CLOSED` incidents without a corresponding `incident_reports` record.
4. **Report Rendering**: Generates a PDF report containing executive summary, timeline events, diagnostic evidence, and RCA using ReportLab.
5. **Static Publishing**: Writes `reports/INC-*.pdf` and records report metadata in `incident_reports`. Nginx serves PDF reports at `http://localhost:8080/reports/INC-*.pdf`.

## Manual verification

To close an incident and verify report generation:

1. **Verify incident status**:
   Ensure the incident is in `RESOLVED` state:
   ```bash
   psql -h localhost -U sentinelops -d sentinelops -c "SELECT reference, status FROM incidents WHERE reference='INC-2026-0001';"
   ```
2. **Create an RCA text file**:
   ```bash
   cat << 'EOF' > /tmp/rca.txt
   Root Cause: Memory leak in worker pool leading to out-of-memory crash.
   Resolution: Service restarted automatically by SentinelOps. Memory pool cap adjusted in configuration.
   EOF
   ```
3. **Execute closure script**:
   ```bash
   ./automation/scripts/close_incident.sh INC-2026-0001 /tmp/rca.txt
   ```
4. **Verify PDF report generation**:
   Confirm PDF report exists in `reports/`:
   ```bash
   ls -la reports/INC-2026-0001.pdf
   ```
   Or access via browser/curl:
   ```bash
   curl -I http://localhost:8080/reports/INC-2026-0001.pdf
   ```

## Escalation

Escalate if:

- Incident closure fails due to status mismatch (e.g. attempting to close an incident still in `IN_PROGRESS` or `ESCALATED`).
- `report-generator` service fails to pick up `CLOSED` incidents or fails during ReportLab PDF compilation.
- Generated PDF reports are missing timeline events or diagnostic evidence.
