# Backup and Disaster Recovery

## Symptom

PostgreSQL database corruption, container volume loss, or routine disaster recovery testing requires backing up or restoring SentinelOps system state.

## Detection

Trigger condition:

- Scheduled automated backup job execution.
- Operational maintenance window or database upgrade preparation.
- System recovery after critical failure or storage corruption.

Severity:

- Operational procedure.

## Automated response

Playbook: `backup-and-restore`

The backup script (`automation/scripts/backup.sh`) executes the following workflow:

1. **Environment Validation**: Loads `.env` and validates `BACKUP_RETENTION >= 1` (rejecting non-positive values to prevent accidental wipeout).
2. **PostgreSQL Dump**: Uses `docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"` to export full schema and data to SQL.
3. **Grafana Configuration**: Copies provisioned dashboard JSON files from `docker/grafana/dashboards/`.
4. **Atomic Tarball Creation**: Packages files into `.sentinelops-*.tar.gz.tmp` in staging and atomically renames to `backups/sentinelops-YYYYMMDDTHHMMSSZ.tar.gz`.
5. **Retention Pruning**: Retains the newest `BACKUP_RETENTION` archives (default: 7) and prunes older archives.

## Manual verification

To execute a backup or restore the system from a backup archive:

1. **Execute backup**:
   ```bash
   ./automation/scripts/backup.sh
   ```
2. **Verify created archive**:
   Confirm archive file exists and is non-empty:
   ```bash
   ls -la backups/sentinelops-*.tar.gz
   tar -ztvf backups/sentinelops-*.tar.gz
   ```
3. **Database Restore Procedure**:
   To restore PostgreSQL state from a backup archive:
   ```bash
   # 1. Unpack archive to temporary staging directory
   mkdir -p /tmp/restore && tar -xzf backups/sentinelops-<TIMESTAMP>.tar.gz -C /tmp/restore

   # 2. Restore PostgreSQL database via container psql
   docker compose exec -T postgres psql -U sentinelops -d sentinelops < /tmp/restore/postgres.sql

   # 3. Clean up staging directory
   rm -rf /tmp/restore
   ```
4. **Verify restored data**:
   Confirm tables and incident records exist:
   ```bash
   docker compose exec postgres psql -U sentinelops -d sentinelops -c "SELECT COUNT(*) FROM incidents;"
   ```

## Escalation

Escalate if:

- `backup.sh` fails due to PostgreSQL connection timeout or container failure.
- `BACKUP_RETENTION` validation fails or backup storage filesystem is full.
- Database restore fails due to schema conflicts or corrupted SQL dump files.
