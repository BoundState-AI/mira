-- Migration 017: MUA Audit Schema
-- WHAT (material) x WHY (concern domain) x HOW (mitigation pattern)
--
-- Run: psql -d mira -f 017_mua_audit_schema.sql
-- Depends: 001_create_mua_precedents_v7.sql (mua_precedents_v7 table)

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- Concern Domains (the WHY)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS concern_domains (
    id SERIAL PRIMARY KEY,
    code VARCHAR(10) UNIQUE NOT NULL,          -- FLAMM, SCC, CORR, TOX, TVS, FC, FORBIDDEN
    name VARCHAR(100) NOT NULL,
    triggering_standard TEXT,                   -- Primary NASA/MSFC standard
    description TEXT
);

INSERT INTO concern_domains (code, name, triggering_standard, description)
VALUES
    ('FLAMM', 'Flammability', 'NASA-STD-6001 Test 1/17',
     'Material does not meet flammability requirements for oxygen-enriched or habitable environments'),
    ('SCC', 'Stress Corrosion Cracking', 'MSFC-STD-3029 / MSFC-SPEC-522',
     'Material susceptible to stress corrosion cracking under sustained load in corrosive environment'),
    ('CORR', 'Corrosion', 'SSP 30233 / MSFC-SPEC-250',
     'Galvanic corrosion, dissimilar metal contact, or inadequate corrosion protection'),
    ('TOX', 'Toxicity / Offgassing', 'NASA-STD-6001 Test 7',
     'Material does not meet offgassing or toxicity requirements for habitable environments'),
    ('TVS', 'Thermal Vacuum Stability', 'ASTM E595 / NASA-STD-6001 Test 7',
     'Material exceeds TML/CVCM limits for outgassing in vacuum environment'),
    ('FC', 'Fluid Compatibility', 'SSP 30233 / MSFC-STD-1813',
     'Material not compatible with service fluid: propellants (hydrazine, NTO), oxygen, LOX, GOX, or other media'),
    ('FORBIDDEN', 'Forbidden / Prohibited Material', 'SSP 30233 Appendix B',
     'Material is on the forbidden/prohibited list per program requirements'),
    ('FUNGUS', 'Fungus Resistance', 'MIL-STD-454 / SSP 30233',
     'Material does not meet fungus resistance requirements per MIL-STD-454 Group II')
ON CONFLICT (code) DO NOTHING;


-- ═══════════════════════════════════════════════════════════════════════════
-- Rationale Patterns (the HOW)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS rationale_patterns (
    id SERIAL PRIMARY KEY,
    pattern_code VARCHAR(30) UNIQUE NOT NULL,
    pattern_name VARCHAR(100) NOT NULL,
    description TEXT,
    regex_pattern TEXT,                         -- Python regex used for matching
    usage_count INTEGER DEFAULT 0              -- Updated during population
);

INSERT INTO rationale_patterns (pattern_code, pattern_name, description, regex_pattern)
VALUES
    ('small_amount', 'Small Amount / Negligible Quantity',
     'Mitigation based on minimal quantity of material used',
     'small amount|small quantity|minimal amount|negligible'),
    ('metallic_enclosure', 'Metallic Enclosure / Housing',
     'Material contained within metallic enclosure limiting exposure',
     'metallic enclosure|aluminum housing|metal housing|enclosed in|contained within'),
    ('no_ignition_source', 'No Ignition Source',
     'No ignition mechanism or energy source present to initiate combustion',
     'no ignition source|no ignition mechanism|unpowered'),
    ('heat_sink', 'Heat Sink / Thermal Mass',
     'Adjacent metallic mass acts as heat sink preventing ignition',
     'heat sink|heatsink|adjacent to metal|metallic heat sink'),
    ('sandwich_config', 'Sandwiched Between Metallic Surfaces',
     'Material trapped between metal layers with only edge exposure',
     'sandwiched between|between metallic surfaces'),
    ('heritage_usage', 'Heritage / Flight History',
     'Material has been previously flown or used successfully in similar application',
     'previously flown|flown successfully|heritage|proven reliable|used in similar application'),
    ('edge_exposure_only', 'Edge Exposure Only',
     'Only edge of material is exposed to environment',
     'edge exposure|minimal edge exposure|only edge exposure'),
    ('conformal_coating', 'Conformal Coating Protection',
     'Material protected by conformal coating or surface treatment',
     'conformal coat|coated with|protective coating'),
    ('compression_only', 'Compression Loading Only',
     'Part only experiences compression loads, not susceptible to SCC',
     'compression only|compression loads only|no tension'),
    ('plating_protection', 'Plating / Surface Protection',
     'Material protected from environment by plating or surface treatment',
     'plated|plating|gold plated|nickel plated|iron-phosphate coated'),
    ('inert_environment', 'Inert / Non-Corrosive Environment',
     'Material operates in inert gas or vacuum environment',
     'inert|argon|nitrogen purge|vacuum'),
    ('test_data_supports', 'Supporting Test Data',
     'Acceptance based on test reports, test data, or lab results',
     'test data|tested|test report|WSTF|JSC Report'),
    ('material_nature', 'Inherent Material Properties',
     'Acceptance based on inherent material characteristics (ceramic, inorganic, etc.)',
     'based on the nature of the material|inherently|ceramic|inorganic'),
    ('not_exposed', 'Not Exposed to Environment',
     'Material is internal, enclosed, or otherwise not exposed to hazardous environment',
     'not exposed|no exposed area|enclosed|internal'),
    ('vacuum_bake', 'Vacuum Bake / Outgas Cure',
     'Material pre-processed to remove volatiles before installation',
     'vacuum baked|bake-out|cured at|outgassed'),
    ('no_fluid_contact', 'No Contact With Service Fluid',
     'Material will not contact the incompatible fluid in service',
     'will not be exposed to|not come in contact with|no contact with|will not contact'),
    ('low_stress', 'Low / No Sustained Stress',
     'Part not subject to sustained tensile stress in SCC-susceptible condition',
     'low stress|not stressed|no sustained|transient load')
ON CONFLICT (pattern_code) DO NOTHING;


-- ═══════════════════════════════════════════════════════════════════════════
-- Pattern-Domain Applicability (which patterns apply to which domains)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pattern_domain_applicability (
    id SERIAL PRIMARY KEY,
    pattern_id INTEGER NOT NULL REFERENCES rationale_patterns(id),
    concern_domain_id INTEGER NOT NULL REFERENCES concern_domains(id),
    frequency INTEGER DEFAULT 0,
    UNIQUE (pattern_id, concern_domain_id)
);


-- ═══════════════════════════════════════════════════════════════════════════
-- MUA Records (the WHAT — core material data)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mua_records (
    id SERIAL PRIMARY KEY,
    mua_number VARCHAR(100),
    source_file VARCHAR(255) NOT NULL,

    -- Material identification
    material_designation TEXT,                  -- best available name
    material_designation_v6 TEXT,               -- original v6 extraction
    material_name_v5 TEXT,                      -- v5 parser fallback
    material_family VARCHAR(50),               -- canonical family (stainless_steel, adhesive, etc.)
    specification TEXT,
    manufacturer TEXT,
    trade_name TEXT,

    -- Classification
    category VARCHAR(5),                       -- I, II, III
    determination VARCHAR(30),                 -- APPROVED, REJECTED, APPROVED_WITH_LIMITS, etc.
    confidence FLOAT,
    extraction_mode VARCHAR(20),               -- vision, text

    -- Environment
    environment_type VARCHAR(30),              -- vacuum, cabin_air, oxygen, etc.
    environment_raw TEXT,                       -- original text
    o2_percent FLOAT,
    pressure_psia FLOAT,
    temperature_f FLOAT,
    is_habitable BOOLEAN DEFAULT FALSE,

    -- Content
    application_text TEXT,
    rationale_text TEXT,
    raw_issue_text TEXT,                        -- original issue field before normalization

    -- MUA type classification
    mua_type VARCHAR(20) DEFAULT 'component',  -- component or certification

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (source_file)
);

CREATE INDEX IF NOT EXISTS idx_mua_rec_material ON mua_records(material_designation);
CREATE INDEX IF NOT EXISTS idx_mua_rec_family ON mua_records(material_family);
CREATE INDEX IF NOT EXISTS idx_mua_rec_mua_number ON mua_records(mua_number);
CREATE INDEX IF NOT EXISTS idx_mua_rec_determination ON mua_records(determination);
CREATE INDEX IF NOT EXISTS idx_mua_rec_category ON mua_records(category);
CREATE INDEX IF NOT EXISTS idx_mua_rec_env_type ON mua_records(environment_type);
CREATE INDEX IF NOT EXISTS idx_mua_rec_mua_type ON mua_records(mua_type);


-- ═══════════════════════════════════════════════════════════════════════════
-- MUA Concerns (junction: record x concern domain)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mua_concerns (
    id SERIAL PRIMARY KEY,
    mua_record_id INTEGER NOT NULL REFERENCES mua_records(id) ON DELETE CASCADE,
    concern_domain_id INTEGER NOT NULL REFERENCES concern_domains(id),
    raw_issue_text TEXT,                        -- the fragment that triggered this match
    UNIQUE (mua_record_id, concern_domain_id)
);

CREATE INDEX IF NOT EXISTS idx_mua_concerns_record ON mua_concerns(mua_record_id);
CREATE INDEX IF NOT EXISTS idx_mua_concerns_domain ON mua_concerns(concern_domain_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- MUA Patterns (junction: record x rationale pattern)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mua_patterns (
    id SERIAL PRIMARY KEY,
    mua_record_id INTEGER NOT NULL REFERENCES mua_records(id) ON DELETE CASCADE,
    rationale_pattern_id INTEGER NOT NULL REFERENCES rationale_patterns(id),
    matched_text TEXT,                         -- the snippet that triggered the match
    match_confidence FLOAT DEFAULT 1.0,
    UNIQUE (mua_record_id, rationale_pattern_id)
);

CREATE INDEX IF NOT EXISTS idx_mua_patterns_record ON mua_patterns(mua_record_id);
CREATE INDEX IF NOT EXISTS idx_mua_patterns_pattern ON mua_patterns(rationale_pattern_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- MUA Evidence (test reports, standard citations, memos)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mua_evidence (
    id SERIAL PRIMARY KEY,
    mua_record_id INTEGER NOT NULL REFERENCES mua_records(id) ON DELETE CASCADE,
    evidence_type VARCHAR(30),                 -- test_report, standard, memo, attachment
    reference_text TEXT,                        -- full reference string
    test_number VARCHAR(50),                   -- e.g., "Test 1", "Test 7", "Test 17"
    standard_cited VARCHAR(100)                -- e.g., "MSFC-SPEC-522", "NASA-STD-6001"
);

CREATE INDEX IF NOT EXISTS idx_mua_evidence_record ON mua_evidence(mua_record_id);
CREATE INDEX IF NOT EXISTS idx_mua_evidence_type ON mua_evidence(evidence_type);


COMMIT;
