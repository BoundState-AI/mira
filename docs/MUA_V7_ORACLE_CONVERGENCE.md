# MUA v7 Oracle Convergence Synthesis
## Where They Agree, Where They Clash, and the Gold

**Date:** 2026-02-07  
**Inputs:** Grok (stress test), Gemini (edge cases), Fran (schema), CC (implementation)

---

## VERDICT: No Fatal Flaws Found

All four validated the 5-step workflow. Nobody said "scrap this." The architecture holds. What they DID find: important refinements, missing edge cases, and one naming change that matters more than it sounds.

---

## 1. UNIVERSAL AGREEMENT (Build Without Debate)

These items got 4/4 convergence. Ship them.

### 1a. Build v7 as New Files, Deprecate Gradually
- **CC:** Explicit parallel route at `/mua-v7`, keep `/mua-generator` untouched
- **Fran:** "Keep old tabs behind Advanced/Legacy accordion"
- **Grok:** Assumes new pipeline throughout
- **Gemini:** Assumes new structure

**Action:** New `mira/mua/v7/` directory. Frontend parallel route. Legacy tabs get a warning banner: *"Legacy mode: does not enforce v7 safety gates."* Switch default after validation.

### 1b. V6PrecedentRetriever Is the Search Backend
- **CC:** "Don't build a new search backend. Reuse V6PrecedentRetriever, add supporting/conflicting as post-filter (3 lines of code)."
- **Grok:** Validates hybrid FAISS+BM25+RRF, discusses scaling it
- **Fran:** Assumes unified search throughout schema design

**Action:** v7 `investigator.py` wraps V6PrecedentRetriever + classification from enriched_search.

### 1c. PostgreSQL for Session State
- **CC:** Explicit schema with JSONB columns, cites existing `review_queue.py` pattern
- **Fran:** Structured Pydantic + append-only event log
- **Grok:** Validates concurrent access, confirms Redis too volatile

**Action:** PostgreSQL `mua_sessions` table per CC's schema, with Fran's Pydantic models as the serialization layer.

### 1d. Compliance Models Promoted as Unified Models
- **CC:** "Promote `compliance/models/` to shared"
- **Fran:** Builds unified EvidenceRef extending compliance patterns

**Action:** `mira/compliance/models/` becomes the single source of truth for evidence, gaps, and determination models.

### 1e. Safety Fixes Before Redesign
- **CC:** C1 ✅, C4 ✅, C2 planned, C3 planned, C5 out-of-scope (MIUL)
- All others assume fixes happen first

**Action:** C2 (missing data defaults) and C3 (top-k consensus) are next. C5 is a separate MIUL ticket.

---

## 2. STRONG AGREEMENT (3+ Oracles, Minor Reconciliation Needed)

### 2a. Don't Call It "Confidence" — Call It "Evidence Strength"
- **Fran:** "Don't let 'confidence' imply probability of correctness. Call it Evidence Strength."
- **Grok:** "A 0.72 might scream 'probably fine' to a rushed reviewer, implying precision where it's fuzzy math."
- **Gemini:** Implies through divergence tracking design (tracks when human disagrees with AI score)

**The Insight:** "Confidence: 0.72" reads as "72% chance this is correct." That's not what the number means. "Evidence Strength: MODERATE (0.72)" reads as "we have moderate evidence." Same number, radically different interpretation.

**Action:** Rename throughout. UI shows band (STRONG/MODERATE/WEAK) prominently. Numeric score is secondary/expandable.

### 2b. Show Bands Prominently, Number Secondary
- **Fran:** "Output both EvidenceStrengthScore AND EvidenceStrengthBand. UI shows band prominently; number is secondary."
- **Grok:** "Tiers are cruder but safer—less gamable, more interpretable. Revert to tiers if formula isn't battle-tested."

**Resolution:** Fran and Grok actually agree — they just got there from different directions. Fran says "compute the number, show the band." Grok says "bands are safer than numbers." Result is the same: band is primary, number is behind the curtain for audit purposes.

**Action:** Adopt Fran's formula (see §4) but display Grok's recommendation (bands first, number on hover/expand).

### 2c. Center-Specific Parameterization Needed
- **Grok:** "It breaks on expansion. A JSC user gets MSFC-format output, rejected in review."
- **Gemini:** "Abstract with `AuthorityPack`. Build the interface now, implement only NASA-6016C."
- **Fran:** "Add `AuthorityPack` (center/program overrides) to CategoryRouter inputs."
- **CC:** Didn't address (implementation-focused, not design-focused)

**Action:** Add `center: Optional[Enum]` to session state. Build `AuthorityPack` interface. Implement only MSFC/6016C for v7 launch. JSC/GRC/KSC packs are Phase 2.

### 2d. LLM Layer Is the Concurrency Bottleneck
- **Grok:** "The LLM call is the real killer. Rate limits hit at 3-5 concurrent."
- **CC:** Template-based draft as fallback if LLM fails
- **Fran:** Two-layer synthesis (template + LLM polish)

**Action:** Template-first architecture ensures draft generation never blocks on LLM availability. LLM polish is enhancement, not dependency. Add Celery queue for LLM calls if concurrency exceeds 3.

---

## 3. KEY DISAGREEMENT — Needs Dude's Call

### 3a. Boost Cap Values (C1 Fix)

**Beth's spec:** Cap relevance boosts at 1.0 (no boost exceeds raw relevance)  
**CC's implementation:** Caps at 3.0 for boost_factor, 2.0 for final score

These are VERY different. A 1.0 cap means boosts can never increase relevance beyond the base score. A 3.0/2.0 cap means a 0.55 base relevance can still get boosted to 1.10 (2.0 × 0.55) — which was the exact problem in the safety audit (weak matches getting boosted above strong ones).

**Dude's call needed:** CC's fix was applied to the CURRENT codebase as a pragmatic cap. For v7, do we go with Beth's stricter 1.0 cap? Or is there a middle ground? The safety audit showed a 0.55 match boosting to 2.47 — CC's cap would reduce that to 1.10, Beth's would reduce it to 0.55. In safety-critical systems, I'd advocate for the stricter cap unless there's evidence that boosts provide genuine retrieval value.

### 3b. Fact Checker Scope

**Grok:** "For holistic claims, flag as 'Engineering judgment required.' Stick to atomic claims."  
**Gemini:** Didn't address fact checking directly, but process-sensitivity implies claims need to be structured.  
**Fran:** Built `AtomicClaim` into EvidenceRef (claim_type enum: RATING, ENVELOPE, DETERMINATION, etc.)

**Resolution:** Fran's AtomicClaim model IS the fact checker's anchor. If every evidence item has structured claims, the fact checker maps draft sentences to claims, not to unstructured text. Holistic statements get tagged "JUDGMENT" and aren't verified — they're flagged.

**Action:** Adopt Fran's AtomicClaim model. Fact checker verifies RATING/ENVELOPE/DETERMINATION claims deterministically. JUDGMENT claims get a "(Engineering assessment)" tag in the draft.

---

## 4. THE GOLD — Unique Insights Nobody Else Caught

### 🥇 Gemini: Process-Sensitive Materials Need Step 1b

**The catch:** Adhesives and composites don't have fixed properties — they depend on cure cycle, mix ratio, layup orientation. A standard material-only MUA for Epibond is dangerous because the same adhesive has radically different properties depending on how it was processed.

**Nobody else saw this.** The 5-step wizard assumes material = static entity. For 15-20% of aerospace materials, that's wrong.

**Action:** Add "Process Sensitivity" flag to material resolution. If material class is Adhesive/Composite/Potting, inject process definition fields (cure temp, cure time, vacuum pressure, mix ratio). These become part of the investigation query and appear in the MUA document.

### 🥇 Gemini: Chained MUA Dependency Graph

**The catch:** MUA-101 says "approved via similarity to MUA-099." If MUA-099 is later revoked, MUA-101 is a zombie — technically approved but pointing to a corpse. Nobody tracks this.

**Nobody else saw this.** This is a latent institutional risk that exists in the paper world too, but MIRA has the data to actually detect it.

**Action (v7):** When citing precedent MUAs, store the dependency link. Background job: if a precedent MUA's status changes, flag all dependent MUAs. Not auto-revoke — flag for review.

**Action (future):** Full dependency graph visualization. "This MUA has 3 downstream dependents."

### 🥇 Gemini: Split Relevance into Physics vs. Regulatory

**The catch:** A 1995 MUA for 6061-T6 on Shuttle has GREAT flammability data (physics hasn't changed) but USELESS approval logic (standards have changed 3 times). Current system treats "old precedent" as one dimension. It's actually two.

**Nobody else decomposed this.** Grok mentioned precedent age but didn't split it. Fran's currency_score treats it as one number.

**Action:** Split relevance scoring:
- `physics_relevance`: Is the test data still valid? (High weight for heritage)
- `regulatory_relevance`: Is the approval logic still valid? (Decay function based on standard revisions)

**UI:** Tag old precedents: *"Valid Test Data / Obsolete Approval Logic"*

**Impact on Fran's model:** Currency score splits into `data_currency` and `regulatory_currency`. This is a clean extension of the EvidenceQuality model.

### 🥇 Gemini: Novel Material → Test Plan Mode

**The catch:** For genuinely new materials (GRCop-42 in a new heat treat, AM parts), there are ZERO precedents. The system returns 0.0 evidence strength and becomes a glorified text editor.

**The fix:** If `precedents == 0` AND `direct_data == None`, offer to switch to "Qualification Plan Mode" — generate a test plan recommendation instead of an MUA.

**Action (v7):** Detect zero-evidence condition. Prompt: *"This appears to be a novel material. Would you like to generate a Test Qualification Plan instead?"* Output lists required tests (flamm, offgas, SCC, etc.) based on environment.

### 🥇 Fran: Two-Tier Evidence Identity (Content Hash + Deterministic ID)

**The catch:** The compliance module requires SHA-256 hashes. The 5,650 corpus MUAs don't have them. Migration could block the entire redesign.

**Fran's solution:** Tier A (content hash) when you have full excerpt + assertions. Tier B (deterministic ID from source_type + primary_key + locator) as fallback. Both are stable, dedupable, and auditable.

**Nobody else solved the migration problem.** CC said "promote compliance models" but didn't address the hash gap. Grok didn't address it. Gemini didn't address it.

**Action:** Implement two-tier identity. Backfill job runs once across corpus. v7 accepts either tier. Over time, Tier B items get upgraded to Tier A as they're re-processed.

### 🥇 Fran: AtomicClaim Assertions in EvidenceRef

**The catch:** Current evidence items are either unstructured text or simple key-value pairs. Fran's model adds structured `assertions` to every evidence item — typed claims (RATING, ENVELOPE, DETERMINATION, etc.) with subject, value, and qualifiers.

**This solves the fact-checking problem.** If evidence has structured claims, the fact checker has something deterministic to verify against. No NLP needed for "10 approved precedents" — count the DETERMINATION claims.

**Action:** Adopt AtomicClaim model. Populate during ingestion (extraction pipeline already generates these implicitly — make them explicit).

### 🥇 Fran: Saturation Function for Precedent Support

**The formula:** `1 - exp(-k * sum(relevance_i * authority_i))`

**Why it's gold:** This naturally saturates — 20 mediocre precedents can't fake "perfect." It addresses Grok's concern about gaming because the exponential decay means marginal value of each additional precedent drops. 3 strong precedents ≈ 15 weak ones. That matches engineering intuition.

### 🥇 Gemini: Force Rationale When Human Diverges from AI

**The catch:** If AI says "Evidence Strength: STRONG" and engineer rejects, or AI says "WEAK" and engineer approves — that divergence is gold data. Make the rationale field mandatory when human disagrees.

**Nobody else caught the training loop.** These divergences become "gold labels" for model improvement.

**Action:** Step 3 (Review): If engineer's decision opposes evidence strength band, rationale field becomes required. Store these as calibration data.

### 🥇 Grok: Cache Common Material Queries

**The observation:** 6061-T6 shows up in ~20% of MUAs. Redis cache on material resolution + investigation results could cut 50% of full searches.

**Action:** Add Redis cache layer for material resolution results. TTL: 24 hours (test data doesn't change hourly). Cache key: material_code + environment_hash.

### 🥇 Gemini: Regulatory Drift — Standard Version Snapshotting

**The catch:** When 6016C becomes 6016D, every MUA generated under C is technically against an outdated standard.

**Action:** Store `applied_standard_version` in session state and final document. When standards update, background delta job flags MUAs that may need review. Don't auto-revoke — flag as `compliant_at_creation`.

---

## 5. REVISED ARCHITECTURE (Post-Convergence)

### Step 1: DEFINE (Updated)
- Material + Environment + Application (unchanged)
- **NEW:** Process Sensitivity flag → Step 1b for composites/adhesives
- **NEW:** Center selection → loads AuthorityPack (MSFC default)
- O2 ≥ 23.5% → enrichment banner (unchanged)
- Both temp min AND max required (unchanged)

### Step 2: INVESTIGATE (Updated)
- Unified search via V6PrecedentRetriever + classification post-filter (unchanged)
- **NEW:** Zero-precedent detection → offer Test Plan Mode
- **NEW:** Physics vs Regulatory relevance split on precedents
- **NEW:** Dependency check on cited precedent MUAs (zombie detection)
- Evidence Strength (not "confidence") derived from Fran's formula
- Band displayed: STRONG/MODERATE/WEAK (number secondary)
- **NEW:** Cache hit for common materials (Redis, 24hr TTL)

### Step 3: REVIEW (Updated)
- Engineer reviews flagged items (unchanged)
- **NEW:** Mandatory rationale when diverging from AI recommendation
- **NEW:** Divergence decisions stored as calibration gold labels
- All gaps/conflicts must be addressed before draft (unchanged)

### Step 4: DRAFT (Updated)
- Template-first, LLM-polish-second (unchanged)
- **NEW:** Fact checker anchored to AtomicClaim model
- **NEW:** Claims tagged as VERIFIED or JUDGMENT
- **NEW:** Process constraints appear in rationale for adhesives/composites
- Inline editing with audit trail (unchanged)

### Step 5: FINALIZE (Updated)
- **NEW:** `applied_standard_version` recorded
- **NEW:** Dependency links stored for cited precedent MUAs
- **NEW:** Center/AuthorityPack recorded
- Export options unchanged

### Data Model (Fran's Schema, Extended)
- EvidenceRef with two-tier identity (hash + deterministic ID)
- AtomicClaim assertions on every evidence item
- EvidenceQuality with split currency (data + regulatory)
- CategoryRoutingResult with AuthorityPack support
- MuaSessionState in PostgreSQL with JSONB + Pydantic serialization

---

## 6. IMPLEMENTATION PRIORITY (Revised)

### P0: Safety Fixes (Before Anything) — 1 day
1. ✅ C1: Boost caps (done, but revisit 3.0→1.0 for v7)
2. ✅ C4: Temp min (done)
3. C2: Missing data defaults → 0.0 not 0.5
4. C3: Top-k consensus rule

### P1: Backend Pipeline — 1 week
- New `mira/mua/v7/` directory (CC's file structure)
- Session model (Fran's Pydantic + CC's PostgreSQL)
- Unified EvidenceRef with two-tier identity (Fran)
- Investigator with V6PrecedentRetriever wrapper (CC)
- Conflict detector (Beth's spec)
- Category router with AuthorityPack interface (Fran + Gemini)
- Evidence Strength calculator (Fran's formula)

### P2: API Surface — 2 days
- 5 endpoints per CC's spec
- Session CRUD
- Add center param and process sensitivity flag

### P3: Frontend Wizard — 1 week
- 6 components per CC's breakdown
- URL params + React context (no zustand)
- Step 1b process definition (conditional)

### P4: Production Features — 1 week
- Fact checker with AtomicClaim anchoring
- Physics/Regulatory relevance split
- Divergence tracking + mandatory rationale
- Redis cache for common materials

### P5: Future (Post-March 17)
- Dependency graph for chained MUAs
- Test Plan Mode for novel materials
- Multi-center AuthorityPack implementations
- Standard version delta reporting
- Reviewer calibration analytics

---

## 7. MARCH 17th DEMO SCOPE

**Need P0 through P3.** The demo story:

1. Type "Inconel 718" → live resolution (green checkmark)
2. Fill environment: 30% O2, 3000 psi, -100°F to 500°F
3. System shows: "Enriched oxygen detected" banner + "Cryogenic range" banner
4. Click Investigate → watch evidence gather
5. Results: "14 precedents (12 supporting, 2 conflicting). Evidence Strength: MODERATE"
6. Review: 3 flagged items. Engineer makes calls.
7. Generate draft → full 7-section NASA document
8. Finalize with audit trail

**Punchline:** *"Two hours of MAPTIS searching and manual writing → two minutes of MIRA investigation + five minutes of engineering judgment. Same rigor. Fraction of the time."*

---

## 8. OPEN QUESTIONS FOR DUDE

1. **Boost cap:** 1.0 (Beth's strict) or 3.0/2.0 (CC's pragmatic)? For v7 specifically.
2. **Process sensitivity in v7 or v8?** Gemini's right that it matters, but it's scope creep for March 17th unless adhesive MUAs are common in the demo dataset.
3. **Test Plan Mode:** Love it, but is it March 17th scope? Or is it a "coming soon" slide?
4. **Reviewer divergence tracking:** Gold for long-term model improvement, but could make engineers nervous about being monitored. Roll out quietly or announce as a feature?

---

*Four Oracles spoke. None broke the design. All made it stronger. The 5-step wizard holds — it just got smarter about what it doesn't know.*
