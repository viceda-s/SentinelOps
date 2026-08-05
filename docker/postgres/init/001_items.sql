-- The /items endpoint performs a real PostgreSQL query against this table, providing a simple end-to-end health check that exercises:
--
--   Client → Nginx → API → PostgreSQL → API → Client
--
-- The data itself has no business meaning; it simply verifies that the API can connect to the database and execute queries successfully.
--
-- This script runs automatically the first time the PostgreSQL data directory is initialized (docker-entrypoint-initdb.d).

CREATE TABLE IF NOT EXISTS items (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO items (name) VALUES
    ('widget'),
    ('gadget'),
    ('gizmo');

