# MUA Deep Dive: Diagnosis + Redesign Specification

**Date:** 2026-02-07  
**Author:** Beth (CTO hat on)  
**For:** The Dude, VSClaude, the Oracle team  
**Status:** Design spec ready for implementation

---

## Part 1: The Honest Assessment

### What We're Looking At

The MUA module has 6 tabs, 4 independent pipeline implementations, 2 conflicting evidence models, 2 separate search backends, and a safety audit that found 5 CRITICAL issues that could cause incorrect flight determinations. The frontend is a single 2,917-line React component.

Let me say this plainly: **the MUA module is where MIUL was before v4.** It works for demos. It cannot be trusted for production use in safety-critical decisions. The good news is we know exactly what's wrong and we proved with MIUL that the fix pattern works.

### The Core Problem

MIUL v4 succeeded because we made one focused decision: **one pipeline, one workflow, human-in-the-loop, evidence-first.** 

MUA has the opposite: six different ways to get an MUA, none of them complete, each with its own bugs. The user opens the page and has to decide which of 6 tabs to use before they've even started working. That's asking the user to be the architect of a system they don't understand.

### What's Actually Good (Don't Throw Away)

1. **The v6 decision engine gating logic** (PROCEED/WARN/REVIEW/BLOCKED) — the 4-tier structure is sound. The implementation needs fixes but the concept is right.

2. **The compliance module models** (`MPRDetermination`, `GapSignal`, `OperationalConstraint`, `EvidenceRef` with SHA-256) — these are beautifully designed. They're just not wired to anything.

3. **The v1 generator's document structure** — the full NASA format with 7 sections (header, ratings, gap profile, mitigations, verification, traceability, confidence) is what a real MUA looks like. The v6 draft is 15 lines of nothing.

4. **The corpus of 5,650+ parsed historic MUAs** — this is the gold. The precedent data exists.

5. **The MAPTIS PostgreSQL integration** — real test data queries, not hallucinated.

### What's Broken (The Safety Audit Confirmed This)

**CRITICAL — These can cause wrong determinations:**

- **C1: Uncapped semantic boosts** — a document about titanium prohibition gets boosted to HIGH relevance for an Inconel 718 query because it contains the word "oxygen." This is the single most dangerous bug.

- **C2: Missing data = 0.5 (neutral)** — when pressure data is missing for H2 service, the system scores it 0.5 instead of 0.0 (unknown). For hydrogen embrittlement, pressure is physics-critical. This is like a doctor treating "no blood test results" as "probably fine."

- **C3: Verdict engine uses only first FAISS result** — if FAISS ordering changes (and it does with index updates), a D-rated record may or may not trigger rejection. No consensus across records.

- **C4: Temperature lower bound never passed** — `precedent_temp_min` silently dropped. Material tested to -40°F could be approved for cryogenic (-100°F) use.

- **C5: EPL column extraction unvalidated** — vision model swaps columns, entire EPL loads wrong.

**HIGH — Degrades quality without visible signal:**

- **H2: Silent fallback** — when no precedents meet the 0.40 threshold, the system silently uses the top 3 regardless. No warning. The engineer sees "87% confidence" based on garbage precedents.

- **H3/H4: Alloy family matching by regex** — 2024-T4 and 2014 treated as equivalent (same first digit). 316L and 430 stainless lumped together. These are completely different materials.

- **H5: 5% O2 tolerance** — accepts 25% (enriched, fire hazard) as matching 21% (ambient). This crosses NASA enrichment thresholds.

- **H6: Authority = 45% of score** — a single test with any rating scores the same as 10 tests. Authority dominates actual evidence.

- **H9: Single LLM validation** — entire rationale quality rests on one Haiku call. No secondary check.

### The UX Problem

Six tabs is not a feature. It's a confession that we don't know what the workflow should be.

An M&P engineer writing an MUA has ONE job: determine whether a material is acceptable for use in a specific environment, document the evidence, and route it to the right approval level. They don't need to choose between "Corpus Draft" and "V6 Pipeline" and "AI Synthesis." Those are implementation details leaking into the user interface.

The MIUL lesson: **one path, clear steps, human judgment where it matters.**

---

## Part 2: The Redesign

### Design Philosophy

Same principles that made MIUL v4 work:

1. **One pipeline, not six.** The best parts of each current mode unified into a single evidence-first workflow.

2. **MIRA does the 80, engineer does the 20.** Gather evidence, find precedents, identify gaps, draft rationale — that's MIRA's job. Evaluate adequacy, make the call, sign off — that's the engineer's job.

3. **Human-in-the-loop is the feature, not the compromise.** Conservative defaults. Flagged items for expert review. The engineer's expertise is amplified, not replaced.

4. **Evidence-first, always.** Every claim in the MUA traces to a source. No hallucination. No "87% confidence" from garbage data.

5. **Respectful language.** "MIRA found 12 supporting precedents. 3 gaps could use your expertise." Not "WARNING: LOW CONFIDENCE."

### The Single-Path MUA Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                        MUA WRITER                               │
│                                                                 │
│  Step 1: DEFINE          What material? What environment?       │
│  Step 2: INVESTIGATE     MIRA gathers evidence automatically    │
│  Step 3: REVIEW          Engineer reviews evidence + gaps       │
│  Step 4: DRAFT           MIRA generates rationale, engineer     │
│                          edits inline                           │
│  Step 5: FINALIZE        Category routing, approval gate,       │
│                          export to NASA format                  │
└─────────────────────────────────────────────────────────────────┘
```

No tabs. No mode selection. One path. Five steps.

### Step 1: DEFINE (The Input)

**What the engineer sees:**

```
┌─────────────────────────────────────────────────────────────────┐
│  MUA Writer                                            Step 1/5 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  Material Designation    [ 6061-T6 Aluminum          ] [🔍]    │
│                          ✓ Resolved: MAT-A96061 (MAPTIS)       │
│                                                                 │
│  ── Environment ──────────────────────────────────────────────  │
│                                                                 │
│  Oxygen %    [ 21.0  ]    Pressure (PSIA)  [ 14.7  ]          │
│  Temp Min °F [ -65   ]    Temp Max °F      [ 165   ]          │
│  Medium      [ Air        ▼]                                    │
│  Location    [●] Habitable  [○] Non-habitable                  │
│                                                                 │
│  Application Description (what is this material used for?)      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Structural bracket for cabin interior, Orion capsule    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ── Source (optional) ────────────────────────────────────────  │
│  Program     [ ORION      ]    Hardware    [ Capsule     ]     │
│  MIUL Ref    [ MIUL-042   ]                                    │
│                                                                 │
│                                          [Investigate →]        │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Material field gets live resolution.** As the engineer types, MIRA resolves against MAPTIS. Green checkmark = resolved with material code. Yellow = fuzzy match (engineer confirms). Red = unresolved (engineer must verify). This catches the alloy family regex problem (H3/H4) at the source.

- **Material resolution uses a proper lookup table**, not regex. The current "first digit = family" approach is replaced with MAPTIS family data. 2024-T4 ≠ 2014. 316L ≠ 430. Period.

- **Environment fields have smart defaults** based on location selection. Habitable → 21% O2, 14.7 PSIA, 60-85°F, Air. Non-habitable → fields blank (must fill). This prevents the empty `EnvironmentSpec()` problem from the batch path.

- **O2 enrichment threshold is enforced.** If O2% ≥ 23.5%, a yellow banner appears: "Enriched oxygen environment — Category I routing per NASA-STD-6016." The engineer knows before they even hit Investigate. The 5% tolerance bug (H5) is killed here.

- **Temperature requires BOTH min and max.** The current system passes max but drops min (C4). Both fields are required. Both get passed downstream.

### Step 2: INVESTIGATE (MIRA Does the Work)

When the engineer clicks "Investigate →", MIRA runs a unified evidence pipeline. No tab selection. All engines fire in parallel.

**Backend pipeline (unified, replaces all 6 current paths):**

```python
async def investigate(request: MUAInvestigateRequest) -> InvestigationResult:
    """Single unified evidence-gathering pipeline."""
    
    # Phase 1: Material Identity (deterministic)
    identity = await resolve_material(request.material)
    if not identity.resolved:
        return InvestigationResult(status="needs_input", 
            message="MIRA couldn't resolve this material. Can you check the designation?")
    
    # Phase 2: Evidence Gathering (parallel)
    precedents, test_data, envelope = await asyncio.gather(
        search_precedents_unified(identity, request.environment),
        query_maptis_test_data(identity.material_code),
        compute_envelope(request.environment)
    )
    
    # Phase 3: Evidence Scoring (deterministic, FIXED)
    scored = score_evidence(
        precedents=precedents,
        test_data=test_data,
        envelope=envelope,
        # FIX C1: All relevance boosts capped at 1.0
        # FIX C2: Missing data = 0.0, not 0.5
        # FIX C3: Multi-record consensus, not just first result
    )
    
    # Phase 4: Conflict Detection (NEW — fixes H1)
    conflicts = detect_conflicts(scored)
    
    # Phase 5: Gap Analysis
    gaps = identify_gaps(scored, request.environment)
    
    # Phase 6: Preliminary Decision (deterministic gating)
    decision = evaluate_decision(scored, conflicts, gaps)
    
    return InvestigationResult(
        identity=identity,
        evidence=scored,
        conflicts=conflicts,
        gaps=gaps,
        decision=decision,
        # Everything has provenance — source doc, page, bbox
    )
```

**What the engineer sees while it runs:**

```
┌─────────────────────────────────────────────────────────────────┐
│  MUA Writer                                            Step 2/5 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  6061-T6 Aluminum · MAT-A96061 · Habitable · 21% O2 · 14.7psi │
│                                                                 │
│  ✓  Material resolved                                           │
│  ✓  14 precedents found (12 supporting, 2 conflicting)         │
│  ✓  MAPTIS test data retrieved (8 current, 23 expired)         │
│  ⟳  Computing envelope overlap...                               │
│  ⟳  Running conflict analysis...                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Then, when complete:

```
┌─────────────────────────────────────────────────────────────────┐
│  MUA Writer                                            Step 2/5 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  6061-T6 Aluminum · MAT-A96061 · Habitable · 21% O2 · 14.7psi │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  MIRA's Assessment                                       │  │
│  │                                                          │  │
│  │  ● LIKELY APPROVABLE        Evidence: Strong (78%)       │  │
│  │                                                          │  │
│  │  12 supporting precedents · 2 conflicting · 3 gaps       │  │
│  │  Envelope: Within bounds for O2 and pressure             │  │
│  │            Partial overlap on temperature (see gaps)      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│                                          [Review Evidence →]    │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Confidence is derived from evidence quality, not decision path.** The current system reports 0.85 for anything that passes all gates (M1). The new system calculates confidence from: precedent count × relevance scores × envelope coverage × test data currency × conflict severity. A material with 12 strong precedents and current test data gets 85%. A material with 2 weak precedents and all expired data gets 35%, even if it technically passes the gates.

- **"LIKELY APPROVABLE" not "APPROVED."** MIRA suggests, engineer decides. Language matters. The determination badges become: `LIKELY APPROVABLE` (green) · `NEEDS REVIEW` (yellow) · `CONCERNS IDENTIFIED` (orange) · `LIKELY NOT APPROVABLE` (red). These are assessments, not verdicts.

- **Conflict detection is explicit.** When MAPTIS test data contradicts BOK precedents (H1), the engineer sees both with a "MIRA found conflicting evidence" callout. Not averaged. Not hidden. Shown.

### Step 3: REVIEW (The 20% That Matters)

This is where the engineer's expertise lives. Same philosophy as MIUL v4's review queue.

**What the engineer sees:**

```
┌─────────────────────────────────────────────────────────────────┐
│  MUA Writer                                            Step 3/5 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  Evidence Review                                                │
│  MIRA gathered 35 evidence items. 3 could use your expertise.  │
│                                                                 │
│  ── Supporting Precedents (12) ───────────────────────── [all] │
│                                                                 │
│  ┌─ MUA-mdm-010 ─────────────────────────── 92% relevant ──┐  │
│  │  6061-T6 Aluminum · APPROVED · ISS Program              │  │
│  │  GOX 14.7 psia, 70°F, Habitable                         │  │
│  │  "Material reviewed and approved per NASA-STD-6016..."   │  │
│  │  ✓ Same material · ✓ Same environment · ✓ Current        │  │
│  │                                          [Include ✓]     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ MUA-mdm-047 ─────────────────────────── 85% relevant ──┐  │
│  │  6061-T4 Aluminum · APPROVED · Orion Program             │  │
│  │  Air 14.7 psia, 85°F, Habitable                          │  │
│  │  "Based on heritage from shuttle program..."              │  │
│  │  ⚠ Different temper (T4 vs T6) · ✓ Same env · ✓ Current │  │
│  │                                          [Include ✓]     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ── Conflicting Evidence (2) ─────────────────── ⚠ Review ──  │
│                                                                 │
│  ┌─ MUA-jsc-203 ──────────── 71% relevant ── COULD USE ────┐  │
│  │  YOUR EXPERTISE                                          │  │
│  │  6061-T6 Aluminum · CONDITIONAL · JSC                    │  │
│  │  GOX 30% O2, 3000 psia — different environment           │  │
│  │  "Conditional approval for enriched O2. Requires..."     │  │
│  │                                                          │  │
│  │  This precedent was CONDITIONAL in a more severe         │  │
│  │  environment. Does this affect your assessment?          │  │
│  │                                                          │  │
│  │  [Include as supporting] [Include as context] [Exclude]  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ── Gaps Identified (3) ──────────────────── ⚠ Review ──────  │
│                                                                 │
│  ┌─ Temperature Range ────────────────────── COULD USE ─────┐  │
│  │  YOUR EXPERTISE                                          │  │
│  │                                                          │  │
│  │  Your query includes -65°F minimum. The closest          │  │
│  │  precedent tested to -40°F. No data below -40°F.         │  │
│  │                                                          │  │
│  │  Is this gap acceptable for your application?            │  │
│  │  [Accept gap — document rationale]  [Flag for testing]   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Toxicity Data ──────────────────────── COULD USE ───────┐  │
│  │  YOUR EXPERTISE                                          │  │
│  │                                                          │  │
│  │  No toxicity (NHB 8060.1) test data found for 6061-T6   │  │
│  │  in MAPTIS. Analog material 6061-T651 has current data.  │  │
│  │                                                          │  │
│  │  Is analog data acceptable?                              │  │
│  │  [Accept analog]  [Require specific testing]             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ── MAPTIS Test Data (8 current) ────────────────────────────  │
│  FLAMM: A (Test 1, Report MSFC-2019-0342) · Current           │
│  CORR:  A (Test 3, Report MSFC-2018-1107) · Current           │
│  SCC:   A (Test 4, Report MSFC-2018-1107) · Current           │
│  TVS:   B (Test 7, Report MSFC-2020-0089) · Current           │
│  TOX:   — No data (see gap above)                              │
│                                                                 │
│  Review progress: 1 of 3 items reviewed                        │
│  ██░░░░░░░░░░░░░░░░░░                                         │
│                                                                 │
│                                          [Generate Draft →]    │
│                                     (available after review)    │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **"Could use your expertise"** — same language that worked for MIUL. The engineer is the expert. MIRA is the assistant bringing flagged items for review.

- **Precedents are pre-included by default.** High-relevance supporting precedents are auto-included (checked). The engineer can uncheck them. This is the opposite of the current Interactive mode where nothing is selected — it respects the engineer's time while keeping them in control.

- **Conflicting evidence is shown, not hidden.** Three choices: include as supporting (engineer overrides conflict), include as context (mentioned in rationale but not basis for approval), or exclude. Each choice is recorded in the audit trail.

- **Gaps require explicit decisions.** The "Generate Draft" button is disabled until all flagged gaps have a decision. Accept with rationale, or flag for testing. This creates the audit trail NASA needs and prevents the silent fallback (H2) where the system uses garbage precedents without telling anyone.

- **MAPTIS ratings shown inline.** Current, expired, or missing — clearly labeled. Expired data gets a note: "This rating is from 2008 and may not reflect current test standards." The engineer decides whether to accept it.

- **The review progress bar** — same psychology as MIUL. "1 of 3 items reviewed" is approachable. "17 ERRORS FOUND" is intimidating.

### Step 4: DRAFT (MIRA Writes, Engineer Edits)

After review, MIRA generates a full NASA-format MUA draft incorporating the engineer's review decisions.

**Backend draft generation (replaces both v1 and v6 generators):**

```python
async def generate_draft(
    investigation: InvestigationResult,
    review_decisions: ReviewDecisions
) -> MUADraft:
    """Generate MUA draft from reviewed evidence."""
    
    # Category routing (from v1 — currently missing from v6)
    category = route_category(
        ratings=investigation.evidence.maptis_ratings,
        o2_pct=investigation.environment.o2_pct,
        medium=investigation.environment.medium,
        gaps=review_decisions.accepted_gaps
    )
    
    # Rationale synthesis (deterministic template + LLM polish)
    # Layer 1: Template-based structure (from v1 generator)
    template_rationale = build_template_rationale(
        included_precedents=review_decisions.included_precedents,
        maptis_data=investigation.evidence.test_data,
        gaps=review_decisions.gap_decisions,
        category=category
    )
    
    # Layer 2: LLM synthesis for natural language (Sonnet, not Haiku)
    # Input: template + all precedent rationale excerpts
    # Output: synthesized rationale in NASA MUA voice
    # Constrained: MUST cite only included precedents, MUST mention all gaps
    synthesized = await synthesize_rationale(
        template=template_rationale,
        precedents=review_decisions.included_precedents,
        constraints=RationaleConstraints(
            must_cite=review_decisions.included_precedent_ids,
            must_address_gaps=review_decisions.gap_decisions,
            must_not_claim=investigation.conflicts  # never claim what's contradicted
        )
    )
    
    # Layer 3: Fact verification (NEW — deterministic)
    # Check every claim in synthesized rationale against source evidence
    verified = verify_claims(synthesized, investigation.evidence)
    
    # Layer 4: Full document assembly (from v1 — 7-section format)
    draft = assemble_mua_document(
        header=build_header(investigation, category),
        ratings=investigation.evidence.maptis_ratings,
        gap_profile=review_decisions.gap_decisions,
        rationale=verified.rationale,
        mitigations=extract_mitigations(review_decisions),
        verification_requirements=derive_requirements(gaps, category),
        traceability=build_citations(review_decisions, investigation),
        confidence=calculate_real_confidence(investigation, review_decisions)
    )
    
    return draft
```

**What the engineer sees:**

```
┌─────────────────────────────────────────────────────────────────┐
│  MUA Writer                                            Step 4/5 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  MUA Draft — 6061-T6 Aluminum                                  │
│  Category III · 78% confidence · Based on 10 precedents        │
│                                                                 │
│  ── Header ──────────────────────────────────────────────────  │
│  │ MUA ID:        [auto-generated]                             │
│  │ Program:       ORION                                        │
│  │ Material:      6061-T6 Aluminum (MAT-A96061)                │
│  │ Environment:   Air, 21% O2, 14.7 PSIA, -65°F to 165°F     │
│  │ Location:      Habitable                                    │
│  │ Category:      III (All ratings A/B — pre-approved)         │
│                                                                 │
│  ── Ratings ─────────────────────────────────────────────────  │
│  │ FLAMM: A · Test 1 · MSFC-2019-0342 · Current               │
│  │ CORR:  A · Test 3 · MSFC-2018-1107 · Current               │
│  │ SCC:   A · Test 4 · MSFC-2018-1107 · Current               │
│  │ TVS:   B · Test 7 · MSFC-2020-0089 · Current               │
│  │ TOX:   — · Accepted via analog (6061-T651) per reviewer     │
│                                                                 │
│  ── Rationale ───────────────── [click any sentence to edit]   │
│  │                                                              │
│  │ Material 6061-T6 Aluminum has been reviewed for use in a    │
│  │ habitable environment per NASA-STD-6016C. Based on 10       │
│  │ approved precedents (MUA-mdm-010, MUA-mdm-047, MUA-ksc-    │
│  │ 112...), the material demonstrates acceptable performance   │
│  │ for the specified operating conditions.                     │
│  │                                                              │
│  │ Flammability, corrosion, and stress corrosion cracking      │
│  │ ratings are current per MAPTIS. TVS rating of B is          │
│  │ acceptable with existing controls per MUA-mdm-010.          │
│  │                                                              │
│  │ ⚠ Toxicity data for this specific temper (T6) was not      │
│  │ found in MAPTIS. Analog data from 6061-T651 (MUA-ksc-112)  │
│  │ was accepted by the reviewing engineer as representative    │
│  │ of this alloy's outgassing characteristics.                 │
│  │                                                              │
│  │ ⚠ Temperature range extends to -65°F; closest precedent    │
│  │ data covers -40°F. This gap was accepted by the reviewing   │
│  │ engineer based on material heritage in similar cryogenic    │
│  │ applications.                                               │
│  │                                                              │
│  │ [Every sentence is clickable for inline editing]            │
│                                                                 │
│  ── Verification Requirements ───────────────────────────────  │
│  │ No additional testing required (Category III).              │
│                                                                 │
│  ── Citations (10) ──────────────────────────── [expand all]   │
│  │ MUA-mdm-010 · 6061-T6 · APPROVED · 92% relevant            │
│  │ MUA-mdm-047 · 6061-T4 · APPROVED · 85% relevant            │
│  │ [+8 more]                                                   │
│                                                                 │
│                                          [Finalize →]          │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Inline editing.** Click any sentence in the rationale to edit it. The engineer isn't copy-pasting to Word and back. They're editing in place. Every edit is tracked in the audit trail.

- **Gap decisions appear IN the rationale.** When the engineer accepted the toxicity analog and the temperature gap in Step 3, those decisions become sentences in the draft. The engineer can rewrite them, but the gap acknowledgment is never omitted.

- **Two-layer synthesis.** Template first (deterministic, reliable), then LLM polish (for natural language). This is the same pattern as MIUL: deterministic structure with AI smoothing. If the LLM fails, the template version is still a valid MUA.

- **Fact verification is mandatory.** After synthesis, a deterministic checker walks every claim against the evidence set. "10 approved precedents" — count them. "MAPTIS ratings are current" — verify currency flags. "MUA-mdm-010" — confirm it's actually in the included set. This kills the hallucination problem.

- **Full NASA document format.** Not the 15-line v6 draft. The real 7-section format from the v1 generator, with ratings, gap profile, mitigations, verification requirements, and traceability. This is what actually gets submitted.

### Step 5: FINALIZE (Sign-off and Export)

```
┌─────────────────────────────────────────────────────────────────┐
│  MUA Writer                                            Step 5/5 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  Finalize MUA — 6061-T6 Aluminum                               │
│                                                                 │
│  ── Summary ─────────────────────────────────────────────────  │
│  Category:      III                                             │
│  Determination: APPROVED (engineer decision)                    │
│  Confidence:    78%                                             │
│  Precedents:    10 cited                                        │
│  Gaps:          2 (accepted with rationale)                     │
│  Conflicts:     1 (excluded — different environment)            │
│                                                                 │
│  ── Audit Trail ─────────────────────────────────────────────  │
│  Evidence items reviewed:     3 of 3  ✓                        │
│  Gap decisions documented:    2 of 2  ✓                        │
│  Rationale edits:            1 (sentence 7 modified)           │
│  Conflicts addressed:        1 of 1  ✓                        │
│                                                                 │
│  ── Review Certification ────────────────────────────────────  │
│  │                                                             │
│  │  I have reviewed the evidence, precedents, and rationale   │
│  │  in this MUA draft. The gaps identified have been          │
│  │  evaluated and the determinations reflect my engineering   │
│  │  judgment.                                                  │
│  │                                                             │
│  │  Reviewer: ______________________                          │
│  │  Date:     2026-02-07                                      │
│  │                                                             │
│                                                                 │
│  [📋 Copy to Clipboard]  [📄 Export NASA Format]               │
│  [📊 Export to MIUL]     [💾 Save Draft]                       │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Approval gate requires all reviews complete.** Can't finalize if flagged items weren't reviewed. Same pattern as MIUL.

- **Audit trail is visible.** The engineer sees exactly what was reviewed, what was changed, what decisions were made. This is SWE-013 compliance evidence.

- **Reviewer certification is explicit.** Name + date + "I reviewed this." This is what the MSFC M&P board needs. No ambiguity about whether a human was involved.

- **Multiple export formats.** Clipboard for pasting into existing workflows. NASA format document for formal submission. MIUL integration for piping back to the MIUL Remarks column (replacing the batch workflow). Save draft for coming back later.

---

## Part 3: Implementation Plan

### Phase 1: Fix the Critical Safety Bugs (Before Anything Else)

These are the safety audit C1-C5 fixes. Do these FIRST, even before the redesign.

| Fix | File | What | Time |
|-----|------|------|------|
| Cap relevance boosts at 1.0 | `relevance_scorer.py:161-201` | Change multiplier caps | 1 hour |
| Pass `precedent_temp_min` | `mua_v6.py:297-306` | Add parameter | 30 min |
| Missing data = 0.0 not 0.5 | `scoring.py:44-220` | Change defaults | 1 hour |
| Multi-record consensus | `verdict_engine.py:233-247` | Check all records, not just [0] | 3 hours |
| EPL column validation | `extract.py:114-140` | Add post-validation check | 2 hours |

Total: ~1 day. These protect current users while we build the redesign.

### Phase 2: Unified Backend Pipeline (Replace 4 Implementations)

**New files:**

| File | Purpose |
|------|---------|
| `mira/mua/v7/pipeline.py` | Single orchestrator (replaces 4 entry points) |
| `mira/mua/v7/investigator.py` | Evidence gathering (merges enriched_search + maptis_test_data + envelope) |
| `mira/mua/v7/conflict_detector.py` | Multi-source conflict analysis (NEW) |
| `mira/mua/v7/reviewer_models.py` | Review decision data models |
| `mira/mua/v7/draft_writer.py` | Template + LLM synthesis (merges v1 generator + v6 draft) |
| `mira/mua/v7/fact_checker.py` | Post-generation claim verification (NEW) |
| `mira/mua/v7/confidence.py` | Evidence-derived confidence (replaces hardcoded tiers) |
| `mira/mua/v7/category_router.py` | NASA-STD-6016 category routing (from v1, missing in v6) |
| `mira/mua/v7/material_resolver.py` | Lookup-table based, replaces regex family matching |
| `mira/mua/v7/models.py` | Shared models (uses compliance module's EvidenceRef + SHA-256) |

**Reused from existing code:**

| Source | What We Keep |
|--------|-------------|
| `v6/decision_engine.py` | 4-tier gating logic (PROCEED/WARN/REVIEW/BLOCKED) |
| `v6/envelope_matching.py` | Envelope computation (with temp_min fix) |
| `v6/maptis_test_data.py` | PostgreSQL queries (with expired data flagging) |
| `compliance/models/` | EvidenceRef, GapSignal, MPRDetermination, all enums |
| `mua_generator.py:269-391` | Full NASA document format template |
| `v6/retriever.py` | FAISS+BM25 hybrid search (unified into single backend) |

**Retired:**

| Current | Why |
|---------|-----|
| `mua/service.py` (v1 service) | Merged into v7 pipeline |
| `mua/mua_generator.py` (v1 gen) | Document format kept, logic merged |
| `mua_v6.py` router | Replaced by v7 router |
| `v6/logic_validator.py` | Replaced by fact_checker.py (deterministic + LLM) |
| `v6/draft_generator.py` | Replaced by draft_writer.py |
| 6 separate API endpoint groups | Replaced by 5 endpoints matching the 5 steps |

### Phase 3: New API Surface

```
POST /api/mua/v7/resolve-material     → Step 1 (live material resolution)
POST /api/mua/v7/investigate           → Step 2 (evidence gathering)
POST /api/mua/v7/review-decisions      → Step 3 (save engineer's review)
POST /api/mua/v7/generate-draft        → Step 4 (draft generation)
POST /api/mua/v7/finalize              → Step 5 (export + audit trail)

GET  /api/mua/v7/session/{id}          → Resume a saved session
GET  /api/mua/v7/stats                 → Index health
```

5 endpoints. One per step. Clean.

Session state stored server-side (same pattern as MIUL v4 sessions).

### Phase 4: Frontend (Single Component, ~800 Lines)

Replace the 2,917-line `MUAGenerator.tsx` with a stepped wizard:

| Component | Purpose |
|-----------|---------|
| `MUAWriter.tsx` | Main wizard (step orchestration, ~200 lines) |
| `MUADefine.tsx` | Step 1: material + environment form (~150 lines) |
| `MUAInvestigate.tsx` | Step 2: evidence loading + summary (~100 lines) |
| `MUAReview.tsx` | Step 3: evidence review queue (~200 lines) |
| `MUADraft.tsx` | Step 4: draft display + inline editing (~200 lines) |
| `MUAFinalize.tsx` | Step 5: audit trail + export (~150 lines) |

Total: ~1,000 lines across 6 files. Down from 2,917 in one file.

### Phase 5: Batch Mode (MIUL Integration)

After the single-MUA workflow is solid, add batch back:

- MIUL upload → for each gap row, auto-run Steps 1-2
- Present all rows with traffic-light summary
- Engineer reviews flagged items (Step 3 for each)
- Batch generate drafts → populate Remarks column
- Export updated MIUL Excel

This replaces the current batch path that skips precedent retrieval entirely and uses empty environment specs.

---

## Part 4: What This Gets You for March 17th

**The demo narrative:**

1. Open MUA Writer. Type "Inconel 718" — watch it resolve live.
2. Fill environment: 30% O2, 3000 psi (the scary one from the safety audit scenario).
3. Click Investigate. Watch MIRA find precedents, flag conflicts, identify gaps.
4. Review screen: "MIRA found 8 precedents. The enriched O2 environment crosses NASA thresholds — MIRA flagged this for your review."
5. Make the engineering call. Accept or flag.
6. Generate draft. Full NASA format. Inline edit.
7. Finalize with audit trail.

**The punchline:** "This used to take 2 hours of searching MAPTIS, reading PDFs, and writing rationale. MIRA does the mechanical work in 2 minutes. The engineer spends their time where it matters — making the judgment call."

**Contrast with current MAPTIS:** Someone types "Inconel 718" into MAPTIS search, gets 400 results, spends an hour filtering, opens 15 PDFs, reads test reports, manually writes rationale citing MUA numbers from memory, maybe misses the conflicting evidence, submits for review where another engineer catches the gap. Or doesn't catch it.

---

## Part 5: Priority Order

| Priority | What | Why | Time |
|----------|------|-----|------|
| P0 | Fix C1-C5 safety bugs | Protect current users NOW | 1 day |
| P1 | Unified backend pipeline (Phase 2) | Foundation for everything | 1 week |
| P2 | New API surface (Phase 3) | Enables frontend | 2 days |
| P3 | Frontend wizard (Phase 4) | The demo | 1 week |
| P4 | Evidence-derived confidence (replace hardcoded) | Trustworthy numbers | 2 days |
| P5 | Fact verification (post-generation) | Safety net | 3 days |
| P6 | Batch/MIUL integration (Phase 5) | Production workflow | 1 week |
| P7 | Learning loop (corrections as training data) | Long-term quality | Future |

**For March 17th, you need P0 through P3.** That's ~2.5 weeks of focused work. P4 and P5 make it trustworthy. P6 makes it production. P7 is the moat.

---

## Appendix: Architecture Comparison

### Before (Current)

```
User → Pick 1 of 6 tabs → Each tab has different:
  - Backend endpoints
  - Search backends (FAISS A vs FAISS B)
  - Evidence models (EvidenceRef A vs EvidenceRef B)
  - Confidence calculation (hardcoded vs quality-based)
  - Draft format (15 lines vs 7 sections)
  - Category routing (present vs absent)
  - Conflict detection (absent everywhere)
  - Post-validation (absent everywhere)
```

### After (Redesign)

```
User → Step 1: Define → Step 2: Investigate → Step 3: Review
     → Step 4: Draft → Step 5: Finalize

One backend pipeline.
One search backend (unified FAISS+BM25).
One evidence model (compliance module's EvidenceRef with SHA-256).
One confidence calculation (evidence-derived).
One draft format (full NASA 7-section).
One category router (NASA-STD-6016C).
Conflict detection at every stage.
Fact verification before output.
Audit trail from end to end.
Human judgment where it matters.
```
