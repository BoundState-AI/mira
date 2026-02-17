-- Migration: 001_authority_fc_schema.sql
-- Purpose: Fracture Control Authority Pack — deterministic classification engine
--
-- BoundState AI 2026
-- Version: 1.0.0
-- Classification: BoundState Proprietary
--
-- Co-Authored-By: Claude "Beth" Opus 4.6 <noreply@anthropic.com>
-- Co-Authored-By: Dr. Joseph Wilde, BoundState AI
--
-- Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-5019A, NASA-STD-5009C, JSC-27301
-- Safety Critical: True
--
-- Source Standards:
--   NASA-STD-5019A  — Fracture Control Requirements for Spaceflight Hardware
--   NASA-STD-5009C  — Nondestructive Evaluation Requirements for Fracture-Critical Metallic Components
--   JSC-27301       — MSFC implementation (Materials & Fracture Control Certification)
--   ISO 14623       — Space systems — Pressure vessels and pressurized structures (design)
--
-- DESIGN PRINCIPLES (from multi-AI design review 2026-02-17):
--   1. PostgreSQL-first. No FAISS. Fracture is deterministic, not semantic.
--   2. Citation-closed: every output traces to doc/revision/section/page/hash.
--   3. CLARIFY on missing inputs, never assume or infer.
--   4. Pack versioning is immutable — new version only, never mutate active packs.
--   5. LLM role: intent parsing + answer formatting ONLY. No decisions.
--   6. Derived values computed at evaluation time, never stored pre-baked.
--   7. Classification rule order is safety-critical with explicit stop semantics.
--
-- CRITICAL: Run this migration in a transaction.

BEGIN;

-- ============================================================
-- Schema namespace
-- ============================================================

CREATE SCHEMA IF NOT EXISTS authority_fc;
SET search_path TO authority_fc, public;

-- ============================================================
-- 1. Pack Registry (versioned, immutable once active)
-- ============================================================

CREATE TABLE IF NOT EXISTS pack_registry (
    pack_id             VARCHAR(64) PRIMARY KEY,
    version             VARCHAR(32) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'draft',
    title               VARCHAR(256) NOT NULL,
    description         TEXT,
    source_standards    TEXT[] NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    activated_at        TIMESTAMPTZ,
    retired_at          TIMESTAMPTZ,
    created_by          VARCHAR(128) NOT NULL,
    provenance_hash     VARCHAR(64),

    CONSTRAINT valid_pack_status CHECK (status IN ('draft', 'pending_review', 'active', 'retired')),
    CONSTRAINT immutable_active CHECK (
        NOT (status = 'retired' AND activated_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_pack_status ON pack_registry(status);
CREATE INDEX IF NOT EXISTS idx_pack_version ON pack_registry(version);

-- ============================================================
-- 2. Source Documents (what we ingested and when)
-- ============================================================

CREATE TABLE IF NOT EXISTS source_documents (
    doc_id              SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),
    standard_number     VARCHAR(128) NOT NULL,
    revision            VARCHAR(32) NOT NULL,
    title               VARCHAR(512) NOT NULL,
    effective_date      DATE,
    total_pages         INTEGER,
    extraction_mode     VARCHAR(16) NOT NULL DEFAULT 'text',
    content_hash        VARCHAR(64) NOT NULL,
    ingested_at         TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_extraction_mode CHECK (extraction_mode IN ('text', 'vision', 'hybrid')),
    CONSTRAINT unique_doc_per_pack UNIQUE (pack_id, standard_number, revision)
);

CREATE INDEX IF NOT EXISTS idx_doc_pack ON source_documents(pack_id);
CREATE INDEX IF NOT EXISTS idx_doc_standard ON source_documents(standard_number);

-- ============================================================
-- 3. Requirement Clauses (individual normative statements)
-- ============================================================
-- Each row = one "shall" / "should" / "may" from a source document.
-- This is the citation anchor for every output.

CREATE TABLE IF NOT EXISTS requirement_clauses (
    clause_id           SERIAL PRIMARY KEY,
    doc_id              INTEGER NOT NULL REFERENCES source_documents(doc_id),
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),

    -- Location in source
    section_number      VARCHAR(64) NOT NULL,
    clause_number       VARCHAR(64),
    page_number         INTEGER,
    figure_reference    VARCHAR(64),
    table_reference     VARCHAR(64),

    -- Content
    modality            VARCHAR(16) NOT NULL DEFAULT 'SHALL',
    raw_text            TEXT NOT NULL,
    normalized_text     TEXT,

    -- Tagging
    topic_tags          TEXT[] NOT NULL DEFAULT '{}',
    applies_to_class    TEXT[] NOT NULL DEFAULT '{}',

    -- Active flag (partial index target)
    active              BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT valid_modality CHECK (modality IN ('SHALL', 'SHOULD', 'MAY', 'RECOMMENDED'))
);

CREATE INDEX IF NOT EXISTS idx_clause_doc ON requirement_clauses(doc_id);
CREATE INDEX IF NOT EXISTS idx_clause_pack ON requirement_clauses(pack_id);
CREATE INDEX IF NOT EXISTS idx_clause_section ON requirement_clauses(section_number);
CREATE INDEX IF NOT EXISTS idx_clause_topic ON requirement_clauses USING GIN(topic_tags);
CREATE INDEX IF NOT EXISTS idx_clause_class ON requirement_clauses USING GIN(applies_to_class);
CREATE INDEX IF NOT EXISTS idx_clause_active ON requirement_clauses(active) WHERE active = TRUE;

-- ============================================================
-- 4. Classification Rules (THE CORE DECISION ENGINE)
-- ============================================================
-- Encodes NASA-STD-5019A Section 6 / Figure 2 classification logic.
-- Rules evaluated in priority_order. First matching rule with
-- stop_processing=TRUE terminates classification.
--
-- SAFETY-CRITICAL: Rule order determines part classification.
-- A gap or misordering silently corrupts fracture assessments.

CREATE TABLE IF NOT EXISTS classification_rules (
    rule_id             SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),

    -- Evaluation order
    priority_order      INTEGER NOT NULL,
    stop_processing     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Rule identity
    rule_code           VARCHAR(32) NOT NULL,
    rule_name           VARCHAR(256) NOT NULL,
    description         TEXT,

    -- Predicate (JSONB DSL — evaluated by typed predicate engine)
    predicate_expr      JSONB NOT NULL,
    predicate_schema_version VARCHAR(16) NOT NULL DEFAULT '1.0.0',

    -- Minimum required context fields (auto-CLARIFY if missing)
    min_context_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Output
    output_part_class   VARCHAR(64) NOT NULL,
    output_fcr_set      TEXT[] NOT NULL DEFAULT '{}',
    output_nde_required BOOLEAN NOT NULL DEFAULT FALSE,

    -- Citation
    source_clause_ids   INTEGER[] NOT NULL DEFAULT '{}',
    source_figure       VARCHAR(64),
    source_table        VARCHAR(64),

    -- Active flag
    active              BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT unique_rule_order UNIQUE (pack_id, priority_order),
    CONSTRAINT unique_rule_code UNIQUE (pack_id, rule_code)
);

CREATE INDEX IF NOT EXISTS idx_rule_pack ON classification_rules(pack_id);
CREATE INDEX IF NOT EXISTS idx_rule_order ON classification_rules(pack_id, priority_order);
CREATE INDEX IF NOT EXISTS idx_rule_class ON classification_rules(output_part_class);
CREATE INDEX IF NOT EXISTS idx_rule_active ON classification_rules(active) WHERE active = TRUE;

-- ============================================================
-- 5. NDE Applicability (what inspection is required per class)
-- ============================================================
-- Maps part classification -> NDE method requirements.
-- Flaw detection fields stored as base values with explicit
-- units and statistical basis — NEVER pre-derived ratios.

CREATE TABLE IF NOT EXISTS nde_applicability (
    nde_id              SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),

    -- What this applies to
    part_class          VARCHAR(64) NOT NULL,
    geometry_type       VARCHAR(64),
    material_condition  VARCHAR(64),

    -- NDE method
    nde_method          VARCHAR(64) NOT NULL,
    nde_standard_ref    VARCHAR(128),

    -- Detectable flaw specification (explicit, not derived)
    detectable_flaw_value   NUMERIC(10,4),
    detectable_flaw_unit    VARCHAR(16) NOT NULL DEFAULT 'mm',
    flaw_type               VARCHAR(32) NOT NULL DEFAULT 'surface',
    statistical_basis       VARCHAR(32) NOT NULL DEFAULT '90/95 POD',

    -- POD confidence reference per 5009C
    pod_confidence_level    VARCHAR(64),

    -- Applicability predicate (optional further filtering)
    applicability_expr  JSONB,

    -- Citation
    source_clause_ids   INTEGER[] NOT NULL DEFAULT '{}',

    -- Active flag
    active              BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT valid_flaw_unit CHECK (detectable_flaw_unit IN ('mm', 'in', 'mils')),
    CONSTRAINT valid_flaw_type CHECK (flaw_type IN ('surface', 'subsurface', 'volumetric', 'through')),
    CONSTRAINT valid_stat_basis CHECK (statistical_basis IN ('90/95 POD', '90/50 POD', 'deterministic', 'engineering_judgment'))
);

CREATE INDEX IF NOT EXISTS idx_nde_pack ON nde_applicability(pack_id);
CREATE INDEX IF NOT EXISTS idx_nde_class ON nde_applicability(part_class);
CREATE INDEX IF NOT EXISTS idx_nde_method ON nde_applicability(nde_method);
CREATE INDEX IF NOT EXISTS idx_nde_active ON nde_applicability(active) WHERE active = TRUE;

-- ============================================================
-- 6. NDE Exceptions (when you DON'T need inspection)
-- ============================================================

CREATE TABLE IF NOT EXISTS nde_exceptions (
    exception_id        SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),

    -- What this exempts
    part_class          VARCHAR(64) NOT NULL,
    exception_code      VARCHAR(32) NOT NULL,
    exception_name      VARCHAR(256) NOT NULL,

    -- Conditions for exemption
    condition_expr      JSONB NOT NULL,

    -- What it exempts from
    exempts_nde_method  VARCHAR(64),
    exempts_all_nde     BOOLEAN NOT NULL DEFAULT FALSE,

    -- Citation
    source_clause_ids   INTEGER[] NOT NULL DEFAULT '{}',

    -- Active flag
    active              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_nde_exc_pack ON nde_exceptions(pack_id);
CREATE INDEX IF NOT EXISTS idx_nde_exc_class ON nde_exceptions(part_class);
CREATE INDEX IF NOT EXISTS idx_nde_exc_active ON nde_exceptions(active) WHERE active = TRUE;

-- ============================================================
-- 7. Material Fracture Properties
-- ============================================================
-- Base properties ONLY. KIc/Fty ratios computed at evaluation time.
-- Links to MAPTIS via maptis_material_id for cross-pack joins.

CREATE TABLE IF NOT EXISTS material_fracture_properties (
    prop_id             SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),

    -- Material identity
    material_designation VARCHAR(256) NOT NULL,
    material_spec       VARCHAR(128),
    material_condition  VARCHAR(128),
    maptis_material_id  INTEGER,

    -- Base fracture properties (NOT derived ratios)
    kic_ksi_sqrt_in     NUMERIC(10,3),
    kic_mpa_sqrt_m      NUMERIC(10,3),
    fty_ksi             NUMERIC(10,3),
    fty_mpa             NUMERIC(10,3),
    ftu_ksi             NUMERIC(10,3),
    ftu_mpa             NUMERIC(10,3),
    elongation_pct      NUMERIC(6,2),
    da_dn_threshold     NUMERIC(12,6),

    -- Test conditions
    test_temperature_f  NUMERIC(10,2),
    test_environment    VARCHAR(64),
    specimen_orientation VARCHAR(32),

    -- Source
    data_source         VARCHAR(128) NOT NULL,
    data_class          VARCHAR(32) NOT NULL DEFAULT 'handbook',
    source_clause_ids   INTEGER[] NOT NULL DEFAULT '{}',

    -- Active flag
    active              BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT valid_fc_data_class CHECK (data_class IN ('direct_test', 'handbook', 'mmpds', 'nasgro', 'derived'))
);

CREATE INDEX IF NOT EXISTS idx_fc_prop_pack ON material_fracture_properties(pack_id);
CREATE INDEX IF NOT EXISTS idx_fc_prop_designation ON material_fracture_properties(material_designation);
CREATE INDEX IF NOT EXISTS idx_fc_prop_maptis ON material_fracture_properties(maptis_material_id);
CREATE INDEX IF NOT EXISTS idx_fc_prop_active ON material_fracture_properties(active) WHERE active = TRUE;

-- ============================================================
-- 8. Center Overrides (JSC, MSFC, KSC deviations)
-- ============================================================
-- Centers can add/replace/suppress base-pack rules.
-- Precedence: suppress > replace > add (evaluated in that order).

CREATE TABLE IF NOT EXISTS center_overrides (
    override_id         SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),

    -- Which center
    center_code         VARCHAR(8) NOT NULL,

    -- What it overrides
    target_rule_code    VARCHAR(32),
    target_part_class   VARCHAR(64),

    -- Override action
    action              VARCHAR(16) NOT NULL,
    override_rule_code  VARCHAR(32),
    override_predicate  JSONB,
    override_output     JSONB,

    -- Precedence (lower = evaluated first within same action type)
    precedence_order    INTEGER NOT NULL DEFAULT 100,

    -- Citation
    source_clause_ids   INTEGER[] NOT NULL DEFAULT '{}',
    rationale           TEXT NOT NULL,

    -- Active flag
    active              BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT valid_override_action CHECK (action IN ('add', 'replace', 'suppress')),
    CONSTRAINT valid_center_code CHECK (center_code IN ('MSFC', 'JSC', 'KSC', 'GRC', 'GSFC', 'JPL', 'ARC', 'LaRC', 'SSC'))
);

CREATE INDEX IF NOT EXISTS idx_override_pack ON center_overrides(pack_id);
CREATE INDEX IF NOT EXISTS idx_override_center ON center_overrides(center_code);
CREATE INDEX IF NOT EXISTS idx_override_action ON center_overrides(action);
CREATE INDEX IF NOT EXISTS idx_override_active ON center_overrides(active) WHERE active = TRUE;

-- ============================================================
-- 9. Cross-References (links between standards)
-- ============================================================

CREATE TABLE IF NOT EXISTS cross_references (
    xref_id             SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),
    from_clause_id      INTEGER NOT NULL REFERENCES requirement_clauses(clause_id),
    to_standard         VARCHAR(128) NOT NULL,
    to_section          VARCHAR(64),
    relationship        VARCHAR(32) NOT NULL DEFAULT 'references',

    CONSTRAINT valid_relationship CHECK (relationship IN ('references', 'implements', 'supersedes', 'conflicts_with', 'elaborates'))
);

CREATE INDEX IF NOT EXISTS idx_xref_pack ON cross_references(pack_id);
CREATE INDEX IF NOT EXISTS idx_xref_from ON cross_references(from_clause_id);
CREATE INDEX IF NOT EXISTS idx_xref_to ON cross_references(to_standard);

-- ============================================================
-- 10. Documentation Requirements (what paperwork is needed)
-- ============================================================

CREATE TABLE IF NOT EXISTS documentation_requirements (
    doc_req_id          SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL REFERENCES pack_registry(pack_id),

    -- What triggers this requirement
    part_class          VARCHAR(64) NOT NULL,
    trigger_conditions  JSONB,

    -- What document is needed
    document_type       VARCHAR(128) NOT NULL,
    document_template   VARCHAR(128),
    required_fields     TEXT[] NOT NULL DEFAULT '{}',

    -- Citation
    source_clause_ids   INTEGER[] NOT NULL DEFAULT '{}',

    -- Active flag
    active              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_doc_req_pack ON documentation_requirements(pack_id);
CREATE INDEX IF NOT EXISTS idx_doc_req_class ON documentation_requirements(part_class);
CREATE INDEX IF NOT EXISTS idx_doc_req_active ON documentation_requirements(active) WHERE active = TRUE;

-- ============================================================
-- 11. Classification Trace Log (audit trail)
-- ============================================================
-- Every classification evaluation is logged immutably.
-- Derived values (KIc/Fty ratio, etc.) computed and logged HERE,
-- not stored in material properties.

CREATE TABLE IF NOT EXISTS classification_trace (
    trace_id            SERIAL PRIMARY KEY,
    pack_id             VARCHAR(64) NOT NULL,
    pack_version        VARCHAR(32) NOT NULL,

    -- Query context
    query_text          TEXT NOT NULL,
    parsed_context      JSONB NOT NULL,

    -- Input fields used
    input_material      VARCHAR(256),
    input_part_class    VARCHAR(64),
    input_pressure_boundary BOOLEAN,
    input_consequence_of_failure VARCHAR(64),
    input_inspectability VARCHAR(64),
    input_geometry_type VARCHAR(64),
    input_material_condition VARCHAR(64),
    input_center_code   VARCHAR(8),

    -- Derived values (computed at eval time, logged for audit)
    derived_values      JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Classification result
    output_part_class   VARCHAR(64) NOT NULL,
    output_fcr_set      TEXT[] NOT NULL DEFAULT '{}',
    output_nde_required BOOLEAN NOT NULL DEFAULT FALSE,
    output_nde_methods  TEXT[] NOT NULL DEFAULT '{}',

    -- Rule matching trace
    rules_evaluated     JSONB NOT NULL,
    rule_matched        VARCHAR(32),
    rules_skipped       TEXT[] NOT NULL DEFAULT '{}',
    center_overrides_applied TEXT[] NOT NULL DEFAULT '{}',

    -- Citations
    cited_clauses       INTEGER[] NOT NULL DEFAULT '{}',
    cited_documents     TEXT[] NOT NULL DEFAULT '{}',

    -- Confidence
    classification_confidence FLOAT NOT NULL DEFAULT 1.0,
    clarify_fields      TEXT[] NOT NULL DEFAULT '{}',

    -- Provenance
    provenance_hash     VARCHAR(64) NOT NULL,
    evaluated_at        TIMESTAMPTZ DEFAULT NOW(),
    evaluated_by        VARCHAR(128) DEFAULT 'mira_fc_engine'
);

CREATE INDEX IF NOT EXISTS idx_trace_pack ON classification_trace(pack_id);
CREATE INDEX IF NOT EXISTS idx_trace_class ON classification_trace(output_part_class);
CREATE INDEX IF NOT EXISTS idx_trace_time ON classification_trace(evaluated_at);
CREATE INDEX IF NOT EXISTS idx_trace_hash ON classification_trace(provenance_hash);

-- ============================================================
-- 12. Query Log (what users asked)
-- ============================================================

CREATE TABLE IF NOT EXISTS fc_query_log (
    query_id            SERIAL PRIMARY KEY,
    raw_query           TEXT NOT NULL,
    safety_context      VARCHAR(32) NOT NULL DEFAULT 'fracture_control',
    parsed_intent       VARCHAR(64),
    trace_id            INTEGER REFERENCES classification_trace(trace_id),
    response_summary    TEXT,
    query_at            TIMESTAMPTZ DEFAULT NOW(),
    response_time_ms    INTEGER,
    user_session        VARCHAR(128)
);

CREATE INDEX IF NOT EXISTS idx_qlog_time ON fc_query_log(query_at);
CREATE INDEX IF NOT EXISTS idx_qlog_intent ON fc_query_log(parsed_intent);

-- ============================================================
-- Views
-- ============================================================

-- Active pack rules in evaluation order
CREATE OR REPLACE VIEW active_classification_rules AS
SELECT cr.*, pr.version AS pack_version, pr.status AS pack_status
FROM classification_rules cr
JOIN pack_registry pr ON cr.pack_id = pr.pack_id
WHERE cr.active = TRUE AND pr.status = 'active'
ORDER BY cr.priority_order;

-- Active NDE requirements by part class
CREATE OR REPLACE VIEW active_nde_requirements AS
SELECT na.*, pr.version AS pack_version
FROM nde_applicability na
JOIN pack_registry pr ON na.pack_id = pr.pack_id
WHERE na.active = TRUE AND pr.status = 'active'
ORDER BY na.part_class, na.nde_method;

-- Classification summary (latest trace per part class)
CREATE OR REPLACE VIEW classification_summary AS
SELECT DISTINCT ON (output_part_class)
    output_part_class,
    output_fcr_set,
    output_nde_required,
    output_nde_methods,
    classification_confidence,
    evaluated_at
FROM classification_trace
ORDER BY output_part_class, evaluated_at DESC;

-- ============================================================
-- Functions
-- ============================================================

-- Immutability guard: prevent mutation of active packs
CREATE OR REPLACE FUNCTION guard_active_pack_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'active' AND NEW.status = 'active' THEN
        -- Allow status change FROM active (to retired), block field edits
        IF OLD.version != NEW.version
           OR OLD.title != NEW.title
           OR OLD.source_standards != NEW.source_standards THEN
            RAISE EXCEPTION 'Cannot mutate active pack %. Create new version instead.', OLD.pack_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_guard_active_pack
    BEFORE UPDATE ON pack_registry
    FOR EACH ROW EXECUTE FUNCTION guard_active_pack_mutation();

-- Classification rule gap detector
-- Returns TRUE if there is no fallback rule (highest priority with universal match)
CREATE OR REPLACE FUNCTION check_classification_rule_gaps(p_pack_id VARCHAR)
RETURNS TABLE(has_gaps BOOLEAN, gap_details TEXT) AS $$
DECLARE
    max_priority INTEGER;
    last_rule RECORD;
BEGIN
    SELECT MAX(priority_order) INTO max_priority
    FROM classification_rules
    WHERE pack_id = p_pack_id AND active = TRUE;

    IF max_priority IS NULL THEN
        RETURN QUERY SELECT TRUE, 'No active classification rules found for pack';
        RETURN;
    END IF;

    SELECT * INTO last_rule
    FROM classification_rules
    WHERE pack_id = p_pack_id AND active = TRUE AND priority_order = max_priority;

    -- Last rule should be a catch-all fallback
    IF last_rule.rule_code NOT LIKE '%FALLBACK%' AND last_rule.rule_code NOT LIKE '%DEFAULT%' THEN
        RETURN QUERY SELECT TRUE,
            format('Last rule (priority %s, code %s) does not appear to be a fallback. '
                   'Add a FALLBACK rule to prevent classification gaps.',
                   max_priority, last_rule.rule_code);
        RETURN;
    END IF;

    RETURN QUERY SELECT FALSE, 'No gaps detected';
END;
$$ LANGUAGE plpgsql;

COMMIT;

-- ============================================================
-- Post-migration verification
-- ============================================================
-- Run manually:
--   SELECT table_name FROM information_schema.tables WHERE table_schema = 'authority_fc';
--   SELECT * FROM authority_fc.check_classification_rule_gaps('fc_5019a_v1');
