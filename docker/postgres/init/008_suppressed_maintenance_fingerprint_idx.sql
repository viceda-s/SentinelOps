-- Prevents duplicate SUPPRESSED_MAINTENANCE incidents for the same
-- suppressed alert firing.
--
-- incidents_active_fingerprint_idx (002_incidents.sql) deliberately excludes
-- SUPPRESSED_MAINTENANCE: an alert that resolves and later re-fires during
-- the same maintenance window should produce a second incident, not be
-- deduplicated against the first. That means SUPPRESSED_MAINTENANCE
-- dedup keys on (fingerprint, detected_at) -- the alert's original startsAt --
-- rather than fingerprint alone.
--
-- Application code already performs this check (maintenance.py's
-- suppressed_incident_exists()) before inserting, but a check-then-insert
-- with no backing constraint is a race: two overlapping executions of the
-- maintenance poller (e.g. during a rolling restart) can both see "no row
-- exists" before either commits. This index closes that race the same way
-- incidents_active_fingerprint_idx already does for the webhook path --
-- the application check remains as the fast, common-case path, and this
-- index is the correctness backstop, raising a UniqueViolation for the
-- database to catch and reconcile.

CREATE UNIQUE INDEX incidents_suppressed_maintenance_fingerprint_idx
ON incidents (fingerprint, detected_at)
WHERE status = 'SUPPRESSED_MAINTENANCE';
