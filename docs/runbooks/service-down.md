# Service Down

## Symptom

The monitored service is no longer responding.

## Detection

Alert: `ServiceDown`

Trigger condition:

- `up == 0` for 1 minute.

Severity:

- Critical

## Automated response

Playbook: `restart_service`

The response engine will:

1. Verify that the container exists.
2. Restart the container.
3. Wait for the service to start.
4. Verify recovery using the strategy configured in the CMDB for the affected service. Depending on the service, this may be an HTTP health endpoint, a Docker `HEALTHCHECK`, or confirmation that the container is running.
5. If verification fails, wait for the configured cooldown period and retry once.

The playbook is bounded to a maximum of two restart attempts.

## Manual verification

After automation completes:

1. Confirm the incident timeline shows a successful restart.
2. Confirm the affected service passes its configured verification strategy (see `cmdb/services.yaml`) — an HTTP health check, a Docker `HEALTHCHECK`, or a running-state check, depending on the service.
3. Verify the application is responding normally.
4. Confirm the alert has cleared in Prometheus/Alertmanager.

## Escalation

Escalate if:

- Both restart attempts fail.
- The health check continues to fail after the final restart attempt.
