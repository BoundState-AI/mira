-- ============================================================================
-- MUA Precedent Migration — BS-SPEC-MUA-DB-001 Phase 1
-- BoundState Technologies / MIRA Platform
--
-- Migrates existing data from:
--   public.mua_records      (7,334 rows, V5/V6 parse)
--   bok.mua_precedents      (9,366 rows, V7 Haiku-batch parse)
--
-- Into:
--   mua_precedent.mua_records (new V10-aligned schema)
--
-- PREREQUISITES: Run mua_precedent_schema.sql first.
--
-- Run:
--   psql -U postgres -h 127.0.0.1 -p 55433 -d mira -f mua_precedent_migrate.sql
--
-- Safe to re-run (uses ON CONFLICT source_hash DO NOTHING).
-- ============================================================================

BEGIN;

-- ============================================================================
-- HELPER: Normalize raw_issue_text → V10 issue column (FLAM/FS/TOX/TVS/SCC/CORR)
-- ============================================================================
-- Many MUAs address multiple issues. We extract the PRIMARY issue.
-- Multi-issue MUAs get one row per issue in Phase 2 (normalization pass).
-- For now, take the first/dominant issue.

CREATE OR REPLACE FUNCTION mua_precedent.normalize_issue(raw TEXT)
RETURNS TEXT AS $$
DECLARE
    r TEXT := UPPER(TRIM(COALESCE(raw, '')));
BEGIN
    -- Empty / junk
    IF r = '' OR r = 'N/A' OR r LIKE 'MUL%' OR r = 'CERTIFICATION'
       OR r = 'PROPERTIES' THEN
        RETURN '';
    END IF;

    -- SCC (must check before general "CORR" because "Stress Corrosion" contains corrosion)
    IF r LIKE '%STRESS%CORR%' OR r LIKE '%SCC%' THEN RETURN 'SCC'; END IF;

    -- CORR (general corrosion, dissimilar metals)
    IF r LIKE '%CORR%' OR r LIKE '%DISSIMILAR%' OR r LIKE '%GALVANIC%' THEN
        RETURN 'CORR';
    END IF;

    -- FLAM (all the variants)
    IF r LIKE '%FLAM%' OR r LIKE '%FLM%' OR r LIKE '%FL,%'
       OR r LIKE 'FL %' OR r = 'FL' THEN
        RETURN 'FLAM';
    END IF;

    -- TVS (thermal vacuum stability / outgassing)
    IF r LIKE '%TVS%' OR r LIKE '%TV,%' OR r LIKE '%OUTGAS%'
       OR r LIKE '%THERMAL%VACUUM%' THEN
        RETURN 'TVS';
    END IF;

    -- TOX (toxicity / offgassing)
    IF r LIKE '%TOX%' OR r LIKE '%OFFGAS%' THEN RETURN 'TOX'; END IF;

    -- FS (fluid system compatibility)
    IF r LIKE '%FLUID%' OR r LIKE '%FS%' THEN RETURN 'FS'; END IF;

    -- O2 compatibility → FLAM (promoted ignition is the screening)
    IF r LIKE '%O2%COMPAT%' OR r LIKE '%OXYGEN%COMPAT%' THEN RETURN 'FLAM'; END IF;

    RETURN '';
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================================
-- HELPER: Map environment_type → media_category
-- ============================================================================
CREATE OR REPLACE FUNCTION mua_precedent.env_to_media_category(env_type TEXT)
RETURNS TEXT AS $$
DECLARE
    e TEXT := LOWER(TRIM(COALESCE(env_type, '')));
BEGIN
    CASE e
        WHEN 'cabin_air'    THEN RETURN 'air';
        WHEN 'vacuum'       THEN RETURN 'inert';     -- vacuum ≈ no reactive media
        WHEN 'enriched_o2'  THEN RETURN 'oxygen';
        WHEN 'lox_gox'      THEN RETURN 'oxygen';
        WHEN 'pure_o2'      THEN RETURN 'oxygen';
        WHEN 'cryogenic'    THEN RETURN 'other';     -- could be LH2 or LOX, ambiguous
        WHEN 'water'        THEN RETURN 'aqueous';
        WHEN 'co2'          THEN RETURN 'other';
        WHEN 'high_pressure' THEN RETURN 'other';
        ELSE RETURN 'other';
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================================
-- HELPER: Map material_family → alloy_family
-- ============================================================================
CREATE OR REPLACE FUNCTION mua_precedent.normalize_family(fam TEXT)
RETURNS TEXT AS $$
DECLARE
    f TEXT := LOWER(TRIM(COALESCE(fam, '')));
BEGIN
    CASE f
        WHEN 'stainless_steel' THEN RETURN 'austenitic_ss';  -- most common, refine later
        WHEN 'aluminum'        THEN RETURN 'al_alloy';
        WHEN 'nickel_alloy'    THEN RETURN 'ni_superalloy';
        WHEN 'copper_alloy'    THEN RETURN 'cu_alloy';
        WHEN 'titanium'        THEN RETURN 'ti_alloy';
        WHEN 'carbon_steel'    THEN RETURN 'carbon_steel';
        WHEN 'adhesive'        THEN RETURN 'adhesive';
        WHEN 'polymer'         THEN RETURN 'polymer';
        WHEN 'elastomer'       THEN RETURN 'elastomer';
        WHEN 'coating'         THEN RETURN 'coating';
        WHEN 'lubricant'       THEN RETURN 'lubricant';
        WHEN 'ceramic'         THEN RETURN 'ceramic';
        WHEN 'sealant'         THEN RETURN 'sealant';
        WHEN 'composite'       THEN RETURN 'composite';
        ELSE RETURN '';
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================================
-- HELPER: Map determination → approved boolean
-- ============================================================================
CREATE OR REPLACE FUNCTION mua_precedent.determination_to_approved(det TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    d TEXT := UPPER(TRIM(COALESCE(det, '')));
BEGIN
    IF d IN ('APPROVED', 'APPROVED_WITH_LIMITS', 'ACCEPTED', 'CONDITIONAL')
        THEN RETURN TRUE;
    END IF;
    IF d IN ('REJECTED') THEN RETURN FALSE; END IF;
    RETURN NULL;  -- DEFERRED, CANCELLED, blank
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================================
-- HELPER: Extract media string from bok.configuration text
-- ============================================================================
-- Configuration looks like: "Environment: HABITABLE; Media: 30%OXY.; Application: ..."
CREATE OR REPLACE FUNCTION mua_precedent.extract_media_from_config(config TEXT)
RETURNS TEXT AS $$
DECLARE
    m TEXT;
    pos_start INTEGER;
    pos_end INTEGER;
BEGIN
    IF config IS NULL OR config = '' THEN RETURN ''; END IF;

    -- Look for "Media: <value>;" or "Media: <value>" at end
    pos_start := position('Media:' in config);
    IF pos_start = 0 THEN
        pos_start := position('media:' in config);
    END IF;
    IF pos_start = 0 THEN RETURN ''; END IF;

    m := substring(config FROM pos_start + 6);
    m := TRIM(m);

    -- Trim at semicolon if present
    pos_end := position(';' in m);
    IF pos_end > 0 THEN
        m := LEFT(m, pos_end - 1);
    END IF;

    RETURN TRIM(m);
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================================
-- HELPER: Extract environment from bok.configuration text
-- ============================================================================
CREATE OR REPLACE FUNCTION mua_precedent.extract_env_from_config(config TEXT)
RETURNS TEXT AS $$
DECLARE
    m TEXT;
    pos_start INTEGER;
    pos_end INTEGER;
BEGIN
    IF config IS NULL OR config = '' THEN RETURN 'non-habitable'; END IF;

    pos_start := position('Environment:' in config);
    IF pos_start = 0 THEN
        pos_start := position('environment:' in config);
    END IF;
    IF pos_start = 0 THEN RETURN 'non-habitable'; END IF;

    m := substring(config FROM pos_start + 12);
    m := UPPER(TRIM(m));

    pos_end := position(';' in m);
    IF pos_end > 0 THEN
        m := LEFT(m, pos_end - 1);
    END IF;

    m := TRIM(m);

    IF m LIKE '%HABITABLE%' AND m NOT LIKE '%NON%' THEN
        RETURN 'habitable';
    END IF;

    RETURN 'non-habitable';
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ============================================================================
-- MIGRATION 1: public.mua_records → mua_precedent.mua_records
-- ============================================================================

INSERT INTO mua_precedent.mua_records (
    mua_number,
    source_hash,
    maptis_code,
    material_name,
    material_class,
    alloy_family,
    material_spec,
    issue,
    rating,
    media,
    media_category,
    environment,
    category,
    disposition,
    approved,
    rationale_text,
    application,
    project,
    source_file,
    source_format,
    confidence
)
SELECT
    -- Identity
    COALESCE(r.mua_number, 'UNK-' || r.id::text),
    md5('public.mua_records.' || r.id::text || '.' || r.source_file),

    -- Material: no MAPTIS code in this table
    '',
    COALESCE(r.material_designation, r.material_designation_v6, r.material_name_v5, ''),
    CASE
        WHEN r.material_family IN ('stainless_steel','aluminum','nickel_alloy',
            'copper_alloy','titanium','carbon_steel')
        THEN 'metal'
        ELSE 'nonmetallic'
    END,
    mua_precedent.normalize_family(r.material_family),
    COALESCE(r.specification, ''),

    -- Flag
    mua_precedent.normalize_issue(r.raw_issue_text),
    '',  -- No explicit rating in this table

    -- Environment
    COALESCE(r.environment_raw, r.environment_type, ''),
    mua_precedent.env_to_media_category(r.environment_type),
    CASE WHEN r.is_habitable THEN 'habitable' ELSE 'non-habitable' END,

    -- Outcome
    COALESCE(r.category, ''),
    COALESCE(r.determination, ''),
    mua_precedent.determination_to_approved(r.determination),

    -- Content
    COALESCE(r.rationale_text, ''),
    COALESCE(r.application_text, ''),

    -- Context: no project field in this table
    '',

    -- Provenance
    COALESCE(r.source_file, ''),
    'pdf',
    COALESCE(r.confidence, 0.5)

FROM public.mua_records r
ON CONFLICT (source_hash) DO NOTHING;


-- ============================================================================
-- MIGRATION 2: bok.mua_precedents → mua_precedent.mua_records
-- ============================================================================

INSERT INTO mua_precedent.mua_records (
    mua_number,
    source_hash,
    maptis_code,
    material_name,
    material_class,
    material_spec,
    issue,
    rating,
    media,
    media_category,
    environment,
    category,
    disposition,
    approved,
    rationale_text,
    application,
    source_file,
    source_format,
    confidence
)
SELECT
    -- Identity
    b.mua_number,
    md5('bok.mua_precedents.' || b.mua_id::text),

    -- Material: no MAPTIS code in this table either
    '',
    COALESCE(b.material_name, ''),
    -- Can't reliably infer metal/nonmetal from bok, default metal
    'metal',
    COALESCE(b.material_specification, ''),

    -- Flag: bok doesn't have explicit issue column
    -- We'll populate in the enrichment pass below
    '',
    '',

    -- Environment: extract from configuration text
    mua_precedent.extract_media_from_config(b.configuration),
    mua_precedent.normalize_media(
        mua_precedent.extract_media_from_config(b.configuration)
    ),
    mua_precedent.extract_env_from_config(b.configuration),

    -- Outcome
    CASE b.determination
        WHEN 'APPROVED' THEN 'II'     -- most approved MUAs are Cat II
        WHEN 'CONDITIONAL' THEN 'II'
        WHEN 'REJECTED' THEN ''
        ELSE ''
    END,
    b.determination,
    mua_precedent.determination_to_approved(b.determination),

    -- Content
    COALESCE(b.rationale, ''),
    COALESCE(b.configuration, ''),

    -- Provenance
    COALESCE(b.source_pdf, ''),
    'pdf',
    COALESCE(b.parser_confidence, 0.5)

FROM bok.mua_precedents b
ON CONFLICT (source_hash) DO NOTHING;


-- ============================================================================
-- ENRICHMENT PASS 1: Extract issue from rationale_text for bok rows
-- ============================================================================
-- Many bok rows lack explicit issue fields. Scan rationale text for keywords.

UPDATE mua_precedent.mua_records
SET issue = CASE
    -- SCC first (before CORR, since "stress corrosion" contains corrosion)
    WHEN UPPER(rationale_text) LIKE '%STRESS CORROSION%'
      OR UPPER(rationale_text) LIKE '%SCC%'
      OR UPPER(rationale_text) LIKE '%MSFC-SPEC-522%'
    THEN 'SCC'

    -- FLAM
    WHEN UPPER(rationale_text) LIKE '%FLAMMAB%'
      OR UPPER(rationale_text) LIKE '%BURN LENGTH%'
      OR UPPER(rationale_text) LIKE '%PROMOTED IGNITION%'
      OR UPPER(rationale_text) LIKE '%PROMOTED COMBUSTION%'
      OR UPPER(rationale_text) LIKE '%NHB 8060%'
    THEN 'FLAM'

    -- TVS
    WHEN UPPER(rationale_text) LIKE '%OUTGASSING%'
      OR UPPER(rationale_text) LIKE '%ASTM E595%'
      OR UPPER(rationale_text) LIKE '%THERMAL VACUUM%'
      OR UPPER(rationale_text) LIKE '%TML%' AND UPPER(rationale_text) LIKE '%CVCM%'
    THEN 'TVS'

    -- TOX
    WHEN UPPER(rationale_text) LIKE '%TOXICITY%'
      OR UPPER(rationale_text) LIKE '%OFFGAS%'
      OR UPPER(rationale_text) LIKE '%TEST 7%'
    THEN 'TOX'

    -- FS
    WHEN UPPER(rationale_text) LIKE '%FLUID COMPAT%'
      OR UPPER(rationale_text) LIKE '%TEST 15%'
      OR UPPER(rationale_text) LIKE '%HYDRAZINE%'
    THEN 'FS'

    -- CORR
    WHEN UPPER(rationale_text) LIKE '%CORROSION%'
      OR UPPER(rationale_text) LIKE '%DISSIMILAR METAL%'
      OR UPPER(rationale_text) LIKE '%GALVANIC%'
    THEN 'CORR'

    ELSE issue  -- keep whatever's there
END
WHERE issue = '' AND rationale_text != '';


-- ============================================================================
-- ENRICHMENT PASS 2: Infer material_class for bok rows from material_name
-- ============================================================================

UPDATE mua_precedent.mua_records
SET material_class = 'nonmetallic'
WHERE source_hash LIKE 'bok.%'  -- only bok rows (we defaulted to 'metal')
  AND (
    UPPER(material_name) LIKE '%ADHESIVE%'
    OR UPPER(material_name) LIKE '%EPOXY%'
    OR UPPER(material_name) LIKE '%TEFLON%'
    OR UPPER(material_name) LIKE '%PTFE%'
    OR UPPER(material_name) LIKE '%VITON%'
    OR UPPER(material_name) LIKE '%RUBBER%'
    OR UPPER(material_name) LIKE '%SILICONE%'
    OR UPPER(material_name) LIKE '%NYLON%'
    OR UPPER(material_name) LIKE '%KAPTON%'
    OR UPPER(material_name) LIKE '%POLYIMIDE%'
    OR UPPER(material_name) LIKE '%VESPEL%'
    OR UPPER(material_name) LIKE '%POLYMER%'
    OR UPPER(material_name) LIKE '%FOAM%'
    OR UPPER(material_name) LIKE '%TAPE%'
    OR UPPER(material_name) LIKE '%SEALANT%'
    OR UPPER(material_name) LIKE '%COATING%'
    OR UPPER(material_name) LIKE '%PAINT%'
    OR UPPER(material_name) LIKE '%PRIMER%'
    OR UPPER(material_name) LIKE '%LUBRICANT%'
    OR UPPER(material_name) LIKE '%GREASE%'
    OR UPPER(material_name) LIKE '%NOMEX%'
    OR UPPER(material_name) LIKE '%KEVLAR%'
    OR UPPER(material_name) LIKE '%VELCRO%'
    OR UPPER(material_name) LIKE '%LABEL%'
    OR UPPER(material_name) LIKE '%VINYL%'
    OR UPPER(material_name) LIKE '%FABRIC%'
    OR UPPER(material_name) LIKE '%CLOTH%'
    OR UPPER(material_name) LIKE '%FILM%'
    OR UPPER(material_name) LIKE '%WRAP%'
    OR UPPER(material_name) LIKE '%SHRINK%'
    OR UPPER(material_name) LIKE '%KEL%F%'
    OR UPPER(material_name) LIKE '%PCTFE%'
    OR UPPER(material_name) LIKE '%ELASTOMER%'
    OR UPPER(material_name) LIKE '%O-RING%'
  );


-- ============================================================================
-- ENRICHMENT PASS 3: Alloy family from material_name for bok rows
-- ============================================================================

UPDATE mua_precedent.mua_records
SET alloy_family = CASE
    WHEN UPPER(material_name) ~ '\m(304|316|321|347|303)\m' THEN 'austenitic_ss'
    WHEN UPPER(material_name) ~ '\mA[\-\s]?286\m' THEN 'fe_superalloy'
    WHEN UPPER(material_name) ~ '\mINCONEL\m' THEN 'ni_superalloy'
    WHEN UPPER(material_name) ~ '\mMONEL\m' THEN 'ni_alloy'
    WHEN UPPER(material_name) ~ '\mHASTELLOY\m' THEN 'ni_superalloy'
    WHEN UPPER(material_name) ~ '\mWASPALOY\m' THEN 'ni_superalloy'
    WHEN UPPER(material_name) ~ '\mMP35N\m' THEN 'ni_superalloy'
    WHEN UPPER(material_name) ~ '\m70[0-9]{2}\m' THEN 'al_alloy'
    WHEN UPPER(material_name) ~ '\m60[0-9]{2}\m' THEN 'al_alloy'
    WHEN UPPER(material_name) ~ '\m20[0-9]{2}\m' THEN 'al_alloy'
    WHEN UPPER(material_name) ~ '\mTI[\-\s]*6AL' THEN 'ti_alloy'
    WHEN UPPER(material_name) ~ '\m17[\-\s]*4\s*PH\m' THEN 'martensitic_ss'
    WHEN UPPER(material_name) ~ '\m15[\-\s]*5\s*PH\m' THEN 'martensitic_ss'
    WHEN UPPER(material_name) ~ '\mC63[02]00\m' THEN 'cu_alloy'
    WHEN UPPER(material_name) ~ '\mBRONZE\m' THEN 'cu_alloy'
    WHEN UPPER(material_name) ~ '\mCOPPER\m|\mOFHC\m' THEN 'cu_alloy'
    WHEN UPPER(material_name) ~ '\mVESPEL\m' THEN 'polyimide'
    WHEN UPPER(material_name) ~ '\mTEFLON\m|\mPTFE\m' THEN 'fluoropolymer'
    WHEN UPPER(material_name) ~ '\mKEL[\-\s]*F\m|\mPCTFE\m' THEN 'fluoropolymer'
    WHEN UPPER(material_name) ~ '\mVITON\m' THEN 'fluoroelastomer'
    ELSE alloy_family  -- keep existing
END
WHERE alloy_family = '' AND material_name != '';


-- ============================================================================
-- REFRESH MATERIALIZED VIEWS
-- ============================================================================

REFRESH MATERIALIZED VIEW mua_precedent.precedent_counts;
REFRESH MATERIALIZED VIEW mua_precedent.family_precedent;


COMMIT;


-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- How many rows migrated from each source?
SELECT
    CASE
        WHEN source_hash LIKE 'public.%' THEN 'public.mua_records'
        ELSE 'bok.mua_precedents'
    END AS source_table,
    COUNT(*) AS total_migrated
FROM mua_precedent.mua_records
GROUP BY 1;

-- Issue distribution
SELECT issue, COUNT(*) AS cnt
FROM mua_precedent.mua_records
WHERE issue != ''
GROUP BY issue ORDER BY cnt DESC;

-- Media category distribution
SELECT media_category, COUNT(*) AS cnt
FROM mua_precedent.mua_records
GROUP BY media_category ORDER BY cnt DESC;

-- Material class split
SELECT material_class, COUNT(*) AS cnt
FROM mua_precedent.mua_records
GROUP BY material_class ORDER BY cnt DESC;

-- Approval rate
SELECT
    approved,
    COUNT(*) AS cnt,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) AS pct
FROM mua_precedent.mua_records
GROUP BY approved ORDER BY cnt DESC;

-- Precedent counts view (the money query)
SELECT issue, rating, media_category, material_class, mua_type,
       total_count, approved_count, most_common_category
FROM mua_precedent.precedent_counts
ORDER BY total_count DESC
LIMIT 20;

-- Data quality: how many rows have issue populated?
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE issue != '') AS has_issue,
    COUNT(*) FILTER (WHERE media_category != 'other') AS has_media,
    COUNT(*) FILTER (WHERE alloy_family != '') AS has_family,
    COUNT(*) FILTER (WHERE rationale_text != '') AS has_rationale,
    COUNT(*) FILTER (WHERE confidence >= 0.5) AS high_confidence
FROM mua_precedent.mua_records;
