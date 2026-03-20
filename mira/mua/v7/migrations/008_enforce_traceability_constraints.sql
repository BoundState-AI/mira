-- MUA Precedents v7 - Enforce Source Traceability
--
-- Applies hard constraints after source_hash has been backfilled:
--   - source_hash must be present
--   - source_hash must look like SHA-256 hex (64 lowercase hex chars)
--
-- Run:
--   psql -d mira -f mira/mua/v7/migrations/008_enforce_traceability_constraints.sql

BEGIN;

-- Ensure no blank hashes survive.
UPDATE mua_precedents_v7
SET source_hash = NULL
WHERE source_hash IS NOT NULL
  AND trim(source_hash) = '';

ALTER TABLE mua_precedents_v7
    ALTER COLUMN source_hash SET NOT NULL;

-- Drop/recreate for idempotent reruns.
ALTER TABLE mua_precedents_v7
    DROP CONSTRAINT IF EXISTS chk_mua_v7_source_hash_sha256;

ALTER TABLE mua_precedents_v7
    ADD CONSTRAINT chk_mua_v7_source_hash_sha256
    CHECK (source_hash ~ '^[0-9a-f]{64}$');

-- Helpful for hash-based provenance checks.
CREATE INDEX IF NOT EXISTS idx_mua_v7_source_hash
    ON mua_precedents_v7(source_hash);

COMMIT;
