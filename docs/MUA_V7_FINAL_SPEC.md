# MUA v7 Writer — Final Specification
## Post-Oracle Convergence Build Document

**Date:** 2026-02-07  
**Status:** LOCKED — Ready for Implementation  
**Oracle Inputs:** Fran (schema), CC (implementation), Grok (stress test), Gemini (edge cases), Beth (architecture)  
**Decision Authority:** Dude

---

## Design Philosophy

### The 80/20 Contract
MIRA does 80% of the work: searching, matching, comparing, classifying, explaining, writing, formatting.  
The engineer does 20%: deciding.

### Core Principles (From MIUL v4)
1. **One pipeline, not six.** Kill the tabs. One confident path beats six tentative ones.
2. **MIRA does the legwork, engineer does the judgment.** Same rigor. Fraction of the time.
3. **Human-in-the-loop IS the feature.** Not a safety net — the architecture.
4. **Evidence-first always.** Every claim traceable to source. Every gap surfaced.
5. **"May be applicable" — never "is approved."** MIRA presents evidence and explains fit. It never makes the determination.
6. **Respectful language.** "Could use your expertise" — not "ERROR: REVIEW REQUIRED."

### The Flow
```
MIRA explains the evidence
    → Engineer makes calls
        → MIRA explains the logic of those calls back in document form
            → Engineer validates or corrects
```

At no point does MIRA say "this is approved." It says "based on your decisions about this evidence, here's the case for approval, written in the language NASA expects."

The engineer owns the judgment. MIRA owns the legwork. The document shows both.

---

## Architecture Overview

### Single 5-Step Wizard
```
DEFINE → INVESTIGATE → REVIEW → DRAFT → FINALIZE
```

Replaces 6 independent tabs with one linear workflow.

### File Structure
```
mira/mua/v7/
├── __init__.py
├── session.py              # Pydantic session model (5-step state)
├── investigator.py         # Step 2: unified search + evidence gathering
├── conflict_detector.py    # Cross-source conflict detection
├── category_router.py      # NASA-STD-6016C routing (AuthorityPack interface)
├── material_resolver.py    # Lookup-table based (no regex)
├── draft_renderer.py       # 7-section NASA document (template-first)
├── fact_checker.py         # Post-generation claim verification
├── confidence.py           # Evidence Strength calculator
├── process_sensitivity.py  # Step 1b: adhesive/composite process params
└── models.py               # v7-specific request/response models
```

### What v7 Imports (Don't Rewrite)
- `v6/retriever.py` — V6PrecedentRetriever (FAISS+BM25+RRF) — best search we have
- `v6/envelope_matching.py` — compute_envelope_overlap (with temp_min fix applied)
- `v6/data_cleaner.py` — RationaleSynthesizer, V6DataCleaner
- `v6/maptis_test_data.py` — query_maptis_test_data
- `v6/material_identity.py` — resolve_material_identity
- `compliance/models/evidence.py` — EvidenceRef (promoted as unified model)
- `compliance/models/gaps.py` — GapSignal, OperationalConstraint
- `compliance/models/determination.py` — MPRDetermination

### What v7 Retires (After Validation)
- `mua/service.py` (v1 service) — routing logic extracted to category_router.py
- `mua/mua_generator.py` (v1 generator) — templates extracted to draft_renderer.py
- `api/routers/mua_v6.py` (v6 router) — replaced by v7 endpoints
- All 6 frontend tabs — replaced by single wizard

### Migration Strategy
- v7 runs parallel at `/api/mua/v7/` and `/mua-v7` frontend route
- v6 endpoints get deprecation warnings
- Legacy tabs moved behind "Advanced / Legacy" accordion with banner: *"Legacy mode: does not enforce v7 safety gates"*
- After 1 sprint with no v6 traffic, remove v6 router

---

## Step 1: DEFINE

### What the Engineer Does
Types material, fills environment, describes application.

### Material Resolution
Live resolution against lookup table (not regex — fixes H3/H4):
- 🟢 Green checkmark = resolved to MAPTIS code
- 🟡 Yellow = fuzzy match, engineer picks from suggestions
- 🔴 Red = unresolved, needs manual input

**Input validation:**
- Standard designations (AMS/AISI/UNS patterns) accepted
- Generic terms ("aluminum" without alloy) → yellow, show suggestions
- Non-materials ("material per drawing note 7") → red, prompt: *"This doesn't appear to be a material designation. Please enter an alloy or specification."*
- Garbage ("asdf") → red, blocks Investigate

### Environment Fields
| Field | Required | Notes |
|-------|----------|-------|
| O2 concentration (%) | Yes | ≥23.5% triggers enrichment banner |
| Pressure (PSIA) | Yes | Missing = blocks Investigate for O2/H2 service |
| Temperature min (°F) | **Yes** | Fixes C4: both bounds required |
| Temperature max (°F) | **Yes** | Fixes C4: both bounds required |
| Medium | Yes | Dropdown: Air, GOX, LOX, GH2, LH2, GN2, etc. |
| Location | Yes | Habitable / Non-habitable / External |
| Application | Yes | Free text describing use case |

**Smart defaults by location:**
- Habitable → 21% O2, 14.7 PSIA, 60-85°F, Air
- Engineer can override any default

**Banners (immediate, deterministic):**
- O2 ≥ 23.5% → 🟡 *"Enriched oxygen environment — Category I routing applies"*
- Temp min ≤ -150°F → 🟡 *"Cryogenic range — verify material compatibility below -150°F"*
- Medium = GH2/LH2 → 🟡 *"Hydrogen service — embrittlement assessment required"*

### Step 1b: Process Definition (Conditional)

**Trigger:** Material class resolves to Adhesive, Composite, Potting, or Sealant.

**Additional fields (when triggered):**
| Field | Required | Notes |
|-------|----------|-------|
| Cure temperature (°F) | Yes | Process-critical for adhesives |
| Cure time (min) | Yes | Process-critical for adhesives |
| Cure pressure (psi) | If applicable | Vacuum bag, autoclave |
| Mix ratio | If applicable | Two-part systems |
| Layup orientation | If applicable | Composites only |

These process parameters feed into precedent matching — a 250°F/60min cure precedent is flagged as *potentially* non-equivalent to a 350°F/30min cure application.

### Center Selection
- Default: MSFC (current deployment)
- Dropdown: MSFC, JSC, GRC, KSC (future)
- Loads AuthorityPack for center-specific routing and templates
- v7 launch: MSFC only. Interface built for all.

### Session Created
On "Continue to Investigate" → session row created in PostgreSQL.

---

## Step 2: INVESTIGATE

### What MIRA Does
Runs all evidence sources in parallel. Returns results WITH explanations of how each one relates to the new MUA.

### Backend Pipeline
```python
async def investigate(session: MuaSession) -> InvestigationResult:
    # 1. Material identity (from Step 1, cached)
    identity = session.inputs.material_resolution

    # 2. Check Redis cache (common materials)
    cache_key = f"{identity.material_code}:{hash(session.inputs.environment)}"
    cached = await redis.get(cache_key)
    if cached:
        return deserialize(cached)

    # 3. Parallel evidence gathering
    precedents, test_data, envelope = await asyncio.gather(
        search_precedents_unified(identity, session.inputs.environment),
        query_maptis_test_data(identity.material_code),
        compute_envelope_overlap(identity, session.inputs.environment),
    )

    # 4. Classify supporting/conflicting
    supporting = [m for m in precedents if m.determination in SUPPORTING_SET]
    conflicting = [m for m in precedents if m.determination in CONFLICTING_SET]

    # 5. Conflict detection (cross-source)
    conflicts = detect_conflicts(supporting, conflicting, test_data)

    # 6. Gap identification
    gaps = identify_gaps(envelope, test_data, session.inputs.environment)

    # 7. Dependency check (zombie MUA detection)
    dependency_warnings = check_precedent_dependencies(supporting)

    # 8. Evidence Strength calculation
    strength = calculate_evidence_strength(
        supporting, conflicting, test_data, envelope, conflicts, gaps
    )

    # 9. Category routing (preliminary)
    category = route_category(session.inputs.environment, test_data, gaps)

    # 10. Generate per-precedent explanations
    explanations = generate_relationship_explanations(
        precedents, session.inputs, identity
    )

    # 11. Zero-precedent detection
    if len(supporting) == 0 and not test_data.has_current:
        novel_material_flag = True

    result = InvestigationResult(...)

    # Cache for 24 hours (test data doesn't change hourly)
    await redis.setex(cache_key, 86400, serialize(result))

    return result
```

### Search Backend
V6PrecedentRetriever (FAISS+BM25+RRF hybrid) with supporting/conflicting classification as post-filter. No new search backend needed.

**Boost policy (v7):** Relevance boosts capped at 1.0. Boosts are tiebreakers between similar results, not promoters of weak matches. A 0.55 base relevance stays 0.55. The engineer evaluates each result in Review with full context — they don't need inflated scores telling them garbage is relevant.

**Why 1.0 cap:** The safety audit showed a titanium prohibition document (0.55 base) getting boosted to 2.47 via stacked keyword multipliers, outranking actual Inconel 718 precedents (0.85 base). In safety-critical flight hardware, the boost mechanism should never override the fundamental relevance signal. CC's 3.0/2.0 cap was right for the live hotfix. v7 does it right.

### What the Engineer Sees

**Summary banner:**
> "14 precedents found (12 supporting, 2 conflicting). MAPTIS test data: 8 current, 23 expired."  
> **Evidence Strength: MODERATE**  
> "3 items could use your expertise."

**Per-precedent explanations (the core innovation):**

Each precedent comes with a plain-English explanation of HOW it fits the new MUA:

> **MUA-2022-087** — Inconel 718, 25% O2, 3200 psi, -40°F to 400°F  
> *"Strong analog. Same alloy, similar enriched O2 environment. Pressure envelope covers your requirement. Temperature range partially covers — your -100°F lower bound extends beyond tested range. May require cryogenic gap disposition."*

> **MUA-2019-145** — Inconel 718, Ambient Air, 5000 psi  
> *"Same alloy at higher pressure, but ambient O2 only. Pressure data may support your case. O2 environment does not — ambient air precedent cannot justify enriched O2 service without additional evidence."*

> **MUA-2017-033** — Inconel 625, 30% O2, 2800 psi  
> *"Different alloy, same family (nickel superalloy). Exact O2 match. Lower pressure. May be applicable as family analog if 718-specific precedent is insufficient — alloy substitution requires engineering justification."*

> **⚠️ MUA-2020-091** — Inconel 718, 28% O2, 3000 psi — CONFLICTING  
> *"Approved with restrictions: limited to non-structural applications due to SCC concerns at elevated O2. If your application is structural, this precedent opposes your case."*

For process-sensitive materials (adhesives/composites), explanations include process comparison:

> **MUA-2021-112** — Epibond 1590, LOX-adjacent, 250°F/60min cure  
> *"Process parameters match your specification. May be applicable as direct precedent."*

> **MUA-2018-067** — Epibond 1590, GOX service, 350°F/30min cure  
> *"Same material, different cure cycle (350°F vs your 250°F). May be applicable as analog — higher cure temp generally improves cross-linking but changes flexibility. Engineering judgment needed on equivalency."*

**Key language discipline:** Always "may be applicable," never "is approved." MIRA did the legwork. It found them, matched them, compared environments, flagged differences, and explained why the differences might matter. The determination is the engineer's.

### Relevance Split: Physics vs. Regulatory

Old precedents get two-dimensional relevance tags:

> **MUA-1995-014** — 6061-T6, Shuttle program  
> Physics Relevance: HIGH *(Flammability test data still valid — physics hasn't changed)*  
> Regulatory Relevance: LOW *(Approved under NASA-STD-6016A — approval logic obsolete, current standard is 6016C)*

UI tag: *"Valid Test Data / Obsolete Approval Logic"*

### Zero-Precedent Detection (Novel Materials)

If MIRA finds zero supporting precedents AND no current MAPTIS test data:

> 🔵 *"This appears to be a novel material with no established precedent history. Would you like to switch to Qualification Plan Mode?"*

**Qualification Plan Mode** generates a test plan recommendation instead of an MUA:
- Lists required tests based on environment (flammability, offgassing, SCC, corrosion, etc.)
- Cites applicable test standards (NASA-STD-6001 test numbers)
- Provides test condition recommendations based on Step 1 environment definition
- Output: "Usage Agreement Pending Test" — actionable, not a dead end

### Evidence Strength (Not "Confidence")

**Renamed from "confidence" — Fran and Grok converged on this independently.**

"Confidence: 0.72" makes engineers think "72% chance I'm right."  
"Evidence Strength: MODERATE" makes them think "I should look at the gaps."

**Calculation (Fran's formula):**

```
EvidenceStrength = clamp(0, 1,
    wP × PrecedentSupport +
    wT × TestCoverage +
    wE × EnvelopeCoverage +
    wC × Currency +
    wK × Consistency
) × Penalties
```

**Components:**

| Component | Weight | Calculation |
|-----------|--------|-------------|
| PrecedentSupport (wP) | 0.30 | `1 - exp(-k × Σ(relevance_i × authority_i))` — saturates naturally, 20 mediocre precedents can't fake "perfect" |
| TestCoverage (wT) | 0.25 | Per required dimension (flamm, SCC, corr, TVS, tox, FS): A/B=high, missing=0, analog=partial |
| EnvelopeCoverage (wE) | 0.20 | Per dimension (temp, pressure, O2%, phase): within=1.0, partial=0.6, extrapolation=0.2, insufficient=0.0. Take weighted min. |
| Currency (wC) | 0.10 | Split: data_currency (current=1.0, expired=0.4, unknown=0.2) + regulatory_currency (post-current-standard=1.0, pre-current-standard=decay function) |
| Consistency (wK) | 0.15 | No conflicts=1.0, soft conflict=0.7, hard conflict=0.4 |

**Penalties (multiplicative):**
- Gap severity: `exp(-g × gap_severity_sum)`
- Unresolved material: × 0.5
- Missing critical field (pressure in H2, temp bounds): × 0.0 → forces REVIEW

**Output:**
- `EvidenceStrengthScore`: 0.0 – 1.0 (for audit, secondary display)
- `EvidenceStrengthBand`: STRONG / MODERATE / WEAK (primary display)

**UI:** Band shown prominently. Score available on hover/expand. Component breakdown available in detail view so engineer can see *why* — "Precedent support is strong (0.88) but envelope coverage is partial (0.45) due to cryogenic gap."

---

## Step 3: REVIEW

### What the Engineer Does
Reviews flagged items. Makes judgment calls. MIRA pre-included the easy ones.

### Review Queue

**Summary:**
> *"MIRA gathered 35 evidence items. 3 could use your expertise."*

**Pre-included (no action needed):**
- 12 supporting precedents with strong relevance → pre-checked ✅
- Engineer can uncheck any they disagree with

**Flagged for review (engineer decides):**

**Conflicting evidence** — 3 choices per item:
- Include as supporting (override conflict — rationale required)
- Include as context (mention in MUA but not as basis)
- Exclude (not relevant to this case)

**Gaps** — 2 choices per gap:
- Accept with rationale (engineer explains why gap is acceptable)
- Flag for testing (gap becomes a verification requirement in the MUA)

**Dependency warnings** (if any):
- "MUA-2022-087 cites MUA-2019-033, which was restricted in 2024. Review dependency."

### HITL on Relevance (Not on Boosts)

The engineer never sees "boost factor 1.3x on keyword match." They see:

> **Why MIRA thinks this is relevant:**  
> *"Same alloy family, similar O2 environment, tested to 3500 psi"*
>
> **Why it might NOT be relevant:**  
> *"Tested at ambient temperature only — your environment includes cryogenic range"*
>
> **Your call:** Include as supporting / Include as context / Exclude

MIRA explains its reasoning in plain English. The engineer validates or overrides the *outcome*. The boost mechanism stays internal. Include/exclude decisions implicitly correct the ranking — and over time, those corrections become training gold labels.

### Divergence Tracking (Silent Rollout)

**When the engineer's decision opposes the Evidence Strength band:**
- AI says STRONG + engineer rejects → high-value signal (AI missed something)
- AI says WEAK + engineer approves → high-risk signal (possible rubber-stamping)

**Mechanism:** Rationale field becomes **mandatory** when human decision diverges from AI recommendation. These rationales are stored as calibration gold labels for model improvement.

**Rollout:** Silent. No UI indicator of tracking. Engineers just see the mandatory rationale field. The system gets smarter over time. They get better recommendations and never know why — they just think MIRA keeps improving. Which it does.

### Completion Gate
"Generate Draft" button disabled until all flagged items reviewed.

Progress bar: *"2 of 3 items reviewed"* — approachable, not intimidating.

---

## Step 4: DRAFT

### What MIRA Does
Writes the full MUA document. Explains its own reasoning chain. Engineer reads, edits, corrects.

### Two-Layer Generation
1. **Template-based structure** (deterministic, from v1 generator) — always produces valid output
2. **LLM polish** (Sonnet for natural language) — enhancement, not dependency

If LLM fails → template version is still a valid NASA MUA. No blocked workflows.

### The Reasoning Chain (Core Innovation)

The draft doesn't just cite precedents — it explains the logic behind every decision the engineer made in Step 3:

> **Section 4: Rationale**
>
> *Inconel 718 has demonstrated acceptable performance in enriched oxygen environments based on 12 supporting precedents spanning 25–32% O2 concentrations at pressures from 2800 to 5000 psi. Primary basis: MUA-2022-087 (25% O2, 3200 psi), which provides the closest environmental match to the current application.*
>
> *Pressure adequacy is supported by MUA-2022-087 (3200 psi, direct coverage) and MUA-2019-145 (5000 psi, exceeds requirement). O2 concentration of 30% extends slightly beyond the closest direct precedent (25%) but falls within the range established by family analog MUA-2017-033 (Inconel 625 at 30% O2).*
>
> *A cryogenic gap exists: the lowest tested temperature in the precedent set is -40°F, while the current application specifies -100°F. This gap was accepted by the reviewing engineer based on: "[engineer's rationale from Step 3]". Recommend verification testing per NASA-STD-6001 Test 17 to close this gap definitively.*
>
> *One conflicting precedent (MUA-2020-091) identified SCC restrictions for structural applications at 28% O2. The current application is non-structural. This restriction does not apply.*

**What happened:** Every decision from Step 3 shows up with its reasoning. The engineer's gap acceptance rationale gets quoted. The conflict disposition gets explained. The precedent selection logic is transparent.

The engineer reads the draft and recognizes their own thinking — structured into NASA-format language with proper citations. They didn't write it, but every judgment call is theirs.

### Full NASA 7-Section Document Format

| Section | Content | Source |
|---------|---------|--------|
| 1. Header | MUA ID, program, material (resolved), environment, category | Session state |
| 2. Ratings | Per test class with MAPTIS evidence and currency flags | Test data + evidence |
| 3. Gap Profile | Identified gaps + engineer dispositions + category routing | Gaps + review decisions |
| 4. Rationale | Synthesized reasoning chain with precedent citations | Review decisions + evidence |
| 5. Mitigations/Controls | Operational constraints derived from gaps and conflicts | Gap decisions + category |
| 6. Verification Requirements | Required tests to close gaps | Gap decisions flagged for testing |
| 7. Traceability & Citations | Every evidence item cited, linked to source | Evidence bundle |

For process-sensitive materials, Section 4 includes process constraints:

> *"This approval is limited to Epibond 1590 cured at 250°F ± 10°F for 60 ± 5 minutes. Alternative cure cycles have not been evaluated and require separate assessment."*

### Fact Verification (Deterministic)

Anchored to Fran's AtomicClaim model. Every evidence item has structured assertions (RATING, ENVELOPE, DETERMINATION, CONSTRAINT, etc.).

**Verifiable claims (checked automatically):**
- "10 approved precedents" → count DETERMINATION claims where status=APPROVED
- "FLAMM rating: A" → match against MAPTIS RATING assertion
- "MUA-2022-087" → confirm in included evidence set
- "Tested to 3200 psi" → verify ENVELOPE assertion value

**Judgment claims (tagged, not verified):**
- "Material demonstrates acceptable performance" → tagged *(Engineering assessment)*
- "Cure cycle equivalency accepted" → tagged *(Engineering judgment — see Step 3 rationale)*

The fact checker never rubber-stamps. Atomic claims get verified deterministically. Judgment claims get flagged transparently.

### Inline Editing
- Click any sentence to edit
- Engineer edits tracked in audit trail (sentence-level diffs)
- Gap decisions appear IN rationale text
- If engineer changes a factual claim, fact checker re-verifies
- Claim-to-evidence links preserved through edits

---

## Step 5: FINALIZE

### What the Engineer Does
Reviews audit trail. Signs off. Exports.

### Audit Trail (Visible)
```
Evidence items reviewed:     3 of 3 ✓
Gap decisions documented:    2 of 2 ✓
Conflicts addressed:         1 of 1 ✓
Rationale edits:             1 (sentence 7 modified)
Fact verification:           12 claims verified, 2 tagged as judgment
Evidence Strength:           MODERATE (0.68)
Category:                    I (enriched O2)
Applied standard:            NASA-STD-6016C Rev. 3
```

### Reviewer Certification
- Name + date + *"I have reviewed the evidence and approve this MUA"*
- SWE-013 compliance evidence captured

### Export Options
- Copy to clipboard
- NASA-format document (PDF/DOCX — future)
- Export to MIUL (populate Remarks column)
- Save draft (resume later via session)

### Metadata Recorded
- `applied_standard_version`: "NASA-STD-6016C" — for regulatory drift tracking
- `center`: MSFC (or future center)
- `authority_pack_version`: hash of routing rules used
- `evidence_bundle_id`: frozen snapshot of what investigation found
- `compute_manifest`: model versions, index versions, DB snapshot
- `dependency_links`: which precedent MUAs were cited (for zombie detection)
- `session_id`: link back to full decision history

---

## Data Models (Fran's Schema)

### Unified EvidenceRef (Two-Tier Identity)

```python
class EvidenceRef(BaseModel):
    # Identity — content-addressed when possible, deterministic ID when not
    evidence_id: str  # Tier A: sha256 of canonical payload
                      # Tier B: sha256(f"{source_type}:{primary_id}:{locator}:{span}")

    source_type: SourceType  # MAPTIS_TEST, MUA_CORPUS, BOK_REQUIREMENT,
                             # STANDARD_SECTION, REPORT_PDF, USER_NOTE

    source_locator: SourceLocator  # Typed per source_type
    excerpt: Optional[Excerpt]     # text + span/bbox

    # Structured assertions (anchors for fact checking)
    assertions: list[AtomicClaim]

    # Quality scores (split currency)
    quality: EvidenceQuality

    # Provenance
    provenance_chain: Optional[list[str]]  # evidence_ids of parent items
```

### AtomicClaim

```python
class AtomicClaim(BaseModel):
    claim_type: ClaimType  # RATING, ENVELOPE, DETERMINATION, MITIGATION,
                           # CONSTRAINT, APPLICABILITY, PROHIBITION
    subject: str           # material_key / property / environment dimension
    value: Any             # typed per claim_type
    qualifiers: dict       # units, bounds, conditions
```

### EvidenceQuality

```python
class EvidenceQuality(BaseModel):
    relevance_score: float        # 0–1
    physics_relevance: float      # 0–1 (test data validity — age-resistant)
    regulatory_relevance: float   # 0–1 (approval logic validity — decays with standard revisions)
    authority_score: float        # 0–1
    data_currency: float          # 0–1 (current/expired/unknown)
    regulatory_currency: float    # 0–1 (post-current-standard / pre-current-standard)
    completeness_score: float     # 0–1
    conflicts_with: list[str]     # evidence_ids
```

### Session State (PostgreSQL + Pydantic)

```sql
CREATE TABLE mua_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    current_step TEXT NOT NULL DEFAULT 'define',
    status TEXT NOT NULL DEFAULT 'active',
    center TEXT DEFAULT 'MSFC',

    -- Step 1
    material TEXT,
    environment JSONB,
    process_params JSONB,          -- Step 1b (adhesives/composites)
    application TEXT,

    -- Step 2 (cached investigation)
    investigation_result JSONB,

    -- Step 3 (human decisions)
    review_decisions JSONB,
    divergence_labels JSONB,       -- Silent: gold labels for calibration

    -- Step 4
    draft_text TEXT,
    draft_metadata JSONB,
    edit_history JSONB DEFAULT '[]'::jsonb,
    fact_check_report JSONB,

    -- Step 5
    finalized_at TIMESTAMPTZ,
    reviewer TEXT,
    applied_standard_version TEXT,
    dependency_links JSONB,
    export_format TEXT
);

CREATE INDEX idx_mua_sessions_user ON mua_sessions(created_by, status);
CREATE INDEX idx_mua_sessions_updated ON mua_sessions(updated_at);
```

### Category Routing

```python
class CategoryRoutingResult(BaseModel):
    category: Literal["I", "II", "III"]
    routing_basis: list[RoutingRuleHit]  # rule_id + explanation + citation
    required_approvals: list[ApprovalGate]
    required_verifications: list[VerificationRequirement]
    authority_pack: str             # "NASA-STD-6016C" (future: ECSS-Q-ST-70)
    authority_pack_version: str     # hash of routing rules
```

**Propagation:**
- Step 1: Preliminary flags (O2 enrichment banner)
- Step 2: Provisional category (based on evidence + ratings)
- Step 3: Category can change via gap decisions (accepting analog data may keep Cat III vs forcing Cat II)
- Step 5: Category locked and recorded with standard version

---

## API Surface

### Endpoints

```
POST /api/mua/v7/resolve-material     # Live material resolution
POST /api/mua/v7/investigate           # Step 2: full evidence gathering
POST /api/mua/v7/review-decisions      # Step 3: save review decisions
POST /api/mua/v7/generate-draft        # Step 4: generate MUA document
POST /api/mua/v7/finalize              # Step 5: lock + export

GET  /api/mua/v7/session/{id}          # Resume session
GET  /api/mua/v7/sessions              # List user's sessions
GET  /api/mua/v7/stats                 # Usage analytics

POST /api/mua/v7/qualification-plan    # Novel material → test plan
```

Session state is server-side. URL params track step + session ID.

---

## Frontend Components

Replace 2,917-line `MUAGenerator.tsx` with ~1,000 lines total:

```
frontend/src/pages/
├── MUAWizardV7.tsx              # Step router + session management (~200 lines)
├── components/mua-v7/
│   ├── MUADefineStep.tsx        # Material + env + process (~150 lines)
│   ├── MUAInvestigateStep.tsx   # Evidence results + explanations (~200 lines)
│   ├── MUAReviewStep.tsx        # Per-item decisions (~200 lines)
│   ├── MUADraftStep.tsx         # Draft + inline editing (~150 lines)
│   └── MUAFinalizeStep.tsx      # Audit trail + export (~100 lines)
```

**State management:** URL params + React context. Same pattern as DTTreeEditor. Server is source of truth.

**Route:** `/mua-v7?step=investigate&session=abc123`

---

## Safety Fixes (P0 — Before Redesign)

Applied to CURRENT codebase. No API contract changes.

| Fix | Status | File | Change |
|-----|--------|------|--------|
| C1: Boost cap | ✅ Done (3.0/2.0) | relevance_scorer.py | v7 tightens to 1.0 |
| C2: Missing data defaults | 🔲 Next | decision_engine.py | None → penalty 1.0, not 0.5 |
| C3: Top-k consensus | 🔲 Next | verdict_engine.py | Multi-record consensus, not first-only |
| C4: Temp min passed | ✅ Done | mua_v6.py:305 | precedent_temp_min wired |
| C5: EPL validation | 🔲 Separate | MIUL scope | Out of scope for MUA |

---

## Implementation Roadmap

### P0: Safety Fixes — 1 day
C2 + C3. Non-negotiable. Before any new code.

### P1: Backend Pipeline — 1 week
- `mira/mua/v7/` directory with all new files
- Session model (Pydantic + PostgreSQL)
- Unified EvidenceRef with two-tier identity
- Investigator wrapping V6PrecedentRetriever
- Per-precedent relationship explanations
- Conflict detector
- Category router with AuthorityPack interface
- Evidence Strength calculator
- Process sensitivity handler

### P2: API Surface — 2 days
- 5 step endpoints + session CRUD + qualification plan
- Center param, process sensitivity flag
- Redis cache for common material queries

### P3: Frontend Wizard — 1 week
- 6 components, parallel route at `/mua-v7`
- Step 1b conditional expansion
- Evidence explanations in Investigate step
- Inline editing in Draft step
- Legacy tabs behind accordion with warning banner

### P4: Production Features — 1 week
- Fact checker with AtomicClaim anchoring
- Physics/Regulatory relevance split display
- Divergence tracking (silent backend)
- Mandatory rationale on divergence
- Qualification Plan Mode for novel materials

### P5: Future (Post-March 17)
- Dependency graph for chained MUAs (zombie detection)
- Multi-center AuthorityPack implementations (JSC, GRC, KSC)
- Standard version delta reporting (6016C → 6016D migration)
- Reviewer calibration analytics (from gold labels)
- FAISS partitioning by material family (scale to 50K+ MUAs)
- Batch MUA generation (from MIUL export)

---

## March 17th Demo

### What We Show (P0 through P3 + P4 partial)

1. Open MUA Writer — single clean wizard, no tabs
2. Type "Inconel 718" → green checkmark, live resolution
3. Fill environment: 30% O2, 3000 psi, -100°F to 500°F
4. Banners fire: "Enriched oxygen" + "Cryogenic range"
5. Click Investigate → watch MIRA gather evidence
6. Results: 14 precedents with per-item explanations
   - *"Same alloy, similar O2... may require cryogenic gap disposition"*
   - *"Same alloy at higher pressure, but ambient O2 only..."*
   - ⚠️ Conflicting: *"SCC restrictions for structural applications"*
7. Evidence Strength: MODERATE — component breakdown shows why
8. Review: 3 flagged items. Engineer makes judgment calls.
9. Generate Draft → full 7-section NASA MUA with reasoning chain
   - Every engineer decision reflected in rationale
   - Precedent selection logic transparent
   - Gap rationale quoted from engineer's own words
10. Finalize with full audit trail

### The Punchline

*"Two hours of MAPTIS searching and manual writing → two minutes of MIRA investigation plus five minutes of engineering judgment. Same rigor. Fraction of the time.*

*MIRA doesn't write the MUA. The engineer writes the MUA. MIRA just does the legwork so the engineer can focus on what they're actually good at — making judgment calls with evidence."*

### The Contrast

Current workflow: 400 MAPTIS search results → 1 hour filtering → 15 PDFs → manual rationale writing → maybe miss the conflicting precedent → hope the category routing is right.

MIRA v7: Evidence gathered and explained in 2 minutes → 3 items need your expertise → draft reflects your decisions → audit trail proves your rigor.

---

*"Data is noise. Information is organized noise. Intelligence is 'here's what you actually do about it.'"*

*The MUA Writer is where MIRA stops organizing noise and starts telling engineers what they can do about it — with evidence, with citations, with explanations of fit, and with the humility to say "may be applicable" instead of "is approved."*

*The engineer's judgment is the final word. MIRA's job is to make sure that judgment is the most informed judgment in the room.*
