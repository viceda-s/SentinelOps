-- Deduplicates maintenance reconciliation NOTE events by Alertmanager silence.
--
-- When a maintenance window silences an alert whose fingerprint already has an open actionable incident, process_suppressed_alert() records a reconciliation NOTE on that incident. It has no way to know it already did so, and re-notes on every 30s poll for as long as the collision persists (170 NOTE events over ~85 minutes were observed live during PR #11 verification).
--
-- Deduplication keys on the Alertmanager silence ID -- the identity of the operator action being recorded -- rather than on message text or on the incident's last event. A text/position guard breaks as soon as any other event lands in between; the silence ID does not.
--
-- The index predicate is deliberately narrow. The invariant is "one reconciliation NOTE per incident per silence", NOT "one arbitrary event per incident per silence": a future STATE_CHANGE that also wants to name a silence must not be blocked by this index.
-- silence_id is nullable and NULL rows are excluded from the index, so the webhook duplicate-notification path (which records NOTEs without any silence) and all pre-existing NOTE rows are unaffected -- no backfill required.
--
-- As with incidents_active_fingerprint_idx and incidents_suppressed_maintenance_fingerprint_idx, the application performs a best-effort insert and reconciles the UniqueViolation: a check-then-insert with no backing constraint is a race two overlapping pollers can lose.

ALTER TABLE incident_events ADD COLUMN silence_id TEXT;

CREATE UNIQUE INDEX incident_events_maintenance_silence_idx
ON incident_events (incident_id, silence_id)
WHERE event_type = 'NOTE' AND silence_id IS NOT NULL;
