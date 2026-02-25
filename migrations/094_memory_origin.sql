-- TASK-095 v2: Cold memory origin tracking.
-- vec0 virtual tables don't support ALTER TABLE, so we use a separate lookup table.
-- Every cold memory read/write path JOINs against this table.

CREATE TABLE IF NOT EXISTS cold_memory_origin (
    source_id TEXT PRIMARY KEY,
    origin TEXT NOT NULL DEFAULT 'organic'
    -- Values: 'organic' (self-generated), 'manager_injected' (backstory from manager)
);

-- Backfill: all pre-existing cold memories are organic (self-generated).
INSERT OR IGNORE INTO cold_memory_origin (source_id, origin)
SELECT source_id, 'organic' FROM cold_memory_vec;
