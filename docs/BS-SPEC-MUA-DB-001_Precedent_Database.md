# BS-SPEC-MUA-DB-001: MUA Precedent Database

**BoundState Technologies — MIRA Platform**
**Classification:** BoundState Proprietary
**Version:** 1.0.0 DRAFT
**Date:** 2026-02-28

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True

---

## 1. Why This Database Exists

The V10 classifier is a deterministic state machine. It computes the right answer
from first principles every time. But "I computed this" doesn't close MUAs —
"I computed this AND 47 prior approved MUAs for the same scenario agree" does.

8,000+ historic MUAs represent 40 years of NASA engineering judgment, encoded in
signed documents. This database turns that judgment into queryable precedent.

### What it enables for V10

| Capability | Without DB | With DB |
|-----------|-----------|---------|
| Classification | ✅ Pure logic | ✅ Pure logic (unchanged) |
| Confidence score | Static per-type (0.70-0.95) | Dynamic: base + precedent weight |
| Rationale text | Template-generated | Template + "consistent with N prior approvals" |
| Precedent citation | None | "See MUA-2019-0847, MUA-2021-1203" |
| Human-required triage | "Route to engineer" | "Route to engineer. 12 prior MUAs for this scenario, 11 approved Cat I" |
| Anomaly detection | None | "WARNING: No precedent exists for CORR=U in LH2 for this alloy family" |
| Rationale quality | Good templates | Templates enriched with real engineer language |

### What it does NOT do

- Does NOT change classification logic. The classifier is deterministic. Period.
- Does NOT override safety decisions. Precedent informs, never decides.
- Does NOT require the DB to function. V10 runs without it. DB adds richness.

---

## 2. Schema Design

One schema, three tables, two views. Intentionally flat.

### 2.1 Schema: `mua_precedent`

```sql
CREATE SCHEMA IF NOT EXISTS mua_precedent;
```

### 2.2 Table: `mua_records`

The core table. One row per historic MUA. Every field maps to something
the V10 classifier either produces or consumes.

```sql
CREATE TABLE mua_precedent.mua_records (
    -- Identity
    id              SERIAL PRIMARY KEY,
    mua_number      TEXT NOT NULL,               -- e.g., "MUA-2019-0847"
    source_hash     TEXT UNIQUE NOT NULL,         -- SHA-256 of source JSON, dedup key

    -- Material (what)
    maptis_code     TEXT NOT NULL,                -- MAPTIS material code
    material_name   TEXT NOT NULL DEFAULT '',     -- human-readable designation
    material_class  TEXT NOT NULL DEFAULT 'metal',-- "metal" or "nonmetallic"
    alloy_family    TEXT DEFAULT '',              -- normalized: "austenitic_ss", "ni_superalloy", "al_alloy", "ti_alloy", etc.
    material_spec   TEXT DEFAULT '',              -- AMS/ASTM/MIL spec if captured

    -- Flag (why)
    issue           TEXT NOT NULL,                -- FLAM, FS, TOX, TVS, SCC, CORR
    rating          TEXT NOT NULL,                -- A, B, C, I, U, S, K, N, blank
    flag_type       TEXT DEFAULT '',              -- V10 FlagType if retroactively classified
    mua_type        TEXT DEFAULT '',              -- V10 MUAType if retroactively classified

    -- Environment (where)
    media           TEXT NOT NULL DEFAULT '',     -- raw media string: GH2, LH2, GOX, N2H4, etc.
    media_category  TEXT NOT NULL DEFAULT '',     -- normalized: "hydrogen", "oxygen", "propellant", "inert", "air", "other"
    environment     TEXT NOT NULL DEFAULT 'non-habitable',
    pressure        TEXT DEFAULT '',
    temperature     TEXT DEFAULT '',

    -- Outcome (what happened)
    category        TEXT DEFAULT '',              -- "I", "II", or empty
    disposition     TEXT DEFAULT '',              -- "Accepted", "Accepted with conditions", "Rejected", "Deferred"
    approved        BOOLEAN DEFAULT NULL,         -- TRUE = approved, FALSE = rejected, NULL = unknown
    approval_date   DATE DEFAULT NULL,

    -- Content (what they wrote)
    rationale_text  TEXT DEFAULT '',              -- full rationale from Form 551
    disposition_text TEXT DEFAULT '',             -- full disposition text
    application     TEXT DEFAULT '',              -- application description

    -- Context
    project         TEXT DEFAULT '',              -- DMLLV, SLS, ISS, Orion, etc.
    system          TEXT DEFAULT '',
    part_numbers    TEXT[] DEFAULT '{}',
    part_count      INTEGER DEFAULT 0,

    -- Provenance
    source_file     TEXT DEFAULT '',              -- original filename
    source_format   TEXT DEFAULT 'json',          -- json, docx, pdf
    parsed_date     TIMESTAMPTZ DEFAULT NOW(),
    confidence      NUMERIC(3,2) DEFAULT 0.0,    -- parse confidence (0-1)

    -- Housekeeping
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 2.3 Table: `mua_rationale_patterns`

Extracted rationale patterns from the 8K corpus. Not the full text —
the reusable structural patterns that real engineers used.

```sql
CREATE TABLE mua_precedent.mua_rationale_patterns (
    id              SERIAL PRIMARY KEY,
    pattern_key     TEXT UNIQUE NOT NULL,         -- e.g., "FLAM_C_hydrogen_metal_ANTI_RULE"

    -- Match criteria (what scenario does this pattern apply to)
    issue           TEXT NOT NULL,
    rating          TEXT NOT NULL,
    media_category  TEXT NOT NULL,
    material_class  TEXT NOT NULL,
    mua_type        TEXT NOT NULL,                -- V10 MUAType

    -- Pattern content
    rationale_template TEXT NOT NULL,             -- generalized rationale with {placeholders}
    disposition_template TEXT NOT NULL DEFAULT '',
    example_mua_ids INTEGER[] DEFAULT '{}',       -- FK references to mua_records.id

    -- Quality
    source_count    INTEGER DEFAULT 0,            -- how many MUAs contributed to this pattern
    human_reviewed  BOOLEAN DEFAULT FALSE,
    reviewed_by     TEXT DEFAULT '',
    reviewed_date   DATE DEFAULT NULL,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 2.4 Table: `mua_alloy_families`

Lookup table for normalizing material designations to alloy families.
The classifier doesn't need this — precedent matching does.

```sql
CREATE TABLE mua_precedent.mua_alloy_families (
    id              SERIAL PRIMARY KEY,
    pattern         TEXT NOT NULL,                -- regex pattern: "\\bA[- ]?286\\b"
    family          TEXT NOT NULL,                -- "austenitic_ss"
    subfamily       TEXT DEFAULT '',              -- "iron_based_superalloy"
    display_name    TEXT NOT NULL,                -- "Austenitic Stainless Steel"
    example_alloys  TEXT[] DEFAULT '{}',          -- {"A286", "316L", "321", "347"}

    UNIQUE(pattern, family)
);
```

---

## 3. Indexes

These are the queries the classifier will actually run. Index for them.

```sql
-- Primary precedent lookup: "have we seen this exact scenario before?"
CREATE INDEX idx_precedent_lookup ON mua_precedent.mua_records
    (issue, rating, media_category, material_class);

-- Broader precedent: same issue+media, any rating
CREATE INDEX idx_precedent_issue_media ON mua_precedent.mua_records
    (issue, media_category, material_class);

-- Material-specific: "all MUAs for this MAPTIS code"
CREATE INDEX idx_maptis ON mua_precedent.mua_records (maptis_code);

-- Alloy family: "all MUAs for austenitic SS in hydrogen"
CREATE INDEX idx_family_media ON mua_precedent.mua_records
    (alloy_family, media_category, issue);

-- Outcome stats: approval rates by type
CREATE INDEX idx_outcome ON mua_precedent.mua_records
    (mua_type, approved);

-- Full-text on rationale (for pattern mining)
CREATE INDEX idx_rationale_fts ON mua_precedent.mua_records
    USING GIN (to_tsvector('english', rationale_text));

-- Pattern lookup
CREATE INDEX idx_pattern_key ON mua_precedent.mua_rationale_patterns
    (issue, rating, media_category, material_class, mua_type);
```

---

## 4. Views

### 4.1 Precedent Counts

The query the classifier actually needs. Fast, pre-aggregated.

```sql
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
WHERE issue != '' AND rating != ''
GROUP BY issue, rating, media_category, material_class, mua_type
WITH DATA;

CREATE UNIQUE INDEX idx_precedent_counts_pk ON mua_precedent.precedent_counts
    (issue, rating, media_category, material_class, mua_type);

-- Refresh nightly or after bulk import:
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mua_precedent.precedent_counts;
```

### 4.2 Alloy Family Stats

Broader view for "has any material in this family been approved?"

```sql
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
WHERE alloy_family != ''
GROUP BY alloy_family, issue, media_category
WITH DATA;
```

---

## 5. Media Category Normalization

The raw `media` field from historic MUAs is messy. Normalize to categories
that match classifier logic.

```sql
-- Helper function for import pipeline
CREATE OR REPLACE FUNCTION mua_precedent.normalize_media(raw_media TEXT)
RETURNS TEXT AS $$
DECLARE
    m TEXT := UPPER(TRIM(COALESCE(raw_media, '')));
BEGIN
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
    IF m IN ('AIR','AMBIENT','ATMOSPHERE','SEA LEVEL') THEN RETURN 'air';
    END IF;

    -- Water / aqueous
    IF m IN ('WATER','H2O','COOLANT','DEIONIZED WATER')
        OR m LIKE '%WATER%' THEN RETURN 'aqueous';
    END IF;

    RETURN 'other';
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

---

## 6. How V10 Uses This

### 6.1 Precedent Lookup (new function in pipeline.py)

After classification, before rationale generation:

```python
def lookup_precedent(
    issue: str,
    rating: str,
    media: str,
    material_class: str,
    mua_type: str,
) -> PrecedentSummary | None:
    """Query precedent_counts materialized view.

    Returns None if DB unavailable (graceful degradation).
    V10 classifier runs identically with or without this.
    """
    media_cat = normalize_media_category(media)  # python mirror of SQL function

    row = db_query_one(
        "SELECT * FROM mua_precedent.precedent_counts "
        "WHERE issue=%s AND rating=%s AND media_category=%s "
        "AND material_class=%s AND mua_type=%s",
        (issue, rating, media_cat, material_class, mua_type),
    )
    if not row:
        return None

    return PrecedentSummary(
        total_count=row["total_count"],
        approved_count=row["approved_count"],
        rejected_count=row["rejected_count"],
        distinct_materials=row["distinct_materials"],
        most_common_category=row["most_common_category"],
        earliest_approval=row["earliest_approval"],
        latest_approval=row["latest_approval"],
    )
```

### 6.2 Confidence Adjustment

Current V10 confidence is static per type:

```python
_TYPE_CONFIDENCE = {
    MUAType.THIN_SCREENING: 0.90,
    MUAType.ANTI_RULE: 0.70,
    ...
}
```

With precedent:

```python
def adjust_confidence(base: float, precedent: PrecedentSummary | None) -> float:
    if precedent is None:
        return base  # No DB, no change. Classifier unchanged.

    if precedent.total_count == 0:
        return base * 0.9  # Slight penalty: "no one has done this before"

    approval_rate = precedent.approved_count / precedent.total_count
    # Precedent weight: saturates at ~20 MUAs
    weight = min(precedent.total_count / 20.0, 1.0) * 0.15

    return min(base + (weight * approval_rate), 0.99)
```

ANTI_RULE goes from 0.70 → 0.82 with 15 approved precedents.
THIN_SCREENING goes from 0.90 → 0.95 with 30 approved precedents.
No precedent? Still the same number. **DB is additive, never required.**

### 6.3 Rationale Enrichment

Template output today:
> "A286 (MAPTIS 10392) has a fluid system compatibility rating of U,
> indicating no test data exists..."

With precedent appended:
> "...The FS=U rating does not represent a deficiency for GH2 service.
> This disposition is consistent with 23 prior approved Category II MUAs
> for FS=U in hydrogen service across 14 distinct materials, including
> Inconel 718 (MUA-2019-0847) and 316L SS (MUA-2021-1203)."

The rationale engine already returns a string. Add a `precedent_suffix()` function
that appends one sentence if precedent exists, returns empty string if not.

### 6.4 Human-Required Enrichment

For REAL_PROBLEM and REAL_GAP (the ones we route to engineers), precedent
data becomes decision support:

> "FLAG_FOR_HUMAN: SCC=C in GH2 for A286.
> Precedent context: 12 prior MUAs for SCC=C in hydrogen.
> 11 approved as Category I, 1 rejected.
> Most recent: MUA-2024-0391 (DMLLV, approved)."

This doesn't change the routing. It gives the engineer what they need
to write the MUA faster.

---

## 7. Import Pipeline

### 7.1 JSON → mua_records

The 8K parsed JSONs need a loader. Shape varies, so the loader
normalizes on insert.

```python
def import_mua_json(filepath: str) -> int:
    """Import one parsed MUA JSON into mua_records.

    Returns 1 if inserted, 0 if duplicate (source_hash match).
    """
    raw = json.load(open(filepath))
    source_hash = hashlib.sha256(
        json.dumps(raw, sort_keys=True).encode()
    ).hexdigest()

    record = {
        "mua_number": extract_mua_number(raw),
        "source_hash": source_hash,
        "maptis_code": extract_maptis_code(raw),
        "material_name": extract_material_name(raw),
        "material_class": infer_material_class(raw),
        "alloy_family": infer_alloy_family(raw),
        "issue": extract_issue(raw),
        "rating": extract_rating(raw),
        "media": extract_media(raw),
        "media_category": normalize_media_category(extract_media(raw)),
        "environment": extract_environment(raw),
        "category": extract_category(raw),
        "approved": infer_approval(raw),
        "approval_date": extract_date(raw),
        "rationale_text": extract_rationale(raw),
        "disposition_text": extract_disposition(raw),
        "project": extract_project(raw),
        "part_numbers": extract_parts(raw),
        "source_file": filepath,
        "confidence": assess_parse_confidence(raw),
    }

    # Retroactive V10 classification
    try:
        v10_result = classify_mua(
            maptis_code=record["maptis_code"],
            issue_key=record["issue"],
            rating=record["rating"],
            material_class=record["material_class"],
            media=record["media"],
            environment=record["environment"],
        )
        record["flag_type"] = v10_result.flag_type.value if v10_result.flag_type else ""
        record["mua_type"] = v10_result.mua_type.value
    except Exception:
        pass  # V10 classification is bonus, not required

    return upsert_record(record)  # ON CONFLICT (source_hash) DO UPDATE
```

### 7.2 Bulk Import Script

```bash
# Import all 8K MUAs
py -3 scripts/import_mua_precedent.py --input-dir data/historic_muas/ --batch-size 500

# Refresh materialized views after import
py -3 scripts/import_mua_precedent.py --refresh-views

# Validate import quality
py -3 scripts/import_mua_precedent.py --validate
```

### 7.3 Retroactive V10 Classification

Run every historic MUA through the V10 classifier to populate
`flag_type` and `mua_type` columns. This lets us answer:
"how would V10 have classified this historic MUA?"

Validation metric: V10 classification should agree with actual
historic outcome for >90% of automatable types.

---

## 8. What the JSON Parsers Need to Extract

For each of the 8K MUAs, the import pipeline needs these fields.
Not all will be present in every source. Parse confidence tracks
extraction quality.

| Field | Priority | Source hints |
|-------|----------|-------------|
| mua_number | HIGH | "MUA-YYYY-NNNN", header, filename |
| maptis_code | HIGH | 5-digit code, "MAPTIS", form field |
| material_name | HIGH | "Material:", alloy designation |
| issue | HIGH | "FLAM", "FS", "TOX", "SCC", "CORR", "TVS" |
| rating | HIGH | Single letter after issue column name |
| media | HIGH | "Media:", "Fluid:", "Service medium:" |
| category | MEDIUM | "Cat I", "Cat II", "Category" |
| rationale_text | MEDIUM | Longest prose block, "Rationale:" section |
| disposition_text | MEDIUM | "Disposition:", "Accepted", "Rejected" |
| project | MEDIUM | "Project:", "Program:" |
| approval_date | LOW | Date near signatures |
| part_numbers | LOW | Drawing numbers, "Part:" |
| material_spec | LOW | AMS/ASTM/MIL numbers |
| pressure | LOW | "psi", "psig", "MPa" |
| temperature | LOW | "°F", "°R", "K" |

---

## 9. Data Quality Gates

### 9.1 Minimum Viable Record

A record must have ALL of these to count as a valid precedent:

```python
REQUIRED_FIELDS = ["mua_number", "maptis_code", "issue", "rating", "media"]

def is_valid_precedent(record: dict) -> bool:
    for field in REQUIRED_FIELDS:
        if not record.get(field, "").strip():
            return False
    return True
```

Records missing required fields still get imported (for completeness)
but with `confidence < 0.5` and excluded from precedent_counts view.

### 9.2 Parse Confidence Scoring

```python
def assess_parse_confidence(raw: dict) -> float:
    score = 0.0
    if raw.get("mua_number"):   score += 0.20
    if raw.get("maptis_code"):  score += 0.20
    if raw.get("issue"):        score += 0.15
    if raw.get("rating"):       score += 0.15
    if raw.get("media"):        score += 0.15
    if raw.get("rationale"):    score += 0.10
    if raw.get("category"):     score += 0.05
    return min(score, 1.0)
```

### 9.3 Expected Distribution

From 8K MUAs, expected rough distribution:

| MUA Type (retroactive) | Expected % | Expected Count |
|------------------------|-----------|---------------|
| THIN_SCREENING | ~35% | ~2,800 |
| ANTI_RULE | ~20% | ~1,600 |
| INCOMPLETE_PASS | ~15% | ~1,200 |
| REAL_PROBLEM (Cat I) | ~10% | ~800 |
| REAL_GAP | ~5% | ~400 |
| STANDARD (no MUA needed) | ~5% | ~400 |
| Unclassifiable | ~10% | ~800 |

If actuals deviate significantly, that's a signal about either
parse quality or classifier logic.

---

## 10. Migration Path

### Phase 1: Import + Validate (this week)

1. Create schema on Raider Postgres (or GovCloud RDS)
2. Run bulk import of 8K JSONs
3. Run retroactive V10 classification
4. Validate: compare V10 classifications vs actual historic outcomes
5. Refresh materialized views

### Phase 2: Wire to V10 (next week)

1. Add `PrecedentSummary` model to `mira/mua/classifier/models.py`
2. Add `precedent.py` module with lookup + confidence adjustment
3. Modify `pipeline.py` to call precedent lookup after classification
4. Modify `rationale.py` to append precedent suffix
5. Add precedent info to `ClassifierResult` (optional field)
6. Frontend: show precedent badge in Step 3 ("47 prior approvals")

### Phase 3: Pattern Mining (following week)

1. Cluster rationale texts by (issue, rating, media_category, mua_type)
2. Extract common sentence structures → `mua_rationale_patterns`
3. Human review of top 20 patterns (Dr. Wilde validates)
4. Upgrade rationale engine to prefer mined patterns over templates
5. A/B test: template rationale vs precedent-enriched rationale

---

## 11. Query Examples

### "How many times has FS=U in hydrogen been approved?"

```sql
SELECT * FROM mua_precedent.precedent_counts
WHERE issue = 'FS' AND rating = 'U'
  AND media_category = 'hydrogen'
  AND material_class = 'metal';
```

### "Find the 3 most recent approved MUAs for FLAM=C in hydrogen"

```sql
SELECT mua_number, material_name, maptis_code, category,
       approval_date, LEFT(rationale_text, 200) AS rationale_preview
FROM mua_precedent.mua_records
WHERE issue = 'FLAM' AND rating = 'C'
  AND media_category = 'hydrogen'
  AND material_class = 'metal'
  AND approved = TRUE
ORDER BY approval_date DESC
LIMIT 3;
```

### "What's the approval rate for ANTI_RULE MUAs?"

```sql
SELECT
    mua_type,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE approved) AS approved,
    ROUND(100.0 * COUNT(*) FILTER (WHERE approved) / NULLIF(COUNT(*), 0), 1) AS pct
FROM mua_precedent.mua_records
WHERE mua_type = 'ANTI_RULE'
GROUP BY mua_type;
```

### "Has any nickel superalloy been approved for SCC=C in hydrogen?"

```sql
SELECT DISTINCT material_name, mua_number, category, approval_date
FROM mua_precedent.mua_records
WHERE alloy_family = 'ni_superalloy'
  AND issue = 'SCC'
  AND rating = 'C'
  AND media_category = 'hydrogen'
  AND approved = TRUE
ORDER BY approval_date DESC;
```

---

## 12. File Summary

| File | Action | Purpose |
|------|--------|---------|
| `mira/mua/precedent/schema.sql` | NEW | DDL for all tables, indexes, views, functions |
| `mira/mua/precedent/models.py` | NEW | PrecedentSummary, PrecedentRecord pydantic models |
| `mira/mua/precedent/lookup.py` | NEW | DB query functions, graceful degradation |
| `mira/mua/precedent/importer.py` | NEW | JSON → mua_records bulk loader |
| `mira/mua/precedent/families.py` | NEW | Alloy family normalization + seed data |
| `mira/mua/precedent/media_norm.py` | NEW | Media category normalization (Python mirror of SQL) |
| `scripts/import_mua_precedent.py` | NEW | CLI for bulk import + validation |
| `mira/mua/classifier/pipeline.py` | MODIFY | Add optional precedent lookup after classification |
| `mira/mua/classifier/rationale.py` | MODIFY | Add precedent suffix to rationale text |
| `mira/mua/classifier/models.py` | MODIFY | Add PrecedentSummary optional field to ClassifierResult |

### DO NOT MODIFY

All existing classifier logic (classifier.py, screening.py, domain_facts.py, grouping.py).
The classifier is deterministic. Precedent is additive.
