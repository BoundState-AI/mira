# Tier-One Compliance Audit — `mira`

**Date:** 2026-04-11
**Branch:** `claude/audit-tier-one-compliance-QnyWn`
**Scope:** 1,083 Python files · ~212k LOC in `mira/` (357k repo-wide)
**Method:** Subsystem sampling across the largest and most critical files in
`mira/api`, `mira/mua`, `mira/bsmh`, `mira/compliance`, `mira/miul`,
`mira/forge`, `mira/forge_claude`, `mira/knowledge_twins`, `mira/core`,
`mira/utils`, and top-level `core/` + `common/`.

---

## 1. Executive Verdict

The codebase is **production-capable with a strong safety-critical backbone,
but documentation-poor and structurally uneven.** It is closest to Tier-One in
the compliance, MUA v7, and fracture-engine modules (exemplary headers, named
exceptions, explicit authority packs). It is furthest from Tier-One in BSMH
service orchestration, API-router implementation, and legacy-archive
entanglement, where function sizes balloon past 150 lines, exceptions are
silently swallowed, and parallel versions coexist with no deprecation signals.

### Tier-One grade by principle (0 – 5)

| Principle          | Score | Summary                                                                                                       |
| ------------------ | :---: | ------------------------------------------------------------------------------------------------------------- |
| Intent & Reasoning |  2.5  | Module headers are strong; in-function "why" comments are missing in 60–80 % of large methods.                |
| Auditability       |  3.0  | 262+ NASA-STD / FAR citations exist, but BSMH and `core/search_engine.py` silently swallow exceptions.        |
| Composability      |  2.0  | Systemic >50-line violations across API routers, `v3/builder`, `forge/compiler`, `draft_renderer`, `service`. |
| Defensive Design   |  2.5  | Good: Pydantic boundary validators, named exceptions in MUA/compliance. Bad: multiple `except: pass` sites.   |
| Consistency        |  3.0  | snake_case is uniform; logger naming drifts (`logger` vs `LOGGER` vs none); return shapes drift across API.   |
| Boring Execution   |  3.5  | Few clever tricks. Main infractions are cascading optional imports and hand-rolled sort chains.               |

**Overall: ≈ 2.8 / 5. Production-ready, not Tier-One-ready.**

---

## 2. Critical Findings

### C1 — Silent exception swallowing in safety-critical paths

These violate **Auditability** directly: a compliance determination can fail
and leave zero trace.

Verified sites (all `except Exception: pass` with no logger and no fallback
signal):

- `mira/bsmh/service.py:591, 643, 657, 673` — silent pass inside
  material-resolution DB searches that feed compliance decisions.
- `mira/bsmh/bok_adapter.py:80` — engine errors return empty rows silently.
- `mira/bsmh/bouncer.py:540-543` — `BSMHStructuredQuery.model_validate` wrapped
  in bare except returning `None`; parser failures become silent false
  negatives at the domain-gate boundary.
- `mira/core/search_engine.py:1210, 1245, 1257, 1263` — bare pass inside
  FAISS-result scoring; scoring failures silently return lower scores.
- `mira/api/routers/mua_v7.py:382-387` — "table is optional" swallow with no
  fallback policy documented.
- `mira/mua/v7/material_resolver.py:~1311` and
  `mira/mua/v7/investigator.py:~285` — "partial data, continue" pattern without
  a structured degradation signal.

**Fix pattern:** every `except` in a safety-critical path must
(a) name the exception class,
(b) log with context (`LOGGER.exception(...)`),
(c) either propagate or attach a structured degradation marker to the response
envelope.

### C2 — Oversized functions in decision endpoints

These fail **Composability** — the functions cannot be reviewed in a single
sitting.

- `mira/api/routers/mira_v4.py:935` — `query_v4()` spans lines 935 – 1695
  (~760 LOC) embedding a 7-step pipeline (parse → guardrail → material search →
  lineage build → serialize). Describing it forces "AND" at least four times.
- `mira/api/routers/mua_v7.py:1531` `review_decisions_endpoint` (~208 LOC)
- `mira/api/routers/mua_v7.py:1739` `generate_draft_endpoint` (~168 LOC)
- `mira/api/routers/mua_v7.py:941`  `material_intel_endpoint` (~198 LOC)
- `mira/api/routers/mua_v7.py:1174` `import_miul_endpoint` (~123 LOC)
- `mira/api/routers/miul.py:619`    `extract_miul_v3` (~255 LOC)
- `mira/api/routers/forge.py:795`   `_execute_compiled_plan` (~177 LOC)
- `mira/api/routers/forge.py:580`   `_run_query_execution` (~144 LOC)
- `mira/miul/v3/builder.py:1353`    `_process_assembly` (~136 LOC)
- `mira/miul/v3/builder.py:1067`    `_build_graph` (~138 LOC)
- `mira/miul/v3/builder.py:482`     `extract_directory` (~122 LOC)
- `mira/forge_claude/question_gen/curator.py` — `curate_questions()` > 300 LOC
- `mira/mua/v7/draft_renderer.py:604` `_render_rationale` (~263 LOC)
- `mira/bsmh/service.py:222`        `run()` (~140 LOC)
- `mira/compliance/conductor.py:222` `run()` (~140 LOC)

### C3 — Version forks without deprecation

Three forks coexist in live code with no sunset markers, TODO deprecations, or
routing decisions documented.

- **MUA v6 / v7 / v8 / v10** — v7 is canonical
  (`mira/mua/matchmaker/adapters.py:9-10` imports only v7), but v6 and v8 ship
  intact with independent `draft_generator.py`, `retriever.py`, envelope
  matching. No `__init__.py` deprecation note.
- **BOK extractors** — `bok_standards_extractor_v6.py`, `bok_extractor_v7.py`,
  `bok_extractor_v8.py`, `bok_extractor_v10.py` all present; **v9 is missing**;
  the same class names replicate across versions.
- **MIUL v1_archive (9,552 LOC) is still imported live.**
  `mira/miul/v3/builder.py:1498` imports `MAPTIS_COLUMNS` from
  `v1_archive.dt_miul_builder`; `mira/miul/workflow.py:14-17` imports
  `HaikuExtractor`, `ExtractorService`, `MIULTreeBuilder` from the archive.
  Not archived in practice.
- **`mira/forge` vs `mira/forge_claude`** — `forge/compiler.py` (2,082 LOC,
  deterministic) and `forge_claude/compiler.py` (311 LOC, LLM-wrapping) both
  live. No routing comment in either `__init__.py`.

### C4 — Likely god classes

**Fails one-sentence smell test:**

- `mira/bsmh/service.py` (1,116 LOC) — mixes bouncer orchestration, material
  search, rules invocation, response formatting, and fracture-control routing.
  ~50 undocumented private helpers at lines 84 – 400.
- `mira/core/search_engine.py` (2,146 LOC) — semantic search + intent
  classification + material indexing + H2 category filtering. Compounds with
  C1.
- `mira/forge/compiler.py` (2,082 LOC, 54 methods) — introspects schema,
  discovers relationships, generates questions, bundles artifacts. Split
  recommended.
- `mira/api/routers/forge.py` (1,345 LOC) — mixes FORGE compilation + BSMS
  pipeline execution (two unrelated responsibilities).

**Looks like god-class but PASSES smell test (keep as-is):**

- `mira/mua/v7/material_resolver.py` (2,006 LOC) — resolves free-text →
  MAPTIS codes. Cohesive.
- `mira/mua/v7/investigator.py` (1,881 LOC) — orchestrates 10-phase evidence
  pipeline. Cohesive.
- `mira/mua/v7/draft_renderer.py` (1,244 LOC) — renders 7-section NASA doc
  (minus `_render_rationale` sprawl). Cohesive.
- `mira/knowledge_twins/h2_knowledge_twin_v2.py` (1,801 LOC) — H2 compatibility
  verdict engine. Exemplary section dividers.
- `mira/miul/v3/builder.py` (2,792 LOC) — build MIUL from drawings. Cohesive
  but decomposable.

---

## 3. Must-Have Violations by Principle

### 3.1 Intent & Reasoning

- API routers document "what" in headers but omit "why" in bodies:
  `mua_v7.py` has docstrings on only 5/43 functions (12 %);
  `mp_plan.py` 5/28 (18 %);
  `forge.py` 10/34 (29 %).
- `mira/bsmh/service.py:84-400` — ~50 helpers (`_merge_v4_request`,
  `_dedupe_keep_order`, `_material_matches_requested`,
  `_sanitize_requested_materials`) with zero intent comments.
- `mira/forge/generator.py:200-300` — template-generation methods have no
  rationale for the chosen router structure.
- `mira/miul/v3/extract.py:1491-1522` — `_call_vision_multi_page()` has no
  comment on retry strategy or why multi-pass exists.
- `mira/knowledge_twins/envelope_overlap.py`, `verdict_engine.py` — module
  docstrings equal the filename.

### 3.2 Auditability

- **Compliance references are real but uneven.** 262 NASA-STD-6016/6001, FAR,
  SWE citations across `mira/mua` and `mira/compliance`. But:
  - `mira/forge/compiler.py` (2,082 LOC) has **zero** compliance references
    despite generating safety-critical artifacts.
  - `mira/forge_claude/question_gen/curator.py` (1,527 LOC) has no compliance
    header.
  - `mira/miul/v3/text_extract.py:59-75` uses regex for CAGE-code validation
    without citing DFARS inline.
- `mira/api/routers/miul.py` header cites "SWE-032, SWE-033" but the body has
  zero inline compliance comments.
- `mira/api/routers/mua_v7.py:298` caches DB params via `@lru_cache` with no
  comment on TTL or invalidation strategy (perf–safety tradeoff unstated).

### 3.3 Composability

See C2. Roll-up: at least **12 functions over 120 LOC** across router +
builder + renderer layers, plus one **760-line endpoint** (`query_v4`).

### 3.4 Defensive Design

- **Strong:** `mira/mua/mua_generator.py:55-79` `_validate_environment`
  explicitly checks `habitable_volume`, `pressure_kpa`, `temperature_c`,
  `oxygen_pct` with named errors. `mira/api/models/*` Pydantic `Field()`
  constraints are present on `V4QueryRequest:84-95`.
- **Weak:** `mira/api/routers/mira_v4.py:1045-1073` unit-conversion helpers
  lack range checks; `mira/bsmh/service.py:176-192`
  `_sanitize_requested_materials` does regex substitution with no length/
  content bound.
- **Broken:** see C1.

### 3.5 Consistency

- **Logger name drift:** `mua_v7.py` uses `logger`; `mira_v4.py`, `miul.py`,
  `mp_plan.py` use `LOGGER`; `forge.py` has no logger at all.
- **Return-shape drift:** `mua_v7.py` mixes dict returns and Pydantic models
  across endpoints.
- **Helper-naming drift:** BSMH uses `_safe_int`, `_safe_float`,
  `_normalize_token`; compliance uses `quantize_hee_severity`, `compute_gap_id`
  (library style).
- snake_case is otherwise uniform across the repo.

### 3.6 Boring Execution

- **Clever imports with fallback flags:**
  `mira/miul/material_code_lookup.py:44-61` cascades optional
  `alloy_normalizer`, `rapidfuzz`, `psycopg2` imports with
  `NORMALIZER_AVAILABLE` flags. Debuggability suffers.
- **Hand-rolled sort chains:**
  `mira/forge_claude/question_gen/curator.py:653-707` nests 3 fallback sort
  strategies without intermediate names.
- Otherwise clean: `difflib.SequenceMatcher`, stdlib `logging`, no metaclass
  tricks.

---

## 4. Nice-to-Have Gaps

- **Self-documenting examples:** Almost no doctests or inline usage examples.
  Exceptions: `h2_knowledge_twin_v2.py:1697` (`demo()`),
  `miul/v3/text_extract.py:28-41`. Critical functions like `resolve_material()`
  (`material_resolver.py:1755`) should ship with usage examples.
- **Traceability back to requirements:** Citations are at the file-header
  level. Few function-level comments reference which FAR / NASA section the
  logic implements. Exception: `mira/mua/v7/category_router.py:74-100`
  `AuthorityPack` — textbook pattern; every threshold traced to source
  document, section, and effective date. **This pattern should be exported
  repo-wide.**
- **Graceful degradation documentation:** `mira/mua/retrieval.py:27-45` falls
  back to `None` when FAISS / `sentence_transformers` are absent, but doesn't
  document behavior when both fail. No user-facing warning emitted.
- **Performance notes:** MUA's 10-phase investigator pipeline has no
  async/perf rationale. `forge/compiler.py:58-71` budgets lack tuning
  justification.

---

## 5. Notable Strengths (preserve & propagate)

1. **`mira/mua/v7/category_router.py:74-100` AuthorityPack pattern** — every
   threshold linked to document + section + effective date. Gold-standard for
   Tier-One traceability. Export this pattern.
2. **`mira/mua/v7/material_resolver.py:1-20` and `investigator.py:1-26`** —
   15-50-line module headers citing legacy issues being fixed (v6 regex
   grouping, 4 independent paths, safety fixes C1 – C4). Exemplary "why"
   documentation.
3. **`mira/bsmh/fracture_engine.py` (665 LOC)** — NASA-STD-5019A determinism
   documented; citation chain tracking at lines 391 – 399; explicit NULL
   handling lines 97 – 98; seed classification rules inline-commented; errors
   logged at line 659. Closest file in the repo to Tier-One.
4. **`mira/compliance/` module uniformly** — every file has `Purpose:`,
   `Compliance:`, `Safety Critical:` headers; `severity.py` and `id_utils.py`
   are <200 LOC single-responsibility reference implementations.
5. **`mira/api/rate_limit.py` (140 LOC)** — tight <50-line functions, explicit
   error naming, sliding-window algorithm documented, key-derivation fallback
   chain.
6. **`mira/api/app_factory.py` (273 LOC)** — single-responsibility factory,
   lazy-loading rationale lines 71 – 80.
7. **100+ named exception handlers in MUA / compliance** with
   `LOGGER.exception()` + context. Where logging exists, it is done well — the
   failure is silencing, not format.
8. **Type hints and `from __future__ import annotations`** are uniform in
   critical paths; 826 structured `LOGGER` calls dominate the codebase
   (vs. 507 `print()`). Print cleanup is a low-effort hygiene win.
9. **Pydantic boundary validation** present at API entry
   (e.g. `V4QueryRequest`).
10. **`__safety_critical__ = True`** marker is applied consistently across
    knowledge-twins modules.

---

## 6. One-Paragraph Summary

The `mira` codebase has Tier-One DNA — the MUA v7 headers, fracture engine,
compliance module, and AuthorityPack pattern prove the team knows what
Tier-One looks like. The problem is that quality is localized: those same
standards are not enforced in BSMH service orchestration, the API-router
layer, `core/search_engine.py`, or the forge compiler, where silent exception
handling, 120 – 760-LOC functions, and unmarked version forks violate every
Tier-One must-have simultaneously. The good news is that the fixes are
mechanical: add logging to silent excepts, break up a dozen named functions,
and mark the legacy archives as deprecated. **None** of the P0 items require
architectural redesign. The codebase can be dragged to Tier-One compliance by
propagating the patterns it already owns.
