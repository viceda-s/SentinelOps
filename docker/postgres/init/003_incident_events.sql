-- Immutable incident audit log.
--
-- Every meaningful action performed on an incident is recorded here: creation, state transitions, duplicate notifications, playbook activity, escalation, acknowledgements and operator notes.
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
