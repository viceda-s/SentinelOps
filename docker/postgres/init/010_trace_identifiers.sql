-- Durable, queryable identity for one remediation execution (one restart
-- attempt, one collect_diagnostics run, one disk_cleanup run). Nullable and
-- not backfilled: historical rows have no reliable execution identity to
-- reconstruct. attempt_number remains the human-readable per-incident
-- sequence; execution_id is the globally-unique execution identity -- they
-- serve different purposes and both stay.
ALTER TABLE remediation_attempts
    ADD COLUMN execution_id UUID;

CREATE UNIQUE INDEX remediation_attempts_execution_id_idx
    ON remediation_attempts (execution_id);

-- Efficient lookup of every incident_events row caused by one webhook
-- request. correlation_id lives inside the existing payload JSONB column
-- (added by application code, not this migration) rather than as its own
-- incidents column, since one incident can be touched by many separate
-- webhook deliveries over its lifetime. The partial WHERE clause keeps the
-- index small: only rows that actually carry the key are included.
CREATE INDEX incident_events_correlation_id_idx
    ON incident_events ((payload ->> 'correlation_id'))
    WHERE payload ? 'correlation_id';
