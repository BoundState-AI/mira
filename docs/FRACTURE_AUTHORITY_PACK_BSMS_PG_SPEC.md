# BSMS Fracture Authority Pack (PostgreSQL) Specification

## Version: 1.0.0-draft
## Date: 2026-02-17
## Classification: BoundState Proprietary
## Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
## Spec Reference: BS-BSMS-FC-PG-001-REV0

---

## 1. Purpose

Define a deterministic, PostgreSQL-first Fracture Control authority pack for BSMS/BSMH.

This spec implements fracture decision support from:
- `NASA-STD-5019A`
- `NASA-STD-5009C`
- `JSC-27301` (center implementation overlays)
- `ISO 21347` (supporting context/citation layer)

The architecture goal is deterministic requirement retrieval with explicit citations, not semantic similarity ranking.

---

## 2. Scope

### 2.1 In Scope

1. PostgreSQL schema for fracture authority data and rule execution.
2. BSMH parser/rules/model deltas for `fracture_control` safety context.
3. Deterministic classification, requirement binding, NDE lookup, center-level overlay.
4. Provenance-compatible output for audit and cache stability.
5. Implementation plan, test plan, and acceptance gates.

### 2.2 Out of Scope

1. Full replacement of all existing FAISS paths outside fracture flow.
2. UI redesign.
3. Historical backfill of all legacy fracture records beyond defined authority docs.

---

## 3. Current Baseline (Code Anchors)

1. BSMH retrieval path is DB-first (`mira/bsmh/service.py:549`).
2. Hydrogen BoK enrichment still uses FAISS (`mira/bsmh/bok_adapter.py:44`, `mira/h2/engine.py:193`).
3. Safety contexts do not include fracture (`mira_v4/models.py:37`, `mira/api/routers/mira_v4.py:246`, `mira/bsmh/service.py:129`).
4. Current deterministic packet shape is material-compatibility-oriented (`mira/bsmh/models.py:73`).
5. Existing authority-pack pattern is present in MUA routing (`mira/mua/v7/category_router.py:113`).
6. BSMH formatter already has pack-portable hooks (`mira/bsmh/response_formatter.py:218`).

---

## 4. Engineering Principles

1. Deterministic over semantic for normative obligations.
2. Every returned requirement must carry section/page citation and source hash lineage.
3. LLM role is intent/slot parsing and answer composition only.
4. Rule values must be pack-configured and citation-bound. No magic numbers in code.
5. Unknown critical inputs produce `CLARIFY` or `INSUFFICIENT_DATA`, never implied assumptions.

---

## 5. Target Runtime Flow

Query -> Bouncer -> Sonnet Parse -> Fracture Rule Engine (PG) -> Sonnet Formatter -> Provenance Hash

Deterministic fracture flow:
1. Parse fracture context from query.
2. Classify part via 5019A decision path.
3. Bind applicable requirements by class + context.
4. Bind NDE obligations via 5009C method/geometry/accessibility tables.
5. Apply JSC-27301 center overlays.
6. Emit verdict, required actions, and exact citations.

---

## 6. PostgreSQL Data Model

### 6.1 Schema

Use dedicated schema:

```sql
CREATE SCHEMA IF NOT EXISTS authority_fc;
```

### 6.2 Pack Registry and Source Control

```sql
CREATE TABLE authority_fc.pack_registry (
    pack_id              VARCHAR(64) PRIMARY KEY,
    pack_name            VARCHAR(256) NOT NULL,
    version              VARCHAR(32) NOT NULL,
    status               VARCHAR(16) NOT NULL DEFAULT 'draft',
    effective_from       DATE,
    effective_to         DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by           VARCHAR(128) NOT NULL,
    notes                TEXT,
    CONSTRAINT chk_pack_status CHECK (status IN ('draft','active','deprecated','retired'))
);

CREATE TABLE authority_fc.source_documents (
    document_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_id              VARCHAR(64) NOT NULL REFERENCES authority_fc.pack_registry(pack_id),
    doc_code             VARCHAR(64) NOT NULL,
    title                TEXT NOT NULL,
    revision             VARCHAR(32),
    issue_date           DATE,
    file_path            TEXT NOT NULL,
    file_sha256          CHAR(64) NOT NULL,
    page_count           INTEGER,
    text_layer_coverage_pct NUMERIC(5,2),
    extraction_mode      VARCHAR(16) NOT NULL DEFAULT 'text',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (pack_id, doc_code, revision)
);
```

### 6.3 Section and Requirement Normalization

```sql
CREATE TABLE authority_fc.document_sections (
    section_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id          UUID NOT NULL REFERENCES authority_fc.source_documents(document_id) ON DELETE CASCADE,
    section_key          VARCHAR(64) NOT NULL,
    heading              TEXT,
    parent_section_id    UUID REFERENCES authority_fc.document_sections(section_id),
    page_start           INTEGER,
    page_end             INTEGER,
    is_normative         BOOLEAN NOT NULL DEFAULT FALSE,
    section_text         TEXT NOT NULL,
    UNIQUE (document_id, section_key)
);

CREATE TABLE authority_fc.requirement_clauses (
    requirement_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id           UUID NOT NULL REFERENCES authority_fc.document_sections(section_id) ON DELETE CASCADE,
    clause_key           VARCHAR(64) NOT NULL,
    modality             VARCHAR(16) NOT NULL,
    requirement_text     TEXT NOT NULL,
    condition_expr       JSONB NOT NULL DEFAULT '{}'::jsonb,
    obligation_expr      JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity             VARCHAR(16) NOT NULL DEFAULT 'mandatory',
    source_doc_code      VARCHAR(64) NOT NULL,
    source_section       VARCHAR(64) NOT NULL,
    source_page_start    INTEGER,
    source_page_end      INTEGER,
    source_sha256        CHAR(64) NOT NULL,
    CONSTRAINT chk_modality CHECK (modality IN ('SHALL','SHOULD','MAY','PROHIBITED')),
    CONSTRAINT chk_severity CHECK (severity IN ('mandatory','recommended','advisory')),
    UNIQUE (section_id, clause_key)
);
```

### 6.4 Fracture Classification and Rule Binding

```sql
CREATE TABLE authority_fc.classification_rules (
    rule_id              VARCHAR(64) PRIMARY KEY,
    pack_id              VARCHAR(64) NOT NULL REFERENCES authority_fc.pack_registry(pack_id),
    rule_order           INTEGER NOT NULL,
    rule_name            TEXT NOT NULL,
    predicate_expr       JSONB NOT NULL,
    class_outcome        VARCHAR(64),
    source_requirement_id UUID REFERENCES authority_fc.requirement_clauses(requirement_id),
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (pack_id, rule_order)
);

CREATE TABLE authority_fc.requirement_bindings (
    binding_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_id              VARCHAR(64) NOT NULL REFERENCES authority_fc.pack_registry(pack_id),
    part_class           VARCHAR(64) NOT NULL,
    requirement_id       UUID NOT NULL REFERENCES authority_fc.requirement_clauses(requirement_id),
    applicability_expr   JSONB NOT NULL DEFAULT '{}'::jsonb,
    priority             INTEGER NOT NULL DEFAULT 100,
    active               BOOLEAN NOT NULL DEFAULT TRUE
);
```

### 6.5 NDE Rules (5009C)

```sql
CREATE TABLE authority_fc.nde_methods (
    method_id            VARCHAR(64) PRIMARY KEY,
    method_name          TEXT NOT NULL,
    source_doc_code      VARCHAR(64) NOT NULL,
    source_section       VARCHAR(64),
    source_page          INTEGER,
    notes                TEXT
);

CREATE TABLE authority_fc.nde_applicability (
    nde_rule_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_id              VARCHAR(64) NOT NULL REFERENCES authority_fc.pack_registry(pack_id),
    part_class           VARCHAR(64) NOT NULL,
    geometry_type        VARCHAR(64) NOT NULL,
    accessibility_class  VARCHAR(32) NOT NULL,
    method_id            VARCHAR(64) NOT NULL REFERENCES authority_fc.nde_methods(method_id),
    detectable_flaw_mm   NUMERIC(10,4),
    applicability_expr   JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_requirement_id UUID REFERENCES authority_fc.requirement_clauses(requirement_id),
    active               BOOLEAN NOT NULL DEFAULT TRUE
);
```

### 6.6 Center Overlays (JSC-27301)

```sql
CREATE TABLE authority_fc.center_overrides (
    override_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_id              VARCHAR(64) NOT NULL REFERENCES authority_fc.pack_registry(pack_id),
    center_code          VARCHAR(32) NOT NULL,
    target_type          VARCHAR(32) NOT NULL,
    target_id            VARCHAR(128) NOT NULL,
    override_action      VARCHAR(16) NOT NULL,
    override_payload     JSONB NOT NULL,
    source_requirement_id UUID REFERENCES authority_fc.requirement_clauses(requirement_id),
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT chk_target_type CHECK (target_type IN ('classification_rule','requirement_binding','nde_rule')),
    CONSTRAINT chk_override_action CHECK (override_action IN ('add','replace','suppress'))
);
```

### 6.7 Performance Indexes

```sql
CREATE INDEX idx_fc_sections_doc ON authority_fc.document_sections(document_id, section_key);
CREATE INDEX idx_fc_requirements_section ON authority_fc.requirement_clauses(section_id);
CREATE INDEX idx_fc_class_rules_pack ON authority_fc.classification_rules(pack_id, rule_order) WHERE active = TRUE;
CREATE INDEX idx_fc_bindings_class ON authority_fc.requirement_bindings(pack_id, part_class, priority) WHERE active = TRUE;
CREATE INDEX idx_fc_nde_lookup ON authority_fc.nde_applicability(pack_id, part_class, geometry_type, accessibility_class) WHERE active = TRUE;
CREATE INDEX idx_fc_overrides_center ON authority_fc.center_overrides(pack_id, center_code, target_type) WHERE active = TRUE;
```

---

## 7. Rule Predicate Contract (JSONB)

Use a strict, auditable predicate DSL for `predicate_expr` and `applicability_expr`.

Allowed operators:
- `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `exists`, `all`, `any`

Context keys (minimum set):
- `material_designation`
- `material_form`
- `condition`
- `fracture_toughness_mpa_sqrt_m`
- `yield_strength_mpa`
- `kic_over_fy_sqrt_mm`
- `eac_sensitive`
- `pressure_boundary`
- `consequence_of_failure`
- `design_life_cycles`
- `geometry_type`
- `accessibility_class`
- `center_code`

Example:

```json
{
  "all": [
    {"eq": ["pressure_boundary", true]},
    {"gte": ["kic_over_fy_sqrt_mm", 1.66]},
    {"eq": ["eac_sensitive", false]}
  ]
}
```

Note: Engineering values and thresholds must be confirmed in pack loading QA before activation.

---

## 8. BSMS/BSMH Code Delta

### 8.1 Safety Context and Parse

1. Add `FRACTURE_CONTROL = "fracture_control"` to `SafetyContext` in `mira_v4/models.py`.
2. Extend parse prompt allowed contexts in `mira/api/routers/mira_v4.py:246`.
3. Extend heuristic parse branch in `mira/api/routers/mira_v4.py:497`.
4. Extend `_normalize_safety_context` and `_infer_safety_context_from_query` in `mira/bsmh/service.py:129`.

### 8.2 Bouncer

Update `mira/bsmh/bouncer.py`:
1. In-scope fracture keywords (fracture critical, crack growth, KIC, NDE, fail-safe, safe-life, damage tolerance).
2. Structured extraction fields for fracture intent.

### 8.3 BSMH Models

Extend `mira/bsmh/models.py` with fracture-specific packet payloads:
- `FractureAssessment`
- `FractureRequirementItem`
- `NDERequirementItem`

Add optional field to `RuleDecisionPacket`:
- `fracture: Optional[FractureAssessment]`

### 8.4 Rules Engine

Add fracture branch in `mira/bsmh/rules_engine.py`:
1. `build_fracture_decision(...)` for deterministic SQL-driven classification and bindings.
2. Keep current material compatibility branch intact.
3. Set `standards_category` mapping for fracture context explicitly.

### 8.5 BOK Adapter Generalization

Refactor `mira/bsmh/bok_adapter.py` from H2-specific helper into context-pack adapter.

Minimum target interface:

```python
def fetch_pack_evidence(
    *,
    safety_context: str,
    query: str,
    requested_materials: list[str],
    pack_id: str,
    center_code: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    ...
```

For fracture, retrieval source is PostgreSQL `authority_fc` tables, not FAISS.

### 8.6 Formatter

Keep current formatter pipeline, but add fracture lexicon in pack-config term corrections (`mira/bsmh/response_formatter.py:218`).

---

## 9. Data Ingestion Pipeline

### 9.1 Source Triage

For each source PDF:
1. Compute SHA-256.
2. Measure text layer coverage.
3. Route extraction mode:
- `text` if text layer sufficient
- `vision` only for pages with extraction failure

Current workspace probe indicates strong text-layer coverage across all four docs; default ingestion should be text-first with selective vision fallback.

### 9.2 Extraction Steps

1. Parse hierarchy: section, subsection, table, figure references.
2. Extract normative clauses (`shall`, `shall not`, mandatory conditions).
3. Normalize into `document_sections` and `requirement_clauses`.
4. Build classification and NDE mapping rows.
5. Human-in-the-loop adjudication queue for low-confidence or ambiguous obligations.
6. Activate pack version only after validation suite passes.

### 9.3 Loader Outputs

Loader must emit:
1. `pack_registry` row with version hash.
2. Source document rows with file hash and extraction mode.
3. Fully citation-bound requirements and rule bindings.

---

## 10. Deterministic Query Contract

Given normalized query context `Q`, engine returns:

1. `part_class`
2. `classification_trace[]` (rule_id, pass/fail, citation)
3. `applicable_requirements[]` (requirement_id, text, citation)
4. `nde_requirements[]` (method, geometry, detectability, citation)
5. `center_overrides_applied[]`
6. `verdict`
7. `evidence_gaps[]`

If required context fields are missing, return `CLARIFY`/`INSUFFICIENT_DATA` with explicit missing field list.

---

## 11. Provenance and Audit

1. Reuse existing query hash + snapshot hash path (`mira_v4/provenance.py`).
2. Store pack metadata in response metadata:
- `authority_pack_id`
- `authority_pack_version`
- `authority_pack_hash`
3. Ensure output citations include document revision and source SHA-256.

---

## 12. Migration and Rollout Plan

### Phase 0: Foundation

1. Add migration file: `mira/bsmh/migrations/001_create_authority_fc_schema.sql`.
2. Add loader scaffold script: `scripts/load_fracture_authority_pack.py`.
3. Add seed pack metadata row (draft state).

### Phase 1: Parse and Context

1. Add fracture context to v4/BSMH enums and parser prompts.
2. Add bouncer fracture extraction.
3. Add fracture query model fields.

### Phase 2: Rule Engine Integration

1. Implement SQL-backed fracture classification and bindings.
2. Wire into `run_bsmh_query` branch on `safety_context == fracture_control`.
3. Return deterministic fracture payload in `RuleDecisionPacket`.

### Phase 3: Formatter and Provenance

1. Extend formatter templates for fracture output structure.
2. Attach pack/version metadata.
3. Add citation formatting standard.

### Phase 4: Validation and Hardening

1. Gold query suite with expected requirement IDs and citations.
2. Non-regression tests for oxygen/hydrogen/cryogenic flows.
3. Performance and deterministic-repeatability checks.

---

## 13. Test Requirements

### 13.1 Unit Tests

1. Predicate evaluator correctness.
2. Classification order determinism.
3. Requirement binding and center override precedence.
4. NDE lookup by class/geometry/accessibility.

### 13.2 Integration Tests

1. End-to-end fracture query through BSMH endpoint.
2. Verify no FAISS code path is invoked for fracture context.
3. Verify citations contain section/page/hash.

### 13.3 Acceptance Gates

1. Deterministic replay: same input -> same rule/citation outputs.
2. Citation completeness: 100 percent citation coverage for returned requirements.
3. Coverage: gold scenarios pass with expected part class and obligations.
4. Safety: missing critical fields never produce `COMPATIBLE` verdicts.

---

## 14. Open Engineering Decisions (Must Be Closed Before Activation)

1. Final canonical part-class vocabulary for fracture domain.
2. Exact threshold set lock from 5019A/5009C adjudication review.
3. Minimum required context fields for automatic classification versus clarify.
4. Override precedence when center-level and base-pack rules conflict.

---

## 15. Definition of Done

Fracture authority pack is complete when:
1. `fracture_control` context is parseable and routable in BSMH.
2. Fracture decisions execute against PostgreSQL authority tables only.
3. Responses include deterministic requirement sets, NDE obligations, and exact citations.
4. Pack metadata and source hashes are present in provenance.
5. Gold suite and non-regression suite pass in CI.

---

## 16. Immediate Implementation Checklist

1. Create migration SQL for `authority_fc` schema and tables.
2. Add fracture context enum and parser prompt updates.
3. Add fracture models in `mira/bsmh/models.py`.
4. Implement fracture branch in `mira/bsmh/rules_engine.py`.
5. Add PG retrieval helpers in `mira/bsmh/service.py`.
6. Implement authority pack loader script for four fracture docs.
7. Add tests for classification, requirement binding, NDE lookup, and citations.

