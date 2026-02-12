# MUA v7 — Opus Build Handoff
## Implementation Brief for Sandbox Build

**Date:** 2026-02-07  
**From:** Beth (Architecture) + Dude (Domain Authority)  
**To:** Opus (Builder)  
**Review:** Codex 5.3 (Inspector) → Beth + Dude (Sign-off) → Opus (Final Implementation)

---

## Your Job

Build the MUA v7 module in sandbox. The full specification is in `MUA_V7_FINAL_SPEC.md`. This document tells you what to build, what order, and what to be careful about.

After you build, Codex reviews the sandbox. Then we review Codex's findings. Then you implement for real.

---

## Read These Files (In This Order)

1. **`MUA_V7_FINAL_SPEC.md`** — The locked specification. This is the source of truth. Everything you build must match this.

2. **`MUA_SAFETY_AUDIT.md`** — The safety findings. 5 CRITICAL bugs, 13 HIGH, 8 MEDIUM. P0 fixes (C2 and C3) must be implemented BEFORE any v7 code. C1 and C4 are already done.

3. **`MUA_DEEP_DIVE_AND_REDESIGN.md`** — The original analysis. Has file-by-file breakdown of current code, what to reuse, what to retire.

4. **CC's implementation answers** (in `MUA_V7_ORACLE_CONVERGENCE.md` or provided separately) — Has exact merge strategy, file paths, PostgreSQL schema, frontend component breakdown.

---

## Build Order

### Phase 0: Safety Fixes (BEFORE anything else)

**C2: Missing data defaults to 0.5 instead of 0.0**
- File: `mira/mua/v6/decision_engine.py`
- Where: `MUADecisionEngine.evaluate()` — when `envelope_result` is None or `test_data_status` is None
- Fix: `envelope_result is None` → treat as OUTSIDE (penalty 1.0). `test_data_status is None` → add review factor "No MAPTIS test data available"
- Test: Create `tests/mira/mua/v6/test_decision_engine.py`
- API impact: None

**C3: Verdict engine checks only first record**
- File: `mira/knowledge_twins/verdict_engine.py`
- Where: Line ~234: `best_record = matched_records[0]`
- Fix: Add `_check_consensus(matched_records, top_k=5)` method. Hard conflict (COMPATIBLE vs INCOMPATIBLE in top-5) → 0.4× penalty + downgrade to MARGINAL. Soft conflict → 0.7× penalty.
- Wire into: `compute()` after Step 8 (confidence penalty), before Step 9 (warnings)
- Test: Add `TestTopKConsensus` in `tests/mira/knowledge_twins/test_knowledge_twins.py`
- API impact: None (internal scoring only, but confidence scores will change)

### Phase 1: Backend Pipeline

Create `mira/mua/v7/` directory:

```
mira/mua/v7/
├── __init__.py
├── models.py               # Request/response models, AtomicClaim, EvidenceQuality
├── session.py              # MuaSession Pydantic model + PostgreSQL CRUD
├── material_resolver.py    # Lookup-table resolution (not regex)
├── process_sensitivity.py  # Step 1b: adhesive/composite process params
├── investigator.py         # Step 2: unified search + evidence gathering
├── relationship_explainer.py # Per-precedent plain-English explanations
├── conflict_detector.py    # Cross-source conflict detection
├── category_router.py      # NASA-STD-6016C routing (AuthorityPack interface)
├── confidence.py           # Evidence Strength calculator (Fran's formula)
├── draft_renderer.py       # 7-section NASA document (template-first + LLM polish)
├── fact_checker.py         # Post-generation claim verification via AtomicClaim
└── qualification_plan.py   # Novel material → test plan generator
```

**What to import (don't rewrite):**
- `mira/mua/v6/retriever.py` → `V6PrecedentRetriever` (FAISS+BM25+RRF)
- `mira/mua/v6/envelope_matching.py` → `compute_envelope_overlap`
- `mira/mua/v6/data_cleaner.py` → `RationaleSynthesizer`, `V6DataCleaner`
- `mira/mua/v6/maptis_test_data.py` → `query_maptis_test_data`
- `mira/mua/v6/material_identity.py` → `resolve_material_identity`
- `mira/compliance/models/evidence.py` → `EvidenceRef` (extend, don't replace)
- `mira/compliance/models/gaps.py` → `GapSignal`, `OperationalConstraint`
- `mira/compliance/models/determination.py` → `MPRDetermination`

**Critical implementation details:**

1. **Boost cap = 1.0 in v7.** When scoring retrieved precedents, no relevance boost may push a result above its base relevance score. Boosts are tiebreakers, not promoters. This is a safety-critical design decision.

2. **Missing data = 0.0 (unknown), not 0.5 (neutral).** For pressure, temperature, O2 concentration — if data is missing, the score is zero. Neutral implies "probably fine." Zero implies "we don't know."

3. **Both temp_min AND temp_max required.** Step 1 form validation. Cannot proceed to Investigate without both bounds.

4. **Evidence Strength, not Confidence.** The metric is called `evidence_strength` everywhere — variable names, API fields, UI labels. Never `confidence`. Display band (STRONG/MODERATE/WEAK) prominently, numeric score secondary.

5. **"May be applicable" language.** All relationship explanations use hedged language. Never "is approved" or "is compatible." Always "may be applicable," "may support your case," "engineering judgment needed."

6. **Template-first draft generation.** Template (deterministic) MUST produce valid output even if LLM fails. LLM polish is enhancement, not dependency.

7. **Two-tier evidence identity.** Tier A: SHA-256 of canonical JSON (sort keys, normalize whitespace, drop volatile fields). Tier B: SHA-256 of `f"{source_type}:{primary_id}:{locator}:{span}"`. Accept either. Prefer Tier A when content is available.

8. **Divergence tracking is silent.** Backend stores it. No UI indicator. Rationale field becomes mandatory when engineer decision opposes Evidence Strength band. That's the only user-visible effect.

9. **Process sensitivity is conditional.** Only show Step 1b fields when material class resolves to Adhesive/Composite/Potting/Sealant. Don't show for metals/alloys.

10. **AuthorityPack interface built, only MSFC/6016C implemented.** The category router accepts an authority_pack parameter. Only one implementation exists (NASA-STD-6016C). But the interface is there for future centers.

### Phase 2: API Surface

```python
# mira/api/routers/mua_v7.py

POST /api/mua/v7/resolve-material     # Live material resolution
POST /api/mua/v7/investigate           # Step 2: full evidence gathering
POST /api/mua/v7/review-decisions      # Step 3: save review decisions
POST /api/mua/v7/generate-draft        # Step 4: generate MUA document
POST /api/mua/v7/finalize              # Step 5: lock + export

GET  /api/mua/v7/session/{id}          # Resume session
GET  /api/mua/v7/sessions              # List user's sessions (filter by status)
DELETE /api/mua/v7/session/{id}        # Abandon session

POST /api/mua/v7/qualification-plan    # Novel material → test plan
GET  /api/mua/v7/stats                 # Usage analytics
```

### Phase 3: PostgreSQL Migration

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
    process_params JSONB,
    application TEXT,

    -- Step 2
    investigation_result JSONB,

    -- Step 3
    review_decisions JSONB,
    divergence_labels JSONB DEFAULT '[]'::jsonb,

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

### Phase 4: Frontend

New route at `/mua-v7`. Do NOT touch existing `MUAGenerator.tsx`.

```
frontend/src/pages/MUAWizardV7.tsx
frontend/src/components/mua-v7/
├── MUADefineStep.tsx
├── MUAInvestigateStep.tsx
├── MUAReviewStep.tsx
├── MUADraftStep.tsx
└── MUAFinalizeStep.tsx
```

State management: URL params + React context. Server is source of truth.
Route: `/mua-v7?step=investigate&session=abc123`

---

## What NOT to Do

1. **Don't delete v6 code.** v7 imports from it. Deprecation happens after validation.
2. **Don't build a new search backend.** Wrap V6PrecedentRetriever.
3. **Don't use "confidence" anywhere.** It's "evidence_strength" with band display.
4. **Don't hardcode 0.5 for missing data.** 0.0 always. This is a safety fix.
5. **Don't auto-approve anything.** Every determination is the engineer's. MIRA presents evidence and explains fit.
6. **Don't expose boost mechanics to UI.** Engineers see relevance explanations, not score multipliers.
7. **Don't skip the template fallback.** If LLM fails, template draft must still work.
8. **Don't build zustand/redux.** URL params + context is sufficient for a linear wizard.

---

## Testing Requirements

Every module needs tests. Minimum:

- `test_material_resolver.py` — Standard inputs, fuzzy matches, garbage, non-materials
- `test_investigator.py` — Normal case, zero precedents, process-sensitive materials
- `test_confidence.py` — All components, saturation behavior, penalty multiplication
- `test_category_router.py` — Cat I/II/III routing, O2 threshold, boundary cases
- `test_conflict_detector.py` — Supporting/conflicting classification, cross-source conflicts
- `test_fact_checker.py` — Atomic claim verification, judgment tagging
- `test_draft_renderer.py` — Full 7-section output, template fallback, process constraints
- `test_session.py` — CRUD, resume, step advancement, auto-abandon
- `test_decision_engine.py` — C2 fix: missing data defaults (P0 safety)
- `test_verdict_consensus.py` — C3 fix: top-k consensus (P0 safety)

---

## Success Criteria

When the sandbox build is complete, Codex should be able to verify:

1. ✅ C2 and C3 safety fixes pass tests
2. ✅ Material resolver handles standard, fuzzy, garbage, and non-material inputs
3. ✅ Investigation returns per-precedent explanations with "may be applicable" language
4. ✅ Evidence Strength shows bands, not "confidence"
5. ✅ Missing data scores 0.0, not 0.5
6. ✅ Boost cap is 1.0 (no weak match outranks strong match)
7. ✅ Template draft generates valid 7-section NASA MUA without LLM
8. ✅ Session persists in PostgreSQL and resumes correctly
9. ✅ Divergence labels stored silently when engineer opposes AI band
10. ✅ Process sensitivity fields appear only for adhesives/composites
11. ✅ Zero-precedent case offers Qualification Plan Mode
12. ✅ Category routing produces deterministic I/II/III with basis citations
13. ✅ Fact checker verifies atomic claims, tags judgment claims
14. ✅ Draft rationale reflects engineer's Step 3 decisions in their own words
15. ✅ All flagged items must be reviewed before draft generation (completion gate)

---

## Codex Review Categories

When Codex reviews, have it categorize findings as:

- **SAFETY** — Touches a P0 fix or audit finding. Must fix before sign-off.
- **CORRECTNESS** — Logic bug, type mismatch, unhandled edge case. Must fix.
- **DRIFT** — Works but diverges from spec intent. Beth + Dude decide.
- **STYLE** — Works, matches spec, could be cleaner. Opus decides on final implementation.

---

*Build it right. Build it safe. Build it so the engineer trusts it with their career.*
