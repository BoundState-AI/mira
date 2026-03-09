# CODEX TASK: MUA Runtime System — Full Pipeline Build

## Document ID: BS-TASK-MUA-RUNTIME-001
## Author: Beth (Claude) — Architecture & Specification
## Reviewed By: Dr. Joseph Wilde — Domain Authority
## Builder: Atlas (Codex) — Implementation
## Date: 2026-03-01

---

## 1. THE MISSION

Build the MUA system that makes a NASA materials engineer enter their
material, environment, and MAPTIS flags — then lean back, adjust their
glasses, and say "fuck me." The rationale reads like a 30-year M&P veteran
wrote it, because the language literally came from 30 years of M&P veterans.
Every sentence traces to a source document. The classifier is deterministic.
The frontier model only drafts language from real evidence. The engineer
approves or edits. Out comes a Form 551 DOCX.

Single-material flow first. MIUL batch is the same pipeline called N times.

---

## 2. WHAT EXISTS AND WORKS (DO NOT REWRITE)

These modules are FROZEN. Use them. Import them. Do not rewrite them.

### Decision Engine (deterministic, zero AI)
| File | Purpose | Status |
|------|---------|--------|
| `classifier/classifier.py` | Steps 1-6 flag classification | FROZEN |
| `classifier/screening.py` | Material-class applicability gate | FROZEN |
| `classifier/models.py` | All data models (FlagType, MUAType, ClassifierResult, Form551Fields, PipelineResult) | FROZEN (extend only) |
| `classifier/domain_facts.py` | Curated standards facts | FROZEN |
| `classifier/grouping.py` | Group by MAPTIS+issue | FROZEN |

### Rationale & Rendering
| File | Purpose | Status |
|------|---------|--------|
| `classifier/rationale.py` | Template engine + precedent_suffix() | EXTEND (add synthesis integration) |
| `classifier/docx_renderer.py` | Form 551 DOCX output | FROZEN |
| `classifier/pipeline.py` | Orchestrator (Steps 1-8) | EXTEND (add evidence + synthesis stages) |

### Precedent Database (9,939 deduplicated historic MUAs)
| File | Purpose | Status |
|------|---------|--------|
| `precedent/lookup.py` | 3-ring count lookup (exact/family/broad) | EXTEND (add exemplar retrieval) |
| `precedent/models.py` | PrecedentSummary model | EXTEND (add PrecedentExemplar) |

### Material Resolution
| File | Purpose | Status |
|------|---------|--------|
| `v7/material_resolver.py` | Free text → MAPTIS code resolution | USE via adapter |
| `matchmaker/adapters.py` | Anti-corruption bridge to v7 | USE |

### Phrase Extraction
| File | Purpose | Status |
|------|---------|--------|
| `matchmaker/rationale_extractor.py` | Extract ranked engineering phrases from rationale text | USE (import into new pipeline) |
| `matchmaker/models.py` | IssueCode, PrecedentMatch, RationalePhrase | USE |

### API & Frontend
| File | Purpose | Status |
|------|---------|--------|
| `api/routers/mua_v10.py` | Current V10 endpoints | EXTEND |
| `frontend/src/pages/MUAV10.tsx` | Current V10 UI | EXTEND |

---

## 3. WHAT TO BUILD

### 3A. New Module: `mira/mua/evidence/` (3 files)

This module retrieves and packages all evidence for the synthesis stage.

**`mira/mua/evidence/__init__.py`**
```python
from .retriever import retrieve_evidence_bundle
from .models import EvidenceBundle, PrecedentExemplar
```

**`mira/mua/evidence/models.py`**
```python
@dataclass(frozen=True)
class PrecedentExemplar:
    """A single historic MUA with full rationale text."""
    mua_number: str
    material_name: str
    alloy_family: str
    media_category: str
    determination: str  # APPROVED, CONDITIONAL, REJECTED
    category: str       # I, II, III
    rationale_text: str
    confidence: float
    match_ring: str     # "exact", "family", "broad"
    match_score: float  # composite ranking score

@dataclass(frozen=True)
class EvidenceBundle:
    """Complete evidence package for one classified flag."""
    # From classifier
    issue: str
    rating: str
    mua_type: str  # MUAType.value
    material_class: str
    media: str
    
    # From precedent counts (existing)
    precedent_summary: Optional[PrecedentSummary]
    precedent_ring: Optional[str]
    
    # NEW: Full exemplar MUAs with rationale text
    exemplars: list[PrecedentExemplar]  # Top 5, ranked
    
    # NEW: Extracted engineering phrases from exemplars
    phrases: list[RationalePhrase]  # Top 8, scored
    
    # Metadata
    evidence_hash: str  # SHA-256 of all inputs for audit
```

**`mira/mua/evidence/retriever.py`**

Core function: `retrieve_evidence_bundle(result: ClassifierResult) -> EvidenceBundle`

1. Call existing `lookup_precedent_with_ring()` for counts (already works).
2. NEW: Query `mua_precedent.mua_records` for top 5 exemplars matching the
   same ring logic:
   - Ring 1: issue + media_category + material_class + alloy_family
   - Ring 2: issue + material_class + alloy_family (any media)
   - Ring 3: issue + material_class (any media, any family)
   - Ranking within ring: same_alloy_family_bonus(+0.3) + confidence + 
     LENGTH(rationale_text) > 100 filter + approved first
3. Call existing `rationale_extractor.extract_rationale_phrases()` on the
   exemplar rationale texts.
4. Compute evidence_hash (SHA-256 of issue+rating+media+material_class+exemplar_ids).
5. Return EvidenceBundle.

SQL for exemplar query (Ring 1 example):
```sql
SELECT mua_number, material_name, alloy_family, media_category,
       disposition, category, rationale_text, confidence
FROM mua_precedent.mua_records
WHERE issue = %s
  AND media_category = %s
  AND material_class = %s
  AND COALESCE(alloy_family, '') = %s
  AND rationale_text != ''
  AND LENGTH(rationale_text) > 100
  AND confidence >= 0.5
ORDER BY 
  CASE WHEN approved = TRUE THEN 0 ELSE 1 END,
  confidence DESC,
  LENGTH(rationale_text) DESC
LIMIT 5
```

**CRITICAL: Graceful degradation.** If DB is unreachable, return EvidenceBundle
with empty exemplars and empty phrases. The pipeline continues with template-only
rationale. Never crash.

---

### 3B. New Module: `mira/mua/synthesis/` (3 files)

This module uses a frontier model to draft rationale from evidence.

**`mira/mua/synthesis/__init__.py`**
```python
from .synthesizer import synthesize_rationale
from .models import SynthesisResult, Claim
```

**`mira/mua/synthesis/models.py`**
```python
@dataclass(frozen=True)
class Claim:
    """A single factual claim in the rationale with evidence link."""
    text: str               # The claim sentence
    source_mua: str         # MUA number it came from (or "TEMPLATE" or "STANDARD")
    source_type: str        # "precedent", "template", "standard", "domain_fact"
    confidence: float       # 0.0-1.0

@dataclass(frozen=True)
class SynthesisResult:
    """Output of frontier model synthesis."""
    rationale: str              # Full rationale paragraph
    disposition: str            # Disposition sentence
    claims: list[Claim]         # Every factual claim with evidence link
    model_id: str               # e.g. "claude-sonnet-4-5-20250929"
    prompt_version: str         # e.g. "v1.0.0"
    tokens_used: int
    latency_ms: int
    template_fallback: bool     # True if model was unavailable
```

**`mira/mua/synthesis/synthesizer.py`**

Core function: `synthesize_rationale(result: ClassifierResult, evidence: EvidenceBundle, material_name: str) -> SynthesisResult`

**Strategy by MUA type:**

For THIN_SCREENING and ANTI_RULE (automatable):
- Template rationale provides the structural skeleton
- Extracted phrases provide real engineer language
- Frontier model weaves them into a single coherent paragraph
- Precedent suffix appended at end (count sentence)

For INCOMPLETE_PASS (automatable):
- Template rationale is usually sufficient
- Extracted phrases strengthen the "all tested specimens passed" argument
- Lighter model touch — may just insert 1 phrase

For REAL_PROBLEM and REAL_GAP (human-required):
- Model presents top 5 extracted phrases as "suggested rationale elements"
- Does NOT draft a full rationale (that's the engineer's job)
- Provides structured evidence summary for engineer to work from

For STANDARD (no MUA needed):
- Template only. No model call. No evidence retrieval.

**Prompt structure:**
```
SYSTEM: You are drafting an MUA rationale for NASA Form 551. You write
like a 30-year materials and processes engineer — precise, terse, 
citation-heavy. Every claim must trace to either a test standard, a 
MAPTIS rating definition, or a specific prior approved MUA number.

Never speculate. Never use phrases like "it is believed" or "it is 
expected." State facts. Cite sources. Close the gap.

CONTEXT:
Material: {material_name} (MAPTIS {maptis_code})
Issue: {column}={rating} — {decoded_meaning}
Classification: {mua_type}
Service Environment: {media}
Material Class: {material_class}

TEMPLATE SKELETON (structural basis — preserve core logic):
{template_rationale}

PRECEDENT EVIDENCE (real language from prior approved MUAs):
{formatted_phrases_with_mua_numbers}

PRECEDENT SUMMARY:
{total_count} prior MUAs for this scenario, {approved_count} approved,
most common category: {most_common_category}

TASK: Write a single rationale paragraph that:
1. Starts with the material identification and rating (from template)
2. States why the flag does not apply to this environment (from template)  
3. Incorporates 1-2 supporting precedent phrases naturally (from evidence)
4. Cites specific MUA numbers parenthetically
5. Ends with the precedent count sentence
6. Total length: 4-7 sentences. Terse. Respect the reviewer's time.

Return JSON:
{
  "rationale": "...",
  "disposition": "...",
  "claims": [
    {"text": "...", "source_mua": "MUA-XXXX", "source_type": "precedent"},
    {"text": "...", "source_mua": "TEMPLATE", "source_type": "template"},
    ...
  ]
}
```

**Model call:**
- Provider: AWS Bedrock (GovCloud) or direct Anthropic API
- Model: claude-sonnet-4-5-20250929
- Max tokens: 1000
- Temperature: 0.2 (low creativity, high fidelity)
- Response format: JSON

**CRITICAL: Template fallback.** If the model call fails for ANY reason
(timeout, rate limit, credentials, network), fall back to the existing
template rationale from `classifier/rationale.py`. Set `template_fallback=True`.
The system ALWAYS returns a rationale. The model makes it better, not possible.

---

### 3C. New Function in `classifier/rationale.py`: `verify_claims()`

NOT a new module. A function added to the existing rationale.py.

```python
def verify_claims(
    synthesis: SynthesisResult,
    evidence: EvidenceBundle,
) -> tuple[list[Claim], list[Claim]]:
    """Verify each claim in the synthesis traces to evidence.
    
    Returns (verified_claims, blocked_claims).
    A blocked claim has source_mua that doesn't appear in the evidence bundle.
    """
```

Logic:
- For each claim where source_type == "precedent":
  - Confirm source_mua appears in evidence.exemplars[].mua_number
  - If not found → blocked
- For each claim where source_type == "template":
  - Always verified (template is deterministic)
- For each claim where source_type == "standard":
  - Confirm referenced standard exists in domain_facts.py
  - If not found → blocked
- For each claim where source_type == "domain_fact":
  - Confirm fact exists in domain_facts.py
  - If not found → blocked

If ANY claim is blocked:
- Log warning with details
- Fall back to template-only rationale
- Do NOT serve unverified claims to the engineer

---

### 3D. Extend `classifier/pipeline.py`

Modify `process_miul_row()` to add evidence retrieval and synthesis
stages between classification and form filling.

Current flow:
```
classify → precedent_counts → fill_form → return
```

New flow:
```
classify → evidence_bundle → synthesize → verify → fill_form → return
```

Changes to `process_miul_row()`:

After the existing precedent lookup block (lines ~170-180), add:

```python
# --- Evidence retrieval ---
try:
    evidence = retrieve_evidence_bundle(result)
except Exception as exc:
    logger.warning("Evidence retrieval failed: %s", exc)
    evidence = None

# --- Frontier synthesis ---
synthesis = None
if evidence and result.automatable:
    try:
        synthesis = synthesize_rationale(
            result=result,
            evidence=evidence,
            material_name=material_designation or maptis_code,
        )
    except Exception as exc:
        logger.warning("Synthesis failed, using template: %s", exc)
        synthesis = None

# --- Claim verification ---
if synthesis and not synthesis.template_fallback:
    verified, blocked = verify_claims(synthesis, evidence)
    if blocked:
        logger.warning("Blocked %d ungrounded claims, falling back to template", len(blocked))
        synthesis = None  # fall back to template

# --- Apply synthesis or template ---
if synthesis and not synthesis.template_fallback:
    form.rationale = synthesis.rationale
    form.disposition = synthesis.disposition
    result.synthesis = synthesis
    result.evidence_bundle = evidence
else:
    # Existing template path (already works)
    form.rationale = render_rationale(result, material_name=...)
```

**Add to ClassifierResult model:**
```python
# In classifier/models.py, add optional fields:
synthesis: Optional[Any] = None       # SynthesisResult when available
evidence_bundle: Optional[Any] = None # EvidenceBundle when available
```

---

### 3E. New Endpoint: `POST /api/mua/v10/process-single`

Add to `mira/api/routers/mua_v10.py`.

**Purpose:** Single-material intake. Engineer enters material name (free text),
environment, and MAPTIS ratings. System resolves material, classifies, retrieves
evidence, synthesizes, verifies, returns draft for review.

**Request:**
```json
{
  "material_text": "Inconel 718",
  "media": "GH2",
  "environment": "non-habitable",
  "ratings": {
    "FLAM": "C",
    "FS": "U",
    "SCC": "A",
    "TOX": null,
    "TVS": null,
    "CORR": null
  },
  "project": "SLS",
  "system": "RS-25 Engine",
  "pressure": "6000 psia",
  "temperature": "-423°F to 1200°F"
}
```

**Response:**
```json
{
  "material_resolution": {
    "input_text": "Inconel 718",
    "status": "resolved",
    "maptis_code": "MAT-A00718",
    "resolved_name": "INCONEL 718 (UNS N07718)",
    "family": "ni_superalloy",
    "material_class": "metal"
  },
  "pipeline_result": {
    "maptis_code": "MAT-A00718",
    "total_flags": 2,
    "automatable_count": 2,
    "human_required_count": 0,
    "classifications": [
      {
        "issue_key": "FLAM",
        "rating": "C",
        "mua_type": "ANTI_RULE",
        "category": "II",
        "confidence": 0.94,
        "precedent": {
          "total_count": 177,
          "approved_count": 177,
          "most_common_category": "II"
        },
        "synthesis": {
          "rationale": "Inconel 718 (MAPTIS MAT-A00718) carries a promoted ignition rating of C, indicating burn length greater than 6.0 inches under standard promoted combustion conditions per NHB 8060.1C. This rating is not applicable to the actual service environment. The material operates exclusively in GH2 media with no oxygen-enriched atmosphere. The failure mode underlying the C rating — promoted ignition and sustained combustion in enriched oxygen — is not credible in a hydrogen fluid system. Prior approved MUAs for Inconel 718 and comparable nickel superalloys in hydrogen service confirm this disposition (MUA-2019-0847, MUA-2022-0156). The flammability screening requirement per NASA-STD-6016C §4.2.1.1 [MPR 44] is satisfied because the hazard condition does not exist at the point of use. This disposition is consistent with 177 prior approved Category II MUAs for promoted ignition screening of metals in oxygen service.",
          "disposition": "Accepted. The screening failure does not constitute a hazard in this application. Material operates in GH2 with no conditions that would activate the failure mode. No additional testing or controls required for this screening deficiency.",
          "claims": [
            {"text": "burn length greater than 6.0 inches under standard promoted combustion conditions", "source_mua": "TEMPLATE", "source_type": "template"},
            {"text": "not applicable to the actual service environment", "source_mua": "TEMPLATE", "source_type": "template"},
            {"text": "Prior approved MUAs for Inconel 718 and comparable nickel superalloys in hydrogen service confirm this disposition", "source_mua": "MUA-2019-0847", "source_type": "precedent"}
          ],
          "template_fallback": false,
          "model_id": "claude-sonnet-4-5-20250929"
        }
      },
      ...
    ],
    "forms": [...]
  }
}
```

**Implementation:**
```python
@router.post("/process-single")
async def process_single_material(request: SingleMaterialRequest):
    # 1. Resolve material
    resolution = resolve_material(request.material_text)
    
    # 2. If fuzzy/unresolved, return candidates for engineer to pick
    if resolution.status != "resolved":
        return {"status": "needs_resolution", "candidates": resolution.candidates}
    
    # 3. Run full pipeline (classify + evidence + synthesize + verify)
    result = process_miul_row(
        ratings=request.ratings,
        maptis_code=resolution.material_code,
        material_designation=resolution.resolved_name,
        material_class=resolution.material_class,
        media=request.media,
        environment=request.environment,
        alloy_family=resolution.family,
        project=request.project,
        system=request.system,
        pressure=request.pressure,
        temperature=request.temperature,
    )
    
    # 4. Create session record
    session = create_mua_session(request, resolution, result)
    
    # 5. Return for engineer review
    return {"session_id": session.id, "material_resolution": resolution, "pipeline_result": result}
```

---

### 3F. Database: `mua_runtime` Schema (6 tables)

Create in `mira` database on port 55433. Schema: `mua_runtime`.

**Table 1: `sessions`**
```sql
CREATE TABLE mua_runtime.sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_text   TEXT NOT NULL,
    maptis_code     TEXT,
    material_name   TEXT,
    material_class  TEXT,
    alloy_family    TEXT,
    media           TEXT NOT NULL,
    environment     TEXT DEFAULT 'non-habitable',
    project         TEXT DEFAULT '',
    system          TEXT DEFAULT '',
    ratings_input   JSONB NOT NULL,       -- raw input ratings
    decisions       JSONB,                -- classifier output snapshot
    status          TEXT DEFAULT 'draft', -- draft, reviewed, approved, generated
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

**Table 2: `evidence_bundles`**
```sql
CREATE TABLE mua_runtime.evidence_bundles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES mua_runtime.sessions(id),
    issue           TEXT NOT NULL,
    rating          TEXT NOT NULL,
    evidence_hash   TEXT NOT NULL,         -- SHA-256 dedup/audit key
    precedent_count JSONB,                 -- PrecedentSummary as JSON
    precedent_ring  TEXT,
    exemplar_muas   JSONB,                 -- array of exemplar records
    extracted_phrases JSONB,               -- array of scored phrases
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

**Table 3: `synthesis_drafts`**
```sql
CREATE TABLE mua_runtime.synthesis_drafts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES mua_runtime.sessions(id),
    evidence_id     UUID REFERENCES mua_runtime.evidence_bundles(id),
    issue           TEXT NOT NULL,
    rationale_draft TEXT NOT NULL,
    disposition_draft TEXT NOT NULL,
    claims          JSONB NOT NULL,        -- array of Claim objects
    model_id        TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    tokens_used     INT,
    latency_ms      INT,
    template_fallback BOOLEAN DEFAULT FALSE,
    verified        BOOLEAN DEFAULT FALSE,
    blocked_claims  JSONB,                 -- any claims that failed verification
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

**Table 4: `engineer_actions`**
```sql
CREATE TABLE mua_runtime.engineer_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES mua_runtime.sessions(id),
    issue           TEXT NOT NULL,
    action          TEXT NOT NULL,         -- 'approve', 'edit', 'reject'
    original_rationale TEXT,
    edited_rationale   TEXT,               -- NULL if approved without edit
    original_disposition TEXT,
    edited_disposition   TEXT,
    comment         TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

**Table 5: `final_documents`**
```sql
CREATE TABLE mua_runtime.final_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES mua_runtime.sessions(id),
    mua_number      TEXT,
    final_rationale TEXT NOT NULL,
    final_disposition TEXT NOT NULL,
    final_form_fields JSONB NOT NULL,     -- complete Form551Fields
    docx_hash       TEXT,                  -- SHA-256 of generated file
    docx_path       TEXT,                  -- storage path
    generated_at    TIMESTAMPTZ DEFAULT now()
);
```

**Table 6: `learning_events`**
```sql
CREATE TABLE mua_runtime.learning_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES mua_runtime.sessions(id),
    event_type      TEXT NOT NULL,         -- 'draft_vs_final', 'approval', 'rejection', 'edit_diff'
    payload         JSONB NOT NULL,        -- event-specific structured data
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_learning_type ON mua_runtime.learning_events(event_type);
CREATE INDEX idx_learning_session ON mua_runtime.learning_events(session_id);
```

**DDL file:** `mira/mua/runtime_schema.sql` — idempotent, safe to re-run.

---

### 3G. Frontend: Updated `MUAV10.tsx`

The "fuck me" UI. Two states:

**State 1: Input**
- Material name (free text with typeahead from MAPTIS)
- OR MAPTIS code (direct entry)
- Environment / Media dropdown + free text
- MAPTIS ratings: 6 dropdowns (FLAM, FS, TOX, TVS, SCC, CORR)
  with options per column (A, B, C, I, S, U, N, blank)
- Project / System / Pressure / Temperature (optional context)
- "Classify" button

**State 2: Review**
Per flag, a card showing:
- **Classification badge:** THIN_SCREENING / ANTI_RULE / etc. with color
- **Category badge:** I (amber) or II (green) or STANDARD (gray)
- **Confidence meter:** with precedent ring indicator
- **Precedent badge:** "177 prior MUAs, 100% approved" with expand for top 3 exemplar citations
- **Rationale:** editable textarea, pre-filled with synthesized text
  - Source highlighting: template text (gray), precedent phrases (blue), 
    MUA citations (linked)
- **Disposition:** editable textarea, pre-filled
- **Approve / Edit / Reject** buttons per flag

Bottom bar:
- "Generate DOCX" (enabled when all flags approved/edited)
- "Save Draft" (persist session)
- Session timestamp and evidence hash for audit

---

### 3H. Finalize & DOCX Endpoints

**`POST /api/mua/v10/finalize`**

Accepts engineer's approved/edited rationale for all flags in a session.
Stores engineer_actions and final_documents. Logs learning_events
(draft_vs_final diff for every edit).

**`POST /api/mua/v10/generate-docx`** (already exists — extend)

Reads from final_documents table. Generates DOCX with approved text.
Returns file stream. Stores docx_hash for audit.

---

## 4. GOLDEN TEST SET

Before writing any new code, create 20 test cases from the precedent DB.

```sql
-- Pull 20 diverse cases covering all MUA types and environments
SELECT mua_number, material_name, alloy_family, issue, rating,
       media_category, material_class, disposition, category,
       LEFT(rationale_text, 500)
FROM mua_precedent.mua_records
WHERE rationale_text != '' AND issue != '' AND confidence >= 0.8
ORDER BY random()
LIMIT 20;
```

For each, manually define:
- Expected MUA type (THIN_SCREENING, ANTI_RULE, etc.)
- Expected category (I or II)
- Key phrases that SHOULD appear in synthesized rationale
- Key phrases that should NOT appear

Store as `tests/golden_mua_cases.json`. Run after every pipeline change.
All 20 must pass before any PR merges.

---

## 5. CONSTRAINTS

1. **Classifier logic is FROZEN.** classifier.py and screening.py do not change.
   Classification is deterministic. Synthesis is additive.

2. **Template fallback ALWAYS.** If model/DB/evidence fails at any point,
   the system returns template-only rationale. Never return nothing.

3. **Fail-closed verification.** If ANY claim can't be traced to evidence,
   fall back to template. Don't serve ungrounded text.

4. **No MAPTIS leakage.** Raw MAPTIS data stays inside the GovCloud boundary.
   The frontier model sees: material name, rating letter, decoded meaning,
   media, and extracted phrases from precedent text. It does NOT see raw
   test data, raw MAPTIS records, or engineer PII.

5. **Connection config via `mira.core.db_config`.** Database `mira`, schema
   `mua_precedent` for precedent data, schema `mua_runtime` for session/audit
   data. Port from env `POSTGRES_PORT` (default 5432, Raider is 55433).

6. **Log everything.** `logging.getLogger(__name__)` for all modules.
   Every synthesis call, every verification result, every fallback.

7. **No new dependencies** beyond what's in requirements.txt.
   psycopg2, anthropic (or boto3 for Bedrock), python-docx already present.

---

## 6. FILE MAP

### New files to create:
```
mira/mua/evidence/__init__.py
mira/mua/evidence/models.py
mira/mua/evidence/retriever.py
mira/mua/synthesis/__init__.py
mira/mua/synthesis/models.py
mira/mua/synthesis/synthesizer.py
mira/mua/runtime_schema.sql
tests/golden_mua_cases.json
tests/test_mua_pipeline_golden.py
```

### Existing files to modify:
```
mira/mua/classifier/models.py     — add synthesis + evidence_bundle optional fields
mira/mua/classifier/pipeline.py   — add evidence + synthesis + verify stages
mira/mua/classifier/rationale.py  — add verify_claims() function
mira/mua/precedent/models.py      — add PrecedentExemplar (or import from evidence)
mira/api/routers/mua_v10.py       — add /process-single + /finalize endpoints
frontend/src/pages/MUAV10.tsx      — full review UI
frontend/src/lib/mua-v10-api.ts   — add process-single + finalize API calls
```

### Files to NOT touch:
```
mira/mua/classifier/classifier.py   — FROZEN
mira/mua/classifier/screening.py    — FROZEN
mira/mua/classifier/domain_facts.py — FROZEN
mira/mua/classifier/grouping.py     — FROZEN
mira/mua/classifier/docx_renderer.py — FROZEN
```

---

## 7. IMPLEMENTATION ORDER

1. **Golden test set** — 20 cases from precedent DB with expected outcomes
2. **runtime_schema.sql** — 6 tables, run on Raider PG
3. **evidence/models.py** — PrecedentExemplar, EvidenceBundle
4. **evidence/retriever.py** — exemplar SQL + phrase extraction integration
5. **synthesis/models.py** — SynthesisResult, Claim
6. **synthesis/synthesizer.py** — prompt + model call + JSON parse + fallback
7. **rationale.py** — add verify_claims()
8. **pipeline.py** — wire evidence → synthesis → verify into existing flow
9. **models.py** — extend ClassifierResult with optional synthesis/evidence fields
10. **mua_v10.py** — /process-single and /finalize endpoints
11. **Run golden tests** — all 20 must pass
12. **MUAV10.tsx** — review UI with editable rationale
13. **mua-v10-api.ts** — frontend API layer
14. **End-to-end test** — single material through UI to DOCX

---

## 8. WHAT SUCCESS LOOKS LIKE

Engineer enters: "Inconel 718, GH2, FLAM=C, FS=U"

System returns in < 5 seconds:

**Flag 1: FLAM=C → ANTI_RULE, Category II, Confidence 0.94**
> Inconel 718 (MAPTIS MAT-A00718) carries a promoted ignition rating of C,
> indicating burn length greater than 6.0 inches under standard promoted
> combustion conditions per NHB 8060.1C. This rating is not applicable to
> the actual service environment. The material operates exclusively in GH2
> media with no oxygen-enriched atmosphere. The failure mode underlying
> the C rating — promoted ignition and sustained combustion propagation in
> enriched oxygen — is not credible in a hydrogen fluid system. Prior
> approved MUAs for Inconel 718 and comparable nickel superalloys in
> hydrogen service confirm this disposition (MUA-2019-0847, MUA-2022-0156).
> The flammability screening requirement per NASA-STD-6016C §4.2.1.1
> [MPR 44] is satisfied because the hazard condition does not exist at
> the point of use. This disposition is consistent with 177 prior approved
> Category II MUAs for promoted ignition screening of metals in hydrogen
> service.

**Flag 2: FS=U → THIN_SCREENING, Category II, Confidence 0.92**
> Inconel 718 (MAPTIS MAT-A00718) has a fluid system compatibility rating
> of U, indicating no test data exists in MAPTIS for the NASA-STD-6001B
> Test 15 screening. Test 15 is a 48-hour screening test designed to
> evaluate material compatibility with hydrazine (N2H4), monomethylhydrazine
> (MMH), and nitrogen tetroxide (N2O4) class propellants. This material is
> not in service with those fluids; the operating medium is GH2. Inconel 718
> has extensive hydrogen service heritage in RS-25 engine components with no
> fluid compatibility concerns (MUA-2021-1203). The FS=U rating does not
> represent a deficiency for GH2 service. This disposition is consistent
> with 24 prior approved Category II MUAs for fluid system compatibility
> screening of metals in hydrogen service.

Engineer reads it. Adjusts glasses. Hits approve. Downloads DOCX.

That's the system.

---

## 9. ANSWERS TO ATLAS'S PREREQUISITE QUESTIONS

**Approved providers and boundary policy:**
- Frontier model: Claude Sonnet (claude-sonnet-4-5-20250929) via AWS Bedrock on GovCloud.
  Fallback: direct Anthropic API if Bedrock unavailable. Template-only if both fail.
- Model sees: material name, rating letter, decoded meaning, media, extracted
  phrases from precedent text, standard references from domain_facts.py.
- Model does NOT see: raw MAPTIS test data, MAPTIS database records, engineer PII,
  export-controlled specifications.

**Data classification policy:**
- CUI: MAPTIS codes, raw test data, ITAR specifications
- Not CUI: Rating letters (A/B/C/I/S/U/N), decoded meanings (published in 
  NHB 8060.1C), standard section references, precedent MUA numbers
- The prompt contains only non-CUI data. Precedent rationale text is derived
  from signed MUAs which are program records, not CUI per se, but treat as
  CUI-adjacent — route through GovCloud Bedrock.

**Acceptance thresholds (initial, will refine with data):**
- Grounding: 100% of claims must trace to evidence. No exceptions.
- Edit rate: Track but don't gate. Goal: < 30% of rationales edited.
- Latency: < 5 seconds end-to-end for single material.
- Failure rate: Template fallback < 5% of requests.

**Golden test set:** 20 cases from precedent DB. Defined in implementation step 1.

**Deployment target:** Local Raider (development) + GovCloud (production). Dual.
