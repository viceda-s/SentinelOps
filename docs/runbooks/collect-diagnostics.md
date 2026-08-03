# Collect Diagnostics

## Symptom

This runbook applies to the following alerts:

- `HighCPU`
- `HighMemory`
- `HighErrorRate`
- `HighLatency`

Each alert represents a different symptom but uses the same automated response.

## Detection

### HighCPU

- CPU usage > 90% for 5 minutes.

### HighMemory

- Memory usage > 85% for 5 minutes.

### HighErrorRate

- 5xx error ratio > 5% for 2 minutes.

### HighLatency

- p95 latency > 1s for 5 minutes.

## Automated response

Playbook: `collect_diagnostics`

The response engine will:

1. Capture a metrics snapshot.
2. Collect the last 100 container logs.
3. Collect container statistics.
4. Record the diagnostics.
5. Escalate the incident.

The playbook never restarts the affected service.

## Manual verification

Review the collected diagnostics to determine the underlying cause.

Depending on the alert, verify:

- CPU utilization
- Memory utilization
- Error rates
- Request latency

Determine whether the service has recovered since the diagnostics were collected or whether manual remediation is still required.

## Escalation

This playbook always escalates after collecting diagnostics.

Unlike `restart_service`, `collect_diagnostics` never attempts automated remediation. Its purpose is to preserve evidence while the issue is occurring and provide that evidence to an operator for investigation.
