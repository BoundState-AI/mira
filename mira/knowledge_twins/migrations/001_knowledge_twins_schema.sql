-- Migration: 001_knowledge_twins_schema.sql
-- Purpose: Create schema for H2/O2 Knowledge Twins compatibility assessment
--
-- BoundState AI 2025
-- Version: 0.3.0
-- Classification: BoundState Proprietary
--
-- Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
-- Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
-- Co-Authored-By: Dr. Joseph Wilde, BoundState AI
--
-- Compliance: SWE-032, SWE-033, NASA-STD-6016, NASA-STD-6001B
-- Safety Critical: True
--
-- CRITICAL: Run this migration in a transaction

BEGIN;

-- Create schema if not exists
CREATE SCHEMA IF NOT EXISTS knowledge_twins;

-- Set search path
SET search_path TO knowledge_twins, public;

-- ---------------------------------------------------------------------------
-- Core Compatibility Records Table
-- ---------------------------------------------------------------------------
-- Envelope fields allow NULLs because MAPTIS data is incomplete

CREATE TABLE IF NOT EXISTS compatibility_records (
    record_id           VARCHAR(64) PRIMARY KEY,

    -- Identity fields (validated, not string-matched)
    material_key        VARCHAR(64) NOT NULL,  -- Canonical ID: "MAPTIS:{int}"
    material_name       VARCHAR(256) NOT NULL, -- Display only - NOT used for decisions
    material_type_key   INTEGER NOT NULL,
    material_family_key VARCHAR(32),           -- Validated MaterialFamilyKey enum or NULL

    -- Gas type (H2 or O2)
    gas_type            VARCHAR(2) NOT NULL,

    -- Envelope fields: ALL NULLABLE (MAPTIS reality)
    temp_min_f          FLOAT NULL,
    temp_max_f          FLOAT NULL,
    pressure_min_psia   FLOAT NULL,
    pressure_max_psia   FLOAT NULL,
    phase               VARCHAR(16) NOT NULL,
    concentration_pct   FLOAT NULL,

    -- Compatibility verdict and reasoning
    compatibility       VARCHAR(32) NOT NULL,
    reason              TEXT NOT NULL,
    mitigation          TEXT,

    -- Source references
    standard_ref        VARCHAR(128) NOT NULL,
    test_report_id      VARCHAR(64),
    source              VARCHAR(256) NOT NULL,

    -- Full record as JSONB for complex queries
    record_jsonb        JSONB NOT NULL,

    -- Timestamps
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT valid_gas_type CHECK (gas_type IN ('H2', 'O2')),
    CONSTRAINT valid_material_type CHECK (material_type_key IN (235, 239, 723, 229, 231, 232, 233)),
    CONSTRAINT valid_compatibility CHECK (compatibility IN ('compatible', 'marginal', 'incompatible', 'insufficient_data')),
    CONSTRAINT valid_phase CHECK (phase IN ('gaseous', 'liquid', 'supercritical', 'unknown')),
    CONSTRAINT valid_temp_range CHECK (temp_min_f IS NULL OR temp_max_f IS NULL OR temp_max_f >= temp_min_f),
    CONSTRAINT valid_pressure_range CHECK (pressure_min_psia IS NULL OR pressure_max_psia IS NULL OR pressure_max_psia >= pressure_min_psia),
    CONSTRAINT valid_concentration CHECK (concentration_pct IS NULL OR (concentration_pct >= 0 AND concentration_pct <= 100))
);

-- Indexes for compatibility_records
CREATE INDEX IF NOT EXISTS idx_compat_material_key ON compatibility_records(material_key);
CREATE INDEX IF NOT EXISTS idx_compat_gas_type ON compatibility_records(gas_type);
CREATE INDEX IF NOT EXISTS idx_compat_envelope ON compatibility_records(temp_min_f, temp_max_f, pressure_min_psia, pressure_max_psia);
CREATE INDEX IF NOT EXISTS idx_compat_compatibility ON compatibility_records(compatibility);
CREATE INDEX IF NOT EXISTS idx_compat_family ON compatibility_records(material_family_key);
CREATE INDEX IF NOT EXISTS idx_compat_source ON compatibility_records(source);

-- ---------------------------------------------------------------------------
-- Properties Table (Normalized for querying)
-- ---------------------------------------------------------------------------
-- Each property measurement with full provenance

CREATE TABLE IF NOT EXISTS compatibility_properties (
    id                  SERIAL PRIMARY KEY,
    record_id           VARCHAR(64) NOT NULL REFERENCES compatibility_records(record_id) ON DELETE CASCADE,

    -- Property identification
    property_key        VARCHAR(64) NOT NULL,  -- Validated PropertyKey enum
    value_numeric       FLOAT,
    value_text          VARCHAR(128),
    units               VARCHAR(32),

    -- Test conditions
    test_method         VARCHAR(64),
    test_temp_f         FLOAT,
    test_pressure_psia  FLOAT,

    -- Provenance
    source_ref          VARCHAR(256) NOT NULL,
    data_class          VARCHAR(32) NOT NULL,  -- direct_test, standard_table, bok_precedent, derived
    confidence          FLOAT NOT NULL DEFAULT 1.0,

    -- Constraints
    CONSTRAINT at_least_one_value CHECK (value_numeric IS NOT NULL OR value_text IS NOT NULL),
    CONSTRAINT valid_data_class CHECK (data_class IN ('direct_test', 'standard_table', 'bok_precedent', 'derived')),
    CONSTRAINT valid_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

-- Indexes for compatibility_properties
CREATE INDEX IF NOT EXISTS idx_props_record ON compatibility_properties(record_id);
CREATE INDEX IF NOT EXISTS idx_props_key ON compatibility_properties(property_key);
CREATE INDEX IF NOT EXISTS idx_props_data_class ON compatibility_properties(data_class);
CREATE INDEX IF NOT EXISTS idx_props_source ON compatibility_properties(source_ref);

-- ---------------------------------------------------------------------------
-- FAISS Index Mapping Table
-- ---------------------------------------------------------------------------
-- Maps FAISS vector IDs to record IDs (source of truth is PostgreSQL)

CREATE TABLE IF NOT EXISTS faiss_index_mapping (
    faiss_id            INTEGER NOT NULL,
    record_id           VARCHAR(64) NOT NULL REFERENCES compatibility_records(record_id),
    index_name          VARCHAR(32) NOT NULL,  -- 'h2_bok_v2' or 'o2_bok_v1'
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (faiss_id, index_name)
);

-- Indexes for faiss_index_mapping
CREATE INDEX IF NOT EXISTS idx_faiss_index_name ON faiss_index_mapping(index_name);
CREATE INDEX IF NOT EXISTS idx_faiss_record ON faiss_index_mapping(record_id);

-- ---------------------------------------------------------------------------
-- Scoring Profile Configuration Table
-- ---------------------------------------------------------------------------
-- Versioned scoring profiles with full provenance

CREATE TABLE IF NOT EXISTS scoring_profile_config (
    profile_id          VARCHAR(32) NOT NULL,
    version             VARCHAR(16) NOT NULL,
    gas_type            VARCHAR(2) NOT NULL,

    -- Configuration as JSONB
    weights_jsonb       JSONB NOT NULL,       -- {property_key: weight}
    thresholds_jsonb    JSONB NOT NULL,       -- {compatible: 0.75, marginal: 0.50}
    hard_rules_jsonb    JSONB,                -- {flammability_rating_reject: ["D", "X"]}
    family_bonus_jsonb  JSONB,                -- {austenitic_stainless: 0.10}

    -- Provenance
    provenance          TEXT NOT NULL,        -- Who set it, why
    effective_from      TIMESTAMP NOT NULL,
    effective_to        TIMESTAMP,

    PRIMARY KEY (profile_id, version),

    CONSTRAINT valid_profile_gas_type CHECK (gas_type IN ('H2', 'O2'))
);

-- Index for active profiles
CREATE INDEX IF NOT EXISTS idx_scoring_active ON scoring_profile_config(gas_type, effective_from, effective_to);

-- ---------------------------------------------------------------------------
-- Envelope Overlap Configuration Table
-- ---------------------------------------------------------------------------
-- Versioned envelope overlap weighting

CREATE TABLE IF NOT EXISTS envelope_overlap_config (
    config_id           VARCHAR(32) PRIMARY KEY,
    version             VARCHAR(16) NOT NULL,

    -- Weights as JSONB
    weights_jsonb       JSONB NOT NULL,       -- {temperature: 0.35, pressure: 0.35, phase: 0.20, concentration: 0.10}

    -- Provenance
    provenance          TEXT NOT NULL,
    effective_from      TIMESTAMP NOT NULL,
    effective_to        TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Insert Default Configurations
-- ---------------------------------------------------------------------------

-- H2 Scoring Profile
INSERT INTO scoring_profile_config (
    profile_id, version, gas_type,
    weights_jsonb, thresholds_jsonb, hard_rules_jsonb, family_bonus_jsonb,
    provenance, effective_from
) VALUES (
    'hydrogen_service', '1.0.0', 'H2',
    '{"h2_embrittlement_class": 0.35, "fracture_toughness_ksi_sqrt_in": 0.20, "elongation_pct_at_temp": 0.10, "h2_permeation_rate": 0.05}'::jsonb,
    '{"compatible": 0.75, "marginal": 0.50}'::jsonb,
    '{}'::jsonb,
    '{"austenitic_stainless": 0.10, "nickel_alloy": 0.10, "aluminum_alloy": 0.05, "copper_alloy": 0.03}'::jsonb,
    'Based on NASA Hydrogen Safety Standard (NSS 1740.16) and Sandia hydrogen materials compatibility guide (SAND2012_7321). Set by Dr. Wilde + Claude, 2025-12-17.',
    '2025-12-17T00:00:00Z'
) ON CONFLICT (profile_id, version) DO NOTHING;

-- O2 Scoring Profile
INSERT INTO scoring_profile_config (
    profile_id, version, gas_type,
    weights_jsonb, thresholds_jsonb, hard_rules_jsonb, family_bonus_jsonb,
    provenance, effective_from
) VALUES (
    'oxygen_service', '1.0.0', 'O2',
    '{"flammability_rating": 0.40, "ignition_energy_j": 0.15, "mechanical_impact_ft_lbs": 0.10, "autogenous_ignition_temp_f": 0.05}'::jsonb,
    '{"compatible": 0.70, "marginal": 0.45}'::jsonb,
    '{"flammability_rating_reject": ["D", "X", "U"]}'::jsonb,
    '{"austenitic_stainless": 0.05, "nickel_alloy": 0.05, "copper_alloy": 0.05}'::jsonb,
    'Based on NASA-STD-6001B and NASA-STD-6016C oxygen compatibility guidelines. Flammability ratings D, X, U are hard rejects. Set by Dr. Wilde + Claude, 2025-12-17.',
    '2025-12-17T00:00:00Z'
) ON CONFLICT (profile_id, version) DO NOTHING;

-- Default Envelope Overlap Config
INSERT INTO envelope_overlap_config (
    config_id, version, weights_jsonb, provenance, effective_from
) VALUES (
    'default_envelope', '1.0.0',
    '{"temperature": 0.35, "pressure": 0.35, "phase": 0.20, "concentration": 0.10}'::jsonb,
    'Initial weights based on engineering judgment. Temperature and pressure are primary drivers. Set by Dr. Wilde + Claude, 2025-12-17. Subject to DOE tuning.',
    '2025-12-17T00:00:00Z'
) ON CONFLICT (config_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Fluids Table (If not exists in maptis schema)
-- ---------------------------------------------------------------------------
-- This table maps fluid keys to fluid names for fluid_compatibility join

CREATE TABLE IF NOT EXISTS fluids (
    fluid_key           VARCHAR(64) PRIMARY KEY,
    fluid_name          VARCHAR(256) NOT NULL,
    gas_type            VARCHAR(2),  -- NULL if not H2/O2 relevant
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fluid name search
CREATE INDEX IF NOT EXISTS idx_fluids_name ON fluids(fluid_name);
CREATE INDEX IF NOT EXISTS idx_fluids_gas_type ON fluids(gas_type);

-- ---------------------------------------------------------------------------
-- Assessment Audit Log Table
-- ---------------------------------------------------------------------------
-- Tracks all assessments for SWE-033 compliance

CREATE TABLE IF NOT EXISTS assessment_audit_log (
    id                  SERIAL PRIMARY KEY,

    -- Query context
    material_key        VARCHAR(64) NOT NULL,
    gas_type            VARCHAR(2) NOT NULL,
    query_envelope_jsonb JSONB NOT NULL,

    -- Assessment result
    verdict             VARCHAR(32) NOT NULL,
    confidence_score    FLOAT NOT NULL,
    total_score         FLOAT NOT NULL,
    has_direct_evidence BOOLEAN NOT NULL,

    -- Configuration versions used
    scoring_profile_version VARCHAR(64) NOT NULL,
    envelope_config_version VARCHAR(64) NOT NULL,

    -- Full assessment for audit
    assessment_jsonb    JSONB NOT NULL,

    -- Timestamps
    assessed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assessed_by         VARCHAR(128)  -- User/system identifier
);

-- Indexes for audit log
CREATE INDEX IF NOT EXISTS idx_audit_material ON assessment_audit_log(material_key);
CREATE INDEX IF NOT EXISTS idx_audit_gas_type ON assessment_audit_log(gas_type);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON assessment_audit_log(assessed_at);
CREATE INDEX IF NOT EXISTS idx_audit_verdict ON assessment_audit_log(verdict);

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- View: H2 compatibility records
CREATE OR REPLACE VIEW h2_compatibility_records AS
SELECT * FROM compatibility_records WHERE gas_type = 'H2';

-- View: O2 compatibility records
CREATE OR REPLACE VIEW o2_compatibility_records AS
SELECT * FROM compatibility_records WHERE gas_type = 'O2';

-- View: Records with direct evidence
CREATE OR REPLACE VIEW direct_evidence_records AS
SELECT DISTINCT cr.*
FROM compatibility_records cr
JOIN compatibility_properties cp ON cr.record_id = cp.record_id
WHERE cp.data_class IN ('direct_test', 'standard_table');

-- View: Active scoring profiles
CREATE OR REPLACE VIEW active_scoring_profiles AS
SELECT *
FROM scoring_profile_config
WHERE effective_to IS NULL
ORDER BY effective_from DESC;

-- ---------------------------------------------------------------------------
-- Functions
-- ---------------------------------------------------------------------------

-- Function: Update timestamp on record modification
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-update updated_at
DROP TRIGGER IF EXISTS trigger_compat_updated_at ON compatibility_records;
CREATE TRIGGER trigger_compat_updated_at
    BEFORE UPDATE ON compatibility_records
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

COMMIT;

-- ---------------------------------------------------------------------------
-- Post-migration verification queries
-- ---------------------------------------------------------------------------
-- Run these manually to verify migration success:
--
-- SELECT COUNT(*) FROM compatibility_records;
-- SELECT * FROM active_scoring_profiles;
-- SELECT * FROM envelope_overlap_config;
-- SELECT table_name FROM information_schema.tables WHERE table_schema = 'knowledge_twins';
