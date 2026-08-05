-- Immutable incident audit log.
--
-- Records the incident's lifecycle: creation, state transitions, duplicate notifications, and operator notes. Remediation execution detail (individual restart attempts, their timing, and their verification outcome) is recorded separately in remediation_attempts and joined by incident_id when reconstructing a full incident timeline -- see implementation-findings.md finding 9.
--
-- Events are ordered using an explicit sequence number rather than relying solely on timestamps. This guarantees deterministic ordering even if two events happen within the same timestamp resolution.

CREATE TABLE incident_events (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER NOT NULL
        REFERENCES incidents(id)
        ON DELETE RESTRICT,
    sequence INTEGER NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    message TEXT NOT NULL,
    payload JSONB NOT NULL,

    UNIQUE (incident_id, sequence)
);
