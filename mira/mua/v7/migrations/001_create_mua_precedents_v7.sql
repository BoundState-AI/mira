-- MUA Precedents v7 — Canonical Schema
-- Replaces: mua_precedents (6,181 rows, v1 era)
-- Source: v6_cleaned.jsonl (5,650 records) + v5 historic_mua.jsonl (full-length rationale)
--
-- This is the single source of truth for MUA precedent search.
-- FAISS indexes become archive after this migration.
--
-- Date: 2026-02-08

BEGIN;

-- Preserve the old table for rollback
ALTER TABLE IF EXISTS mua_precedents RENAME TO mua_precedents_v1_archive;

-- Drop old sequence reference if it exists
-- (the archive table keeps its own sequence)

CREATE TABLE mua_precedents_v7 (
    id SERIAL PRIMARY KEY,

    -- Identity
    mua_number VARCHAR(100) NOT NULL,
    source_file VARCHAR(255) NOT NULL,
    source_hash VARCHAR(64),            -- SHA-256 of source PDF

    -- Material (search fields)
    material_designation TEXT NOT NULL,
    material_family VARCHAR(50),        -- canonical enum, nullable for unknowns
    specification TEXT,
    manufacturer TEXT,
    trade_name TEXT,

    -- Environment (envelope overlap fields)
    env_type VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    o2_percent FLOAT,
    pressure_psia FLOAT,
    temp_max_f FLOAT,
    temp_min_f FLOAT,
    is_habitable BOOLEAN DEFAULT FALSE,
    env_raw_text TEXT,                  -- preserve original for debugging

    -- Classification
    category VARCHAR(5),               -- I, II, III (68.5% null in source — OK)
    issues TEXT[] NOT NULL DEFAULT '{}', -- canonical: {SCC, FLAM, HEE, TOX, ...}
    determination VARCHAR(30) NOT NULL, -- APPROVED, REJECTED, APPROVED_WITH_LIMITS, etc.

    -- Content (return fields — the gold)
    rationale TEXT,
    application TEXT,

    -- 6016C extras (for draft generation — mostly null for existing records)
    appendix_b_code VARCHAR(10),       -- 103, 104, 105, 106, 107, 108
    closure_path VARCHAR(50),          -- MINOR_QUANTITY, CONFIG_ANALYSIS, HEAT_SINK, etc.

    -- Metadata
    confidence FLOAT DEFAULT 1.0,
    extraction_mode VARCHAR(20),       -- vision, text, manual
    is_umbrella BOOLEAN DEFAULT FALSE, -- umbrella MUAs cover multiple parts
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Search support
    search_vector TSVECTOR
);

-- ============================================================
-- Indexes for Sonnet-generated queries
-- ============================================================

-- Exact and family-based material search
CREATE INDEX idx_mua_v7_material ON mua_precedents_v7(material_designation);
CREATE INDEX idx_mua_v7_family ON mua_precedents_v7(material_family);

-- Envelope overlap queries
CREATE INDEX idx_mua_v7_env ON mua_precedents_v7(env_type);
CREATE INDEX idx_mua_v7_o2 ON mua_precedents_v7(o2_percent);
CREATE INDEX idx_mua_v7_pressure ON mua_precedents_v7(pressure_psia);
CREATE INDEX idx_mua_v7_temp_max ON mua_precedents_v7(temp_max_f);
CREATE INDEX idx_mua_v7_temp_min ON mua_precedents_v7(temp_min_f);

-- Classification filtering
CREATE INDEX idx_mua_v7_issues ON mua_precedents_v7 USING GIN(issues);
CREATE INDEX idx_mua_v7_determination ON mua_precedents_v7(determination);
CREATE INDEX idx_mua_v7_category ON mua_precedents_v7(category);

-- Full-text search on rationale + application
CREATE INDEX idx_mua_v7_search ON mua_precedents_v7 USING GIN(search_vector);

-- Source traceability
CREATE INDEX idx_mua_v7_source ON mua_precedents_v7(source_file);

-- ============================================================
-- Auto-populate search_vector on insert/update
-- ============================================================

CREATE OR REPLACE FUNCTION mua_precedents_search_vector_trigger()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.material_designation, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.rationale, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.application, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(NEW.env_raw_text, '')), 'D');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_mua_precedents_search_vector
    BEFORE INSERT OR UPDATE ON mua_precedents_v7
    FOR EACH ROW EXECUTE FUNCTION mua_precedents_search_vector_trigger();

COMMIT;
