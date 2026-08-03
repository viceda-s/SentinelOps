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
