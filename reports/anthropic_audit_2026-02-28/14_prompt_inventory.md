# Prompt Template Inventory

This inventory covers runtime prompt templates used with Anthropic/Claude paths.
For exhaustive per-file prompt line extraction in direct-call modules, see:
- `02_calls_prompts_parsing_raw.txt` (PROMPTS blocks)

## Core MIRA/BSMH prompts

| Prompt | File:line | Purpose | Target model(s) |
|---|---|---|---|
| `_PARSE_SYSTEM_PROMPT` | `mira/api/routers/mira_v4.py:243` | NL query -> structured intent/environment/material JSON | Sonnet direct `claude-sonnet-4-5-20250929` or Bedrock `anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `_RESPONSE_SYSTEM_PROMPT` | `mira/api/routers/mira_v4.py:360` | Answer generation from retrieved evidence/materials | Same as above |
| `_BOUNCER_SYSTEM_PROMPT` | `mira/bsmh/bouncer.py:20` | Scope/safety gate output as strict JSON | Haiku default `claude-haiku-4-5-20251001` (or env override) |
| `_FORMATTER_SYSTEM_PROMPT` | `mira/bsmh/response_formatter.py:21` | Engineer-facing compatibility narrative formatting | Haiku/Sonnet (env-routed direct or Bedrock) |
| `_FC_FORMATTER_SYSTEM_PROMPT` | `mira/bsmh/response_formatter.py:559` | Fracture-control response formatting | Sonnet direct/Bedrock via BSMH model env vars |
| `_FC_CONTEXT_PARSE_PROMPT` | `mira/bsmh/service.py:848` | Fracture query -> structured classification context JSON | Sonnet `BSMH_SONNET_MODEL` default `claude-sonnet-4-5-20250929` |

### Few-shot examples present
- `mira/bsmh/service.py:884` onward embeds explicit `Query`/`Answer` examples in `_FC_CONTEXT_PARSE_PROMPT`.

## H2 direct HTTP prompts

| Prompt | File:line | Purpose | Target model(s) |
|---|---|---|---|
| `_build_prompt(...)` template | `mira/h2/condition_resolver.py:145` | Normalize raw heat-treatment condition strings to canonical JSON | `MIRA_H2_CONDITION_RESOLVER_HAIKU_MODEL` (default `claude-haiku-4-5-20251001`) |
| Haiku rewrite prompt in `_rewrite_with_haiku` | `mira/h2/ft_temp.py:603` | Deterministic result -> concise engineer narrative with fixed template | `MIRA_H2_HAIKU_MODEL` (default `claude-haiku-4-5-20251001`) |
| `_SYSTEM_PROMPT` | `mira/h2/ft_temp.py:45` | System instruction for FT/OpenAI path in same service | non-Anthropic by default (`MIRA_H2_TEMP_MODEL`) |

## ATHENA shared prompt modules

| Prompt | File:line | Purpose | Target model(s) |
|---|---|---|---|
| `TRIAGE_SYSTEM_PROMPT` / `TRIAGE_USER_PROMPT_TEMPLATE` | `athena/prompts/triage.py:19`, `:80` | Document classification/routing + suggested schema | `model_key=triage` (Haiku class in provider map) |
| `EXTRACTION_SYSTEM_PROMPT` / `EXTRACTION_USER_PROMPT_TEMPLATE` | `athena/prompts/extract.py:19`, `:111` | Full extraction contract with bbox evidence | `model_key=extract` (Sonnet class in provider map) |
| `EXTRACTION_LIGHT_SYSTEM_PROMPT` | `athena/prompts/extract.py:118` | Light extraction for simple docs | `model_key=triage` (Haiku class) |
| `EXTRACTION_DRAWING_SYSTEM_PROMPT` | `athena/prompts/extract.py:145` | Drawing title-block metadata extraction | `model_key=triage` in pipeline |
| `BOUNDARY_CONFIRMATION_PROMPT` | `athena/prompts/boundary.py:19` | Page boundary confirmation between pages | `model_key=triage` |
| `PAGE_NUMBER_DETECTION_PROMPT` | `athena/prompts/boundary.py:49` | Footer page-number extraction JSON | `model_key=triage` |
| `LETTERHEAD_COMPARISON_PROMPT` | `athena/prompts/boundary.py:68` | Letterhead/header change comparison | triage-tier vision path |
| `DISCOVERY_SYSTEM_PROMPT` | `athena/pipeline/discovery.py:43` | Corpus discovery/taxonomy from OCR text | `complete_text` default provider extract model unless overridden |

## ATHENA extraction-specific prompt modules

| Prompt | File:line | Purpose | Target model(s) |
|---|---|---|---|
| `TABLE_EXTRACTION_PROMPT` | `athena/extraction/prompts.py:25` | Table transcription JSON | Used by transcriber/detector modules (Sonnet in those modules) |
| `TABLE_DETECTION_PROMPT` | `athena/extraction/prompts.py:46` | Detect table bboxes incl. borderless | Sonnet in `athena/extraction/detector.py` |
| `H2_TABLE_EXTRACTION_PROMPT` | `athena/extraction/prompts/h2.py:38` | Hydrogen embrittlement table -> structured test metadata/records | Domain-specific extraction paths |
| `H2_ENRICHMENT_PROMPT` | `athena/extraction/prompts/h2.py:154` | Fill missing H2 metadata from context | Domain-specific enrichment |

## SENTINEL prompt registry (versioned)

Source: `sentinel-main/gptl/prompts.py`

| Prompt ID | Layer | Purpose | Declared tier |
|---|---|---|---|
| `L0_DERIVATION_VALIDATION_V1` | L0 | Validate rule-derived evidence types | haiku |
| `L0_NOISE_DETECTION_V1` | L0 | Detect noise/non-technical content | haiku |
| `L2_INTENT_CLASSIFICATION_V1` | L2 | Query intent classification | sonnet |
| `L2_INTENT_DISAMBIGUATION_V1` | L2 | Ambiguity disambiguation | opus |
| `L3_SEMANTIC_CHECK_V1` | L3 | KEEP/ELIMINATE/DEPRIORITIZE semantic check | haiku |
| `L3_CONSTRAINT_VIOLATION_EXPLAIN_V1` | L3 | Explain constraint violations for audit | haiku (defined, not found used) |
| `L4_ANOMALY_EXPLANATION_V1` | L4 | Explain anomalies in result sets | sonnet |
| `L4_TEMPORAL_DERIVATIVE_V1` | L4 | Temporal trend/supersession analysis | sonnet |
| `L5_SYNTHESIS_V1` | L5 | Standard intelligence synthesis | sonnet |
| `L5_SYNTHESIS_CRITICAL_V1` | L5 | High-stakes/critical synthesis | opus |
| `L5_CONFIDENCE_CALIBRATION_V1` | L5 | Confidence recalibration | sonnet |

## Data-laundering domain-pack prompts

Source: `data_laundering/domain_pack.py`

- `_MIRA_LAYER_1_PROMPT`, `_MIRA_LAYER_2_PROMPT`, `_MIRA_LAYER_4_PROMPT`
- `_AEGIS_LAYER_1_PROMPT`, `_AEGIS_LAYER_2_PROMPT`, `_AEGIS_LAYER_4_PROMPT`
- `_SENTINEL_LAYER_1_PROMPT`, `_SENTINEL_LAYER_2_PROMPT`, `_SENTINEL_LAYER_4_PROMPT`

These are persona/system prompt packs used by the domain-pack abstraction; runtime model targeting depends on the configured layer clients.
