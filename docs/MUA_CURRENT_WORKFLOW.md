# Current MUA Workflow (Implementation Snapshot)

Last updated: 2026-02-07
Source of truth: running code in `mira/api/routers/mua.py`, `mira/api/routers/mua_v6.py`, `mira/mua/service.py`, `mira/mua/v6/*`, and `frontend/src/pages/MUAGenerator.tsx`.

## 1. Endpoint Surface

Backend routers are mounted in `mira/api/app.py` as:
- `/mua` -> legacy + BOK workflows (`mira/api/routers/mua.py`)
- `/mua/v6` -> v6 pipeline + corpus workflows (`mira/api/routers/mua_v6.py`)

Frontend uses `/api/...` paths (proxy prefix), for example:
- `/api/mua/generate-batch`
- `/api/mua/bok/find`
- `/api/mua/v6/generate`
- `/api/mua/v6/corpus/draft`

## 2. Frontend Modes (MUAGenerator)

`frontend/src/pages/MUAGenerator.tsx` has 6 tabs:
1. `Corpus Draft` (default tab)
2. `V6 Pipeline`
3. `AI Synthesis`
4. `Precedent Engine`
5. `Interactive`
6. `Batch`

So the current user-visible workflow is multi-path, not a single linear MUA pipeline.

## 3. Batch Workflow (MIUL -> MUA Remarks/JSON)

Used by Batch tab.

### 3.1 `/mua/generate-batch`

Input:
- Excel file with `MIUL` sheet.
- Optional query params: `program` (default `ORION`), `hardware`.

Flow:
1. Load `MIUL` sheet into dataframe.
2. Detect rating columns by variant names (FLAMM/CORR/SCC/TVS/TOX/FS).
3. Normalize non-standard ratings:
   - `LOW->A`, `MED/MEDIUM->B`, `HIGH/D->C`, `I/K/N->U`.
4. Mark row as gap row if any rating is non-`A`.
5. For each gap row call `mira.mua.service.generate_mua()`.
6. Return JSON list (`muas`) with category, gap profile, and draft text.

Important behavior:
- Rows with all-`A` ratings are skipped.
- No precedent retrieval is used in this path.
- Environment passed to service is mostly empty (`EnvironmentSpec()` defaults).

### 3.2 `/mua/generate-batch-excel`

Same detection/normalization pipeline as above, but returns an Excel file.

Flow difference:
1. Ensures `Remarks` column exists.
2. Writes MUA summary text + mitigation snippets into `Remarks`.
3. Returns workbook with a single `MIUL` sheet containing updated remarks.

## 4. Legacy BOK Interactive Workflow (V2-style)

Used by Interactive tab.

### Step 1: `/mua/bok/find`
- Exact material/issue matching via `MUABOKEngine.find_exact_precedents(...)`.
- Returns precedent cards with rationale summary/full text.

### Step 2: User selection in UI
- User selects precedent IDs to keep.

### Step 3: `/mua/bok/generate-from-selection`
- Generates a draft from selected precedent IDs.
- Returns draft with provenance and cited precedents.

Supporting endpoint:
- `/mua/bok/stats` returns index-level metadata summaries.

## 5. AI Synthesis Workflow (V3)

Used by AI Synthesis tab.

Endpoint:
- `/mua/bok/synthesize`

Flow:
1. Build synthesis request (material, issue, application, environment, location, etc.).
2. `MUASynthesizer.generate_mua(...)` runs applicability analysis per precedent.
3. System returns synthesized rationale, confidence, warnings, and applicability factors.

This is intended to generate new rationale text (not copy/paste precedent rationale).

## 6. Precedent Engine Workflow (V4)

Used by Precedent Engine tab.

Endpoint:
- `/mua/bok/precedent/evaluate`

Flow:
1. Parse deviation types from issue strings (FLAM, SCC, CORR, TVS, TOX, FS).
2. Build query `EnrichedMUA`.
3. Retrieve candidate precedents from BOK engine.
4. Run `PrecedentEngine.evaluate_candidates(...)`.
5. Return tiered results (T1/T2/T3), adequacy rating, and recommended base precedent.

## 7. V6 Pipeline Workflow

Used by V6 Pipeline tab.

### 7.1 `/mua/v6/precedents/search`
Flow:
1. Resolve material identity.
2. Run enriched precedent search.
3. Split response into supporting vs conflicting precedents.

### 7.2 `/mua/v6/generate`
Flow:
1. Resolve material identity.
2. Search enriched precedents.
3. Query MAPTIS flammability data for material code.
4. Compute envelope overlap (O2/pressure/temp).
5. Evaluate decision with `MUADecisionEngine`.
6. If `mode=auto` and decision is `proceed` or `warn`:
   - run `LogicValidator` (requires `ANTHROPIC_API_KEY`),
   - generate formatted draft if validation passes.

Decision outcomes:
- `blocked`
- `review`
- `warn`
- `proceed`

Supporting endpoint:
- `/mua/v6/stats` (index size + validator availability).

## 8. V6 Corpus Draft Workflow

Used by Corpus Draft tab.

Endpoints:
- `/mua/v6/corpus/search`
- `/mua/v6/corpus/draft`
- `/mua/v6/corpus/stats`

Flow (`/corpus/draft`):
1. Build normalized environment from request.
2. Convert issue strings to enum categories.
3. Retrieve matches from parsed corpus retriever:
   - issue-driven retrieval if issues were supplied,
   - otherwise material+environment retrieval.
4. Generate draft with `mira.mua.v6.draft_generator.generate_mua_draft(...)`.
5. Return determination, confidence, citations, gaps, warnings, rationale.

## 9. Shared Dependencies

Current MUA workflows depend on:
- BOK FAISS artifacts for `/mua/bok/*`.
- v6 index artifacts for `/mua/v6/*` and `/mua/v6/corpus/*`.
- MAPTIS PostgreSQL data for v6 test-data checks.
- `ANTHROPIC_API_KEY` for v6 `auto` draft validation and some synthesis flows.

## 10. Current Implementation Notes (Important)

1. `generate-batch-excel` docstring mentions extra sheets, but implementation currently writes only `MIUL` with updated `Remarks`.
2. Batch workflow category routing is mostly heuristic and does not consume precedent engines.
3. Frontend default MUA mode is `Corpus Draft`, not `V6 Pipeline`.
4. Overlap status vocabulary differs between backend and some frontend labels (`partial` vs `partial_overlap` naming).

