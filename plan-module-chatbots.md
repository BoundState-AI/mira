# Plan: Module-Specific Chatbots for MIRA

## Current State

**7 modules already have chat integration** (manifest + adapter):
| Module | Engine ID | What it does in chat |
|--------|-----------|---------------------|
| OCA | `oca` | Oxygen compatibility assessment |
| H2 | `h2` | Hydrogen compatibility assessment |
| BSMH | `bsmh` | General material helper / fallback |
| Galvanic | `galvanic` | Dissimilar metals corrosion risk |
| Fracture | `fracture` | Fracture mechanics assessment |
| GPCM | `gpcm` | NASA-STD-6016C compliance |
| MAPTIS Search | `maptis_search` | Material property lookup |

**5 modules need chat integration** (have engines but no chatbot):
| Module | Priority | Why |
|--------|----------|-----|
| **M&P Plan** | High | Users frequently need M&P Plan generation guidance |
| **MUA** | High | MUA generation/review is a core workflow |
| **MIUL** | Medium | MIUL builder is used alongside MUA |
| **Precedent Engine** | Medium | Precedent lookup supports decision-making |
| **Athena** | Low | Document extraction is more of a backend pipeline |

---

## Architecture (Already Established)

Each module chatbot follows a 3-piece pattern:

1. **Manifest** (`mira/chat/manifests/{module}.json`) — self-declaration of capabilities, inputs, routing aliases
2. **Adapter** (`mira/chat/adapters/{module}_adapter.py`) — bridges the engine into the unified `EngineEnvelope` response format
3. **Query Interpreter routing** (`mira/chat/query_interpreter.py`) — adds intent patterns and fine-routing rules so the chatbot knows when to route to the module

The capability registry auto-discovers manifests at startup, so no manual registration is needed.

---

## Module-by-Module Implementation Plan

### 1. M&P Plan Chatbot (`mp_plan`)

**What it should help with:**
- "Generate an M&P Plan for 316L in GOX at 3000 psi"
- "What sections does an M&P Plan need?"
- "Review my M&P Plan for completeness"
- "What materials require an M&P Plan per NASA-STD-6016C?"
- "Add a new environment to my M&P Plan"

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

**Adapter:** Bridges to `mira.mp_plan` engine. Handles:
- `answer_only` — questions about M&P Plans, what they cover, when they're required
- `draft_artifact` — actually generates an M&P Plan draft using the existing `mp_plan` engine
- Multi-environment support (the engine already supports this in v2)

**Query Interpreter changes:**
- Add coarse intent `plan_generation` for queries containing "M&P Plan", "materials and processes plan", "materials plan"
- Route `plan_generation` → `mp_plan` with 0.95 confidence
- Add `document_lookup` sub-routing when standard_ref matches 6016C plan requirements

**Module context:** Add `mp_plan` to `_MODULE_ENGINE_ALIASES` and pronoun resolution so "this plan" resolves correctly

---

### 2. MUA Chatbot (`mua`)

**What it should help with:**
- "Generate an MUA for Inconel 718 in LOX at 4500 psi"
- "What's the status of MUA-2026-0042?"
- "What test data do I need for an MUA?"
- "Compare my MUA against historical approvals"
- "What gaps exist in my MUA?"
- "Find similar MUAs that were approved"

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

**Adapter:** Bridges to `mira.mua` service layer. Handles:
- `answer_only` — questions about MUA process, requirements, status
- `draft_artifact` — generates MUA drafts (using mua_generator + matchmaker + synthesis pipeline)
- `review_existing` — reviews an existing MUA for completeness, gaps, and compliance
- Historic MUA search via `historic_retrieval.py` for precedent matching

**Query Interpreter changes:**
- Add pattern matching for "MUA", "materials usage agreement", "usage agreement"
- Route to `mua` engine with high confidence
- Handle "generate MUA" as `draft_artifact` task mode
- Handle "review MUA" / "check MUA" as `review_existing` task mode

**Chaining:** OCA `CONDITIONAL_PASS` already chains to MUA — wire this up bidirectionally so MUA can suggest OCA/H2 assessments when compatibility data is missing

---

### 3. MIUL Chatbot (`miul`)

**What it should help with:**
- "Build an MIUL for project X"
- "Add 316L to the MIUL"
- "What material code should I use for Inconel 718 bar stock?"
- "Look up material code for Ti-6Al-4V forging"
- "What form should I select for this material?"
- "Export the current MIUL"

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

**Adapter:** Bridges to `mira.miul` builder + material_code_lookup + material_form_inference. Handles:
- Material code lookup and selection
- Material form inference
- MIUL row construction
- Export triggers

**Query Interpreter changes:**
- Add patterns for "MIUL", "material code", "material form", "inspection list"
- Route with 0.90 confidence when MIUL-specific terms detected

---

### 4. Precedent Engine Chatbot (`precedent`)

**What it should help with:**
- "Find precedents for 316L in GOX at 3000 psi"
- "What similar materials were approved for this application?"
- "Show me historical decisions for Inconel 718 in hydrogen"
- "Are there any precedents for this material-environment combination?"

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

**Adapter:** Bridges to `mira.precedent_engine` for candidate enrichment, clustering, and narrative generation.

**Query Interpreter changes:**
- Add patterns for "precedent", "historical", "past decisions", "similar approvals", "approved before"
- Add coarse intent `precedent_query` routing to `precedent` with 0.85 confidence

---

### 5. Athena Chatbot (`athena`) — Low Priority

**What it should help with:**
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

### D. Chaining Graph (Cross-Module Suggestions)

```
OCA (CONDITIONAL_PASS) → suggests MUA
H2 (CONDITIONAL_PASS)  → suggests MUA
MUA (draft complete)    → suggests M&P Plan
M&P Plan (complete)     → suggests MIUL
MIUL (material added)   → suggests OCA/H2 (verify compatibility)
Precedent (found)       → suggests MUA (use as evidence)
```

---

## Implementation Order

| Phase | Modules | Effort | Why This Order |
|-------|---------|--------|----------------|
| **Phase 1** | M&P Plan, MUA | ~3 days each | Highest user demand, core workflows |
| **Phase 2** | MIUL | ~2 days | Complements MUA, simpler scope |
| **Phase 3** | Precedent Engine | ~2 days | Supports MUA evidence, read-only |
| **Phase 4** | Athena | ~1 day | Nice-to-have, document extraction |

Each phase follows the same steps:
1. Create manifest JSON
2. Implement adapter (with lazy imports, graceful degradation)
3. Add query interpreter patterns + routing
4. Add module context resolution
5. Add frontend ModuleChatButton if not present
6. Write tests (manifest validation, adapter unit tests, routing tests)
7. Update chaining graph

---

## Key Design Decisions

1. **`draft_artifact` task mode** — M&P Plan and MUA chatbots can actually generate documents, not just answer questions. This requires `side_effect_level: "transient_generate"` or `"persisted_draft"` and approval gates per the existing orchestration spec.

2. **Lazy imports everywhere** — Every adapter uses lazy imports to avoid hard failures if a module's dependencies aren't installed. This is the established pattern (see GPCM adapter).

3. **BSMH remains the fallback** — If the query interpreter can't confidently route to a specific module, it falls back to BSMH (the general material helper). This doesn't change.

4. **No new LLM calls in routing** — Routing stays deterministic (pattern matching + confidence scores). LLM calls happen inside the module engines themselves, not in the chat routing layer.

5. **Safety-critical marking** — M&P Plan and MUA adapters should be marked `__safety_critical__ = True` since they produce compliance artifacts.
