# MUA v7 Oracle Brief
## Feed This to the Team — Get Convergent Solutions

**Date:** 2026-02-07  
**Method:** Oracle consultation — each AI reviews independently, we synthesize where they converge  
**Goal:** Validate or challenge the MUA v7 redesign before we build

---

## Context (Give This to Everyone)

MIRA's MUA (Material Usage Agreement) module currently has 6 separate implementation paths for generating MUA documents. A safety audit found 5 CRITICAL bugs that could cause incorrect flight determinations in safety-critical NASA materials reviews. We're consolidating into a single 5-step wizard with human-in-the-loop, same pattern that succeeded for our MIUL v4 module (reduced false positives from 93% to 28%).

**What an MUA is:** A formal document that justifies using a specific material in a specific environment on a spacecraft. It cites test data, precedent approvals, identifies gaps, routes to the correct NASA approval category (I/II/III), and provides engineering rationale. Getting this wrong means approving a material that could fail in flight.

**What we have:**
- 5,650+ parsed historic MUAs as precedent corpus (FAISS indexed)
- MAPTIS PostgreSQL database with 181K+ test records
- O2/H2 compatibility engines (production)
- NASA-STD-6016C category routing logic (in v1, not wired to v6)
- Compliance module with rich evidence models (EvidenceRef with SHA-256, GapSignal, MPRDetermination) — designed but not connected to the MUA pipeline
- 4 independent MUA generation implementations (v1 service, v1 generator, v6 pipeline, v6 corpus)

**What we're building:**
Single pipeline: DEFINE → INVESTIGATE → REVIEW → DRAFT → FINALIZE
- One search backend (unified FAISS+BM25)
- Evidence-derived confidence (not hardcoded 0.0/0.3/0.6/0.85)
- Conflict detection across sources (currently absent)
- Post-generation fact verification (currently absent)
- Human review of flagged gaps/conflicts before draft generation
- Full NASA 7-section document format output
- Audit trail for SWE-013 compliance

**The 5 critical safety bugs being fixed:**
1. Uncapped 2-3x semantic relevance boosts (irrelevant docs rank above real evidence)
2. Missing pressure/temp data defaults to 0.5 (neutral) instead of 0.0 (unknown)
3. Verdict engine checks only first FAISS result (no multi-record consensus)
4. Temperature lower bound silently dropped (cryogenic approval without data)
5. Vision-extracted EPL columns have zero post-validation

**Attached files for reference:**
- `MUA_CURRENT_WORKFLOW.md` — what exists today (endpoints, flows, modes)
- `MUA_SAFETY_AUDIT.md` — full audit findings with file/line references
- `mua-pipeline-analysis.md` — deep code analysis of all 4 implementations
- `MUA_DEEP_DIVE_AND_REDESIGN.md` — Beth's proposed v7 architecture

---

## For Fran (GPT) — Architecture & Schema Design

You're our schema architect. You nailed the universal extractor schema scoping. Now we need you on MUA data models.

**Review and answer:**

1. **Unified evidence model.** We have two competing `EvidenceRef` models:
   - `mira/compliance/models/evidence.py` — SHA-256 hashes, confidence scores, provenance chains
   - `mira/mua/models.py` — bare MAPTIS ID + report number
   
   The compliance version is clearly superior. But the MUA pipeline's precedent data (5,650 parsed MUAs) doesn't have SHA-256 hashes on every record. **How do we migrate?** Do we hash on ingestion? Do we run a backfill? What's the minimum viable evidence model that unifies both without losing the compliance module's rigor?

2. **Session state schema.** The 5-step wizard needs server-side session state (like MIUL v4). Design the session model that tracks:
   - Step 1 inputs (material, environment, application)
   - Step 2 investigation results (all evidence gathered)
   - Step 3 review decisions (per-item: include/exclude/accept-gap with rationale)
   - Step 4 draft (with edit history)
   - Step 5 finalization (reviewer, timestamp, export format)
   
   What's the right schema? Flat JSON? Nested Pydantic? Event-sourced? Consider that engineers may save mid-review and come back tomorrow.

3. **Confidence calculation schema.** Current system hardcodes 0.0/0.3/0.6/0.85 by decision tier. New system derives from evidence quality. Propose a confidence calculation model that takes:
   - Precedent count and relevance scores
   - Envelope coverage (within/partial/extrapolation)
   - Test data currency (current/expired/missing)
   - Conflict severity
   - Gap count and severity
   
   ...and produces a confidence score that actually means something. What are the weights? What's the floor? What's the ceiling?

4. **Category routing data model.** v1 has category routing (I/II/III + Appendix B). v6 doesn't. The compliance module has `MUAAdapterOutput` with a `category` field. Design the routing model that connects NASA-STD-6016C requirements to the decision engine output. How does an O2% ≥ 23.5% trigger propagate from Step 1 through to the final document?

---

## For CC (Claude Code / VSClaude) — Implementation

You're building this. You need to know where every wire connects.

**Review and answer:**

1. **Merge strategy.** We have 4 implementations:
   - `mira/mua/service.py` (278 lines) — v1 service
   - `mira/mua/mua_generator.py` (439 lines) — v1 full document generator
   - `mira/api/routers/mua_v6.py` (783 lines) — v6 pipeline + corpus router
   - `mira/mua/v6/` (8 files, ~3,500 lines) — v6 modules
   
   Plus the compliance models in `mira/compliance/models/` that aren't connected.
   
   **What's the safest merge strategy?** Build v7 as new files and deprecate? Or refactor in place? Consider that the v6 endpoints are currently deployed and the frontend talks to them. We need a migration path that doesn't break the live system.

2. **The 5 safety fixes.** These need to happen BEFORE the redesign, on the current code. Walk through each fix in the safety audit (C1-C5) and confirm:
   - Exact file and line changes needed
   - Whether the fix has downstream effects on other modules
   - Whether we need regression tests
   - Whether any fix changes the API contract (frontend impact)

3. **Search backend unification.** Currently:
   - `MUAFAISSSearch` used by `enriched_search.py` 
   - `V6PrecedentRetriever` used by corpus endpoints (FAISS+BM25 hybrid with RRF)
   
   The retriever is clearly better (hybrid search, structured filtering, ranking). But enriched_search has the supporting/conflicting classification. **How do we merge these?** Write the unified search interface that CC will implement.

4. **Frontend migration.** The current `MUAGenerator.tsx` is 2,917 lines. The new design is 6 components totaling ~1,000 lines. **What's the migration path?** Can we build the new wizard as a parallel route (`/mua-v7`) and switch over? Or do we need to gut the existing component? What state management approach for the 5-step wizard? (zustand? context? URL params?)

5. **Session resume.** MIUL v4 has session resume. MUA v7 needs it too. The investigation step hits MAPTIS, FAISS, and potentially the LLM — that's 5-10 seconds of work. If the engineer closes the browser and comes back, we need to restore their session at whatever step they left off. **What's the storage strategy?** Redis? PostgreSQL? File-based JSON like MIUL?

---

## For Grok — Scale & Edge Cases

You're our stress tester. Break this design before we build it.

**Review and answer:**

1. **What happens at scale?** The corpus is 5,650 MUAs today. What happens at 50,000? At 500,000? The FAISS index, the BM25 index, the hybrid search — where do they break? What's the latency profile for the Investigate step when the corpus is 10x larger?

2. **Concurrent users.** If 5 engineers are running MUA investigations simultaneously, all hitting MAPTIS PostgreSQL, all running FAISS searches, all potentially calling the LLM for rationale synthesis — what breaks first? Is the session state design robust enough for concurrent access?

3. **The confidence calculation.** Beth proposes evidence-derived confidence replacing hardcoded tiers. **Devil's advocate this.** Is a computed confidence score actually more trustworthy than a simple tier? Can the weights be gamed? What happens when the formula produces 0.72 and the engineer interprets that as "probably fine" when it should be "barely acceptable"? Is the number more dangerous than the tier because it implies false precision?

4. **Adversarial inputs.** What happens when an engineer types "asdf" as the material? What about "aluminum" (no alloy designation)? What about "material per drawing note 7" (a common MIUL entry that isn't a material)? How robust is material resolution to real-world garbage input?

5. **The fact checker.** Beth proposes post-generation claim verification. **How do you verify natural language claims against structured evidence?** "10 approved precedents" is easy to count. But "material demonstrates acceptable performance for the specified operating conditions" — how do you fact-check that? Where's the line between verifiable claims and engineering judgment?

6. **Multi-center deployment.** MIRA is expanding beyond MSFC. JSC, GRC, KSC all have different MUA templates, different approval workflows, different local conventions. Does this design accommodate center-specific customization? Or does it assume one NASA-wide format?

---

## For Gemini — Edge Cases & What We're Missing

You find the things nobody else sees.

**Review and answer:**

1. **What document types break this?** Not all MUAs are standard Category I/II/III. What about:
   - MUAs for composite materials (layup-dependent properties)
   - MUAs for adhesives/sealants (cure-dependent, process-sensitive)
   - MUAs for COTS (Commercial Off-The-Shelf) components where material is unknown
   - MUAs that reference other MUAs (chained approvals)
   - MUAs for materials that have been superseded/obsoleted
   
   Does the 5-step workflow handle all of these? Where does it break?

2. **The precedent relevance problem.** A 1995 MUA for 6061-T6 on Shuttle might cite test standards that have since been revised. The material is the same. The environment is similar. But the regulatory basis has changed. **How should the system handle precedent age?** Is a 30-year-old precedent less relevant? More relevant (proven heritage)? It depends on context — how do we surface that to the engineer?

3. **International standards.** NASA works with ESA, JAXA, CSA. Their materials standards differ. If MIRA expands internationally, the MUA format and category routing are NASA-specific. **What's the abstraction layer?** Is it the Authority Pack concept from SENTINEL? Can the MUA writer be parameterized by standards body?

4. **The "no precedent" case.** For novel materials (new alloys, additively manufactured parts, nanomaterials), there may be ZERO precedents in the corpus. The current system either blocks or silently uses garbage. **What's the right workflow for genuinely novel materials?** Should the system produce a different kind of document (test plan recommendation instead of MUA)?

5. **Regulatory drift.** NASA-STD-6016 gets revised. When 6016C becomes 6016D, every MUA generated under 6016C is technically against an outdated standard. **How does the system track which version of the standard was in effect when the MUA was generated?** Is this in the audit trail? Does the system flag MUAs that may need updating when standards change?

6. **The human factor nobody talks about.** Engineers have preferences. Engineer A always accepts analog data. Engineer B never does. Engineer A's MUAs have systematically different risk profiles than Engineer B's. **Should the system track reviewer patterns?** Not to judge, but to flag when a reviewer's acceptance rate is significantly different from the population. Is that useful? Is that dangerous?

---

## Convergence Criteria

After all four respond, we're looking for:

1. **Where do they agree?** That's what we build.
2. **Where do they disagree?** That's what we discuss.
3. **What did someone catch that nobody else did?** That's the gold.
4. **Did anyone find a fatal flaw in the 5-step design?** If so, we redesign before we code.

The v7 MUA Writer should be as clean and confident as MIUL v4. No compromises on safety. No shortcuts on evidence. The engineer's judgment is the final word, and MIRA's job is to make that judgment as informed as possible.

---

*"Data is noise. Information is organized noise. Intelligence is 'here's what you actually do about it.'"*

*The MUA Writer is where MIRA stops organizing noise and starts telling engineers what to actually do about it — with evidence, with citations, and with the humility to flag what it doesn't know.*
