# Disk Cleanup

## Symptom

High disk utilization or low free space on a host filesystem hosting SentinelOps infrastructure services.

## Detection

Alert: `DiskPressure`

Trigger condition:

- Free space percentage on a monitored host filesystem drops below 15% (`DISK_PRESSURE_FREE_PERCENT`).

Severity:

- Warning

## Automated response

Playbook: `disk_cleanup`

The remediation engine (`automation/response_engine/remediation.py`) executes the following workflow:

1. **Docker Asset Pruning**:
   - Prunes stopped containers (`client.containers.prune()`).
   - Prunes dangling container images (`client.images.prune(filters={"dangling": True})`).
   - Prunes Docker build cache (`client.api.prune_builds()`).
   - **Safety Boundary**: Data volumes (`postgres_data`, `prometheus_data`) are **never** pruned to prevent data loss.
2. **Diagnostics Artifact Pruning**:
   - Prunes diagnostics JSON files in `/app/diagnostics/` older than 14 days (`DIAGNOSTICS_RETENTION_DAYS`).
3. **Prometheus Re-Check**:
   - Records `cleanup_completed_at` wall-clock timestamp.
   - Queries Prometheus `node_filesystem_avail_bytes` vs `node_filesystem_size_bytes` for the specific `instance` and `mountpoint` carrying `not_before=cleanup_completed_at`.
   - Polls for up to 20 seconds (`DISK_RECHECK_TIMEOUT`) at 5-second intervals to allow fresh scrape arrival.
4. **Resolution Decision**:
   - If free space percentage >= 15%, transitions incident status from `IN_PROGRESS` to `RESOLVED`.
   - If free space percentage remains < 15% or measurement is unavailable, transitions incident to `ESCALATED`.

## Manual verification

To verify free disk space and remediation status manually:

1. **Check host filesystem usage**:
   ```bash
   df -h /
   ```
2. **Query Prometheus disk metrics**:
   Query Prometheus API for target instance and mountpoint:
   ```bash
   curl -s "http://localhost:9090/api/v1/query?query=node_filesystem_avail_bytes/node_filesystem_size_bytes*100"
   ```
3. **Check Docker disk usage**:
   ```bash
   docker system df
   ```
4. **Verify incident resolution**:
   Confirm the incident timeline records `disk_cleanup` completion and state transition to `RESOLVED`.

## Escalation

Escalate if:

- Disk utilization remains above 85% (free space < 15%) after automated pruning.
- Alert missing `instance` or `mountpoint` labels required for Prometheus verification.
- Prometheus query returns `DiskMeasurementUnavailable` error or stale data (`> 30s` old).
