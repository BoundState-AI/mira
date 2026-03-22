# Plan: Domain-Expert Chatbots for MIRA

## Vision

MIRA's chat system isn't a helpdesk — it's a **panel of domain experts**. Each chatbot is a specialist who has spent decades in their corner of aerospace M&P engineering. When an engineer asks a question, they're not querying a database; they're consulting a colleague who happens to have perfect recall of every relevant standard, test report, and historical decision.

Today, 7 of these experts are already on the panel. This plan adds the remaining 5, each with their own deep specialization, conversational style, and domain authority.

### The Expert Panel (Current + Planned)

| Expert | Domain | Personality | Status |
|--------|--------|-------------|--------|
| **OCA Expert** | Oxygen compatibility | Cautious, methodical — walks through the kindling chain step by step | Live |
| **H2 Expert** | Hydrogen compatibility | Physics-first — always starts with embrittlement mechanisms | Live |
| **BSMH Expert** | General materials | The generalist — knows a bit of everything, refers to specialists | Live |
| **Galvanic Expert** | Dissimilar metals corrosion | Electrochemistry-focused — thinks in galvanic series | Live |
| **Fracture Expert** | Fracture mechanics | Conservative by nature — always considers worst-case flaw sizes | Live |
| **GPCM Expert** | NASA-STD-6016C compliance | The standards lawyer — knows every clause and exception | Live |
| **MAPTIS Search Expert** | Material property lookup | The librarian — finds the right data fast | Live |
| **M&P Plan Expert** | Materials & Processes Plans | The program planner — knows what makes a plan complete and auditable | **Planned** |
| **MUA Expert** | Materials Usage Agreements | The gatekeeper — knows what makes an MUA approvable | **Planned** |
| **MIUL Expert** | Materials & Inspection Usage Lists | The cataloger — knows material codes, forms, and classifications | **Planned** |
| **Precedent Expert** | Historical decisions | The historian — finds what was approved before and why | **Planned** |
| **Athena Expert** | Document extraction | The reader — extracts structured data from unstructured documents | **Planned** |

---

## Architecture (Established)

Each domain expert is composed of three pieces:

1. **Manifest** (`mira/chat/manifests/{module}.json`) — declares what this expert knows, what inputs they need, and what tasks they can perform
2. **Adapter** (`mira/chat/adapters/{module}_adapter.py`) — bridges the expert's domain engine into the unified `EngineEnvelope` response format
3. **Query Interpreter routing** (`mira/chat/query_interpreter.py`) — teaches the routing layer when to consult this expert

The **response formatter** already embodies a senior M&P engineer persona. Each new expert inherits this voice but the adapter shapes what the formatter receives — the evidence structure, authority basis, assumptions, and recommended actions are what give each expert their distinct "feel." An OCA expert talks about kindling chains and promoted combustion because that's what the OCA adapter puts into the envelope. An M&P Plan expert will talk about plan completeness and section requirements because that's what the M&P Plan adapter surfaces.

The capability registry auto-discovers manifests at startup. No manual registration needed.

---

## Expert-by-Expert Implementation

### 1. M&P Plan Expert (`mp_plan`)

**Who they are:** The program planner. Knows NASA-STD-6016C plan requirements inside and out — what sections are required, what evidence must be cited, when a plan is complete vs. incomplete. This expert doesn't just generate plans; they explain *why* each section matters and *what* makes a plan auditable.

**What engineers ask them:**
- "Generate an M&P Plan for 316L in GOX at 3000 psi"
- "What sections does an M&P Plan need?"
- "Review my M&P Plan for completeness"
- "What materials require an M&P Plan per NASA-STD-6016C?"
- "Add a new environment to my M&P Plan"

**Expert knowledge the adapter must surface:**
- Which plan sections are required vs. optional for a given material-environment combination
- Completeness gaps — what's missing and why it matters for audit
- Cross-references to applicable standards (6016C, 6001B, 6003A)
- Environment-specific requirements (oxygen service plans need different sections than general metallic plans)

**Manifest (`mp_plan.json`):**
```json
{
  "engine_id": "mp_plan",
  "display_name": "M&P Plan Generator",
  "version": "2.0.0",
  "supported_tasks": ["answer_only", "draft_artifact"],
  "supported_domains": ["mp_plan", "compliance_planning"],
  "required_inputs": ["material_designation"],
  "optional_inputs": ["gas_service", "pressure", "temperature", "mission_class", "hardware_class"],
  "adapter_module": "mira.chat.adapters.mp_plan_adapter",
  "adapter_class": "MPPlanAdapter",
  "multi_step": true,
  "case_driven": true,
  "side_effect_level": "transient_generate",
  "routing_aliases": ["mp_plan", "m&p plan", "m and p plan", "materials and processes plan"],
  "chaining_outputs": {
    "PASS": {
      "suggests": "mua",
      "auto_chain": false,
      "data_handoff": ["material", "environment", "plan_sections"]
    }
  }
}
```

**Adapter responsibilities:**
- `answer_only` — questions about M&P Plans: what they cover, when they're required, what sections are needed. The adapter should populate `authority_basis` with the specific 6016C clauses that drive plan requirements, and `evidence` with section-by-section status so the formatter can explain completeness.
- `draft_artifact` — generates an M&P Plan draft via the existing `mira.mp_plan` engine. The adapter must mark the envelope with `assumptions` (e.g., "Assuming annealed condition") and `missing_inputs` (e.g., "Operating temperature not specified — using ambient") so the formatter communicates what the engineer should verify.
- Multi-environment support (the engine already supports this in v2).
- **Safety-critical:** `__safety_critical__ = True` — this produces compliance artifacts.

**Query Interpreter changes:**
- Add coarse intent `plan_generation` for queries containing "M&P Plan", "materials and processes plan", "materials plan"
- Route `plan_generation` → `mp_plan` with 0.95 confidence
- Add `document_lookup` sub-routing when standard_ref matches 6016C plan requirements

**Module context:** Add `mp_plan` to `_MODULE_ENGINE_ALIASES` and pronoun resolution so "this plan" resolves correctly in follow-up turns.

---

### 2. MUA Expert (`mua`)

**Who they are:** The gatekeeper. Has reviewed hundreds of MUAs and knows exactly what makes one approvable vs. what gets sent back. This expert understands the full MUA lifecycle — from initial generation through review, gap analysis, and precedent matching. They know what reviewers look for and what evidence is most persuasive.

**What engineers ask them:**
- "Generate an MUA for Inconel 718 in LOX at 4500 psi"
- "What's the status of MUA-2026-0042?"
- "What test data do I need for an MUA?"
- "Compare my MUA against historical approvals"
- "What gaps exist in my MUA?"
- "Find similar MUAs that were approved"

**Expert knowledge the adapter must surface:**
- Completeness assessment — which sections are filled, which have gaps, which gaps are blocking vs. acceptable
- Precedent context — similar MUAs that were approved and what evidence they used
- Reviewer perspective — what a reviewer would flag and how to address it proactively
- Test data requirements — what mechanical, compatibility, or environmental test data is needed
- Risk rationale — when a deviation from standard practice is acceptable and how to justify it

**Manifest (`mua.json`):**
```json
{
  "engine_id": "mua",
  "display_name": "Materials Usage Agreement",
  "version": "10.0.0",
  "supported_tasks": ["answer_only", "draft_artifact", "review_existing"],
  "supported_domains": ["mua", "materials_usage_agreement"],
  "required_inputs": ["material_designation"],
  "optional_inputs": ["gas_service", "pressure", "temperature", "part_name", "mua_id", "mission_class"],
  "adapter_module": "mira.chat.adapters.mua_adapter",
  "adapter_class": "MUAAdapter",
  "multi_step": true,
  "case_driven": true,
  "side_effect_level": "persisted_draft",
  "routing_aliases": ["mua", "materials usage agreement"],
  "chaining_outputs": {}
}
```

**Adapter responsibilities:**
- `answer_only` — questions about MUA process, requirements, status. Populates `authority_basis` with applicable standards and `recommended_actions` with specific next steps.
- `draft_artifact` — generates MUA drafts using `mua_generator` + `matchmaker` + `synthesis` pipeline. Must include `assumptions`, `missing_inputs`, and a clear `evidence` list showing what data was used to populate each MUA section.
- `review_existing` — reviews an existing MUA for completeness and compliance. The adapter should structure `evidence` as a section-by-section assessment with gap severity (blocking vs. informational), so the formatter can walk the engineer through exactly what to fix.
- Historic MUA search via `historic_retrieval.py` for precedent matching — surface in `domain_payload` so the formatter can say "Three similar MUAs were approved for Inconel 718 in LOX, all with ignition testing per ASTM G72."
- **Safety-critical:** `__safety_critical__ = True` — this produces compliance artifacts.

**Query Interpreter changes:**
- Add pattern matching for "MUA", "materials usage agreement", "usage agreement"
- Route to `mua` engine with 0.95 confidence
- Handle "generate MUA" as `draft_artifact` task mode
- Handle "review MUA" / "check MUA" as `review_existing` task mode

**Chaining:** OCA `CONDITIONAL_PASS` already chains to MUA — wire this up bidirectionally so MUA can suggest OCA/H2 assessments when compatibility data is missing from the MUA evidence.

---

### 3. MIUL Expert (`miul`)

**Who they are:** The cataloger. Knows the material code taxonomy cold — every code, form, and classification. When an engineer says "I need Inconel 718 bar stock," this expert knows the exact material code, what form designation to use, and what inspection requirements apply. They make building an MIUL feel like having a knowledgeable colleague looking over your shoulder.

**What engineers ask them:**
- "Build an MIUL for project X"
- "Add 316L to the MIUL"
- "What material code should I use for Inconel 718 bar stock?"
- "Look up material code for Ti-6Al-4V forging"
- "What form should I select for this material?"
- "Export the current MIUL"

**Expert knowledge the adapter must surface:**
- Material code resolution — maps material names to correct codes with confidence
- Form inference — given material + application, recommends the right form designation
- Classification guidance — explains why a material falls under a specific category
- MIUL completeness — what entries are present, what's missing for a complete list

**Manifest (`miul.json`):**
```json
{
  "engine_id": "miul",
  "display_name": "Materials & Inspection Usage List",
  "version": "1.0.0",
  "supported_tasks": ["answer_only", "draft_artifact"],
  "supported_domains": ["miul", "material_codes", "material_forms"],
  "required_inputs": ["material_designation"],
  "optional_inputs": ["material_form", "project_name", "part_name"],
  "adapter_module": "mira.chat.adapters.miul_adapter",
  "adapter_class": "MIULAdapter",
  "multi_step": true,
  "case_driven": true,
  "side_effect_level": "transient_generate",
  "routing_aliases": ["miul", "materials inspection usage list", "material code"],
  "chaining_outputs": {
    "PASS": {
      "suggests": "mua",
      "auto_chain": false,
      "data_handoff": ["material_code", "material_form", "part_name"]
    }
  }
}
```

**Adapter responsibilities:**
- Material code lookup and selection — populate `evidence` with matching codes and their confidence so the formatter can explain why a particular code was chosen
- Material form inference — surface the reasoning in `assumptions`
- MIUL row construction — structure the row data in `domain_payload`
- Export triggers — recommend export as an action in `recommended_actions`

**Query Interpreter changes:**
- Add patterns for "MIUL", "material code", "material form", "inspection list"
- Route with 0.90 confidence when MIUL-specific terms detected

---

### 4. Precedent Expert (`precedent`)

**Who they are:** The historian. Has access to every historical M&P decision and knows how to find the ones that matter for your current situation. This expert doesn't just search — they contextualize, cluster related decisions, and explain how past approvals or rejections apply to the engineer's current case. They're the colleague who says "We did something similar on SLS Block 2 — here's what the board decided and why."

**What engineers ask them:**
- "Find precedents for 316L in GOX at 3000 psi"
- "What similar materials were approved for this application?"
- "Show me historical decisions for Inconel 718 in hydrogen"
- "Are there any precedents for this material-environment combination?"

**Expert knowledge the adapter must surface:**
- Clustered precedents — group similar decisions so the formatter can narrate trends ("All three precedents for this alloy class were approved with testing")
- Decision context — why the decision was made, what evidence was cited
- Relevance scoring — how closely each precedent matches the current query
- Applicability caveats — what's different about the current case vs. the precedent

**Manifest (`precedent.json`):**
```json
{
  "engine_id": "precedent",
  "display_name": "Precedent Search",
  "version": "1.0.0",
  "supported_tasks": ["answer_only"],
  "supported_domains": ["precedent", "historical_decisions"],
  "required_inputs": ["material_designation"],
  "optional_inputs": ["gas_service", "pressure", "temperature", "application"],
  "adapter_module": "mira.chat.adapters.precedent_adapter",
  "adapter_class": "PrecedentAdapter",
  "multi_step": false,
  "case_driven": false,
  "side_effect_level": "read_only",
  "routing_aliases": ["precedent", "historical", "past decisions", "similar approvals"],
  "chaining_outputs": {}
}
```

**Adapter responsibilities:**
- Bridge to `mira.precedent_engine` for candidate retrieval, clustering, and narrative generation
- Structure `evidence` as individual precedent cards with: program, material, environment, decision, rationale, and relevance score
- Populate `authority_basis` with the standards/specs cited in the precedent decisions
- Set `recommended_actions` to suggest using strong precedents as MUA evidence

**Query Interpreter changes:**
- Add patterns for "precedent", "historical", "past decisions", "similar approvals", "approved before"
- Add coarse intent `precedent_query` routing to `precedent` with 0.85 confidence

---

### 5. Athena Expert (`athena`) — Low Priority

**Who they are:** The reader. Specializes in extracting structured data from unstructured documents — test reports, material certifications, legacy PDFs. When an engineer uploads a document, this expert pulls out the relevant data and presents it in a format the other experts can use.

**What engineers ask them:**
- "Extract data from this test report PDF"
- "Parse this material certification"
- "What test results are in document X?"

**Manifest (`athena.json`):**
```json
{
  "engine_id": "athena",
  "display_name": "Document Extraction",
  "version": "1.0.0",
  "supported_tasks": ["answer_only"],
  "supported_domains": ["document_extraction", "ocr", "pdf_parsing"],
  "required_inputs": ["document_reference"],
  "optional_inputs": ["extraction_type", "material_designation"],
  "adapter_module": "mira.chat.adapters.athena_adapter",
  "adapter_class": "AthenaAdapter",
  "multi_step": false,
  "case_driven": false,
  "side_effect_level": "read_only",
  "routing_aliases": ["athena", "extract", "parse document", "ocr"],
  "chaining_outputs": {}
}
```

**Adapter responsibilities:**
- Bridge to `mira.athena` extraction pipeline
- Structure extracted data in `domain_payload` with field-level confidence scores
- Populate `assumptions` with extraction caveats (e.g., "OCR confidence was low for Table 3 — verify values")
- Set `recommended_actions` to suggest feeding extracted data into OCA, H2, or MUA experts

---

## Cross-Cutting Changes

### A. Query Interpreter Updates

Add new coarse intents:
- `plan_generation` — M&P Plan related queries
- `artifact_generation` — MUA/MIUL generation queries
- `precedent_query` — precedent/historical lookup
- `document_extraction` — Athena document parsing

Update `_determine_fine_routing()` to handle the new intents:
```python
if coarse_intent == "plan_generation":
    return "mp_plan", 0.95

if coarse_intent == "artifact_generation":
    if "mua" in keywords:
        return "mua", 0.95
    if "miul" in keywords:
        return "miul", 0.90
    return "mua", 0.80  # default artifact is MUA

if coarse_intent == "precedent_query":
    return "precedent", 0.85

if coarse_intent == "document_extraction":
    return "athena", 0.80
```

### B. Module Context Resolution

Add to `_MODULE_ENGINE_ALIASES`:
```python
"mp_plan": "mp_plan",
"m&p_plan": "mp_plan",
"mua": "mua",
"miul": "miul",
"precedent": "precedent",
"athena": "athena",
```

Add context pronouns:
- "this plan" → mp_plan context
- "this MUA" / "this agreement" → mua context
- "this MIUL" / "this list" → miul context

### C. Frontend ModuleChatButton Integration

Each module page that doesn't already have a `ModuleChatButton` needs one added, pre-populating `module_context` with:
- Module name
- Active case/document ID
- Material and environment from the current form state

### D. Chaining Graph (Cross-Expert Referrals)

Domain experts refer engineers to each other the way real colleagues do:

```
OCA Expert (CONDITIONAL_PASS)   → "You'll need an MUA for this — let me hand you off to the MUA expert"
H2 Expert (CONDITIONAL_PASS)    → "This needs an MUA. The MUA expert can draft one with this data"
MUA Expert (draft complete)     → "You should have an M&P Plan to go with this MUA"
M&P Plan Expert (complete)      → "Your plan references these materials — want me to build the MIUL?"
MIUL Expert (material added)    → "Want to verify compatibility? The OCA or H2 expert can check"
Precedent Expert (found)        → "These precedents would strengthen an MUA — want to use them as evidence?"
```

---

## Implementation Order

| Phase | Experts | Effort | Why This Order |
|-------|---------|--------|----------------|
| **Phase 1** | M&P Plan Expert, MUA Expert | ~3 days each | Highest user demand, core workflows, safety-critical |
| **Phase 2** | MIUL Expert | ~2 days | Complements MUA, simpler scope |
| **Phase 3** | Precedent Expert | ~2 days | Supports MUA evidence, read-only |
| **Phase 4** | Athena Expert | ~1 day | Nice-to-have, document extraction |

Each phase follows the same steps:
1. Create manifest JSON
2. Implement adapter with domain-specific evidence structuring (lazy imports, graceful degradation)
3. Add query interpreter patterns + routing
4. Add module context resolution
5. Add frontend ModuleChatButton if not present
6. Write tests (manifest validation, adapter unit tests, routing tests)
7. Wire up cross-expert referral chaining

---

## Key Design Decisions

1. **Expert personality emerges from evidence structure, not custom prompts.** The response formatter already embodies a senior M&P engineer. Each expert feels distinct because their adapter populates the envelope differently — different authority bases, different evidence formats, different assumptions. The OCA expert "sounds" cautious because it surfaces kindling chain evidence and promoted combustion risks. The M&P Plan expert will "sound" like a program planner because it surfaces plan section completeness and audit requirements. We don't need per-engine system prompts — the data shapes the voice.

2. **`draft_artifact` task mode** — M&P Plan and MUA experts can generate compliance documents, not just answer questions. This requires `side_effect_level: "transient_generate"` or `"persisted_draft"` and approval gates per the existing orchestration spec.

3. **Lazy imports everywhere** — Every adapter uses lazy imports to avoid hard failures if a module's dependencies aren't installed. This is the established pattern (see GPCM adapter).

4. **BSMH remains the generalist** — If the query interpreter can't confidently route to a specialist, it falls back to BSMH — the generalist who knows a bit of everything and can refer to the right expert.

5. **No new LLM calls in routing** — Routing stays deterministic (pattern matching + confidence scores). LLM calls happen inside the domain engines and in the response formatter. The routing layer is fast and predictable.

6. **Safety-critical marking** — M&P Plan and MUA adapters must be marked `__safety_critical__ = True` since they produce compliance artifacts that engineers will rely on for flight hardware decisions.

7. **Cross-expert referrals are suggestions, not auto-chains** — When one expert suggests another, `auto_chain: false` means the engineer decides whether to follow the referral. This respects the engineer's workflow rather than forcing a pipeline.
