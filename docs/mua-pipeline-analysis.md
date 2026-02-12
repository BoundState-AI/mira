# MUA Generation Pipeline - Complete Analysis

> **Date:** 2026-02-07
> **Scope:** Every module, model, and execution path in the MUA generation system
> **Author:** Claude Code deep-dive analysis of BoundState MIRA codebase

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Complete Execution Flow](#2-complete-execution-flow-v6-production)
3. [Determination Objects](#3-determination-objects)
4. [Evidence Models](#4-evidence-models)
5. [Precedent Retrieval Mechanics](#5-precedent-retrieval-mechanics)
6. [Requirements & Policy Application](#6-requirements--policy-application)
7. [Confidence & Gating](#7-confidence--gating)
8. [Drafting Constraints](#8-drafting-constraints)
9. [MUA Document Structure](#9-mua-document-structure)
10. [Deterministic vs LLM Table](#10-deterministic-vs-llm-table)
11. [Pain Points & Fragilities](#11-pain-points--fragilities)
12. [File Index](#12-file-index)

---

## 1. Architecture Overview

The MUA pipeline exists in **three independent implementations** that do not share data models or execution paths:

| System | Entry Point | Determination Model | LLM Usage |
|--------|------------|-------------------|-----------|
| **v1 Service** | `mira/mua/service.py:48` | Category I/II/III + mitigations | None |
| **v1 Generator** | `mira/mua/mua_generator.py:394` | Category + FAISS mitigations + clause-anchored text | None |
| **v6 Pipeline** | `mira/api/routers/mua_v6.py:238` | 4-level gate (PROCEED/WARN/REVIEW/BLOCKED) | Claude Haiku (validation only) |
| **Compliance Module** | `mira/compliance/models/` (models only) | MPRDetermination per requirement | N/A (not wired to v6) |

---

## 2. Complete Execution Flow (v6 - Production)

### Main Pipeline: `POST /mua-v6/generate`

```
POST /mua-v6/generate                    [mira/api/routers/mua_v6.py:237]
  |
  |-- Step 1: Material Resolution        [mira/mua/v6/material_identity.py:209]
  |   resolve_material_identity(designation)
  |   -> MaterialCodeLookupService.lookup_material_code()
  |   -> MaterialIdentity { material_code, confidence, method, family }
  |   -> BLOCKED if material_code is None
  |
  |-- Step 2: Precedent Search           [mira/mua/v6/enriched_search.py:280]
  |   search_enriched_precedents(material, environment, k)
  |   -> MUAFAISSSearch.search()         [mira/miul/mua_faiss_search.py]
  |   -> EnrichedMUAResult.from_search_result()  (classify APPROVED vs REJECTED)
  |   -> EnrichedSearchResults { supporting[], conflicting[], other[] }
  |
  |-- Step 3: MAPTIS Test Data           [mira/mua/v6/maptis_test_data.py:339]
  |   await query_maptis_test_data(material_code)
  |   -> psycopg2 query: silver_report_rows WHERE contract_id='flammability_report'
  |   -> Split by flam_dataexpireflag: '2'=current, '1'=expired, NULL=unknown
  |   -> TestDataStatus { has_current_data, has_expired_data, envelope, ratings }
  |
  |-- Step 4: Envelope Overlap           [mira/mua/v6/envelope_matching.py:114]
  |   compute_envelope_overlap(query_o2, query_pressure, query_temp, prec_bounds)
  |   -> Per-dimension: O2 <= max, pressure <= max, temp_min <= temp <= temp_max
  |   -> Status: WITHIN(0.0) | PARTIAL(0.15) | EXTRAPOLATION(0.4) | OUTSIDE(1.0)
  |
  |-- Step 5: Decision Engine            [mira/mua/v6/decision_engine.py:152]
  |   MUADecisionEngine().evaluate(supporting, conflicting, envelope, test_data, resolved)
  |   -> Phase 1: BLOCKED checks (no supporting, unresolved, outside envelope)
  |   -> Phase 2: REVIEW checks (conflicting, all expired, extrapolation, <2 supporting)
  |   -> Phase 3: WARN checks (mixed currency, partial overlap, weak scores >1.5)
  |   -> Phase 4: PROCEED (all pass)
  |   -> DecisionResult { decision, confidence_score, factors[] }
  |
  |-- Step 6A: Logic Validation (LLM)    [mira/mua/v6/logic_validator.py:132]
  |   (Only if mode="auto" AND decision in {PROCEED, WARN})
  |   LogicValidator.validate(material, environment, precedents[:5])
  |   -> Claude 3.5 Haiku, temp=0, max_tokens=2048
  |   -> Checks: rationale transfers? mitigations present? severity <=? family match?
  |   -> FAIL-CLOSED: any error -> is_valid=False
  |   -> RationaleValidationResult { is_valid, synthesized_rationale, citations }
  |   -> If is_valid=False: decision downgrades to REVIEW_REQUIRED, confidence *= 0.5
  |
  |-- Step 6B: Draft Rendering           [mira/api/routers/mua_v6.py:412]
  |   _render_draft(material, environment, rationale, citations)
  |   -> Simple template: MATERIAL | ENVIRONMENT | LOCATION | RATIONALE | CITATIONS
  |   -> "NOTE: This is a system-generated draft requiring engineering review."
  |
  --> GenerateResponse { decision, confidence, envelope_status, draft_text, warnings }
```

### Alternative Path: Corpus-Based Draft

```
POST /mua-v6/corpus/draft               [mira/api/routers/mua_v6.py:616]
  |-- Build NormalizedEnvironment from request
  |-- V6PrecedentRetriever.retrieve_by_gaps() or retrieve_by_material_env()
  |   -> FAISS search + BM25 hybrid (RRF K=60)
  |   -> StructuredFilterEngine (env compat matrix, issues, determination, confidence)
  |   -> PrecedentRanker.rank() -> composite = 0.6*structured + 0.4*semantic
  |-- DraftGenerator.generate_draft()     [mira/mua/v6/draft_generator.py:126]
  |   -> _analyze_coverage() -> STRONG/MODERATE/WEAK
  |   -> _determine_recommendation() -> APPROVED/CONDITIONAL/REQUIRES_REVIEW
  |   -> _synthesize_rationale() -> template + precedent excerpts (NO LLM)
  |   -> _identify_gaps() -> missing material/env/pressure/issues
  |   -> _build_warnings() -> low confidence, no approved, conflicting, habitable
  --> CorpusDraftResponse { determination, confidence, rationale, citations, gaps, warnings }
```

### v1 Generator Path (Legacy)

```
generate_mua(miul, ratings)              [mira/mua/mua_generator.py:394]
  |-- detect_gaps(ratings)               -> {test_class: rating} for non-A ratings
  |-- _validate_environment(miul, gaps)  -> Hard stop if missing fields
  |-- route_category(miul, gaps)         -> Category I/II/III + Appendix B
  |-- retriever.retrieve(miul, gaps)     -> FAISS-backed mitigation retrieval
  |-- estimate_confidence(mitigations)   -> {global, 68% CI, 95% CI, known_unknowns}
  |-- render_text(...)                   -> Full 5-section MUA document
  --> { id, category, gap_profile, mitigations, confidence, draft_text }
```

---

## 3. Determination Objects

### v6 Decision Engine (`decision_engine.py:56-88`)

```python
class GenerationDecision(str, Enum):
    PROCEED = "proceed"            # Safe to auto-generate
    WARN = "warn"                  # Can generate but with warnings
    REVIEW_REQUIRED = "review"     # Human review needed
    BLOCKED = "blocked"            # Cannot proceed

class DecisionResult(BaseModel):
    decision: GenerationDecision          # The gate
    reasons: list[str]                    # Human-readable
    blocking_factors: list[str]           # What triggered BLOCKED
    review_factors: list[str]             # What triggered REVIEW_REQUIRED
    warning_factors: list[str]            # What triggered WARN
    confidence_score: float               # 0.0 | 0.3 | 0.6 | 0.85 (hardcoded per tier)
    source: str                           # "MUADecisionEngine" (SWE-013)

    # Properties:
    can_auto_generate -> bool             # decision == PROCEED
    requires_human -> bool                # decision in {REVIEW_REQUIRED, BLOCKED}
    can_generate_with_warnings -> bool    # decision in {PROCEED, WARN}
```

### Compliance Module (`determination.py:57-194`) - NOT wired to v6

```python
class MPRDetermination(BaseModel):
    # MPR identity
    mpr_number: int                       # NASA-STD-6016C MPR number
    mpr_section: str                      # Section reference
    mpr_title: str
    mpr_source_evidence: EvidenceRef      # Evidence for the MPR itself

    # Applicability
    applicability_status: ApplicabilityStatus  # APPLICABLE | NOT_APPLICABLE | TAILORED_OUT
    applicability_rationale: str

    # Compliance
    compliant: ComplianceStatus           # COMPLIANT | WITH_CONSTRAINTS | NONCOMPLIANT | UNKNOWN
    compliance_basis: ComplianceBasis     # TEST | ANALYSIS | EVIDENCE_WEIGHTED | POLICY | PRECEDENT
    compliance_rationale: Optional[str]

    # Signals
    gap_signals: list[GapSignal]          # Typed failure signals from adapters
    operational_constraints: list[OperationalConstraint]  # For WITH_CONSTRAINTS

    # Actions
    required_action: RequiredAction       # NONE | GENERATE_MUA | ENGINEERING_REVIEW | ...
    mua_required: bool
    mua_draft_id: Optional[str]           # Links to generated draft

    # Evidence
    supporting_evidence: list[EvidenceRef]
```

### Gap Between the Two Systems

- `DecisionResult` is a **generation gate** (should I produce text?) with 4 levels
- `MPRDetermination` is a **compliance assessment** (is this material compliant?) per requirement
- They don't share data. The v6 pipeline never creates `MPRDetermination` objects.
- The compliance module's `MUAAdapterOutput` has `category`, `precedent_validations`, `draft_text` but v6 doesn't use it.

---

## 4. Evidence Models

### Full-Featured: Compliance Module (`evidence.py:50-152`)

```python
class EvidenceRef(BaseModel):
    source_type: SourceType               # MAPTIS | TEST_REPORT | BOK | STANDARD | MUA_PRECEDENT | ANALYSIS | JUDGMENT
    source_id: str                        # Unique ID
    source_version: Optional[str]         # Document version
    locator: Optional[str]                # Page/section/table
    anchor_id: Optional[str]              # Deep link
    quote: Optional[str]                  # Max 500 chars
    document_fingerprint: Optional[str]   # SHA-256 of document
    content_hash: Optional[str]           # SHA-256 of snippet
    maptis_record_id: Optional[str]
    maptis_query_signature: Optional[str] # Hash of query used
    confidence: float                     # 0.0-1.0
    confidence_basis: str                 # How confidence determined
    retrieved_at: datetime
    retrieval_method: str                 # "faiss_search", "direct_lookup"
```

### Simplified: MUA Module (`models.py:29-87`)

```python
@dataclass
class EvidenceRef:                        # DIFFERENT class, same name
    map_tis_id: Optional[str]
    test_method: Optional[str]
    report_no: Optional[str]
    source: str                           # SWE-013 traceability
```

### Usage Matrix

| Model | Used By | Notes |
|-------|---------|-------|
| Compliance `EvidenceRef` | `MPRDetermination`, `GapSignal`, `OperationalConstraint`, `O2/H2/MUAAdapterOutput` | SHA-256 hashes, full provenance |
| MUA `EvidenceRef` | `RatingResult`, `Mitigation` in `mua_generator.py` | Bare minimum fields |
| Neither | v6 pipeline (`enriched_search.py`, `decision_engine.py`, `draft_generator.py`) | v6 uses `EnrichedMUAResult` fields directly |

---

## 5. Precedent Retrieval Mechanics

### Two Independent Search Backends

**A. MUAFAISSSearch** (`mira/miul/mua_faiss_search.py`)
- Used by v6's `enriched_search.py`
- Returns `MUASearchResult` with `semantic_score` + `string_score`
- Wraps raw FAISS L2 index over MUA BoK v2 corpus
- String matching weight configurable (default 0.4)

**B. V6PrecedentRetriever** (`mira/mua/v6/retriever.py:421-878`)
- Used by corpus endpoints (`/mua-v6/corpus/draft`)
- FAISS + BM25 hybrid with Reciprocal Rank Fusion (K=60)
- BM25 tokenization splits "6061-T6" -> `["6061-t6", "6061", "t6"]`

### Ranking Formula (`retriever.py:254-257`)

```
composite = structured_score * 0.6 + semantic_score * 0.4

structured_score = MatchFactors.weighted_score():
    0.30 * material_match
    0.25 * environment_match
    0.25 * issue_overlap
    0.10 * determination_boost
    0.10 * extraction_confidence
```

### Material Matching (`retriever.py:293-331`)

| Condition | Score |
|-----------|-------|
| Exact match (case-insensitive) | 1.0 |
| Substring match ("6061" in "6061-T6") | 0.9 |
| Same material family | 0.8 |
| Same alloy number (regex `\d{3,4}`) | 0.7 |
| Similar family (predefined matrix) | 0.5-0.6 |
| Default | 0.2 |

### Family Similarity Matrix (`retriever.py:216-224`)

```python
(STAINLESS_STEEL, CARBON_STEEL): 0.6
(STAINLESS_STEEL, NICKEL_ALLOY): 0.5
(ALUMINUM, TITANIUM): 0.4
(POLYMER, ELASTOMER): 0.5
(COATING, ADHESIVE): 0.4
(SEALANT, ADHESIVE): 0.5
```

### Environment Scoring (`retriever.py:352-383`)

```
Type match (exact) -> +0.5
Type match (compatible via matrix) -> +0.3
O2% within 5 -> +0.2 | within 10 -> +0.1
Pressure ratio * 0.15
Habitability match -> +0.15
Max: 1.0
```

### Environment Compatibility Matrix (`retriever.py:59-69`)

```
VACUUM       <-> {VACUUM}
CABIN_AIR    <-> {CABIN_AIR, AMBIENT}
ENRICHED_O2  <-> {ENRICHED_O2, CABIN_AIR, PURE_O2}
PURE_O2      <-> {PURE_O2, ENRICHED_O2, LOX_GOX}
LOX_GOX      <-> {LOX_GOX, PURE_O2}
CRYOGENIC    <-> {CRYOGENIC, LOX_GOX}
HIGH_PRESSURE<-> {HIGH_PRESSURE}
WATER        <-> {WATER}
CO2          <-> {CO2}
```

### Determination Boost (`retriever.py:406-414`)

```python
APPROVED: 1.0
DEFERRED: 0.5
CONDITIONAL: 0.5
CANCELLED: 0.2
REJECTED: 0.0
UNKNOWN: 0.3
```

### Issue Scoring (`retriever.py:385-402`)

- No issues requested -> 0.5 (neutral)
- No overlap -> 0.1 (might still be relevant)
- Overlap -> `|intersection| / |query_issues|` (Jaccard-like)

---

## 6. Requirements & Policy Application

### Critical Finding: No Explicit Standards Engine in v6

The v6 pipeline has **no module that programmatically maps NASA-STD-6001/6016 requirements to materials**. Policy enforcement is implicit:

| Mechanism | File | What It Does |
|-----------|------|-------------|
| Envelope matching | `envelope_matching.py:114` | Checks O2%/pressure/temp coverage vs precedent bounds |
| Test data currency | `maptis_test_data.py:205` | Checks `flam_dataexpireflag` (current vs expired) |
| Category routing (v1 only) | `service.py:179` | Cat I (LOX/GOX/O2>=23.5%/P>300kPa), Cat III (TVS+nonhab), else Cat II |
| Issue pattern detection | `data_cleaner.py:172` | Regex patterns classify FLAM, TOX, SCC, etc. |
| Precedent rejection | `logic_validator.py:266-280` | LLM rejects if environment less severe or mitigations missing |

### What the Compliance Module Has (But v6 Doesn't Use)

```python
# adapter_outputs.py - Category routing with audit trace
class MUAAdapterOutput(BaseModel):
    category: int                          # 1, 2, or 3
    category_rule_id: str                  # Which rule decided
    category_reasoning_trace: list[dict]   # Audit trail

# gaps.py - Typed failure signals
class GapSignal(BaseModel):
    gap_type: FailureMode                  # FLAM, HEE, TVS, SCC, TOX, O2_PROHIBITED...
    trigger: GapTrigger                    # RATING_NON_A, PROHIBITED_FAMILY, MISSING_DATA...
    severity: GapSeverity                  # CRITICAL | HIGH | MEDIUM | LOW
    policy_rule: Optional[str]             # "O2 family gate: titanium"
```

These models are never instantiated by the v6 pipeline.

---

## 7. Confidence & Gating

### Decision Engine Thresholds (`decision_engine.py:147-382`)

```
Constants:
  MIN_SUPPORTING_PRECEDENTS = 2
  MAX_GOOD_PRECEDENT_SCORE  = 1.5  (FAISS L2 distance)
```

### BLOCKED (confidence = 0.0)

```python
if supporting_count == 0:
    "No supporting (APPROVED/APPROVED_WITH_LIMITS) precedents found"
if not material_resolved:
    "Material identity could not be resolved"
if envelope_result.status == OUTSIDE:
    "Query environment completely outside all precedent tested envelopes"
```

### REVIEW_REQUIRED (confidence = 0.3)

```python
if conflicting_count > 0:
    "N conflicting (REJECTED) precedent(s) found"
if not has_current_data and has_expired_data:
    "All N MAPTIS test record(s) are expired (flam_dataexpireflag=1)"
if envelope_result.status == EXTRAPOLATION:
    "Envelope extrapolation: [specific warnings]"
if supporting_count < MIN_SUPPORTING_PRECEDENTS:  # 2
    "Only N supporting precedent(s) found, minimum 2 recommended"
```

### WARN (confidence = 0.6)

```python
if has_current_data and has_expired_data:
    "Mixed test data currency - N current, M expired records"
if not has_current and not has_expired and total_records > 0:
    "Test data currency unknown for N record(s) - flam_dataexpireflag not set"
if envelope_result.status == PARTIAL_OVERLAP:
    "Partial envelope coverage (X%) - some dimensions not fully verified"
if avg_precedent_score > MAX_GOOD_PRECEDENT_SCORE:  # 1.5
    "Average precedent similarity score N.NN indicates weak match"
```

### PROCEED (confidence = 0.85)

All checks pass. No blocking, review, or warning factors.

### Envelope Penalties (`envelope_matching.py:310-326`)

```
overlap_ratio = dims_within / dims_checked

1.0 (all within)      -> WITHIN,         penalty = 0.0
>= 2/3 (most within)  -> PARTIAL_OVERLAP, penalty = 0.15
> 0.0 (some within)   -> EXTRAPOLATION,  penalty = 0.4
0.0 (none within)     -> OUTSIDE,        penalty = 1.0
```

### Draft-Level Confidence (`draft_generator.py:265-294`)

```
HIGH:   approved_count >= 3 AND ratio >= 0.8 AND material_match
        -> confidence = 0.7 + ratio*0.25 (max 0.95)
MEDIUM: approved_count >= 1 AND ratio >= 0.5
        -> confidence = 0.5 + ratio*0.3 + 0.1 if material_match (max 0.85)
LOW:    approved_count > 0
        -> confidence = 0.4 + ratio*0.2
NONE:   -> confidence = 0.3
```

---

## 8. Drafting Constraints

### Layer 1: Rationale Extraction (`data_cleaner.py:44-152`) - ZERO HALLUCINATION

Regex patterns extract existing text from the `application` field of MUA records:

| Category | Pattern Example | What It Captures |
|----------|----------------|-----------------|
| CAUSAL | `because\s+(.{20,300}?)` | Existing justifications |
| ACCEPTABLE | `acceptable\s+(?:for\|because)` | Acceptability statements |
| SAFETY | `will\s+not\s+(?:present\|pose\|cause)` | Safety claims |
| QUANTITY | `(?:small\|negligible)\s+(?:amount\|quantity)` | Quantity mitigations |
| ISOLATION | `(?:enclosed\|sealed\|contained)` | Containment mitigations |
| COMPLIANCE | `(?:tested\|passed\|meets\|complies)` | Test/compliance statements |
| PRECEDENT | `(?:previously\|already)\s+(?:approved)` | Prior approval references |
| PROTECTION | `(?:protective\|conformal)\s+coating` | Protective measures |

All output is prefixed: `[EXTRACTED FROM APPLICATION]` or `[APPLICATION CONTEXT]`

**Never generates new technical claims.**

### Layer 2: Logic Validation (`logic_validator.py:89-353`) - LLM WITH GUARDRAILS

- **Model:** `claude-3-5-haiku-20241022`
- **Temperature:** 0 (deterministic for safety-critical)
- **Max tokens:** 2048

**Prompt rules (lines 276-280):**
- "Be CONSERVATIVE - when in doubt, reject the precedent"
- "Empty rationale = automatic rejection"
- "Approved for similar application without specifics = reject"
- "Mitigation-dependent rationale = reject unless target has same"

**FAIL-CLOSED design (lines 211-222):**
```python
except Exception as e:
    return RationaleValidationResult(is_valid=False, ...)
```

**Output:**
```python
class RationaleValidationResult(BaseModel):
    is_valid: bool                  # Can we use this rationale?
    synthesized_rationale: str      # Generated text (empty if invalid)
    citations: list[str]            # MUA numbers backing rationale
    rejected_precedents: list[str]  # MUAs whose logic didn't transfer
    rejection_reasons: dict[str, str]  # Why each was rejected
    reasoning: str                  # Chain-of-thought from LLM
```

### Layer 3: Draft Generation (`draft_generator.py:82-478`) - TEMPLATES ONLY

Issue-specific templates (lines 96-124):

```python
FLAMMABILITY: "Flammability assessment based on {num_precedents} historic precedent(s). "
              "{material} has demonstrated acceptable flammability characteristics..."
CORROSION:    "Corrosion resistance evaluated per historic usage..."
SCC:          "Stress corrosion cracking (SCC) resistance verified..."
TOXICITY:     "Toxicity assessment per NHB 8060.1..."
OFFGASSING:   "Offgassing characteristics acceptable based on {citations}."
O2_COMPAT:    "Oxygen compatibility established through precedent usage..."
```

Rationale synthesis (lines 314-358) composes from:
- Opening with precedent count and MUA numbers
- Coverage assessment (STRONG/MODERATE/WEAK)
- Issue list
- Top 3 precedent rationale excerpts (300 chars each)
- Conclusion with approved count

**No LLM involved at any point in draft generation.**

### Layer 4: Final Render (`mua_v6.py:412-455`) - SIMPLE TEMPLATE

Plain text with: MATERIAL | ENVIRONMENT | LOCATION | RATIONALE | CITATIONS + engineering review disclaimer.

### What's NOT Done

- No post-generation hallucination check
- No fact-verification against source documents
- No requirement compliance validation after drafting
- No structured output validation (draft is a raw string)

---

## 9. MUA Document Structure

### v6 Draft (15 lines)

```
MATERIAL USAGE AGREEMENT - DRAFT
Generated by MIRA v6 Precedent System
================================================================================
MATERIAL DESIGNATION: [material]
ENVIRONMENT: [env], [O2%], [PSIA], [temp]
LOCATION: Habitable / Nonhabitable
================================================================================
RATIONALE:
[LLM-synthesized from precedents]
================================================================================
PRECEDENT CITATIONS:
  - [MUA-1234]
  - [MUA-5678]
================================================================================
NOTE: This is a system-generated draft requiring engineering review.
```

### v1 Generator Document (Full NASA Format, `mua_generator.py:269-391`)

```
1) Header
   - MUA ID, timestamp, program, hardware
   - MIUL ref, MaterialKey, designator
   - Environment envelope (O2%, P, T, medium, habitable)

2) Ratings
   - Each test class with MAPTIS evidence (ID, method, report)

3) Gap Profile + Category Routing
   - Category I/II/III with Appendix B codes

4) Mitigations / Controls (ranked by score)
   - Mitigation text with clause refs
   - Source precedent with center
   - Historic precedent metadata (material codes, specs, conditions, tags, file hash)
   - Acceptance criteria (CVCM, TML, O2 thresholds)

5) Verification & Acceptance
   - Per-gap test requirements (ASTM E595, flammability testing, etc.)

6) Traceability & Citations
   - Precedent links (with PDF paths)
   - Specs and material codes
   - MAPTIS evidence IDs

7) Confidence Summary
   - Global score, 68% CI, 95% CI
   - Known unknowns list
```

---

## 10. Deterministic vs LLM Table

| Stage | Type | LLM Model | File |
|-------|------|-----------|------|
| Material resolution | Deterministic | - | `v6/material_identity.py` |
| FAISS search | Hybrid (offline embeddings) | - | `v6/enriched_search.py` |
| BM25 search | Deterministic | - | `v6/retriever.py` |
| Structured filtering | Deterministic | - | `v6/retriever.py:55-186` |
| Ranking/scoring | Deterministic | - | `v6/retriever.py:193-414` |
| Envelope matching | Deterministic | - | `v6/envelope_matching.py` |
| MAPTIS test data | Deterministic | - | `v6/maptis_test_data.py` |
| Decision engine | Deterministic | - | `v6/decision_engine.py` |
| Rationale extraction | Deterministic (regex) | - | `v6/data_cleaner.py:44-152` |
| **Logic validation** | **LLM** | **Haiku, temp=0** | **`v6/logic_validator.py`** |
| Draft generation | Deterministic (templates) | - | `v6/draft_generator.py` |
| Final rendering | Deterministic (template) | - | `mua_v6.py:412-455` |
| Post-validation | **Does not exist** | - | - |

---

## 11. Pain Points & Fragilities

### A. Architecture

1. **Two parallel systems that should be one.** The compliance module (`mira/compliance/models/`) has rich `MPRDetermination`, `GapSignal`, `OperationalConstraint`, `EvidenceRef` models. The v6 pipeline ignores them entirely. No shared orchestrator.

2. **Two evidence models with the same name.** `mira.compliance.models.evidence.EvidenceRef` (SHA-256 hashes, confidence, provenance) vs `mira.mua.models.EvidenceRef` (bare MAPTIS ID + report number). No interop.

3. **Two search backends.** `MUAFAISSSearch` (used by `enriched_search`) vs `V6PrecedentRetriever` (used by corpus endpoints). Different ranking, different features, different indexes.

### B. Confidence & Gating

4. **Hardcoded confidence tiers (0.0/0.3/0.6/0.85).** Not adaptive to actual evidence quality. 10 strong precedents = same 0.85 as 2 weak ones that happen to pass all gates.

5. **FAISS score threshold is a magic number.** `MAX_GOOD_PRECEDENT_SCORE = 1.5` has no documented empirical basis.

6. **~95% of MAPTIS data is expired.** Comment at `maptis_test_data.py:359` notes this. Most queries get "unknown currency" which triggers only WARN, not the harder REVIEW gate.

### C. Requirements

7. **No explicit NASA-STD-6001/6016 policy engine.** Requirements are never programmatically mapped to materials. No "material X failed requirement 4.3.2" output.

8. **Category routing only in v1.** The v6 `DraftGenerator` never routes to MUA Category I/II/III. The compliance module's `MUAAdapterOutput` has `category` but v6 doesn't use it.

### D. Drafting

9. **No post-generation validation.** Once the draft is rendered, nothing checks claims against source documents.

10. **v6 draft is trivially simple.** `_render_draft()` at `mua_v6.py:412` produces ~15 lines. The v1 `render_text()` at `mua_generator.py:269` produces a proper document with verification requirements, acceptance criteria, and confidence intervals.

### E. Data Quality

11. **Rationale coverage gap.** `RationaleSynthesizer` extracts from application text when rationale is NULL, but many MUA records have neither field populated.

12. **Environment type detection duplicated.** `data_cleaner.py:218-250` and `mua_v6.py:736-759` use different regex patterns with no shared logic.

13. **Material family detection duplicated.** `retriever.py:333-350` and `data_cleaner.py:257-306` have independent pattern sets.

---

## 12. File Index

| File | Lines | Role |
|------|-------|------|
| `mira/api/routers/mua_v6.py` | 783 | API router, orchestration, draft rendering |
| `mira/mua/v6/decision_engine.py` | 383 | 4-level deterministic gating |
| `mira/mua/v6/logic_validator.py` | 354 | LLM rationale transfer validation |
| `mira/mua/v6/retriever.py` | 879 | FAISS+BM25 hybrid search, filtering, ranking |
| `mira/mua/v6/enriched_search.py` | 438 | FAISS search + supporting/conflicting classification |
| `mira/mua/v6/envelope_matching.py` | 340 | O2/pressure/temp envelope verification |
| `mira/mua/v6/maptis_test_data.py` | 422 | PostgreSQL flammability data query |
| `mira/mua/v6/material_identity.py` | 307 | MAPTIS material code resolution |
| `mira/mua/v6/draft_generator.py` | 479 | Template-based MUA draft generation |
| `mira/mua/v6/data_cleaner.py` | 677 | Record cleaning, rationale extraction, classification |
| `mira/mua/v6/precedent_models.py` | ~184 | CleanedMUARecord, MatchFactors, PrecedentMatch, enums |
| `mira/mua/service.py` | 278 | v1 service layer (category routing, mitigations) |
| `mira/mua/mua_generator.py` | 439 | v1 clause-anchored full document generator |
| `mira/compliance/models/determination.py` | 297 | MPRDetermination, MPRDeterminationSet |
| `mira/compliance/models/evidence.py` | 197 | Full-featured EvidenceRef with SHA-256 |
| `mira/compliance/models/gaps.py` | 276 | GapSignal, OperationalConstraint, GapSummary |
| `mira/compliance/models/adapter_outputs.py` | 300 | O2/H2/MUA adapter output models |
| `mira/compliance/models/enums.py` | ~180 | All compliance enums |
