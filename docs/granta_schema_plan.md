# MIRA v4 Granta MI Database Schema Plan

## Version: 1.0.0
## Maintainer: Dr. Joseph Wilde / Beth (CTO)
## Date: 2026-02-05
## Classification: BoundState Proprietary
## Compliance: NASA-STD-8739.8B, NASA-STD-6016C, SWE-013, SWE-032, SWE-033
## Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1

---

## 1. Design Principles

### 1.1 Why a New Schema

The legacy MAPTIS PostgreSQL schema suffers from ten structural problems that
cannot be fixed by incremental patching:

1. **Unit inconsistency** -- temperatures in Fahrenheit, pressures in psia/psi
   with no canonical form.
2. **Identity confusion** -- `material_code` and `material_key` both exist as
   foreign keys, pointing at different things.
3. **No hierarchy** -- 60+ INCONEL 718 variants are flat rows with no
   family/alloy/condition grouping.
4. **Fragmented tests** -- 13 separate table pairs for test types, each with
   its own schema and join pattern.
5. **No environment envelope** -- `use_temp_min_f` / `use_temp_max_f` are
   rarely populated; no pressure, O2%, or fluid medium columns.
6. **No audit trail** -- no provenance hashing, no schema versioning, no
   lineage linkage.
7. **5,225 unclassified materials** -- NULL material type on 16.6% of rows.
8. **No safety context** -- no native O2/H2/CRYOGENIC/HIGH_PRESSURE
   classification.
9. **No dirty data tracking** -- no per-field data quality flags.
10. **No heritage veto linkage** -- failure records are not structurally
    connected to material-environment pairs.

### 1.2 Canonical Units

All quantities in the v4 schema use SI-adjacent canonical units:

| Quantity        | Canonical Unit | Symbol | Legacy Unit     | Conversion              |
|-----------------|----------------|--------|-----------------|-------------------------|
| Temperature     | Celsius        | C      | Fahrenheit      | C = (F - 32) * 5/9      |
| Pressure        | kilopascal     | kPa    | psia            | kPa = psia * 6.89476    |
| Stress/Strength | megapascal     | MPa    | ksi / psi       | MPa = ksi * 6.89476     |
| Toughness       | MPa*sqrt(m)    |        | ksi*sqrt(in)    | MPa*sqrt(m) = ksi*sqrt(in) * 1.0989 |
| Length          | millimeter     | mm     | inches          | mm = in * 25.4          |
| Energy          | joule          | J      | ft-lbs          | J = ft-lbs * 1.35582    |
| Concentration   | percent        | %      | percent         | 1:1                     |
| Duration        | hours          | hr     | hours           | 1:1                     |

### 1.3 Granta MI Compatibility

This schema is designed to map cleanly onto Granta MI's data model:

- **Tables** map to Granta MI **Tables** (record collections).
- **Columns** map to Granta MI **Attributes** (point, range, discrete,
  hyperlink, file, short-text, long-text).
- **Foreign keys** map to Granta MI **Cross-table record links**.
- **Enums** map to Granta MI **Discrete attributes** with controlled
  vocabularies.
- **JSONB columns** map to Granta MI **File attributes** (JSON documents) for
  complex nested data that does not need columnar filtering.

### 1.4 Naming Conventions

- Table names: `snake_case`, plural (e.g., `materials`, `test_evidence`).
- Column names: `snake_case` with unit suffix where applicable
  (e.g., `temperature_c`, `pressure_kpa`).
- Primary keys: `{table_singular}_id` (e.g., `material_id`).
- Foreign keys: reference the parent column name exactly
  (e.g., `material_id` references `materials.material_id`).
- Enum values: `UPPER_SNAKE_CASE` for application-level enums,
  `lower_snake_case` for database storage.

---

## 2. Entity-Relationship Model

### 2.1 Entity Summary

```
                    MATERIAL HIERARCHY
                    ==================

  material_families (1)
        |
        | 1:N
        v
  materials (N)  <--- material_aliases (N:1)
        |
        | 1:N
        v
  material_conditions (N)
        |
        +-------+--------+--------+--------+
        |       |        |        |        |
        v       v        v        v        v
  environment   test_    mua_     heritage schema_
  _envelopes    evidence precedents failures dictionary
  (N:1)         (N:1)    (N:M)    (N:1)    (standalone)
                  |
                  v
              test_evidence_results (N:1)


                    PROVENANCE & AUDIT
                    ==================

  decision_lineage_log (standalone, append-only)
        |
        | references
        v
  provenance_snapshots (standalone, append-only)


                    CONFIGURATION
                    ==============

  safety_context_rules (standalone)
  scoring_profiles (standalone, versioned)
  schema_versions (standalone, versioned)
```

### 2.2 Relationship Summary

| Parent                  | Child                    | Cardinality | FK Column            |
|-------------------------|--------------------------|-------------|----------------------|
| material_families       | materials                | 1:N         | family_id            |
| materials               | material_conditions      | 1:N         | material_id          |
| materials               | material_aliases         | 1:N         | material_id          |
| material_conditions     | environment_envelopes    | 1:N         | condition_id         |
| material_conditions     | test_evidence            | 1:N         | condition_id         |
| material_conditions     | heritage_failures        | 1:N         | condition_id         |
| test_evidence           | test_evidence_results    | 1:N         | evidence_id          |
| materials               | mua_precedent_materials  | N:M         | (junction table)     |
| mua_precedents          | mua_precedent_materials  | N:M         | (junction table)     |

---

## 3. Table Definitions

### 3.1 `material_families` -- Top-Level Grouping

Groups materials into metallurgical/chemical families. Each family has a
canonical name and optional Sandia/MAPTIS classification codes.

```sql
CREATE TABLE material_families (
    family_id           VARCHAR(64) PRIMARY KEY,
    -- e.g., "austenitic_stainless", "nickel_superalloy", "fluoropolymer"

    family_name         VARCHAR(256) NOT NULL,
    -- Human-readable: "Austenitic Stainless Steel"

    family_class        VARCHAR(64) NOT NULL,
    -- Top-level class: "metal", "polymer", "composite", "ceramic",
    -- "adhesive", "coating", "foam", "thermal_protection", "mineral"

    sandia_code_prefix  VARCHAR(16),
    -- e.g., "2101" for austenitic 304 family (nullable, metals only)

    maptis_type_key     INTEGER,
    -- Legacy MAPTIS material_type_key (235=Metal, 239=Polymer, etc.)
    -- Nullable for families not in MAPTIS

    description         TEXT,
    -- Engineering notes about this family

    h2_susceptibility_class VARCHAR(32),
    -- Default H2 embrittlement susceptibility for the family:
    -- "negligible", "small", "high", "severe", "extreme", NULL
    -- Per NASA/TM-2016-218602 Table 1

    o2_default_compatibility VARCHAR(32),
    -- Default O2 compatibility for the family:
    -- "compatible", "marginal", "incompatible", NULL

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_family_class CHECK (
        family_class IN (
            'metal', 'polymer', 'composite', 'ceramic',
            'adhesive', 'coating', 'foam', 'thermal_protection', 'mineral'
        )
    )
);

CREATE INDEX idx_family_class ON material_families(family_class);
CREATE INDEX idx_family_maptis_type ON material_families(maptis_type_key);
```

**Granta MI mapping:** This is a Granta MI Table named "Material Families"
with discrete attributes for `family_class`, `h2_susceptibility_class`, and
`o2_default_compatibility`.

---

### 3.2 `materials` -- Base Material Identity

The canonical material record. Represents a unique alloy, polymer, or compound
independent of its heat treatment, form, or condition.

```sql
CREATE TABLE materials (
    material_id         VARCHAR(64) PRIMARY KEY,
    -- Canonical ID format: "MIRA:{integer}" for MAPTIS-sourced,
    -- "GRANTA:{guid}" for Granta-native, "MANUAL:{slug}" for hand-entered.

    legacy_material_key INTEGER,
    -- Original MAPTIS material_key (for backward compatibility)
    -- Nullable for non-MAPTIS materials

    legacy_material_code TEXT,
    -- Original MAPTIS material_code (for migration traceability)

    designation         VARCHAR(512) NOT NULL,
    -- Primary material designation: "INCONEL 718", "PTFE", "316L SS"

    specification       VARCHAR(256),
    -- Governing specification: "AMS-5662", "ASTM A240", "AMS-3651"

    uns_number          VARCHAR(16),
    -- UNS designation: "N07718", "S31603" (metals only, nullable)

    family_id           VARCHAR(64) NOT NULL REFERENCES material_families(family_id),
    -- Link to material family

    composition_summary TEXT,
    -- Free-text composition: "Ni-19Cr-18Fe-5Nb-3Mo-1Ti-0.5Al"
    -- For display; structured composition is in material_conditions

    data_source         VARCHAR(128) NOT NULL DEFAULT 'MAPTIS',
    -- Origin: "MAPTIS", "GRANTA", "BOK_EXTRACTION", "MANUAL"

    source_reference    TEXT,
    -- Traceability: report number, database ID, etc.

    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    -- Soft-delete flag

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_data_source CHECK (
        data_source IN ('MAPTIS', 'GRANTA', 'BOK_EXTRACTION', 'MANUAL')
    )
);

CREATE UNIQUE INDEX idx_material_legacy_key
    ON materials(legacy_material_key) WHERE legacy_material_key IS NOT NULL;
CREATE INDEX idx_material_designation ON materials(designation);
CREATE INDEX idx_material_uns ON materials(uns_number) WHERE uns_number IS NOT NULL;
CREATE INDEX idx_material_family ON materials(family_id);
CREATE INDEX idx_material_spec ON materials(specification) WHERE specification IS NOT NULL;
CREATE INDEX idx_material_active ON materials(is_active);
```

**Granta MI mapping:** This is the primary Granta MI Table "Materials" with
short-text attributes for designation, specification, UNS, and a record link
to the "Material Families" table.

---

### 3.3 `material_aliases` -- Alternative Names and Cross-References

Handles the many-names problem: "Inconel 718" = "Alloy 718" = "UNS N07718" =
"AMS 5662" = "ASTM B637".

```sql
CREATE TABLE material_aliases (
    alias_id            SERIAL PRIMARY KEY,
    material_id         VARCHAR(64) NOT NULL REFERENCES materials(material_id)
                            ON DELETE CASCADE,
    alias_name          VARCHAR(512) NOT NULL,
    alias_type          VARCHAR(64) NOT NULL,
    -- "trade_name", "specification", "uns", "common_name", "legacy_code"

    CONSTRAINT valid_alias_type CHECK (
        alias_type IN (
            'trade_name', 'specification', 'uns',
            'common_name', 'legacy_code', 'abbreviation'
        )
    )
);

CREATE INDEX idx_alias_material ON material_aliases(material_id);
CREATE INDEX idx_alias_name ON material_aliases(alias_name);
CREATE INDEX idx_alias_name_lower ON material_aliases(LOWER(alias_name));
```

**Granta MI mapping:** Tabular data attribute on the Materials table, or a
linked "Aliases" subtable.

---

### 3.4 `material_conditions` -- Condition/Form Variants

Each material can exist in multiple conditions: different heat treatments,
product forms, weld states. This resolves the legacy problem of 60+ INCONEL
718 flat rows.

```sql
CREATE TABLE material_conditions (
    condition_id        VARCHAR(128) PRIMARY KEY,
    -- Format: "{material_id}:{condition_slug}"
    -- e.g., "MIRA:12345:STA-1024C-bar" or "MIRA:12345:annealed-sheet"

    material_id         VARCHAR(64) NOT NULL REFERENCES materials(material_id)
                            ON DELETE CASCADE,

    -- Heat treatment
    heat_treat_condition VARCHAR(64),
    -- "annealed", "solution_treated", "solution_treated_aged",
    -- "normalized", "quenched_tempered", "as_received"

    solution_temp_c     FLOAT,
    solution_time_hr    FLOAT,
    age_temp_c          FLOAT,
    age_time_hr         FLOAT,
    second_age_temp_c   FLOAT,
    second_age_time_hr  FLOAT,
    quench_medium       VARCHAR(64),  -- "water", "oil", "air", "furnace"
    heat_treat_description TEXT,      -- Full free-text description

    -- Product form
    product_form        VARCHAR(64),
    -- "plate", "bar", "rolled_bar", "forging", "sheet", "tubing",
    -- "fastener", "casting", "PM", "wire"

    -- Weld state
    weld_state          VARCHAR(32) DEFAULT 'base_metal',
    -- "base_metal", "weld_metal", "HAZ"

    -- Grain direction
    grain_direction     VARCHAR(32),
    -- "longitudinal", "transverse", "short_transverse"

    -- Structured composition (for this specific condition)
    ni_wt_pct           FLOAT,
    cr_wt_pct           FLOAT,
    fe_wt_pct           FLOAT,
    mo_wt_pct           FLOAT,
    mn_wt_pct           FLOAT,
    c_wt_pct            FLOAT,
    n_wt_pct            FLOAT,
    si_wt_pct           FLOAT,
    ti_wt_pct           FLOAT,
    al_wt_pct           FLOAT,
    cu_wt_pct           FLOAT,
    co_wt_pct           FLOAT,
    nb_wt_pct           FLOAT,
    v_wt_pct            FLOAT,
    w_wt_pct            FLOAT,

    -- Mechanical properties (nominal / handbook values)
    yield_strength_mpa  FLOAT,
    uts_mpa             FLOAT,
    elongation_pct      FLOAT,
    hardness_hrc        FLOAT,
    hardness_hv         FLOAT,
    density_g_cm3       FLOAT,

    -- MAPTIS Ratings (1-4 scale per MIUL specification)
    rating_flammability INTEGER,
    rating_scc          INTEGER,
    rating_corrosion    INTEGER,
    rating_outgassing   INTEGER,

    -- Compliance flags
    contains_pfas       BOOLEAN DEFAULT FALSE,
    is_restricted       BOOLEAN DEFAULT FALSE,

    -- Condition display name
    condition_label     VARCHAR(512),
    -- e.g., "STA 1024C/718C - Bar - Base Metal"

    is_primary          BOOLEAN DEFAULT FALSE,
    -- True for the "default" condition of this material

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_heat_treat CHECK (
        heat_treat_condition IS NULL OR heat_treat_condition IN (
            'annealed', 'solution_treated', 'solution_treated_aged',
            'normalized', 'quenched_tempered', 'as_received'
        )
    ),
    CONSTRAINT valid_product_form CHECK (
        product_form IS NULL OR product_form IN (
            'plate', 'bar', 'rolled_bar', 'forging', 'sheet',
            'tubing', 'fastener', 'casting', 'PM', 'wire'
        )
    ),
    CONSTRAINT valid_weld_state CHECK (
        weld_state IN ('base_metal', 'weld_metal', 'HAZ')
    ),
    CONSTRAINT valid_rating_flam CHECK (
        rating_flammability IS NULL OR
        (rating_flammability >= 1 AND rating_flammability <= 4)
    ),
    CONSTRAINT valid_rating_scc CHECK (
        rating_scc IS NULL OR (rating_scc >= 1 AND rating_scc <= 4)
    ),
    CONSTRAINT valid_rating_corr CHECK (
        rating_corrosion IS NULL OR (rating_corrosion >= 1 AND rating_corrosion <= 4)
    ),
    CONSTRAINT valid_rating_outgas CHECK (
        rating_outgassing IS NULL OR (rating_outgassing >= 1 AND rating_outgassing <= 4)
    )
);

CREATE INDEX idx_condition_material ON material_conditions(material_id);
CREATE INDEX idx_condition_heat_treat ON material_conditions(heat_treat_condition);
CREATE INDEX idx_condition_form ON material_conditions(product_form);
CREATE INDEX idx_condition_weld ON material_conditions(weld_state);
CREATE INDEX idx_condition_primary ON material_conditions(material_id, is_primary);
CREATE INDEX idx_condition_uts ON material_conditions(uts_mpa) WHERE uts_mpa IS NOT NULL;
CREATE INDEX idx_condition_yield ON material_conditions(yield_strength_mpa)
    WHERE yield_strength_mpa IS NOT NULL;
```

**Granta MI mapping:** Granta MI Table "Material Conditions" with record links
to "Materials" and point/discrete attributes for each property.

---

### 3.5 `environment_envelopes` -- Structured Operating Envelopes

Defines the validated operating envelope for each material condition. Directly
supports the v4 EnvironmentSpec model and confidence scoring.

```sql
CREATE TABLE environment_envelopes (
    envelope_id         VARCHAR(128) PRIMARY KEY,
    -- Format: "{condition_id}:{gas_type}:{envelope_index}"

    condition_id        VARCHAR(128) NOT NULL
        REFERENCES material_conditions(condition_id) ON DELETE CASCADE,

    -- Gas/fluid context
    gas_type            VARCHAR(8),
    -- "H2", "O2", "N2", "He", "AIR", "LOX", "GOX", "LH2", "GH2", NULL
    -- NULL = general/unknown

    safety_context      VARCHAR(32) NOT NULL DEFAULT 'general',
    -- "oxygen", "hydrogen", "cryogenic", "high_pressure", "general"
    -- Maps directly to SafetyContext enum

    -- Temperature envelope (Celsius)
    temp_min_c          FLOAT,
    temp_max_c          FLOAT,

    -- Pressure envelope (kPa)
    pressure_min_kpa    FLOAT,
    pressure_max_kpa    FLOAT,

    -- Concentration
    o2_concentration_pct FLOAT,
    -- Oxygen concentration percentage (for O2 service)

    fluid_medium        VARCHAR(64),
    -- "LOX", "GOX", "LH2", "GH2", "N2O4", etc.

    phase               VARCHAR(16) DEFAULT 'unknown',
    -- "gaseous", "liquid", "supercritical", "unknown"

    -- Compatibility verdict for this envelope
    compatibility       VARCHAR(32),
    -- "compatible", "marginal", "incompatible", "insufficient_data"

    compatibility_reason TEXT,
    -- Engineering rationale for the verdict

    mitigation          TEXT,
    -- Required mitigations if "marginal"

    -- Provenance
    standard_ref        VARCHAR(256),
    -- "NASA-STD-6016C S4.2.1", "SAND2012-7321 Table A.1"

    data_source         VARCHAR(128),
    -- "MAPTIS", "BOK_H2", "BOK_O2", "MANUAL"

    data_class          VARCHAR(32) NOT NULL DEFAULT 'derived',
    -- "direct_test", "standard_table", "bok_precedent", "derived"

    confidence          FLOAT DEFAULT 1.0,
    -- 0.0-1.0 confidence in this envelope data

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_safety_context CHECK (
        safety_context IN ('oxygen', 'hydrogen', 'cryogenic', 'high_pressure', 'general')
    ),
    CONSTRAINT valid_phase CHECK (
        phase IN ('gaseous', 'liquid', 'supercritical', 'unknown')
    ),
    CONSTRAINT valid_compatibility CHECK (
        compatibility IS NULL OR compatibility IN (
            'compatible', 'marginal', 'incompatible', 'insufficient_data'
        )
    ),
    CONSTRAINT valid_data_class CHECK (
        data_class IN ('direct_test', 'standard_table', 'bok_precedent', 'derived')
    ),
    CONSTRAINT valid_temp_range CHECK (
        temp_min_c IS NULL OR temp_max_c IS NULL OR temp_max_c >= temp_min_c
    ),
    CONSTRAINT valid_pressure_range CHECK (
        pressure_min_kpa IS NULL OR pressure_max_kpa IS NULL
        OR pressure_max_kpa >= pressure_min_kpa
    ),
    CONSTRAINT valid_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX idx_envelope_condition ON environment_envelopes(condition_id);
CREATE INDEX idx_envelope_gas ON environment_envelopes(gas_type);
CREATE INDEX idx_envelope_safety ON environment_envelopes(safety_context);
CREATE INDEX idx_envelope_temp ON environment_envelopes(temp_min_c, temp_max_c);
CREATE INDEX idx_envelope_pressure ON environment_envelopes(pressure_min_kpa, pressure_max_kpa);
CREATE INDEX idx_envelope_compatibility ON environment_envelopes(compatibility);
CREATE INDEX idx_envelope_fluid ON environment_envelopes(fluid_medium);
```

**Granta MI mapping:** Granta MI Table "Environment Envelopes" linked to
"Material Conditions" with range attributes for temperature and pressure,
discrete attributes for safety_context, phase, and compatibility.

---

### 3.6 `test_evidence` -- Unified Test Evidence

Replaces the 13 separate test table pairs with a single unified evidence
table. Each row is one test/measurement on one material condition. The
`test_type` discriminator column replaces the legacy table-per-type pattern.

```sql
CREATE TABLE test_evidence (
    evidence_id         VARCHAR(128) PRIMARY KEY,
    -- Format: "{condition_id}:{test_type}:{source_test_id}"

    condition_id        VARCHAR(128) NOT NULL
        REFERENCES material_conditions(condition_id) ON DELETE CASCADE,

    -- Test classification
    test_type           VARCHAR(64) NOT NULL,
    -- Unified discriminator. Values include:
    -- "flammability", "mechanical_impact", "promoted_combustion",
    -- "pneumatic_impact", "arc_tracking", "tensile_strength",
    -- "high_cycle_fatigue", "tvs_outgassing", "toxicity",
    -- "corrosion", "fluid_compatibility", "vcm_optical",
    -- "crack_growth", "fracture_toughness", "h2_embrittlement",
    -- "hydrogen_permeation", "stress_corrosion", "general"

    test_method         VARCHAR(128),
    -- ASTM/NASA standard: "ASTM E8", "NASA-STD-6001B Test 1", etc.

    -- Test date and facility
    test_date           DATE,
    test_year           INTEGER,
    -- Explicit year column for staleness penalty calculation.
    -- Derived from test_date when available, or extracted from report.

    test_facility       VARCHAR(256),
    test_report_id      VARCHAR(256),
    -- Silver report contract/test report identifier

    -- Test environment conditions (canonical v4 units)
    test_temperature_c  FLOAT,
    test_pressure_kpa   FLOAT,
    test_o2_pct         FLOAT,
    test_fluid_medium   VARCHAR(64),
    test_phase          VARCHAR(16),
    test_duration_hr    FLOAT,
    test_cycles         INTEGER,

    -- Primary result
    result_value        FLOAT,
    result_unit         VARCHAR(64),
    result_text         VARCHAR(512),
    -- For non-numeric results (e.g., flammability rating "A", "B", "C", "D")

    -- Secondary results (type-specific, stored as JSON for flexibility)
    secondary_results   JSONB,
    -- Example for flammability: {"ignition_energy_j": 42.0, "burn_length_mm": 15.2}
    -- Example for tensile: {"elongation_pct": 12.5, "reduction_area_pct": 45.0}
    -- Example for outgassing: {"tml_pct": 0.85, "cvcm_pct": 0.02, "wvr_pct": 0.15}

    -- Data quality
    dirty_flag          BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE if any field contains non-typed or suspect data

    dirty_fields        TEXT[],
    -- Array of field names with non-typed data: {"test_temperature_c", "result_value"}

    raw_values          JSONB,
    -- Original values before unit conversion / normalization.
    -- Preserved for audit trail per BuildSpec Section 3.2.

    -- Data provenance
    data_class          VARCHAR(32) NOT NULL DEFAULT 'derived',
    -- "direct_test", "standard_table", "bok_precedent", "derived"

    data_source         VARCHAR(128) NOT NULL DEFAULT 'MAPTIS',
    source_reference    TEXT,
    confidence          FLOAT DEFAULT 1.0,

    -- Legacy traceability
    legacy_test_table   VARCHAR(64),
    -- Original MAPTIS table name: "flammability_tests", "tvs_outgassing_tests"
    legacy_test_id      VARCHAR(64),
    -- Original MAPTIS PK value

    is_valid            BOOLEAN DEFAULT TRUE,
    is_outlier          BOOLEAN DEFAULT FALSE,

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_data_class_te CHECK (
        data_class IN ('direct_test', 'standard_table', 'bok_precedent', 'derived')
    ),
    CONSTRAINT valid_confidence_te CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX idx_evidence_condition ON test_evidence(condition_id);
CREATE INDEX idx_evidence_type ON test_evidence(test_type);
CREATE INDEX idx_evidence_year ON test_evidence(test_year);
CREATE INDEX idx_evidence_dirty ON test_evidence(dirty_flag);
CREATE INDEX idx_evidence_source ON test_evidence(data_source);
CREATE INDEX idx_evidence_temp ON test_evidence(test_temperature_c)
    WHERE test_temperature_c IS NOT NULL;
CREATE INDEX idx_evidence_pressure ON test_evidence(test_pressure_kpa)
    WHERE test_pressure_kpa IS NOT NULL;
CREATE INDEX idx_evidence_fluid ON test_evidence(test_fluid_medium)
    WHERE test_fluid_medium IS NOT NULL;
CREATE INDEX idx_evidence_valid ON test_evidence(is_valid, is_outlier);
CREATE INDEX idx_evidence_condition_type ON test_evidence(condition_id, test_type);
CREATE INDEX idx_evidence_legacy ON test_evidence(legacy_test_table, legacy_test_id);
```

**Granta MI mapping:** Granta MI Table "Test Evidence" with a discrete
`test_type` attribute acting as the discriminator. Secondary results stored as
a File attribute (JSON). Record link to "Material Conditions".

---

### 3.7 `test_evidence_results` -- Detailed Result Rows

For test types that produce multiple result rows per test (e.g., toxicity gas
species, outgassing sub-measurements, crack growth data points).

```sql
CREATE TABLE test_evidence_results (
    result_id           SERIAL PRIMARY KEY,
    evidence_id         VARCHAR(128) NOT NULL
        REFERENCES test_evidence(evidence_id) ON DELETE CASCADE,

    result_key          VARCHAR(64) NOT NULL,
    -- e.g., "gas_species", "burn_distance", "cycle_count", "crack_length"

    result_value        FLOAT,
    result_text         VARCHAR(512),
    result_unit         VARCHAR(64),

    -- Test-specific context
    measurement_temp_c  FLOAT,
    measurement_pressure_kpa FLOAT,
    measurement_time_hr FLOAT,

    -- Quality
    dirty_flag          BOOLEAN DEFAULT FALSE,
    raw_value           TEXT,
    -- Original value before conversion

    CONSTRAINT at_least_one_result CHECK (
        result_value IS NOT NULL OR result_text IS NOT NULL
    )
);

CREATE INDEX idx_ter_evidence ON test_evidence_results(evidence_id);
CREATE INDEX idx_ter_key ON test_evidence_results(result_key);
```

**Granta MI mapping:** Tabular data attribute on the "Test Evidence" table, or
a linked subtable "Test Result Details".

---

### 3.8 `mua_precedents` -- MUA Decision Records

Material Usage Agreements from MAPTIS legacy data, normalized with structured
fields.

```sql
CREATE TABLE mua_precedents (
    mua_id              VARCHAR(128) PRIMARY KEY,
    -- Format: "MUA:{legacy_id}" or "MUA:{hash}"

    -- Decision
    determination       VARCHAR(64) NOT NULL,
    -- "approved", "approved_with_conditions", "not_approved", "testing_required"

    rationale           TEXT NOT NULL,
    rationale_codes     TEXT[],
    -- Structured rationale codes extracted by BOK parser

    -- Environment context
    safety_context      VARCHAR(32) DEFAULT 'general',
    temperature_c       FLOAT,
    pressure_kpa        FLOAT,
    o2_pct              FLOAT,
    fluid_medium        VARCHAR(64),

    -- References
    test_reports_cited  TEXT[],
    -- Array of cited test report IDs

    standard_references TEXT[],
    -- Array of cited standards: {"NASA-STD-6001B", "MSFC-STD-506"}

    contract_number     VARCHAR(128),
    program             VARCHAR(256),

    -- Provenance
    mua_date            DATE,
    mua_year            INTEGER,
    data_source         VARCHAR(128) DEFAULT 'MAPTIS',
    source_reference    TEXT,

    -- Legacy traceability
    legacy_mua_id       INTEGER,

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_determination CHECK (
        determination IN (
            'approved', 'approved_with_conditions',
            'not_approved', 'testing_required'
        )
    ),
    CONSTRAINT valid_safety_context_mua CHECK (
        safety_context IN ('oxygen', 'hydrogen', 'cryogenic', 'high_pressure', 'general')
    )
);

CREATE INDEX idx_mua_determination ON mua_precedents(determination);
CREATE INDEX idx_mua_safety ON mua_precedents(safety_context);
CREATE INDEX idx_mua_year ON mua_precedents(mua_year);
CREATE INDEX idx_mua_legacy ON mua_precedents(legacy_mua_id);
```

---

### 3.9 `mua_precedent_materials` -- Junction Table (MUA <-> Material)

Each MUA can reference multiple materials, and each material can appear in
multiple MUAs.

```sql
CREATE TABLE mua_precedent_materials (
    mua_id              VARCHAR(128) NOT NULL
        REFERENCES mua_precedents(mua_id) ON DELETE CASCADE,
    material_id         VARCHAR(64) NOT NULL
        REFERENCES materials(material_id) ON DELETE CASCADE,

    role                VARCHAR(32) DEFAULT 'subject',
    -- "subject" (material being evaluated),
    -- "alternative" (alternative material suggested),
    -- "reference" (referenced for comparison)

    PRIMARY KEY (mua_id, material_id)
);

CREATE INDEX idx_mua_mat_material ON mua_precedent_materials(material_id);
CREATE INDEX idx_mua_mat_mua ON mua_precedent_materials(mua_id);
```

---

### 3.10 `heritage_failures` -- Heritage Veto Records

Known failure records for materials in specific environments. Directly
supports the v4 HeritageVetoEngine envelope matching (temperature, pressure,
media).

```sql
CREATE TABLE heritage_failures (
    failure_id          VARCHAR(128) PRIMARY KEY,
    -- Format: "HF:{material_id}:{incident_id}"

    condition_id        VARCHAR(128)
        REFERENCES material_conditions(condition_id) ON DELETE SET NULL,
    -- Link to specific material condition (nullable if condition unknown)

    material_id         VARCHAR(64) NOT NULL
        REFERENCES materials(material_id) ON DELETE CASCADE,
    -- Always linked to the base material

    -- Failure environment (canonical v4 units for envelope matching)
    failure_temperature_c   FLOAT,
    failure_pressure_kpa    FLOAT,
    failure_fluid_medium    VARCHAR(64),
    failure_o2_pct          FLOAT,
    failure_phase           VARCHAR(16),

    safety_context      VARCHAR(32) NOT NULL DEFAULT 'general',
    -- "oxygen", "hydrogen", "cryogenic", "high_pressure", "general"

    -- Failure details
    failure_description TEXT NOT NULL,
    failure_mode        VARCHAR(128),
    -- "embrittlement", "ignition", "stress_corrosion", "thermal_fatigue",
    -- "seal_degradation", "outgassing_violation", etc.

    severity            VARCHAR(32) NOT NULL DEFAULT 'safety_critical',
    -- "safety_critical", "non_safety"
    -- Maps to HeritageVetoType enum

    -- Provenance
    incident_date       DATE,
    incident_year       INTEGER,
    report_reference    TEXT,
    data_source         VARCHAR(128) DEFAULT 'MAPTIS',

    -- Status
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    -- Can be deactivated if later determined to be erroneous

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_severity_hf CHECK (
        severity IN ('safety_critical', 'non_safety')
    ),
    CONSTRAINT valid_safety_context_hf CHECK (
        safety_context IN ('oxygen', 'hydrogen', 'cryogenic', 'high_pressure', 'general')
    )
);

CREATE INDEX idx_hf_material ON heritage_failures(material_id);
CREATE INDEX idx_hf_condition ON heritage_failures(condition_id)
    WHERE condition_id IS NOT NULL;
CREATE INDEX idx_hf_safety ON heritage_failures(safety_context);
CREATE INDEX idx_hf_severity ON heritage_failures(severity);
CREATE INDEX idx_hf_temp ON heritage_failures(failure_temperature_c)
    WHERE failure_temperature_c IS NOT NULL;
CREATE INDEX idx_hf_pressure ON heritage_failures(failure_pressure_kpa)
    WHERE failure_pressure_kpa IS NOT NULL;
CREATE INDEX idx_hf_fluid ON heritage_failures(failure_fluid_medium)
    WHERE failure_fluid_medium IS NOT NULL;
CREATE INDEX idx_hf_active ON heritage_failures(is_active);
```

**Granta MI mapping:** Granta MI Table "Heritage Failures" with record links
to both "Materials" and "Material Conditions". Point attributes for the
failure environment fields.

---

### 3.11 `heritage_overrides` -- Engineer Acknowledgment Records

Immutable records of engineer acknowledgments for heritage veto overrides.
Once created, these records cannot be modified or deleted.

```sql
CREATE TABLE heritage_overrides (
    override_id         VARCHAR(128) PRIMARY KEY,
    -- UUID v4

    material_id         VARCHAR(64) NOT NULL
        REFERENCES materials(material_id),
    failure_id          VARCHAR(128) NOT NULL
        REFERENCES heritage_failures(failure_id),

    -- Environment snapshots (frozen at override time)
    failure_env_json    JSONB NOT NULL,
    -- EnvironmentSpec of the heritage failure

    query_env_json      JSONB NOT NULL,
    -- EnvironmentSpec of the query that triggered the veto

    -- Engineer information
    engineer_name       VARCHAR(256) NOT NULL,
    engineer_rationale  TEXT NOT NULL,

    -- Lineage linkage
    lineage_hash        VARCHAR(64) NOT NULL,
    -- Links to parent Decision Lineage query_hash

    -- Timestamp (immutable)
    acknowledged_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Immutability enforcement: no UPDATE/DELETE triggers
    -- Application layer enforces frozen=True via Pydantic model
    CONSTRAINT override_rationale_nonempty CHECK (LENGTH(engineer_rationale) > 0)
);

CREATE INDEX idx_ho_material ON heritage_overrides(material_id);
CREATE INDEX idx_ho_failure ON heritage_overrides(failure_id);
CREATE INDEX idx_ho_lineage ON heritage_overrides(lineage_hash);
CREATE INDEX idx_ho_engineer ON heritage_overrides(engineer_name);
```

---

### 3.12 `decision_lineage_log` -- Immutable Audit Trail

Append-only log of every Decision Lineage artifact produced by MIRA v4. This
is the primary audit table for IV&V review per NASA-STD-8739.8B.

```sql
CREATE TABLE decision_lineage_log (
    lineage_id          VARCHAR(128) PRIMARY KEY,
    -- UUID v4

    -- Provenance hashes
    query_hash          VARCHAR(64) NOT NULL,
    -- Deterministic: same filters always produce same hash

    snapshot_hash       VARCHAR(64) NOT NULL,
    -- Includes timestamp: unique per query execution

    -- Full lineage artifact as JSONB
    lineage_json        JSONB NOT NULL,
    -- Complete DecisionLineage Pydantic model serialized to JSON.
    -- Includes: parsed_query, confidence, batch_gate, dirty_data,
    -- heritage_veto, intent_disagreement, heritage_overrides.

    -- Denormalized fields for indexing/filtering
    safety_context      VARCHAR(32),
    gate_action         VARCHAR(16),
    -- "PASS", "CLARIFY", "REFUSE"

    confidence_score    FLOAT,
    dirty_data_tier     VARCHAR(16),
    -- "clean", "degraded", "refuse"

    heritage_vetoed     BOOLEAN DEFAULT FALSE,
    batch_mode          BOOLEAN DEFAULT FALSE,

    schema_version      VARCHAR(32) NOT NULL,
    -- Schema Dictionary version at query time

    -- Timestamp
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Append-only: application layer prevents UPDATE/DELETE.
-- Database-level enforcement via REVOKE UPDATE, DELETE if needed.

CREATE INDEX idx_dll_query_hash ON decision_lineage_log(query_hash);
CREATE INDEX idx_dll_snapshot ON decision_lineage_log(snapshot_hash);
CREATE INDEX idx_dll_safety ON decision_lineage_log(safety_context);
CREATE INDEX idx_dll_gate ON decision_lineage_log(gate_action);
CREATE INDEX idx_dll_confidence ON decision_lineage_log(confidence_score);
CREATE INDEX idx_dll_created ON decision_lineage_log(created_at);
CREATE INDEX idx_dll_schema ON decision_lineage_log(schema_version);
CREATE INDEX idx_dll_vetoed ON decision_lineage_log(heritage_vetoed)
    WHERE heritage_vetoed = TRUE;
```

**Granta MI mapping:** Not stored in Granta MI (this is MIRA's own audit
log). Stored in PostgreSQL or a dedicated audit database.

---

### 3.13 `schema_versions` -- Schema Dictionary Versioning

Tracks schema dictionary versions for drift detection per BuildSpec Section 8.

```sql
CREATE TABLE schema_versions (
    version_id          VARCHAR(32) PRIMARY KEY,
    -- Semantic versioning: "1.0.0", "1.1.0", "2.0.0"

    -- Schema definition
    schema_definition   JSONB NOT NULL,
    -- Complete field dictionary: {field_name: field_type, ...}
    -- Compared against live Granta schema for drift detection.

    -- Property aliases (Schema Dictionary)
    property_aliases    JSONB,
    -- {"stiffness": "youngs_modulus_gpa", "strength": "uts_mpa", ...}

    material_class_aliases JSONB,
    form_aliases        JSONB,
    environment_aliases JSONB,
    unit_conversions    JSONB,

    -- Metadata
    description         TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    -- Only ONE version can be active at a time

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at        TIMESTAMP,
    deactivated_at      TIMESTAMP,

    -- Validation results
    last_validation_json JSONB,
    -- SchemaValidationResult from last drift check

    last_validated_at   TIMESTAMP,

    CONSTRAINT only_one_active UNIQUE (is_active) -- Partial: only when TRUE
    -- Note: This constraint only works in PostgreSQL with a partial unique
    -- index. In Granta MI, enforce via application logic.
);

-- Partial unique index: only one active version
CREATE UNIQUE INDEX idx_sv_active ON schema_versions(is_active)
    WHERE is_active = TRUE;

CREATE INDEX idx_sv_created ON schema_versions(created_at);
```

---

### 3.14 `scoring_profiles` -- Versioned Scoring Configuration

Versioned scoring weights and thresholds for compatibility assessment. Supports
both O2 and H2 service profiles.

```sql
CREATE TABLE scoring_profiles (
    profile_id          VARCHAR(64) NOT NULL,
    version             VARCHAR(32) NOT NULL,
    gas_type            VARCHAR(8),
    -- "H2", "O2", or NULL for general

    -- Configuration
    weights_json        JSONB NOT NULL,
    -- {property_key: weight} e.g., {"flammability_rating": 0.40, ...}

    thresholds_json     JSONB NOT NULL,
    -- {"compatible": 0.75, "marginal": 0.50}

    hard_rules_json     JSONB,
    -- {"flammability_rating_reject": ["D", "X", "U"]}

    family_bonus_json   JSONB,
    -- {"austenitic_stainless": 0.10}

    -- Confidence penalty weights (v4 BuildSpec Table 3)
    penalty_config_json JSONB,
    -- {
    --   "unknown_env_per_field": 0.08,
    --   "staleness_per_tier": 0.05,
    --   "sparse_evidence_max": 0.20,
    --   "dirty_data_max": 0.25,
    --   "heritage_conflict": 0.15,
    --   "safety_pass_threshold": 0.85,
    --   "general_pass_threshold": 0.70,
    --   "refuse_threshold": 0.50
    -- }

    -- Provenance
    provenance          TEXT NOT NULL,
    effective_from      TIMESTAMP NOT NULL,
    effective_to        TIMESTAMP,

    PRIMARY KEY (profile_id, version)
);

CREATE INDEX idx_sp_active ON scoring_profiles(gas_type, effective_from, effective_to);
CREATE INDEX idx_sp_profile ON scoring_profiles(profile_id);
```

---

### 3.15 `safety_context_rules` -- Safety Context Detection Configuration

Externalizes the safety context detection thresholds from BuildSpec Table 6
into a configurable table.

```sql
CREATE TABLE safety_context_rules (
    rule_id             VARCHAR(64) PRIMARY KEY,

    safety_context      VARCHAR(32) NOT NULL,
    -- "oxygen", "hydrogen", "cryogenic", "high_pressure"

    -- Detection thresholds
    o2_pct_threshold    FLOAT,
    -- >= this value triggers oxygen context (23.5%)

    temperature_c_threshold FLOAT,
    -- < this value triggers cryogenic context (-73.3C)

    pressure_kpa_threshold FLOAT,
    -- > this value triggers high_pressure context (20684 kPa)

    keyword_patterns    TEXT[],
    -- Regex patterns for query text detection
    -- e.g., {"\\bLOX\\b", "\\bGOX\\b", "\\bOXYGEN\\b"}

    fluid_keywords      TEXT[],
    -- Fluid medium keywords: {"LOX", "GOX", "LIQUID OXYGEN", ...}

    -- Required fields when this context is detected (BuildSpec Table 6)
    required_fields     TEXT[] NOT NULL,
    -- e.g., {"o2_pct", "pressure_kpa", "fluid_medium", "temperature_c"}

    is_active           BOOLEAN DEFAULT TRUE,
    version             VARCHAR(32) DEFAULT '1.0.0'
);

CREATE INDEX idx_scr_context ON safety_context_rules(safety_context);
CREATE INDEX idx_scr_active ON safety_context_rules(is_active);
```

---

### 3.16 `faiss_index_registry` -- FAISS Index Mapping

Maps FAISS vector IDs to database record IDs. FAISS is secondary in v4
(heritage validation + MUA precedent search only).

```sql
CREATE TABLE faiss_index_registry (
    faiss_id            INTEGER NOT NULL,
    record_id           VARCHAR(128) NOT NULL,
    -- May point to test_evidence.evidence_id, mua_precedents.mua_id,
    -- or environment_envelopes.envelope_id depending on index_name.

    index_name          VARCHAR(64) NOT NULL,
    -- "h2_bok_v3", "o2_bok_v2", "mua_precedents_v2", "heritage_v1"

    embedding_model     VARCHAR(128),
    -- "text-embedding-3-small", "nomic-embed-text-v1.5", etc.

    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (faiss_id, index_name)
);

CREATE INDEX idx_faiss_record ON faiss_index_registry(record_id);
CREATE INDEX idx_faiss_index ON faiss_index_registry(index_name);
```

---

## 4. Key Relationships and Indexes

### 4.1 Index Strategy Summary

| Query Pattern                             | Indexes Used                              |
|-------------------------------------------|-------------------------------------------|
| Material by designation                   | `idx_material_designation`                |
| Material by UNS number                    | `idx_material_uns`                        |
| Material by alias name                    | `idx_alias_name`, `idx_alias_name_lower`  |
| Material by family class                  | `idx_family_class` + `idx_material_family`|
| Conditions by heat treatment              | `idx_condition_heat_treat`                |
| Conditions by product form                | `idx_condition_form`                      |
| Environment envelopes by safety context   | `idx_envelope_safety`                     |
| Environment overlap (temp+pressure range) | `idx_envelope_temp`, `idx_envelope_pressure` |
| Test evidence by type + condition         | `idx_evidence_condition_type`             |
| Test evidence by year (staleness)         | `idx_evidence_year`                       |
| Test evidence dirty data                  | `idx_evidence_dirty`                      |
| Heritage failures by environment match    | `idx_hf_temp`, `idx_hf_pressure`, `idx_hf_fluid` |
| MUA precedents by determination           | `idx_mua_determination`                   |
| Decision lineage by query hash            | `idx_dll_query_hash`                      |
| Decision lineage by date range            | `idx_dll_created`                         |

### 4.2 Referential Integrity Cascade Rules

| Parent -> Child                             | ON DELETE    | Rationale                               |
|---------------------------------------------|--------------|-----------------------------------------|
| material_families -> materials              | RESTRICT     | Cannot delete family with materials     |
| materials -> material_conditions            | CASCADE      | Conditions belong to material           |
| materials -> material_aliases               | CASCADE      | Aliases belong to material              |
| material_conditions -> environment_envelopes| CASCADE      | Envelopes belong to condition           |
| material_conditions -> test_evidence        | CASCADE      | Evidence belongs to condition           |
| material_conditions -> heritage_failures    | SET NULL     | Keep failure record even if condition removed |
| materials -> heritage_failures              | CASCADE      | Failures belong to material             |
| test_evidence -> test_evidence_results      | CASCADE      | Results belong to evidence              |
| mua_precedents -> mua_precedent_materials   | CASCADE      | Junction cleanup                        |
| materials -> mua_precedent_materials        | CASCADE      | Junction cleanup                        |
| heritage_failures -> heritage_overrides     | RESTRICT     | Cannot delete failure with overrides    |

---

## 5. Migration Strategy from Legacy MAPTIS Schema

### 5.1 Migration Overview

The migration from the legacy MAPTIS PostgreSQL schema to the new Granta MI
schema proceeds in seven phases. Each phase is independently verifiable and
rollback-safe.

```
Phase 1: Classify material families (resolve 5,225 NULLs)
Phase 2: Build material hierarchy (deduplicate INCONEL 718 variants)
Phase 3: Convert units to canonical (F->C, psia->kPa, psi->MPa)
Phase 4: Unify test evidence (13 table pairs -> 1)
Phase 5: Build environment envelopes (from test conditions)
Phase 6: Migrate MUA precedents with material linkage
Phase 7: Import heritage failures and build lineage infrastructure
```

### 5.2 Phase 1: Material Family Classification

**Input:** `materials.material_type_name` (Polymer, Metal, NULL, Adhesive, etc.)
and `materials.designation` text.

**Strategy:**

1. Map `material_type_name` to `family_class`:
   - "Polymer" -> "polymer"
   - "Metal" -> "metal"
   - "Adhesive" -> "adhesive"
   - "Coating" -> "coating"
   - "Composite" -> "composite"
   - "Foam" -> "foam"
   - "Thermal Protection" -> "thermal_protection"
   - "Minerals" -> "mineral"

2. For the 5,225 NULL-type materials, use the existing
   `material_name_normalizer.py` and alloy-pattern regexes to classify:
   - Materials matching metal alloy patterns (e.g., "XXX-XXX", "UNS X#####")
     -> "metal"
   - Materials matching polymer patterns (e.g., "-silicone-", "PTFE", "Kel-F")
     -> "polymer"
   - Remaining: flag as "UNKNOWN" for manual review.

3. Assign `family_id` values by matching `designation` against known family
   patterns:
   - "316L", "304", "321" -> `austenitic_stainless`
   - "INCONEL", "718", "625" -> `nickel_superalloy`
   - "6061", "7075", "2024" -> `aluminum_alloy`
   - "PTFE", "Teflon", "Kel-F" -> `fluoropolymer`

4. **Validation gate:** All 31,531 materials must have a non-NULL `family_id`
   before proceeding. Materials that cannot be classified are assigned
   `family_id = "UNKNOWN"` and flagged for manual review.

### 5.3 Phase 2: Material Hierarchy Construction

**Input:** 31,531 flat material rows, many duplicates (e.g., 60+ INCONEL 718
variants differing only in condition).

**Strategy:**

1. Group by `designation` after normalization (strip whitespace, normalize
   case, resolve common aliases via `material_aliases`).

2. For each group, create ONE `materials` row with the canonical designation.

3. Create `material_conditions` rows for each unique
   (heat_treatment, product_form, weld_state) combination within the group.

4. Preserve `legacy_material_key` on each `materials` row for backward
   compatibility.

5. **Estimated reduction:** ~31,531 flat rows -> ~12,000 materials + ~25,000
   conditions (many variants share a base material).

### 5.4 Phase 3: Unit Conversion

**Conversion rules applied to all migrated data:**

```python
# Temperature: Fahrenheit -> Celsius
celsius = (fahrenheit - 32) * 5 / 9

# Pressure: psia -> kPa
kpa = psia * 6.89476

# Stress: psi -> MPa
mpa_from_psi = psi / 145.038
mpa_from_ksi = ksi * 6.89476

# Toughness: ksi*sqrt(in) -> MPa*sqrt(m)
mpa_root_m = ksi_root_in * 1.0989

# Energy: ft-lbs -> J
joules = ft_lbs * 1.35582
```

**Critical:** Original values are preserved in `raw_values` JSONB column on
every converted record. The `dirty_flag` is set to TRUE for any record where
the original value was ambiguous or potentially mistyped.

### 5.5 Phase 4: Test Evidence Unification

**Input:** 13 test table pairs with ~210,000 total test rows and ~210,000
result rows.

**Mapping:**

| Legacy Table                    | test_type              | Result Fields                    |
|---------------------------------|------------------------|----------------------------------|
| flammability_tests              | flammability           | rating, burn_length, ignition_energy |
| flammability_test_results       | (child rows)           | per-sample results               |
| mechanical_impact_tests         | mechanical_impact      | impact_energy_j, pass_fail       |
| mechanical_impact_results       | (child rows)           | per-sample results               |
| tvs_outgassing_tests            | tvs_outgassing         | tml_pct, cvcm_pct, wvr_pct      |
| tvs_test_results                | (child rows)           | per-sample results               |
| toxicity_tests                  | toxicity               | toxicity_class                   |
| toxicity_gas_results            | (child rows)           | gas_species, concentration       |
| corrosion_tests                 | corrosion              | corrosion_rate, pitting_depth    |
| fluid_compatibility_tests       | fluid_compatibility    | compatibility_rating             |
| tensile_strength_tests          | tensile_strength       | uts, yield, elongation           |
| tensile_strength_results        | (child rows)           | per-sample results               |
| high_cycle_fatigue_tests        | high_cycle_fatigue     | cycles, stress_amplitude         |
| hcf_test_results                | (child rows)           | per-sample results               |
| promoted_combustion_tests       | promoted_combustion    | ignition_result                  |
| promoted_combustion_results     | (child rows)           | per-sample results               |
| pneumatic_impact_tests          | pneumatic_impact       | impact_energy_j                  |
| pneumatic_impact_results        | (child rows)           | per-sample results               |
| arc_tracking_tests              | arc_tracking           | tracking_result                  |
| arc_tracking_results            | (child rows)           | per-sample results               |
| vcm_optical_tests               | vcm_optical            | optical_result                   |
| vcm_optical_results             | (child rows)           | per-sample results               |

**Process:**

1. For each legacy test row, create one `test_evidence` row with:
   - `condition_id` resolved from `material_code` -> `material_key` ->
     `material_id` -> default condition.
   - `test_type` from the mapping table above.
   - Environment fields converted to canonical units.
   - Primary result in `result_value` / `result_text`.
   - Type-specific secondary results in `secondary_results` JSONB.
   - `legacy_test_table` and `legacy_test_id` preserved.

2. For each legacy result row, create one `test_evidence_results` row linked
   to the parent `test_evidence` row.

3. **test_year extraction:** Parse `test_date` where available. For records
   from `silver_report_rows`, extract year from contract date or report date.

### 5.6 Phase 5: Environment Envelope Construction

**Input:** Test evidence rows with environment conditions, plus BOK records
from the existing `compatibility_records` table.

**Strategy:**

1. For each `material_condition`, aggregate all test evidence rows to determine
   the tested envelope:
   - `temp_min_c` = MIN(test_temperature_c) across all tests
   - `temp_max_c` = MAX(test_temperature_c) across all tests
   - `pressure_min_kpa` = MIN(test_pressure_kpa) across all tests
   - `pressure_max_kpa` = MAX(test_pressure_kpa) across all tests

2. For H2/O2 BOK records from the existing `knowledge_twins.compatibility_records`
   table:
   - Convert `temp_min_f` / `temp_max_f` to Celsius.
   - Convert `pressure_min_psia` / `pressure_max_psia` to kPa.
   - Map `gas_type` and `compatibility` directly.
   - Preserve `standard_ref` and `source`.

3. Create `environment_envelopes` rows for each unique (condition, gas_type)
   combination.

### 5.7 Phase 6: MUA Precedent Migration

**Input:** `mua_precedents` table (6,181 rows) in legacy schema.

**Strategy:**

1. Create `mua_precedents` rows with structured fields extracted from the
   legacy `rationale` text (using the existing `mua_parser_v6.py`).

2. Resolve material linkage via `mua_precedent_materials` junction table:
   - Parse material references from MUA rationale text.
   - Match against `materials.designation` and `material_aliases.alias_name`.

3. Convert any temperature/pressure values to canonical units.

### 5.8 Phase 7: Heritage Failures and Lineage Infrastructure

1. Migrate existing `heritage_failures` records with unit conversion.
2. Create initial `schema_versions` entry with the v4 schema definition.
3. Create initial `scoring_profiles` entries (copy from existing
   `scoring_profile_config` with unit conversions).
4. Create `safety_context_rules` entries per BuildSpec Table 6.
5. Verify `decision_lineage_log` table is empty and ready to receive.

### 5.9 Migration Validation Gates

After each phase, run validation:

| Phase | Validation                                            | Pass Criteria          |
|-------|-------------------------------------------------------|------------------------|
| 1     | All materials have family_id                         | 0 NULL family_id       |
| 2     | All conditions link to valid material                | FK integrity passes    |
| 3     | Spot-check 100 converted values against known values | < 0.1% conversion error|
| 4     | Row counts: SUM(test_evidence) >= legacy test count  | No data loss           |
| 5     | Each H2/O2 BOK record has an envelope                | BOK coverage >= 95%    |
| 6     | MUA material linkage rate                            | >= 80% linked          |
| 7     | Heritage failure count matches legacy                | Exact match            |

---

## 6. How Each v4 Module Queries This Schema

### 6.1 Confidence Calculator (`mira_v4/confidence.py`)

The ConfidenceCalculator needs five inputs from the schema:

**1. Unknown environment penalty:**
```sql
-- Count how many environment fields are specified in the query.
-- The caller (Python) checks query.environment.count_missing_fields().
-- No direct DB query needed -- this is a property of the user's query.
```

**2. Staleness penalty (test_year):**
```sql
-- Get median test year for a material condition's evidence.
SELECT test_year
FROM test_evidence
WHERE condition_id = :condition_id
  AND is_valid = TRUE
  AND test_year IS NOT NULL
ORDER BY test_year;
-- Python computes median and staleness tier.
```

**3. Sparse evidence penalty (evidence count):**
```sql
-- Count evidence rows for a material condition.
SELECT COUNT(*) AS evidence_count
FROM test_evidence
WHERE condition_id = :condition_id
  AND is_valid = TRUE;
```

**4. Dirty data penalty (dirty fraction):**
```sql
-- Count dirty vs total evidence rows.
SELECT
    COUNT(*) AS total_records,
    SUM(CASE WHEN dirty_flag THEN 1 ELSE 0 END) AS dirty_records
FROM test_evidence
WHERE condition_id = :condition_id
  AND is_valid = TRUE;
-- Python computes dirty_fraction = dirty_records / total_records.
```

**5. Heritage conflict penalty:**
```sql
-- Check for heritage failures matching the query environment.
-- See Heritage Veto Engine section (6.4) below.
```

### 6.2 Dirty Data Classifier (`mira_v4/granta_client.py`)

```sql
-- Retrieve evidence rows with dirty data annotations.
SELECT
    evidence_id AS record_id,
    data_source AS source,
    data_class,
    dirty_flag,
    dirty_fields,
    raw_values,
    test_year
FROM test_evidence
WHERE condition_id = :condition_id
  AND is_valid = TRUE
ORDER BY test_year DESC NULLS LAST;
-- Each row maps directly to an EvidenceRow Pydantic model.
```

### 6.3 Batch Safety Gate (`mira_v4/batch_safety.py`)

The BatchSafetyGate does not query the database directly. It operates on
the `ParsedQuery.environment` and `ParsedQuery.safety_context` fields.

Safety context detection uses the `safety_context_rules` table:

```sql
-- Load active safety context rules at startup.
SELECT
    safety_context,
    o2_pct_threshold,
    temperature_c_threshold,
    pressure_kpa_threshold,
    keyword_patterns,
    fluid_keywords,
    required_fields
FROM safety_context_rules
WHERE is_active = TRUE;
```

### 6.4 Heritage Veto Engine (`mira_v4/heritage_veto.py`)

The HeritageVetoEngine performs envelope matching against heritage failures:

```sql
-- Step 1: Get heritage failures for the target material.
SELECT
    failure_id,
    material_id,
    failure_temperature_c,
    failure_pressure_kpa,
    failure_fluid_medium,
    failure_description,
    severity,
    safety_context
FROM heritage_failures
WHERE material_id = :material_id
  AND is_active = TRUE;
```

Python then runs `EnvelopeMatcher.match_envelope()` on each failure record
against the query environment. All three dimensions (temperature, pressure,
media) must overlap for a veto match.

### 6.5 Provenance Calculator (`mira_v4/provenance.py`)

The ProvenanceCalculator does not query the database. It operates on the
filter dictionary and record IDs produced by Granta API queries.

The `schema_version` input comes from:

```sql
-- Get active schema version.
SELECT version_id
FROM schema_versions
WHERE is_active = TRUE;
```

### 6.6 Schema Validation (`mira_v4/schema_validation.py`)

The SchemaValidator compares the expected schema against live Granta metadata:

```sql
-- Load expected schema from schema_versions.
SELECT schema_definition
FROM schema_versions
WHERE is_active = TRUE;
-- Returns JSONB: {field_name: field_type, ...}
```

The live schema is obtained from the Granta MI Python SDK
(`granta_client.get_schema()`) and compared against the expected dictionary.

### 6.7 Decision Lineage Builder (`mira_v4/decision_lineage.py`)

After assembly, the DecisionLineage artifact is persisted:

```sql
-- Insert the immutable lineage record.
INSERT INTO decision_lineage_log (
    lineage_id, query_hash, snapshot_hash,
    lineage_json,
    safety_context, gate_action, confidence_score,
    dirty_data_tier, heritage_vetoed, batch_mode,
    schema_version
) VALUES (
    :lineage_id, :query_hash, :snapshot_hash,
    :lineage_json,
    :safety_context, :gate_action, :confidence_score,
    :dirty_data_tier, :heritage_vetoed, :batch_mode,
    :schema_version
);
```

### 6.8 Material Search (Granta API Primary Path)

The primary material lookup path in v4 uses typed Granta API filters:

```sql
-- Example: Find austenitic stainless steels with UTS > 500 MPa,
-- tested in oxygen service, temperature range -200C to 400C.
SELECT
    m.material_id,
    m.designation,
    m.specification,
    m.uns_number,
    mf.family_name,
    mc.condition_id,
    mc.condition_label,
    mc.heat_treat_condition,
    mc.product_form,
    mc.uts_mpa,
    mc.yield_strength_mpa,
    ee.compatibility,
    ee.temp_min_c,
    ee.temp_max_c,
    ee.pressure_min_kpa,
    ee.pressure_max_kpa
FROM materials m
JOIN material_families mf ON m.family_id = mf.family_id
JOIN material_conditions mc ON m.material_id = mc.material_id
LEFT JOIN environment_envelopes ee ON mc.condition_id = ee.condition_id
WHERE mf.family_id = 'austenitic_stainless'
  AND mc.uts_mpa > 500
  AND ee.safety_context = 'oxygen'
  AND ee.temp_min_c <= -200
  AND ee.temp_max_c >= 400
  AND m.is_active = TRUE
ORDER BY mc.uts_mpa DESC;
```

### 6.9 H2/O2 Knowledge Twins Compatibility Query

```sql
-- Full compatibility query for hydrogen service.
SELECT
    m.material_id,
    m.designation,
    mf.family_name,
    mf.h2_susceptibility_class,
    mc.condition_id,
    mc.condition_label,
    mc.heat_treat_condition,
    mc.product_form,
    mc.yield_strength_mpa,
    mc.uts_mpa,
    ee.compatibility,
    ee.compatibility_reason,
    ee.mitigation,
    ee.temp_min_c,
    ee.temp_max_c,
    ee.pressure_min_kpa,
    ee.pressure_max_kpa,
    ee.phase,
    ee.standard_ref,
    ee.data_class,
    ee.confidence
FROM materials m
JOIN material_families mf ON m.family_id = mf.family_id
JOIN material_conditions mc ON m.material_id = mc.material_id
JOIN environment_envelopes ee ON mc.condition_id = ee.condition_id
WHERE ee.gas_type = 'H2'
  AND ee.safety_context = 'hydrogen'
  AND m.is_active = TRUE
  -- Envelope overlap: query environment within material envelope
  AND (ee.temp_min_c IS NULL OR ee.temp_min_c <= :query_temp_c)
  AND (ee.temp_max_c IS NULL OR ee.temp_max_c >= :query_temp_c)
  AND (ee.pressure_min_kpa IS NULL OR ee.pressure_min_kpa <= :query_pressure_kpa)
  AND (ee.pressure_max_kpa IS NULL OR ee.pressure_max_kpa >= :query_pressure_kpa)
ORDER BY ee.compatibility ASC, ee.confidence DESC;
```

### 6.10 MUA Precedent Lookup

```sql
-- Find MUA precedents for a specific material.
SELECT
    mp.mua_id,
    mp.determination,
    mp.rationale,
    mp.safety_context,
    mp.temperature_c,
    mp.pressure_kpa,
    mp.fluid_medium,
    mp.test_reports_cited,
    mp.standard_references,
    mp.mua_date,
    mp.program
FROM mua_precedents mp
JOIN mua_precedent_materials mpm ON mp.mua_id = mpm.mua_id
WHERE mpm.material_id = :material_id
  AND mpm.role = 'subject'
ORDER BY mp.mua_date DESC NULLS LAST;
```

---

## 7. Views

### 7.1 Active Material Catalog

```sql
CREATE OR REPLACE VIEW v_active_materials AS
SELECT
    m.material_id,
    m.designation,
    m.specification,
    m.uns_number,
    mf.family_id,
    mf.family_name,
    mf.family_class,
    mf.h2_susceptibility_class,
    mf.o2_default_compatibility,
    COUNT(DISTINCT mc.condition_id) AS condition_count,
    COUNT(DISTINCT te.evidence_id) AS evidence_count,
    MIN(te.test_year) AS earliest_test_year,
    MAX(te.test_year) AS latest_test_year
FROM materials m
JOIN material_families mf ON m.family_id = mf.family_id
LEFT JOIN material_conditions mc ON m.material_id = mc.material_id
LEFT JOIN test_evidence te ON mc.condition_id = te.condition_id
    AND te.is_valid = TRUE
WHERE m.is_active = TRUE
GROUP BY m.material_id, m.designation, m.specification, m.uns_number,
         mf.family_id, mf.family_name, mf.family_class,
         mf.h2_susceptibility_class, mf.o2_default_compatibility;
```

### 7.2 Material Dirty Data Summary

```sql
CREATE OR REPLACE VIEW v_dirty_data_summary AS
SELECT
    mc.material_id,
    m.designation,
    mc.condition_id,
    mc.condition_label,
    COUNT(*) AS total_evidence,
    SUM(CASE WHEN te.dirty_flag THEN 1 ELSE 0 END) AS dirty_count,
    ROUND(
        SUM(CASE WHEN te.dirty_flag THEN 1 ELSE 0 END)::NUMERIC
        / NULLIF(COUNT(*), 0), 4
    ) AS dirty_fraction,
    CASE
        WHEN SUM(CASE WHEN te.dirty_flag THEN 1 ELSE 0 END)::NUMERIC
             / NULLIF(COUNT(*), 0) <= 0.10 THEN 'CLEAN'
        WHEN SUM(CASE WHEN te.dirty_flag THEN 1 ELSE 0 END)::NUMERIC
             / NULLIF(COUNT(*), 0) <= 0.30 THEN 'DEGRADED'
        ELSE 'REFUSE'
    END AS dirty_tier
FROM material_conditions mc
JOIN materials m ON mc.material_id = m.material_id
LEFT JOIN test_evidence te ON mc.condition_id = te.condition_id
    AND te.is_valid = TRUE
GROUP BY mc.material_id, m.designation, mc.condition_id, mc.condition_label;
```

### 7.3 Heritage Veto Candidates

```sql
CREATE OR REPLACE VIEW v_heritage_veto_candidates AS
SELECT
    hf.failure_id,
    hf.material_id,
    m.designation,
    hf.failure_temperature_c,
    hf.failure_pressure_kpa,
    hf.failure_fluid_medium,
    hf.failure_description,
    hf.severity,
    hf.safety_context,
    hf.incident_year,
    COUNT(ho.override_id) AS override_count
FROM heritage_failures hf
JOIN materials m ON hf.material_id = m.material_id
LEFT JOIN heritage_overrides ho ON hf.failure_id = ho.failure_id
WHERE hf.is_active = TRUE
GROUP BY hf.failure_id, hf.material_id, m.designation,
         hf.failure_temperature_c, hf.failure_pressure_kpa,
         hf.failure_fluid_medium, hf.failure_description,
         hf.severity, hf.safety_context, hf.incident_year;
```

---

## 8. Schema Dictionary (v4 Translation Layer)

The Schema Dictionary is the deterministic mapping layer between engineer
vocabulary and database field names. It is stored in `schema_versions` and
loaded at MIRA startup.

### 8.1 Property Aliases

```json
{
    "stiffness": "youngs_modulus_gpa",
    "strength": "uts_mpa",
    "tensile strength": "uts_mpa",
    "ultimate tensile strength": "uts_mpa",
    "yield strength": "yield_strength_mpa",
    "yield": "yield_strength_mpa",
    "elongation": "elongation_pct",
    "ductility": "elongation_pct",
    "hardness": "hardness_hrc",
    "density": "density_g_cm3",
    "toughness": "fracture_toughness_mpa_root_m",
    "flammability": "rating_flammability",
    "outgassing": "rating_outgassing",
    "corrosion resistance": "rating_corrosion",
    "stress corrosion": "rating_scc"
}
```

### 8.2 Environment Aliases

```json
{
    "LOX": {"fluid_medium": "LOX", "gas_type": "O2", "phase": "liquid", "safety_context": "oxygen"},
    "GOX": {"fluid_medium": "GOX", "gas_type": "O2", "phase": "gaseous", "safety_context": "oxygen"},
    "LH2": {"fluid_medium": "LH2", "gas_type": "H2", "phase": "liquid", "safety_context": "hydrogen"},
    "GH2": {"fluid_medium": "GH2", "gas_type": "H2", "phase": "gaseous", "safety_context": "hydrogen"},
    "oxygen service": {"gas_type": "O2", "safety_context": "oxygen"},
    "hydrogen service": {"gas_type": "H2", "safety_context": "hydrogen"},
    "cryogenic": {"safety_context": "cryogenic"},
    "high pressure": {"safety_context": "high_pressure"}
}
```

### 8.3 Unit Conversions

```json
{
    "F_to_C": {"factor": 0.5556, "offset": -17.7778, "formula": "(F - 32) * 5/9"},
    "psia_to_kPa": {"factor": 6.89476, "offset": 0},
    "psi_to_MPa": {"factor": 0.00689476, "offset": 0},
    "ksi_to_MPa": {"factor": 6.89476, "offset": 0},
    "ksi_root_in_to_MPa_root_m": {"factor": 1.0989, "offset": 0},
    "ft_lbs_to_J": {"factor": 1.35582, "offset": 0},
    "in_to_mm": {"factor": 25.4, "offset": 0}
}
```

---

## 9. Data Quality Framework

### 9.1 Dirty Data Detection Rules

A record is flagged `dirty_flag = TRUE` if any of the following conditions
are met:

| Rule                          | Field(s) Affected              | Example                     |
|-------------------------------|--------------------------------|-----------------------------|
| Non-numeric in numeric field  | result_value, test_temperature_c | "N/A", ">1000", "~25"    |
| Unit ambiguity                | result_unit                    | "psi" where "psia" expected |
| Missing required field        | test_type, condition_id        | NULL test_type              |
| Out-of-range value            | test_temperature_c             | 99999 C                     |
| Duplicate record              | evidence_id                    | Same test ingested twice    |
| Legacy code mismatch          | material_code vs material_key  | FK resolution failure       |

### 9.2 Dirty Data Tier Classification

Per BuildSpec Section 3.2:

| Tier      | Dirty Fraction | Action                                    |
|-----------|----------------|-------------------------------------------|
| CLEAN     | 0% - 10%       | Proceed normally                          |
| DEGRADED  | 11% - 30%      | Proceed with user warning                 |
| REFUSE    | > 30%          | Refuse for affected property; manual review |

### 9.3 Raw Value Preservation

The `raw_values` JSONB column on `test_evidence` preserves ALL original
values before any unit conversion, normalization, or cleaning. This column
is NEVER modified after initial insertion.

Example:
```json
{
    "temperature_f": 450,
    "pressure_psia": 3000,
    "result_psi": 125000,
    "original_rating": "B-1"
}
```

---

## 10. Security and Access Control

### 10.1 Table Permissions

| Role            | materials | test_evidence | heritage_failures | decision_lineage_log | heritage_overrides |
|-----------------|-----------|---------------|-------------------|---------------------|--------------------|
| mira_reader     | SELECT    | SELECT        | SELECT            | SELECT              | SELECT             |
| mira_writer     | SELECT,INSERT,UPDATE | SELECT,INSERT,UPDATE | SELECT,INSERT,UPDATE | INSERT ONLY | INSERT ONLY |
| mira_admin      | ALL       | ALL           | ALL               | ALL                 | INSERT ONLY        |

**Critical constraints:**
- `decision_lineage_log`: INSERT ONLY (no UPDATE, no DELETE).
- `heritage_overrides`: INSERT ONLY (no UPDATE, no DELETE).
- These constraints are enforced at both the database level (REVOKE) and the
  application level (Pydantic `frozen=True`).

### 10.2 ITAR/Export Control

All material property data in this schema is potentially ITAR-controlled.
The database must be hosted in a FedRAMP-compliant environment. No data
export endpoints should be exposed without ITAR review.

---

## 11. Granta MI-Specific Implementation Notes

### 11.1 Granta MI Table Structure

| Granta MI Table        | PostgreSQL Table           | Link Type          |
|------------------------|----------------------------|--------------------|
| Material Families      | material_families          | Standalone         |
| Materials              | materials                  | Link to Families   |
| Material Aliases       | material_aliases           | Tabular on Materials |
| Material Conditions    | material_conditions        | Link to Materials  |
| Environment Envelopes  | environment_envelopes      | Link to Conditions |
| Test Evidence          | test_evidence              | Link to Conditions |
| Heritage Failures      | heritage_failures          | Link to Materials + Conditions |
| MUA Precedents         | mua_precedents             | Cross-link to Materials (N:M) |

### 11.2 Granta MI Attribute Types

| Column Type     | Granta MI Attribute Type | Notes                        |
|-----------------|--------------------------|------------------------------|
| VARCHAR         | Short Text               | < 256 chars                  |
| TEXT            | Long Text                | > 256 chars                  |
| FLOAT           | Point                    | Single numeric value         |
| FLOAT pair      | Range                    | Min/max pairs                |
| INTEGER         | Integer                  |                              |
| BOOLEAN         | Discrete (Yes/No)        |                              |
| VARCHAR (enum)  | Discrete                 | Controlled vocabulary        |
| JSONB           | File (JSON)              | Complex nested data          |
| TEXT[]          | Multi-value Short Text   | Arrays of strings            |
| DATE/TIMESTAMP  | Date/Time                |                              |

### 11.3 Granta MI API Query Mapping

The Granta MI Python SDK (`ansys.grantami.serverapi_openapi`) supports:

- **Criteria queries:** Map directly to WHERE clauses on Point/Range/Discrete
  attributes.
- **Cross-table links:** Follow relationships between tables (e.g., Materials
  -> Conditions -> Evidence).
- **Bulk export:** For batch operations (MIUL enrichment, M&P plan generation).

The `granta_client.py` module translates `ParsedQuery` filter objects into
Granta API criteria and assembles `EvidenceRow` results from the response.

---

## 12. Open Questions

| # | Question | Impact | Owner |
|---|----------|--------|-------|
| 1 | Can we create custom Granta MI extension attributes, or must we use NCAPS predefined schema? | Schema field names may differ from this plan | Dude / Granta admin |
| 2 | What is the Granta MI API latency for a single material lookup with 3+ linked tables? | May need read-through cache layer | Performance testing |
| 3 | Does Granta MI support partial-text search on Short Text attributes (LIKE/ILIKE)? | Alias search may need FAISS fallback | Granta SDK evaluation |
| 4 | What is the maximum JSONB size for File attributes in Granta MI? | Affects secondary_results storage | Granta documentation |
| 5 | Can Granta MI enforce INSERT-ONLY on specific tables? | heritage_overrides and lineage immutability | Granta admin |
| 6 | ITAR hosting path: NASA-hosted Granta MI instance or GovCloud? | Entire deployment model | Program management |

---

## 13. Appendix: Legacy-to-New Column Mapping

### 13.1 materials (legacy) -> materials + material_conditions (new)

| Legacy Column       | New Table            | New Column              | Conversion      |
|---------------------|----------------------|-------------------------|-----------------|
| material_key        | materials            | legacy_material_key     | Direct copy     |
| material_code       | materials            | legacy_material_code    | Direct copy     |
| designation         | materials            | designation             | Direct copy     |
| composition         | material_conditions  | composition_summary (free text) | Direct copy |
| use_type            | material_conditions  | condition_label         | Direct copy     |
| use_temp_min_f      | environment_envelopes| temp_min_c              | (F-32)*5/9      |
| use_temp_max_f      | environment_envelopes| temp_max_c              | (F-32)*5/9      |
| source              | materials            | data_source             | Direct copy     |
| material_type_key   | material_families    | maptis_type_key         | FK resolution   |
| material_type_name  | material_families    | family_class            | Enum mapping    |

### 13.2 flammability_tests (legacy) -> test_evidence (new)

| Legacy Column       | New Column              | Conversion              |
|---------------------|-------------------------|-------------------------|
| test_id (PK)        | legacy_test_id          | Direct copy             |
| material_code (FK)  | condition_id            | Resolved via material_key |
| test_temp_f         | test_temperature_c      | (F-32)*5/9              |
| test_pressure_psia  | test_pressure_kpa       | psia * 6.89476          |
| test_date           | test_date, test_year    | Direct + extract year   |
| result_rating       | result_text             | Direct copy             |
| (table name)        | test_type               | "flammability"          |
| (table name)        | legacy_test_table       | "flammability_tests"    |

### 13.3 silver_report_rows (legacy) -> test_evidence (new)

The 130,844 silver_report_rows are normalized into `test_evidence` with:
- `data_source = 'MAPTIS'`
- `data_class = 'direct_test'` (when test data present) or `'derived'`
- `test_report_id` from the contract/report identifier
- All temperatures/pressures converted to canonical units
- `dirty_flag` set based on field quality analysis

---

## 14. Revision History

| Version | Date       | Author        | Changes                    |
|---------|------------|---------------|----------------------------|
| 1.0.0   | 2026-02-05 | Beth / Dr. Wilde | Initial schema plan      |
