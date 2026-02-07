# MIRA v4 Architecture Plan: Granta-Native Redesign

## Version: 0.1.0-DRAFT
## Maintainer: Dr. Joseph Wilde / Beth (CTO)
## Date: 2026-02-05
## Classification: BoundState Proprietary
## Compliance: NASA-STD-8739.8B, NASA-STD-6016C, SWE-013, SWE-033

---

## 1. Executive Summary

MIRA v4 is a ground-up redesign that repositions Granta MI as the authoritative
typed data substrate while MIRA retains all reasoning, evidence assembly, and
compliance logic. The current architecture (FAISS-primary, PostgreSQL-secondary)
inverts to Granta-primary, FAISS-secondary (heritage validation only).

**Key architectural moves:**

- Granta MI becomes the single structured retrieval path for current material
  property data.
- Sonnet 5 replaces the current pattern-based IntentClassifier for query parsing,
  translating natural language into typed Granta API filter objects.
- FAISS shrinks to Body-of-Knowledge (BOK) heritage validation and MUA precedent
  search. It no longer drives material property retrieval.
- A new Decision Lineage artifact is emitted for every query, capturing the full
  chain from parsed intent through scored results to final recommendation.
- A recursive clarification loop replaces silent assumption injection when queries
  are underspecified.

**What does not change:**

- Evidence-first architecture (BoundState Integrity Rules).
- Deterministic O2/H2 Knowledge Twins (no LLM in safety-critical paths).
- MUA generation via extractive synthesis with explicit citations.
- All anti-hardcoding rules, PFAS detection via model attributes, property-driven
  scoring.

---

## 2. Assumptions (Flagged for Validation)

| # | Assumption | Status | Risk if Wrong |
|---|-----------|--------|---------------|
| A1 | BoundState controls the Granta extension schema (or at least a custom attribute layer) | **MUST VERIFY** | Cannot enforce typed filters; entire retrieval path breaks |
| A2 | Granta MI Python SDK supports filter queries with acceptable latency (<500ms for single material lookup) | **MUST VERIFY** | Need caching layer; cannot do real-time orchestration |
| A3 | Sonnet 5 is used strictly for parsing/routing/constrained reasoning, never for normative material judgments | Enforced by architecture | Integrity violation if breached |
| A4 | MAPTIS / O2-H2 BOK FAISS corpora are already normalized and provenance-tagged | Partially true | Heritage validation degrades if embeddings are stale |
| A5 | NCAPS migration timeline is stable enough to build against | [Unverified] | Premature redesign if timeline slips |
| A6 | Granta API rate limits are tolerable for batch operations (MIUL enrichment, M&P plan generation) | **MUST VERIFY** | Need throttling / read-through cache |
| A7 | ITAR/FedRAMP compliance for Sonnet 5 inference is achievable (NASA-hosted or GovCloud) | **MUST VERIFY** | Federal export violation if wrong |

**Action required:** Assumptions A1, A2, A6, A7 must be validated before committing
to Phase 2 implementation. Dude needs to confirm Granta API access scope and ITAR
hosting path.

---

## 3. Architecture Overview

```
                        MIRA v4 Architecture
  ┌─────────────────────────────────────────────────────────────┐
  │                      USER INTERFACE                         │
  │              (Web UI / API / Batch CLI)                     │
  └─────────────────────┬───────────────────────────────────────┘
                        │
                        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                   ORCHESTRATOR (MIRA Core)                  │
  │                                                             │
  │  ┌───────────────┐  ┌───────────────┐  ┌────────────────┐  │
  │  │ Query Parser   │  │  Clarifier    │  │ Decision       │  │
  │  │ (Sonnet 5)     │  │  (Recursive)  │  │ Lineage Emitter│  │
  │  └───────┬───────┘  └───────┬───────┘  └────────┬───────┘  │
  │          │                  │                    │           │
  │          ▼                  ▼                    ▼           │
  │  ┌──────────────────────────────────────────────────────┐   │
  │  │              SCHEMA DICTIONARY                       │   │
  │  │   (Engineer Speak → Granta Schema translation)       │   │
  │  │   "stiffness" → "Young's Modulus"                    │   │
  │  │   "strong aluminum" → material_class=Aluminum,       │   │
  │  │                       sort=UTS desc                  │   │
  │  └──────────────────────┬───────────────────────────────┘   │
  │                         │                                   │
  └─────────────────────────┼───────────────────────────────────┘
                            │
              ┌─────────────┼─────────────────┐
              │             │                 │
              ▼             ▼                 ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
  │   GRANTA MI  │ │   FAISS BOK  │ │  O2/H2 KNOWLEDGE │
  │   (Primary)  │ │  (Secondary) │ │  TWINS           │
  │              │ │              │ │  (Deterministic)  │
  │  Typed       │ │  Heritage    │ │                   │
  │  Filters     │ │  Validation  │ │  371 H2 records   │
  │  Property    │ │  MUA Precede │ │  228 O2 BOK sects │
  │  Retrieval   │ │  Fuzzy Fallb │ │                   │
  └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘
         │                │                  │
         └────────────────┼──────────────────┘
                          │
                          ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                    EVIDENCE ASSEMBLER                       │
  │                                                             │
  │  - Merges Granta property data + FAISS heritage + O2/H2    │
  │  - Applies scoring profile (environment-specific weights)   │
  │  - Detects conflicts (Granta says X, heritage says Y)       │
  │  - Calculates confidence intervals                          │
  │  - Emits Decision Lineage artifact                          │
  └─────────────────────────┬───────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
       ┌────────────┐ ┌──────────┐ ┌──────────────┐
       │ MUA        │ │ Material │ │ Compliance   │
       │ Generator  │ │ Card     │ │ Report       │
       │            │ │ Response │ │ (M&P Plan)   │
       └────────────┘ └──────────┘ └──────────────┘
```

---

## 4. Component Specifications

### 4.1 Query Parser (Sonnet 5)

**Role:** Translate natural language into typed filter objects. Not a brain. A
translator.

**What it does:**
- Extracts material class, form, environment constraints, property thresholds
- Maps engineer jargon to schema fields via the Schema Dictionary
- Assigns a confidence score to the parse
- Identifies missing constraints and flags them for clarification

**What it never does:**
- Makes material safety judgments
- Generates rationale text
- Decides compatibility
- Substitutes for missing data

**Output contract:**

```
ParsedQuery {
    intent: QueryIntent           # lookup | comparison | recommendation |
                                  # regulatory | exploratory
    filters: list[GrantaFilter]   # Typed API filter objects
    missing: list[str]            # Constraints user didn't specify
    confidence: float             # 0.0-1.0 parse confidence
    raw_query: str                # Original user text
    schema_mapping: dict          # {user_term: granta_field} for audit
}
```

**Confidence thresholding (per Gemini's recommendation):**
- confidence >= 0.90: Execute immediately, no clarification
- 0.70 <= confidence < 0.90: Execute with caveats shown to user
- confidence < 0.70: Trigger recursive clarification loop

**Integrity constraint:** Every parsed filter is logged. The user sees "I
translated your request into these filters: [Form=Sheet, Material=Al 6061].
Correct?" before execution in safety-critical contexts.

### 4.2 Schema Dictionary

**Role:** Deterministic mapping layer between engineer vocabulary and Granta
schema field names. This is NOT an LLM task; it is a hardcoded taxonomy.

**Why this exists (per Gemini):** Sonnet should not guess the mapping between
"stiffness" and "Young's Modulus" on every query. The dictionary is loaded once,
versioned, and auditable.

**Structure:**

```
SchemaDictionary {
    property_aliases: dict[str, str]     # "stiffness" -> "youngs_modulus_gpa"
    material_class_aliases: dict         # "stainless" -> material_class="Stainless Steel"
    form_aliases: dict                   # "sheet" -> form="Sheet"
    environment_aliases: dict            # "LOX" -> {o2_pct: 100, phase: "liquid"}
    unit_conversions: dict               # "ksi" -> "MPa" with factor
    version: str                         # Schema dictionary version
    last_updated: date
}
```

**Not configurable at runtime.** Changes require a versioned release. This
prevents drift between what Sonnet parses and what Granta accepts.

### 4.3 Recursive Clarification Loop

**Role:** When the query is underspecified, ask before guessing.

**Trigger conditions:**
- Parse confidence < 0.70
- Critical environment parameters missing (O2%, temperature, pressure)
- Ambiguous material class (user said "rubber" but didn't specify application)

**Behavior:**
```
User: "Show me strong aluminum"
MIRA: "I need a few more details to give you a reliable answer:
       - What form? (Sheet, Plate, Bar, Forging, Extrusion)
       - What environment? (Ambient, Oxygen-enriched, Cryogenic, Hydrogen)
       - Temperature range?
       - 'Strong' by which measure? (UTS, Yield, Fatigue life)
       Proceeding without these will return a generic ranking that
       should be reviewed by engineering."
```

**Design function unknown clause:** If the user declines to specify, the
response must include: "Design function unknown -- recommendation is generic
and should be reviewed by engineering."

**Batch/non-interactive mode:** Clarification loop is skipped. All missing
parameters are logged. Confidence is automatically penalized.

### 4.4 Granta MI Integration Layer

**Role:** Typed, filtered retrieval of current material property data. Dumb pipe.
Clean in, clean out.

**Architecture:**

```
GrantaClient {
    _sdk: GrantaMI.Session          # Granta Python SDK connection
    _cache: GrantaCache             # Read-through cache with provenance hashes
    _schema: SchemaRegistry         # Versioned schema definition

    search(filters: list[GrantaFilter]) -> list[GrantaRecord]
    get_record(record_id: str) -> GrantaRecord
    get_schema_version() -> str
    health_check() -> HealthStatus
}
```

**Caching strategy (per Fran's requirement for replay capability):**

```
GrantaCache {
    backend: Redis | SQLite          # Configurable
    ttl: timedelta                   # Default 1 hour for property data
    provenance_hash: SHA-256         # Hash of record content at cache time

    get(key, max_age) -> CachedRecord | None
    set(key, record) -> None
    invalidate(key) -> None
    get_snapshot(timestamp) -> list[CachedRecord]   # For deterministic replay
}
```

**Degraded mode policy (per Fran's requirement):**

When Granta is unavailable:
```
"Granta unavailable. Using cached data from {cache_timestamp}.
 Cache age: {hours} hours. Confidence reduced to {adjusted_confidence}.
 Results should be verified against live data before use in
 safety-critical decisions."
```

This message is mandatory. It cannot be suppressed. It appears in the Decision
Lineage artifact and in the user-facing response.

**Schema confidence metric (per Fran's requirement):**

Every record returned from Granta includes a schema completeness score:

```
SchemaCompleteness {
    total_fields: int               # Fields defined in schema
    populated_fields: int           # Fields with non-null values
    completeness_ratio: float       # populated / total
    critical_missing: list[str]     # Required fields that are NULL
    staleness: timedelta            # Age of most recent test data
}
```

**Null semantics (per Fran's requirement):**
- `UNKNOWN`: Field exists but has no data (not tested)
- `FALSE`: Field tested, result is negative/zero
- `NOT_APPLICABLE`: Field is not relevant for this material class

These are distinct values, not collapsed. UNKNOWN != FALSE != NOT_APPLICABLE.

### 4.5 FAISS Heritage Validation (Demoted)

**Previous role:** Primary search engine for all material queries.

**New role:** Secondary validation layer for:
1. O2/H2 BOK heritage checks (371 H2 records, 228 O2 sections)
2. MUA precedent search (9,734 historic MUAs)
3. Fuzzy fallback when Granta returns zero results

**Critical constraint (per Fran):** Heritage never overrides typed contradictions.

```
If Granta says flammability_rating = UNKNOWN
AND FAISS finds heritage record "approved in O2 service":

Result: "Approved under undocumented conditions; risk elevated.
         Heritage precedent found but current test data is missing.
         Recommend retesting per NASA-STD-6001B before use."
```

FAISS similarity scores never substitute for missing property values. A high
cosine similarity with a heritage MUA does not constitute evidence of
material compatibility.

**Sync requirement:** FAISS indices must be rebuilt whenever Granta schema
changes. Stale embeddings that reference fields no longer in Granta are
a silent failure mode.

### 4.6 O2/H2 Knowledge Twins (Unchanged)

**These are deterministic.** No LLM involvement. No changes needed beyond
wiring them into the new Evidence Assembler output format.

- H2 Knowledge Twin: 371 evidence records, 7-dimension envelope scoring,
  worst-case HEE band selection
- O2 Knowledge Twin: 228 BOK sections, family-based policy gates,
  material family hard rules

**Integration change:** Instead of receiving material data from PostgreSQL/FAISS,
they now receive it from the Granta integration layer (or cache in degraded mode).

### 4.7 Evidence Assembler (NEW)

**Role:** Merges evidence from all sources, applies scoring profiles, detects
conflicts, and emits the Decision Lineage artifact.

This is the component that Fran correctly identified as missing from the
proposal. Decision lineage is not a report afterthought; it is a core data
structure.

**Input sources:**
- Granta property records (typed, current)
- FAISS heritage matches (historical, similarity-scored)
- O2/H2 twin verdicts (deterministic, evidence-weighted)
- MUA precedent matches (historical, extractive)

**Output:**

```
DecisionLineage {
    query_id: UUID                              # Unique per query
    timestamp: datetime
    parsed_intent: ParsedQuery                  # What Sonnet extracted
    applied_filters: list[GrantaFilter]         # What hit Granta
    granta_records: list[GrantaRecord]          # What came back
    heritage_matches: list[HeritageMatch]       # FAISS results
    twin_verdicts: O2H2Verdict | None           # If applicable
    scoring_profile: ScoringProfile             # Which weights applied
    score_components: dict[str, ScoreDetail]    # Per-property breakdown
    unknowns: list[str]                         # What was missing
    assumptions: list[str]                       # What was assumed
    conflicts: list[EvidenceConflict]           # Granta vs heritage
    final_recommendation: MaterialRecommendation
    confidence: float
    schema_completeness: SchemaCompleteness
    cache_status: CacheStatus                   # Live vs cached
}
```

**Negative space reasoning (per Fran):**

The Evidence Assembler must handle empty results explicitly:
- "No materials meet all constraints" (with explanation of which constraint killed each candidate)
- "All candidates fail oxygen ignition threshold" (with the threshold and each candidate's value)
- "Only legacy approvals exist; no modern data" (with age of most recent test)

Silence is never an acceptable result. Absence is always explained.

### 4.8 Scoring Profiles (Preserved)

Environment-specific scoring weights are preserved from v3 without changes.
The only modification is that property values now flow from Granta records
instead of PostgreSQL/FAISS, and each scored property now carries its source
tag (Granta record ID, FAISS match ID, or twin verdict ID) in the
Decision Lineage.

---

## 5. Data Flow: Complete Query Lifecycle

```
1. User submits query
   │
2. Orchestrator receives query
   │
3. Query Parser (Sonnet 5) produces ParsedQuery
   │    - Schema Dictionary resolves aliases
   │    - Confidence score assigned
   │
4. IF confidence < 0.70:
   │    Clarification Loop engages
   │    User provides missing constraints
   │    Re-parse with augmented query
   │
5. IF confidence >= 0.70:
   │    Show user: "Interpreted as: {filters}. Correct?"
   │    (In non-interactive mode: log and proceed)
   │
6. Granta query executes
   │    - Typed filters applied
   │    - Records returned with schema completeness
   │    - Cache updated with provenance hash
   │
7. IF Granta returns zero results:
   │    FAISS fuzzy fallback engages
   │    Results marked: "No exact match in Granta.
   │    Showing heritage-based approximations."
   │
8. IF query involves O2 or H2 environment:
   │    O2/H2 Knowledge Twin executes
   │    Deterministic verdict emitted
   │
9. FAISS heritage check runs in parallel
   │    - BOK matches for safety validation
   │    - MUA precedents for compliance
   │
10. Evidence Assembler merges all sources
    │    - Conflict detection
    │    - Scoring profile applied
    │    - Confidence intervals calculated
    │    - Decision Lineage artifact emitted
    │
11. Response formatted
    │    - Material cards with evidence
    │    - Warnings and limitations prominent
    │    - Uncertainty indicators visible
    │    - UNKNOWN fields displayed, never hidden
    │
12. Decision Lineage stored
         - Immutable audit record
         - Available for IV&V review
         - SHA-256 hash of complete lineage
```

---

## 6. Integrity Verification

### Does this architecture violate BoundState Integrity Rules?

| Rule | Status | Notes |
|------|--------|-------|
| Recommendations from validated property data, not name matching | COMPLIANT | Granta returns typed fields; FAISS is validation only |
| All property comparisons transparent with cited sources | COMPLIANT | Decision Lineage traces every property to source |
| Scoring system configurable and explainable | COMPLIANT | Scoring profiles preserved; weights in lineage |
| No recommendation based solely on name or category tags | COMPLIANT | Sonnet parses to typed filters, not material names |
| Risk substitutions include confidence bounds | COMPLIANT | SchemaCompleteness + confidence intervals |
| Design intent supplied before substitution | COMPLIANT | Clarification loop enforces this |
| Fallback answers default to safe language | COMPLIANT | "More information needed" or "generic, review by engineering" |
| All substitutions logged with scoring rationale | COMPLIANT | Decision Lineage is the log |

### Critical enforcement points (per Fran):

1. Sonnet never makes material judgments -> Enforced: output is ParsedQuery (filters), not MaterialRecommendation
2. FAISS never substitutes for missing properties -> Enforced: heritage matches flagged as "undocumented conditions"
3. Schema completeness is surfaced, not hidden -> Enforced: SchemaCompleteness is in every response
4. Unknowns propagate to final answer -> Enforced: Decision Lineage.unknowns list is non-suppressible
5. All substitutions labeled unverified or conditional -> Enforced: FAISS-only results carry mandatory caveat

---

## 7. Risk Register

### 7.1 Technical Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Schema brittleness (under/over-specification) | HIGH | MEDIUM | Versioned schema with forward compatibility; nullable-but-semantic fields; schema confidence metric per record |
| Granta API latency spikes | MEDIUM | MEDIUM | Read-through cache with provenance hashes; degraded mode with mandatory user notification |
| Granta API outage | MEDIUM | LOW | Cached replay capability; explicit confidence reduction; 24-hour cache TTL for property data |
| Sonnet 5 non-deterministic filter generation | HIGH | MEDIUM | Query Inspection (show filters to user); deterministic Schema Dictionary for aliases; log every parse |
| FAISS index drift from Granta schema | MEDIUM | HIGH | Automated rebuild trigger on schema version change; hash comparison between FAISS metadata and Granta schema |
| Schema drift from Siemens/Ansys updates | MEDIUM | MEDIUM | Pin SDK version; regression tests on schema; version-locked cache |
| Data loss during MAPTIS-to-Granta migration | HIGH | MEDIUM | Checksums on migrated records; bidirectional validation; provenance trail from MAPTIS record ID to Granta record ID |

### 7.2 Operational Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Engineer fatigue from clarification loop | MEDIUM | HIGH | Confidence thresholding (only ask when <0.70); batch mode skips loop entirely |
| Downstream overtrust (clean UI = stop thinking) | HIGH | HIGH | Prominent uncertainty indicators; UNKNOWN never hidden; confidence != certainty language |
| Deterministic replay broken by cache eviction | MEDIUM | LOW | Archive Decision Lineage artifacts independently of cache; lineage is immutable once written |

### 7.3 Business / Political Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| BoundState becomes scapegoat for institutional data ambiguity | HIGH | MEDIUM | Contractual clause: "BoundState encodes what the data says, not what people wish it said." Schema governance model with clear ownership |
| Vendor lock-in perception (Siemens + BoundState + NASA) | MEDIUM | MEDIUM | Open schema definitions; exportable Decision Lineage artifacts; clear separation between data store (Granta) and reasoning (MIRA) |
| ITAR violation from Sonnet API calls with MAPTIS data | CRITICAL | LOW | Validate A7 before any implementation; NASA-hosted inference or FedRAMP High environment required |
| PO overrun if migration uncovers hidden complexity | MEDIUM | MEDIUM | Cap migration service hours; use MIRA to assist validation, not automate fully; phased delivery with go/no-go gates |

---

## 8. Schema Governance Model

### Who owns truth after migration?

This must be contractual, not implied:

- **Granta** owns the typed data store. Siemens/Ansys maintains the platform.
- **NCAPS/NASA** owns the data content. They are the data stewards.
- **BoundState** owns the intelligence layer (MIRA). We encode what the data
  says. We do not resolve institutional disagreements about what the data
  should say.

### Conflicting legacy interpretations:

When MAPTIS record A says one thing and MAPTIS record B says another, the
migration service documents both, flags the conflict, and routes it to
the responsible M&P engineer for resolution. BoundState does not pick a
winner.

### SME disagreement protocol:

When two SMEs disagree about a material classification:
1. Both positions are recorded with attribution
2. The more conservative position is used as the default
3. The conflict is surfaced in any Decision Lineage that touches the material
4. Resolution authority belongs to the program M&P lead, not BoundState

---

## 9. Phase Plan

### Phase 1: Foundation (Months 1-2, current PO)

- [ ] Validate assumptions A1, A2, A6, A7
- [ ] Build GrantaClient with SDK integration
- [ ] Build GrantaCache with provenance hashing
- [ ] Build Schema Dictionary v1 (top 200 engineer terms)
- [ ] Build Decision Lineage data model
- [ ] Stress-test with 5 pathological queries (see Section 10)
- [ ] Define schema governance contract language

### Phase 2: MIRA Integration (Months 3-5, $350K PO)

- [ ] Wire Granta retrieval into MIRA orchestrator
- [ ] Integrate Sonnet 5 query parser with Schema Dictionary
- [ ] Build Evidence Assembler
- [ ] Rewire O2/H2 twins to consume Granta records
- [ ] Demote FAISS to heritage-only role
- [ ] Build recursive clarification loop
- [ ] Implement Query Inspection UI
- [ ] Build degraded mode with mandatory notifications

### Phase 3: Full NASA DBs (Months 6-12, new PO required)

- [ ] Extend schema to additional NASA databases
- [ ] Build BoundState migration service offering
- [ ] Multi-center deployment
- [ ] Scale to 100+ concurrent users
- [ ] Formal NASA IV&V review of Decision Lineage

---

## 10. Stress Test Queries (Pre-Implementation)

Per Fran's recommendation, walk these 5 pathological queries through the
full architecture before writing code:

### Query 1: Underspecified
"What's a good material for my valve?"

Expected behavior: Clarification loop fires. Missing: fluid medium,
temperature, pressure, material class preference, form. Confidence < 0.30.

### Query 2: Contradictory
"I need a lightweight titanium for LOX service"

Expected behavior: O2 twin fires PROHIBITED for titanium family.
Response: "Titanium is prohibited in LOX service per NASA-STD-6001B
regardless of weight requirements. Alternative lightweight materials
for LOX: [Granta query for Al alloys with LOX compatibility data]."

### Query 3: Legacy-only
"Has anyone used Viton in hydrogen service?"

Expected behavior: Granta returns Viton records (if migrated). FAISS
heritage check finds historical MUAs. H2 twin assesses based on
material family (fluoroelastomer). Response includes heritage with
caveat: "Legacy approvals found. No current test data in Granta
for H2 service. Modern retest recommended."

### Query 4: No valid answer
"Find me a polymer that passes both LOX and hydrogen at 5000 psi"

Expected behavior: Granta query returns candidates. O2 and H2 twins
both evaluate. Likely result: no material passes both gates. Response:
"No materials in the database meet all constraints simultaneously.
[Show nearest candidates with which constraint each fails.]"

### Query 5: Mixed O2/H2 with partial data
"Is Inconel 718 safe for our LOX/GH2 turbopump?"

Expected behavior: Both twins fire. Granta returns full property record.
Heritage check finds extensive precedent. But: some properties may have
schema gaps. Response includes full evidence with explicit gap list:
"Inconel 718 has [N] test records for LOX and [M] for H2.
Schema completeness: 87%. Missing: [list fields].
Heritage: [N] approved MUAs for similar applications."

---

## 11. Open Questions Requiring Dude's Input

1. **Granta SDK access**: Do we have the Python SDK license? Can we
   hit a test instance? What's the authentication model?

2. **ITAR hosting**: Where will Sonnet 5 inference run? NASA on-prem?
   AWS GovCloud? This is a hard blocker.

3. **Schema ownership**: Has NCAPS defined who approves schema changes?
   Or are we designing that governance model as part of the BoundState
   offering?

4. **Migration scope**: Are we migrating all of MAPTIS or a subset?
   What's the record count estimate for Phase 2?

5. **Budget for Phase 3**: Is the new PO secured or speculative?
   This affects how much Phase 2 work we scope defensively.

6. **Query Inspection UX**: How much friction are engineers willing to
   tolerate? Should filter confirmation be opt-in (settings toggle)
   or mandatory for safety-critical queries only?

---

## 12. Module Map (New Package Structure)

```
boundstate/
├── api/                        # FastAPI endpoints
│   ├── main.py
│   ├── routes/
│   │   ├── search.py           # Material search (Granta-primary)
│   │   ├── mua.py              # MUA generation
│   │   ├── compliance.py       # 6016C compliance checks
│   │   └── health.py           # Health + degraded mode status
│   └── middleware/
│       └── lineage.py          # Decision Lineage injection
│
├── core/                       # Business logic
│   ├── orchestrator.py         # Main query orchestration
│   ├── evidence_assembler.py   # NEW: Multi-source evidence merge
│   ├── clarifier.py            # NEW: Recursive clarification loop
│   ├── scoring.py              # Scoring profiles (preserved)
│   ├── o2_twin.py              # O2 Knowledge Twin (preserved)
│   ├── h2_twin.py              # H2 Knowledge Twin (preserved)
│   └── mua_generator.py        # MUA synthesis (preserved)
│
├── granta/                     # NEW: Granta integration layer
│   ├── client.py               # GrantaClient (SDK wrapper)
│   ├── cache.py                # Read-through cache + provenance
│   ├── schema_registry.py      # Versioned schema definition
│   ├── schema_dictionary.py    # Engineer-speak translation
│   └── filters.py              # Typed filter objects
│
├── nlp/                        # Query parsing
│   ├── query_parser.py         # Sonnet 5 parser (replaces IntentClassifier)
│   └── confidence.py           # Parse confidence scoring
│
├── heritage/                   # FAISS (demoted)
│   ├── bok_validator.py        # O2/H2 BOK heritage checks
│   ├── mua_precedent.py        # Historic MUA search
│   └── faiss_store.py          # FAISS index management
│
├── lineage/                    # NEW: Decision audit trail
│   ├── models.py               # DecisionLineage data model
│   ├── emitter.py              # Lineage construction
│   └── store.py                # Immutable lineage storage
│
├── risk/                       # Risk analyzers (preserved)
│   ├── pfas_detector.py        # Model-attribute PFAS detection
│   └── negative_space.py       # NEW: Empty-result explanation
│
├── data/                       # Pydantic models
│   ├── query.py                # ParsedQuery, GrantaFilter
│   ├── evidence.py             # EvidenceRow, EvidenceConflict
│   ├── recommendation.py       # MaterialRecommendation
│   ├── granta_record.py        # GrantaRecord, SchemaCompleteness
│   └── lineage.py              # DecisionLineage model
│
├── skills/                     # Knowledge base (preserved)
└── utils/                      # Helpers
```

---

## 13. What We Are NOT Changing

Explicit list of preserved components to prevent scope creep:

- MUA generation pipeline (extractive synthesis with citations)
- O2/H2 Knowledge Twins (deterministic, no LLM)
- Scoring profile weights and structure
- PFAS detection via model attributes (no string matching)
- BoundState Integrity Rules (all preserved, all enforced)
- Evidence Schema (citation requirements, conflict detection)
- NASA-STD-6016C compliance routing (Category I/II/III)
- MUA Writing Skills (templates, envelopes, citation format)

These are working. Don't touch them.
