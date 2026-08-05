-- Allocates sequential incident reference numbers per calendar year.
--
-- The response engine performs an atomic UPSERT:
--
--   INSERT ... ON CONFLICT (year)
--   DO UPDATE SET next_value = next_value + 1
--   RETURNING next_value;
--
-- PostgreSQL's row-level locking guarantees that concurrent requests cannot allocate the same reference number.
--
-- The stored value is always the last reference number allocated for that year, keeping the database state and returned value identical.

CREATE TABLE incident_reference_counters (
    year INTEGER PRIMARY KEY,
    next_value INTEGER NOT NULL CHECK (next_value > 0)
);

COMMENT ON TABLE incident_reference_counters IS
'Tracks the last allocated incident reference number for each calendar year.';

COMMENT ON COLUMN incident_reference_counters.year IS
'UTC calendar year used in incident references (e.g. 2026).';

COMMENT ON COLUMN incident_reference_counters.next_value IS
'Last allocated reference number for the corresponding year.';
