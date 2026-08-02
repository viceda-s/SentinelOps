-- docker/postgres/init/001_items.sql
--
-- Placeholder table for the api service's /items endpoint. Content is arbitrary; it exists so /items does a real round trip to Postgres.
-- Runs once, automatically, on first container init (see docker-entrypoint-initdb.d in the postgres image docs).

CREATE TABLE IF NOT EXISTS items (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO items (name) VALUES
    ('widget'),
    ('gadget'),
    ('gizmo');

