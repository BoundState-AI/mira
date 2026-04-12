# Tier-One Remediation Plan — `mira`

**Companion to:** `01_audit_findings.md`
**Date:** 2026-04-11
**Branch:** `claude/audit-tier-one-compliance-QnyWn`

---

## Tracking Summary

| Phase | Tasks | Principle(s) Addressed            | Risk if Skipped                          |
| ----- | :---: | --------------------------------- | ---------------------------------------- |
| P0    |   7   | Auditability, Composability       | Blocks any external compliance review    |
| P1    |   8   | Composability, Consistency         | Structural debt compounds per release    |
| P2    |   8   | Intent & Reasoning, Auditability  | Reviewer confusion; tribal knowledge     |
| P3    |   5   | Boring Execution, polish          | Hygiene; no safety impact                |

---

## Phase P0 — Blocks Tier-One Compliance Review

These must be resolved before any external reviewer can certify the codebase.

### P0-1. Eliminate silent exception swallowing in `bsmh/service.py`

**Files:** `mira/bsmh/service.py`
**Lines:** 591, 618, 643, 657, 673

**Current (bad):**
```python
except Exception:
    pass
```

**Target (good):**
```python
except Exception:
    LOGGER.warning(
        "Material DB search failed for patterns=%s source=%s",
        candidate_materials, search_source, exc_info=True,
    )
```

**Acceptance criteria:**
- Every `except` block in the file either (a) logs with `LOGGER.warning` /
  `.error` including `exc_info=True`, or (b) raises a named exception.
- No bare `pass` after any `except` in a path that feeds a compliance
  determination.
- Unit test added: mock DB to raise, assert log message emitted.

---

### P0-2. Eliminate silent exception swallowing in `bsmh/bouncer.py`

**Files:** `mira/bsmh/bouncer.py`
**Lines:** 540-543

**Current:**
```python
try:
    structured = BSMHStructuredQuery.model_validate(structured_raw)
except Exception:
    return None
```

**Target:**
```python
try:
    structured = BSMHStructuredQuery.model_validate(structured_raw)
except ValidationError:
    LOGGER.warning(
        "Structured-query validation failed; returning None. raw=%s",
        structured_raw, exc_info=True,
    )
    return None
```

**Acceptance criteria:**
- Exception class narrowed to `ValidationError` (or most-specific applicable).
- Log emitted with raw input context.
- Any remaining bare `except Exception` in the file (lines 542, 602, 655)
  treated the same way.

---

### P0-3. Eliminate silent exception swallowing in `bsmh/bok_adapter.py`

**Files:** `mira/bsmh/bok_adapter.py`
**Line:** 80

**Target:** Replace `except Exception: rows = []` with named exception +
`LOGGER.error` including the engine error context.

**Acceptance criteria:** Same pattern as P0-1.

---

### P0-4. Log scoring failures in `core/search_engine.py`

**Files:** `mira/core/search_engine.py`
**Lines:** 1210, 1245, 1257, 1263

These are inside the FAISS-result scoring loop. Silent `pass` means a scoring
exception silently degrades result ranking with no diagnostic.

**Target:**
```python
except Exception:
    logger.debug("Scoring heuristic skipped: %s", e, exc_info=True)
```

Use `debug` (not `warning`) here because these fire per-result inside a hot
loop. The key requirement is *traceability*, not alerting.

**Acceptance criteria:**
- All four sites emit at minimum `logger.debug` with `exc_info`.
- No bare `pass` remains after any `except` in the file.

---

### P0-5. Break up `query_v4()` (760-line endpoint)

**File:** `mira/api/routers/mira_v4.py`
**Lines:** 935 – 1695

This is the single largest Tier-One composability violation. The function
embeds a 7-step pipeline inline.

**Decomposition plan:**

| Step | Extract to helper                  | Approx lines |
| ---- | ---------------------------------- | ------------- |
| 1    | `_parse_and_validate_query()`      | ~60           |
| 2    | `_run_guardrail_check()`           | ~40           |
| 3    | `_search_materials()`              | ~120          |
| 4    | `_build_decision_lineage()`        | ~180          |
| 5    | `_apply_h2_policy()`              | ~80           |
| 6    | `_serialize_response()`            | ~60           |
| 7    | `_attach_evidence_envelope()`      | ~40           |

The remaining `query_v4()` becomes an orchestrator calling steps 1-7 in
sequence, under 50 lines.

**Acceptance criteria:**
- `query_v4()` body is ≤ 60 lines.
- Each extracted helper has a one-line docstring stating its purpose.
- Existing tests still pass (no behavioral change).
- Each helper is independently callable for unit testing.

---

### P0-6. Add deprecation markers to version forks

**Files (add header comments + `warnings.warn`):**

| Path                              | Mark as            | Canonical replacement     |
| --------------------------------- | ------------------ | ------------------------- |
| `mira/mua/v6/__init__.py`        | `DEPRECATED`       | `mira.mua.v7`             |
| `mira/mua/v8/__init__.py`        | `DEPRECATED`       | `mira.mua.v7`             |
| `mira/knowledge_twins/bok_standards_extractor_v6.py` | `DEPRECATED` | `bok_extractor_v10` |
| `mira/knowledge_twins/bok_extractor_v7.py`           | `DEPRECATED` | `bok_extractor_v10` |
| `mira/knowledge_twins/bok_extractor_v8.py`           | `DEPRECATED` | `bok_extractor_v10` |
| `mira/miul/v1_archive/__init__.py`                   | `DEPRECATED` | `mira.miul.v3`     |

**Pattern to add at top of each:**
```python
import warnings
warnings.warn(
    f"{__name__} is deprecated; use <canonical> instead. "
    "Planned removal: v5.0",
    DeprecationWarning,
    stacklevel=2,
)
```

**Acceptance criteria:**
- Every deprecated module emits `DeprecationWarning` on import.
- Each `__init__.py` has a one-line comment: `# DEPRECATED — use X instead.
  Removal target: v5.0`
- No functional changes to the deprecated code itself.

---

### P0-7. Add `LOGGER.error` to `mua_v7.py` silent swallow

**File:** `mira/api/routers/mua_v7.py`
**Lines:** 382-387

**Target:** Replace silent swallow with named exception + `LOGGER.warning` +
context about which optional table was missing.

**Acceptance criteria:** Same pattern as P0-1.

---

## Phase P1 — Structural Debt

### P1-1. Refactor `bsmh/service.py` into focused modules

**File:** `mira/bsmh/service.py` (1,116 LOC)

**Decomposition:**

| New module                          | Responsibility                         | Lines moved |
| ----------------------------------- | -------------------------------------- | ----------- |
| `mira/bsmh/material_search.py`     | DB batch search, family search         | ~200        |
| `mira/bsmh/query_sanitizer.py`     | `_sanitize_*`, `_normalize_*` helpers  | ~120        |
| `mira/bsmh/response_builder.py`    | Evidence-row assembly, sorting         | ~100        |

`service.py` keeps `BSMHService.run()` as a thin orchestrator importing from
the above.

**Acceptance criteria:**
- `service.py` ≤ 400 LOC.
- Each new module has a header docstring explaining *why* it exists.
- Every extracted helper has at least a one-line docstring.
- All existing tests pass without modification (import paths may change but
  behavior must not).

---

### P1-2. Refactor `core/search_engine.py` into focused modules

**File:** `mira/core/search_engine.py` (2,146 LOC)

**Decomposition:**

| New module                         | Responsibility              |
| ---------------------------------- | --------------------------- |
| `mira/core/intent_classifier.py`  | Query-intent detection      |
| `mira/core/h2_policy.py`          | H2 category filter / policy |
| `mira/core/scoring_boost.py`      | Per-result heuristic boosts |

`search_engine.py` keeps FAISS init + top-level `search()` orchestrator.

**Acceptance criteria:**
- `search_engine.py` ≤ 800 LOC.
- Passes one-sentence smell test.
- P0-4 logging fixes applied in extracted modules.

---

### P1-3. Split `forge/compiler.py` into cohesive modules

**File:** `mira/forge/compiler.py` (2,082 LOC, 54 methods)

**Decomposition:**

| New module                              | Responsibility                |
| --------------------------------------- | ----------------------------- |
| `mira/forge/schema_introspector.py`     | DB schema discovery           |
| `mira/forge/relationship_discoverer.py` | FK / join-path inference      |
| `mira/forge/question_generator.py`      | Question templating + budgets |

`compiler.py` keeps `ForgeCompiler.compile()` as orchestrator.

**Acceptance criteria:**
- `compiler.py` ≤ 600 LOC.
- Budget constants documented with tuning rationale.

---

### P1-4. Document `forge` vs `forge_claude` routing

**Files:**
- `mira/forge/__init__.py`
- `mira/forge_claude/__init__.py`

Add a module docstring to each explaining which is canonical, which wraps the
other, and when to use each.

**Acceptance criteria:**
- A developer can read either `__init__.py` and know the relationship.

---

### P1-5. Break up oversized MUA v7 router endpoints

**File:** `mira/api/routers/mua_v7.py`

| Endpoint (line)                | Current LOC | Target LOC | Extract to                                       |
| ------------------------------ | ----------- | ---------- | ------------------------------------------------ |
| `review_decisions_endpoint` (1531) | ~208    | ≤ 60       | `_validate_gate()`, `_detect_divergence()`, `_execute_review()` |
| `material_intel_endpoint` (941)    | ~198    | ≤ 60       | `_filter_candidates()`, `_disambiguate_materials()` |
| `generate_draft_endpoint` (1739)   | ~168    | ≤ 60       | `_advance_step()`, `_build_draft_context()`         |
| `import_miul_endpoint` (1174)      | ~123    | ≤ 60       | `_parse_miul_file()`, `_enrich_materials()`         |

**Acceptance criteria:**
- Each endpoint body ≤ 60 LOC.
- Each extracted helper has a docstring.
- Existing integration tests pass.

---

### P1-6. Break up oversized MIUL router endpoints

**File:** `mira/api/routers/miul.py`

| Endpoint (line)              | Current LOC | Target |
| ---------------------------- | ----------- | ------ |
| `extract_miul_v3` (619)     | ~255        | ≤ 60   |
| `extract_miul_v4` (1196)    | ~121        | ≤ 60   |

Same decomposition pattern: extract pipeline steps into private helpers.

---

### P1-7. Break up oversized Forge router endpoints

**File:** `mira/api/routers/forge.py`

| Function (line)                | Current LOC | Target |
| ------------------------------ | ----------- | ------ |
| `_execute_compiled_plan` (795) | ~177        | ≤ 60   |
| `_run_query_execution` (580)   | ~144        | ≤ 60   |

---

### P1-8. Decompose `draft_renderer._render_rationale()`

**File:** `mira/mua/v7/draft_renderer.py`
**Line:** 604 (~263 LOC)

Extract:
- `_curate_precedents()` — precedent selection logic
- `_synthesize_conflict_narrative()` — conflicting-evidence prose
- `_render_rationale()` becomes a 40-line orchestrator.

---

## Phase P2 — Documentation Hygiene

### P2-1. Normalize logger naming to `LOGGER` globally

**Scope:** All Python files in `mira/`.

**Action:** `logger = logging.getLogger(__name__)` → `LOGGER = logging.getLogger(__name__)` everywhere. Add logger to `mira/api/routers/forge.py` (currently has none).

**Acceptance criteria:** `grep -rn 'logger = logging' mira/` returns zero results; only `LOGGER` remains.

---

### P2-2. Add "why" docstrings to `bsmh/service.py` helpers

**File:** `mira/bsmh/service.py` lines 84-400

~50 private helpers currently have zero docstrings. Add one-line intent
comment to each explaining the business rule it enforces.

---

### P2-3. Add "why" comments to all functions > 80 LOC in API routers

**Files:** `mira/api/routers/mua_v7.py`, `mira_v4.py`, `miul.py`,
`mp_plan.py`, `forge.py`

Every function over 80 LOC gets a docstring stating:
1. What business rule or pipeline step it implements.
2. Why it is structured this way (e.g., "steps must execute sequentially
   because step 3 depends on step 2's gate decision").

---

### P2-4. Propagate AuthorityPack pattern to BSMH, H2, O2

**Source pattern:** `mira/mua/v7/category_router.py:74-100`

**Targets:**
- `mira/bsmh/rules_engine.py` — scoring weights and confidence thresholds
- `mira/knowledge_twins/h2_knowledge_twin_v2.py` — HEE bands
- `mira/knowledge_twins/scoring.py` — scoring profiles
- `mira/o2/engine.py` — O2 thresholds
- `mira/compliance/severity.py` — severity bands

Each threshold/constant gets a structured comment:
```python
# Authority: NASA-STD-6016C §4.3.2, effective 2023-03-15
# Rationale: <why this value>
THRESHOLD = 0.85
```

---

### P2-5. Add compliance headers to `forge/compiler.py` and `forge_claude/curator.py`

Both files generate safety-critical artifacts but have zero compliance
references.

Add `Purpose:`, `Compliance:`, `Safety Critical:` header blocks matching the
pattern used in `mira/compliance/` modules.

---

### P2-6. Add inline FAR/DFARS citation to `miul/v3/text_extract.py`

**Line:** 59-75 — CAGE-code regex validation.

Add inline comment citing the specific DFARS clause that defines the CAGE code
format being validated.

---

### P2-7. Document `@lru_cache` TTL policy in `mua_v7.py`

**Line:** ~298

Add comment explaining: (a) what is cached, (b) expected TTL / invalidation
strategy, (c) why unbounded cache is acceptable here (or add `maxsize`).

---

### P2-8. Add module docstrings to thin-header files

**Files:**
- `mira/knowledge_twins/envelope_overlap.py`
- `mira/knowledge_twins/verdict_engine.py`
- `mira/forge/generator.py`

Each gets a 3-5 line module docstring explaining *why* the module exists and
what architectural constraint it satisfies.

---

## Phase P3 — Polish

### P3-1. Replace `print()` calls with structured `LOGGER`

**Scope:** 507 `print()` calls across the codebase.

Batch replacement: `print(...)` → `LOGGER.info(...)` or `LOGGER.debug(...)`.

Priority order: safety-critical modules first (`bsmh/`, `compliance/`,
`mua/v7/`), then `miul/`, then `forge/`.

---

### P3-2. Retire `miul/v1_archive/` after migrating live imports

**Prerequisite:** P0-6 deprecation markers are in place.

1. Move `MAPTIS_COLUMNS` constant from `v1_archive/dt_miul_builder.py` into
   `mira/miul/v3/constants.py`.
2. Update `mira/miul/v3/builder.py:1498` import.
3. Update `mira/miul/workflow.py:14-17` to import from v3 equivalents.
4. Once no live imports remain, move `v1_archive/` to a `_deprecated/`
   directory or delete entirely.

---

### P3-3. Simplify cascading optional imports in `material_code_lookup.py`

**File:** `mira/miul/material_code_lookup.py:44-61`

Replace cascading try/except import flags with a single `_check_dependencies()`
function that logs which optional packages are available at init time.

---

### P3-4. Add usage examples to top-10 public entry points

Add `Example:` sections to docstrings of:
1. `BSMHService.run()`
2. `ComplianceConductor.run()`
3. `MaterialResolver.resolve_material()`
4. `Investigator.investigate()`
5. `DraftRenderer.render()`
6. `MIULBuilderV3.build()`
7. `ForgeCompiler.compile()`
8. `SearchEngine.search()`
9. `H2KnowledgeTwinV2.query()`
10. `QuestionCurator.curate_questions()`

---

### P3-5. Add performance SLA comments to hot paths

**Files:**
- `mira/knowledge_twins/h2_knowledge_twin_v2.py` — mentions "sub-millisecond"
  as design goal but no SLA on compute-heavy functions.
- `mira/mua/v7/investigator.py` — 10-phase pipeline with no async/perf notes.
- `mira/forge/compiler.py:58-71` — budget constants with no tuning rationale.

Add inline `# Performance:` comments documenting expected latency, throughput
limits, or why the current approach was chosen over alternatives.

---

## Dependency Graph

```
P0-1 ──┐
P0-2 ──┤
P0-3 ──┼── (independent, can run in parallel)
P0-4 ──┤
P0-7 ──┘

P0-5 ────── standalone (largest single task)

P0-6 ────── prerequisite for P3-2

P1-1 ────── depends on P0-1 (service.py changes should land first)
P1-2 ────── depends on P0-4 (search_engine.py logging lands first)
P1-3 thru P1-8 ── independent of each other

P2-* ────── all independent; can run in any order after P1

P3-2 ────── depends on P0-6
P3-1, P3-3, P3-4, P3-5 ── independent
```

---

## Definition of Done (Tier-One)

A module is Tier-One compliant when:

- [ ] Every function has a docstring explaining *why*, not just *what*.
- [ ] Every `except` block names a specific exception class and logs context.
- [ ] No function exceeds 50 lines (soft limit: 60 for orchestrators).
- [ ] The module can be described in one sentence without "and".
- [ ] Naming follows repo convention (`LOGGER`, snake_case, Pydantic models).
- [ ] Compliance-relevant thresholds cite their authority source.
- [ ] No deprecated version forks are imported without a `DeprecationWarning`.
