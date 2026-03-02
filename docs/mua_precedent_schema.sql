-- ============================================================================
-- MUA Precedent Database — BS-SPEC-MUA-DB-001
-- BoundState Technologies / MIRA Platform
--
-- Creates the mua_precedent schema with all tables, indexes, views,
-- and helper functions needed for historic MUA precedent matching.
--
-- Run against any PostgreSQL 14+ instance:
--   psql -U postgres -d mira -f mua_precedent_schema.sql
--
-- Safe to re-run (all CREATE statements use IF NOT EXISTS).
-- ============================================================================

BEGIN;

-- ── Schema ──────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS mua_precedent;

-- ── Media normalization function ────────────────────────────────────────────
CREATE OR REPLACE FUNCTION mua_precedent.normalize_media(raw_media TEXT)
RETURNS TEXT AS $$
DECLARE
    m TEXT := UPPER(TRIM(COALESCE(raw_media, '')));
BEGIN
    IF m = '' THEN RETURN 'other'; END IF;

    -- Hydrogen
    IF m IN ('H2','GH2','LH2','HYDROGEN','GASEOUS HYDROGEN','LIQUID HYDROGEN')
        OR m LIKE '%HYDROGEN%' THEN RETURN 'hydrogen';
    END IF;

    -- Oxygen
    IF m IN ('O2','GOX','LOX','OXYGEN','GASEOUS OXYGEN','LIQUID OXYGEN')
        OR m LIKE '%OXYGEN%' OR m LIKE '%ENRICHED%' THEN RETURN 'oxygen';
    END IF;

    -- Propellant (FS Test 15 fluids)
    IF m IN ('N2H4','HYDRAZINE','MMH','MONOMETHYLHYDRAZINE','N2O4','NTO',
             'NITROGEN TETROXIDE','UDMH')
        OR m LIKE '%HYDRAZINE%' OR m LIKE '%MMH%' OR m LIKE '%N2O4%'
        THEN RETURN 'propellant';
    END IF;

    -- Inert
    IF m IN ('N2','GN2','LN2','NITROGEN','HE','HELIUM','ARGON','AR','NEON')
        OR m LIKE '%NITROGEN%' OR m LIKE '%HELIUM%' THEN RETURN 'inert';
    END IF;

    -- Air / ambient
    IF m IN ('AIR','AMBIENT','ATMOSPHERE','SEA LEVEL') THEN RETURN 'air'; END IF;

    -- Water / aqueous
    IF m IN ('WATER','H2O','COOLANT','DEIONIZED WATER')
        OR m LIKE '%WATER%' THEN RETURN 'aqueous';
    END IF;

    RETURN 'other';
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ── Core table: mua_records ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mua_precedent.mua_records (
    -- Identity
    id              SERIAL PRIMARY KEY,
    mua_number      TEXT NOT NULL,
    source_hash     TEXT UNIQUE NOT NULL,

    -- Material (what)
    maptis_code     TEXT NOT NULL,
    material_name   TEXT NOT NULL DEFAULT '',
    material_class  TEXT NOT NULL DEFAULT 'metal'
        CHECK (material_class IN ('metal', 'nonmetallic')),
    alloy_family    TEXT DEFAULT '',
    material_spec   TEXT DEFAULT '',

    -- Flag (why)
    issue           TEXT NOT NULL
        CHECK (issue IN ('FLAM', 'FS', 'TOX', 'TVS', 'SCC', 'CORR', '')),
    rating          TEXT NOT NULL,
    flag_type       TEXT DEFAULT '',
    mua_type        TEXT DEFAULT '',

    -- Environment (where)
    media           TEXT NOT NULL DEFAULT '',
    media_category  TEXT NOT NULL DEFAULT ''
        CHECK (media_category IN ('hydrogen', 'oxygen', 'propellant',
                                   'inert', 'air', 'aqueous', 'other', '')),
    environment     TEXT NOT NULL DEFAULT 'non-habitable'
        CHECK (environment IN ('habitable', 'non-habitable')),
    pressure        TEXT DEFAULT '',
    temperature     TEXT DEFAULT '',

    -- Outcome (what happened)
    category        TEXT DEFAULT ''
        CHECK (category IN ('I', 'II', '')),
    disposition     TEXT DEFAULT '',
    approved        BOOLEAN DEFAULT NULL,
    approval_date   DATE DEFAULT NULL,

    -- Content (what they wrote)
    rationale_text  TEXT DEFAULT '',
    disposition_text TEXT DEFAULT '',
    application     TEXT DEFAULT '',

    -- Context
    project         TEXT DEFAULT '',
    system          TEXT DEFAULT '',
    part_numbers    TEXT[] DEFAULT '{}',
    part_count      INTEGER DEFAULT 0,

    -- Provenance
    source_file     TEXT DEFAULT '',
    source_format   TEXT DEFAULT 'json'
        CHECK (source_format IN ('json', 'docx', 'pdf', 'xlsx', 'manual')),
    parsed_date     TIMESTAMPTZ DEFAULT NOW(),
    confidence      NUMERIC(3,2) DEFAULT 0.00
        CHECK (confidence >= 0 AND confidence <= 1),

    -- Housekeeping
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);


-- ── Rationale patterns ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mua_precedent.mua_rationale_patterns (
    id                  SERIAL PRIMARY KEY,
    pattern_key         TEXT UNIQUE NOT NULL,
    issue               TEXT NOT NULL,
    rating              TEXT NOT NULL,
    media_category      TEXT NOT NULL,
    material_class      TEXT NOT NULL,
    mua_type            TEXT NOT NULL,
    rationale_template  TEXT NOT NULL,
    disposition_template TEXT NOT NULL DEFAULT '',
    example_mua_ids     INTEGER[] DEFAULT '{}',
    source_count        INTEGER DEFAULT 0,
    human_reviewed      BOOLEAN DEFAULT FALSE,
    reviewed_by         TEXT DEFAULT '',
    reviewed_date       DATE DEFAULT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ── Alloy family lookup ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mua_precedent.mua_alloy_families (
    id              SERIAL PRIMARY KEY,
    pattern         TEXT NOT NULL,
    family          TEXT NOT NULL,
    subfamily       TEXT DEFAULT '',
    display_name    TEXT NOT NULL,
    example_alloys  TEXT[] DEFAULT '{}',
    UNIQUE(pattern, family)
);


-- ── Indexes ─────────────────────────────────────────────────────────────────

-- Primary precedent lookup
CREATE INDEX IF NOT EXISTS idx_precedent_lookup
    ON mua_precedent.mua_records (issue, rating, media_category, material_class);

-- Broader precedent (issue + media, any rating)
CREATE INDEX IF NOT EXISTS idx_precedent_issue_media
    ON mua_precedent.mua_records (issue, media_category, material_class);

-- Material-specific lookup
CREATE INDEX IF NOT EXISTS idx_maptis
    ON mua_precedent.mua_records (maptis_code);

-- Alloy family + media
CREATE INDEX IF NOT EXISTS idx_family_media
    ON mua_precedent.mua_records (alloy_family, media_category, issue);

-- Outcome statistics
CREATE INDEX IF NOT EXISTS idx_outcome
    ON mua_precedent.mua_records (mua_type, approved);

-- Full-text search on rationale
CREATE INDEX IF NOT EXISTS idx_rationale_fts
    ON mua_precedent.mua_records
    USING GIN (to_tsvector('english', rationale_text));

-- Pattern key lookup
CREATE INDEX IF NOT EXISTS idx_pattern_key
    ON mua_precedent.mua_rationale_patterns
    (issue, rating, media_category, material_class, mua_type);


-- ── Materialized view: precedent_counts ─────────────────────────────────────
-- The primary query target for the V10 classifier.

DROP MATERIALIZED VIEW IF EXISTS mua_precedent.precedent_counts;
CREATE MATERIALIZED VIEW mua_precedent.precedent_counts AS
SELECT
    issue,
    rating,
    media_category,
    material_class,
    mua_type,
    COUNT(*)                                          AS total_count,
    COUNT(*) FILTER (WHERE approved = TRUE)           AS approved_count,
    COUNT(*) FILTER (WHERE approved = FALSE)          AS rejected_count,
    COUNT(*) FILTER (WHERE approved IS NULL)          AS unknown_count,
    COUNT(DISTINCT maptis_code)                       AS distinct_materials,
    COUNT(DISTINCT alloy_family)
        FILTER (WHERE alloy_family != '')             AS distinct_families,
    COUNT(DISTINCT project)
        FILTER (WHERE project != '')                  AS distinct_projects,
    MODE() WITHIN GROUP (ORDER BY category)           AS most_common_category,
    MIN(approval_date)                                AS earliest_approval,
    MAX(approval_date)                                AS latest_approval
FROM mua_precedent.mua_records
WHERE issue != '' AND rating != '' AND confidence >= 0.5
GROUP BY issue, rating, media_category, material_class, mua_type
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_precedent_counts_pk
    ON mua_precedent.precedent_counts
    (issue, rating, media_category, material_class, mua_type);


-- ── Materialized view: family_precedent ─────────────────────────────────────
DROP MATERIALIZED VIEW IF EXISTS mua_precedent.family_precedent;
CREATE MATERIALIZED VIEW mua_precedent.family_precedent AS
SELECT
    alloy_family,
    issue,
    media_category,
    COUNT(*)                                          AS total_count,
    COUNT(*) FILTER (WHERE approved = TRUE)           AS approved_count,
    ARRAY_AGG(DISTINCT maptis_code)                   AS maptis_codes,
    ARRAY_AGG(DISTINCT material_name)
        FILTER (WHERE material_name != '')            AS material_names
FROM mua_precedent.mua_records
WHERE alloy_family != '' AND confidence >= 0.5
GROUP BY alloy_family, issue, media_category
WITH DATA;


-- ── Seed alloy families ─────────────────────────────────────────────────────
INSERT INTO mua_precedent.mua_alloy_families (pattern, family, subfamily, display_name, example_alloys)
VALUES
    ('\mA[\-\s]?286\m',          'fe_superalloy',    'iron_based',    'Iron-Based Superalloy',       '{"A286"}'),
    ('\m(304|316|321|347)\m',    'austenitic_ss',    '300_series',    'Austenitic Stainless Steel',  '{"304L","316L","321","347"}'),
    ('\mINCONEL[\s\-]*6',       'ni_superalloy',    'inconel',       'Nickel Superalloy (Inconel)',  '{"Inconel 625","Inconel 718"}'),
    ('\mMONEL\m',               'ni_alloy',         'monel',         'Nickel-Copper Alloy (Monel)',  '{"Monel 400","Monel K-500"}'),
    ('\mHASTELLOY\m',           'ni_superalloy',    'hastelloy',     'Nickel Superalloy (Hastelloy)','{"Hastelloy C-276","Hastelloy X"}'),
    ('\m70[0-9]{2}\m',          'al_alloy',         '7xxx',          'Aluminum 7xxx Series',         '{"7075-T651","7050-T7451"}'),
    ('\m60[0-9]{2}\m',          'al_alloy',         '6xxx',          'Aluminum 6xxx Series',         '{"6061-T6","6063"}'),
    ('\m20[0-9]{2}\m',          'al_alloy',         '2xxx',          'Aluminum 2xxx Series',         '{"2024-T3","2219-T87"}'),
    ('\mTI[\-\s]*6AL[\-\s]*4V\m','ti_alloy',        'alpha_beta',    'Titanium Alpha-Beta',          '{"Ti-6Al-4V"}'),
    ('\mVESPEL\m',              'polyimide',        'vespel',        'Polyimide (Vespel)',           '{"Vespel SP-1","Vespel SP-21"}'),
    ('\mTEFLON\m|\mPTFE\m',    'fluoropolymer',    'ptfe',          'Fluoropolymer (PTFE)',         '{"PTFE","Teflon"}'),
    ('\mKEL[\-\s]*?F\m',       'fluoropolymer',    'pctfe',         'Fluoropolymer (PCTFE/Kel-F)', '{"Kel-F 81","PCTFE"}'),
    ('\mVITON\m',              'fluoroelastomer',  'viton',         'Fluoroelastomer (Viton)',      '{"Viton A","Viton B"}'),
    ('\mC63000\m|\mAL.*BRONZE\m','cu_alloy',        'al_bronze',     'Aluminum Bronze',              '{"C63000","C63200"}'),
    ('\m17[\-\s]*4\s*PH\m',    'martensitic_ss',   'ph',            'Precipitation-Hardening SS',   '{"17-4 PH","15-5 PH"}'),
    ('\mWASPALOY\m',           'ni_superalloy',    'waspaloy',      'Nickel Superalloy (Waspaloy)', '{"Waspaloy"}'),
    ('\mMP35N\m',              'ni_superalloy',    'multiphase',    'Nickel-Cobalt Multiphase',     '{"MP35N"}'),
    ('\mCOPPER\m|\mOFHC\m',   'cu_alloy',         'pure_cu',       'Copper / OFHC',                '{"OFHC Copper","C10200"}')
ON CONFLICT (pattern, family) DO NOTHING;


-- ── Refresh helper ──────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION mua_precedent.refresh_views()
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mua_precedent.precedent_counts;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mua_precedent.family_precedent;
END;
$$ LANGUAGE plpgsql;


-- ── Updated_at trigger ──────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION mua_precedent.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_mua_records_updated ON mua_precedent.mua_records;
CREATE TRIGGER trg_mua_records_updated
    BEFORE UPDATE ON mua_precedent.mua_records
    FOR EACH ROW EXECUTE FUNCTION mua_precedent.set_updated_at();

DROP TRIGGER IF EXISTS trg_patterns_updated ON mua_precedent.mua_rationale_patterns;
CREATE TRIGGER trg_patterns_updated
    BEFORE UPDATE ON mua_precedent.mua_rationale_patterns
    FOR EACH ROW EXECUTE FUNCTION mua_precedent.set_updated_at();


COMMIT;

-- ── Summary ─────────────────────────────────────────────────────────────────
DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'MUA Precedent Database — BS-SPEC-MUA-DB-001';
    RAISE NOTICE 'Schema: mua_precedent';
    RAISE NOTICE 'Tables: mua_records, mua_rationale_patterns, mua_alloy_families';
    RAISE NOTICE 'Views:  precedent_counts, family_precedent';
    RAISE NOTICE 'Ready for import.';
    RAISE NOTICE '============================================================';
END $$;
