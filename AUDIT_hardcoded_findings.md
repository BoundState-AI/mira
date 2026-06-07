# MIRA Audit — Hardcoded / Canned / Fabricated Behavior

Scope: full `mira/` tree, reviewed module by module. Focus: values presented to
users as **computed, evidence-driven, data-backed** output that are in fact
hardcoded, canned, randomized, or silently faked.

Severity key:
- **HIGH** — fabricated/fake data shown to a user as real, or a live safety bypass / security exposure / runtime crash.
- **MED** — hardcoded magic value that should be config/computed, or silent degradation.
- **LOW** — dev/test scaffolding, dead code, cosmetic, or verified-legitimate.

`(LIVE)` = wired into a production path. `(DEAD)` = present in tree but no caller found.

---

## Cross-cutting theme: "confidence" is theater

Almost nowhere in MIRA is a reported `confidence`/`score` actually derived from
evidence. It is overwhelmingly a literal keyed on a branch or category. A NASA
materials-compliance tool that prints calibrated-looking uncertainty it did not
compute is the single biggest issue here.

---

## HIGH

### Fabricated confidence / scores (LIVE)
| Location | Problem |
|---|---|
| `mua/mua_generator.py:244-246` | `estimate_confidence()` caps to `[0.3,0.95]` and invents "68%/95% intervals" as `avg ± 0.08` / `avg ± 0.15`. No statistical basis. |
| `mua/classifier/classifier.py:467-475` | Confidence assigned by MUA *type* (THIN_SCREENING=0.90, INCOMPLETE_PASS=0.95…), not evidence. |
| `mua/classifier/classifier.py:477-485` | Precedent requirement hardcoded by type; THIN_SCREENING & INCOMPLETE_PASS require **0** precedents. |
| `mua/synthesis/synthesizer.py:317-335` | LLM-failure template fallback returns `confidence=1.0` (canned boilerplate marked maximally confident). |
| `mp_plan/engines/compliance_eval.py:102,118,157,172,208,223` | Every compliance determination returns fixed `0.95/0.9/0.85`. |
| `mp_plan/engines/compliance_eval_codex.py:116` | Blanket `confidence=0.95`. |
| `mp_plan/adapters/maptis_adapter.py:195` | Every MAPTIS lookup → `0.95` regardless of data. |
| `mp_plan/adapters/compliance_adapter.py:116,140` | Fixed `0.95`/`0.9`. |
| `mp_plan/gap_resolution/{full_mua,heat_sink,substitution,configuration,minor_quantity,test_program}.py` | Confidence = decision-tree literal (0.0–0.9), not evidence-derived. |
| `compliance/conductor.py:155,164,177` | Confidence keyed on resolution source. |
| `forge/compiler.py:1879-1940` | Confidence ladder 0.55→0.99 keyed on column-name patterns; magic formulas at `1121,1166,1439`. |
| `forge_claude/question_gen/curator.py:65-186` | Hardcoded `base_value` "engineering value" ladder. |
| `chat/query_interpreter.py:856,859` & `chat/module_context.py:180` | Routing confidence force-set to `0.99`/`0.96` whenever module context present. |
| `miul/extraction_fixes.py:437-579,640-720` | Hardcoded fastener/McMaster/Helicoil material DB with invented confidences; missing material silently replaced by a guessed default + score. |
| `miul/aggregated_ratings.py:457,557,560,577` | Arbitrary confidence multipliers (×0.9/0.8/0.85) presented as scientific weighting. |

### Canned / stub data wired into production (LIVE)
| Location | Problem |
|---|---|
| `oca/engine.py:10` → `oca/maptis_stub.py:133-153` | Production OCA runs on the **stub**: regex family-guessing with hardcoded `confidence 0.95/0.85/0.80/0.5/0.2`. User can't tell stub from real MAPTIS. |
| `chat/adapters/gpcm_adapter.py:171-225` | When the compliance conductor is unavailable, returns `_build_stub_response()` — a structured NASA-STD-6016C envelope ("pending configuration") that looks like a real "insufficient data" result. |
| `chat/adapters/am_adapter.py:155,159,286-290` | Defaults to `"Synthetic GRCop-42 LPBF combustion liner"` / `"GRCop-42"`; output self-labels "Demo Boundary … controlled standards are inert name-only placeholders" — demo/synthetic data served through the qualified chat path. |
| `pipeline/stages/materials_search.py:31-43` | `_FAMILY_COMPOSITION_CODES` hardcoded dict ("stopgap until Granta"); wrong code = silently wrong material search. |
| `mp_plan/engines/data_acquisition.py:96-116` | "Mock mode" fabricates all-`"U"` ratings and proceeds as if real. |

### Live safety bypass / runtime crash
| Location | Problem |
|---|---|
| `knowledge_twins/h2_knowledge_twin_v2.py:175,181,203` | Uses `NI_PREDICTOR` & `ELEVATED_TEMP_PEAK_MATERIALS` that are **never imported** (verified vs. import block 32-64) → `NameError` when the Ni-predictor / elevated-temp path runs. |
| `pipeline/stages/boundary_check.py:125-128` | H2 boundary check is a **stub** that logs and returns ctx unchanged — hydrogen queries skip safety enforcement. |
| `pipeline/stages/boundary_check.py:90` | Unparsed pressure defaults to **1000 psia**, temp to **294 K** — silently substitutes extreme/wrong physical params into O2/cryo decisions. |
| `MIRA_V2/src/material_decider.py:69-70` & `constraint_interpreter.py:103-108` | Env classified by first-keyword-wins; unparsed env silently treated as non-oxygen → O2 rules skipped. |
| `o2/policy_engine.py:594` | `_compute_usage_score()` returns hardcoded `0.0` (TODO: query MUA/MIUL) — all O2 historical-precedent scoring is stubbed. |

### Security
| Location | Problem |
|---|---|
| `core/db_config.py:251,260` | Falls back to `user/password = postgres/postgres` if env vars unset (code calls it a "KNOWN SECURITY RISK"). |
| `api/models/heritage_db.py:76-77` | Same hardcoded `postgres/postgres` fallback. |
| `precedent_engine/utils/maptis.py:85-92` | Default password `"postgres"` fallback. |

---

## MEDIUM

| Location | Problem |
|---|---|
| `o2/engine.py:63` | `np.random.seed(42)` at module import — a "deterministic, auditable" safety engine shouldn't touch numpy RNG at all. |
| `mua/v7/confidence.py:117-123,254-271,360` | Evidence-strength scores are arbitrary quantizations (1.0/0.6/0.2/0.0) + magic blend `0.80*min+0.20*mean`. |
| `mua/historic_retrieval.py:307-377` | Hardcoded environment relevance boosts (+0.20 H2/O2, +0.18 N2/He…), cap +0.30; uncalibrated. |
| `mua/classifier/classifier.py:356-416` | Category I thresholds (23.5% O2, 265 psia, −150°F) hardcoded — cite standards in comments but never pull/verify them. |
| `mua/v6/{retriever.py:304-331,decision_engine.py:209-241,draft_generator.py:280-294}` | Material-match & decision confidences hardcoded per branch. |
| `mua/retrieval.py:388`, `mua/matchmaker/rationale_extractor.py:62,76,88` | Magic dedup/scoring thresholds (0.85, 1.5×, 24 chars) unjustified. |
| `mua/service.py:272` | `confidence_score=0.7` base, no rationale. |
| `miul/mua_synthesizer.py:115-129` | Parse failure silently returns `relevance_score=0.5`, `PARTIAL`. |
| `miul/v3/{extract.py:327,ocr_learning.py}` | Vision error → empty `{}`; OCR-correction thresholds (0.7/0.8/0.9) hardcoded. |
| `compliance/adapters/{o2,h2}_adapter.py` | `_create_placeholder_output()` emits gap signals with `confidence=1.0` when engine unavailable. |
| `compliance/models/result.py:232` | `# TODO: filter` — all MPR determinations returned unfiltered. |
| `core/search_engine.py:657-685,1003-1006,1029` | `except: pass` swallows query-expansion failures; config-fail → silent hardcoded `top_k=25/min_sim=0.1`; intent-fail → `confidence:0.5`. |
| `MIRA_V2/src/llm_answer_generator.py:645-651,752-755` & `pipeline/stages/generate.py:59-62` | LLM-unavailable returns canned error string with no escalation; 6 `TODO None` env/pressure/temp fields fed to the LLM prompt. |
| `precedent_engine/models/config.py` | Hardcoded `us-gov-west-1` + fixed Bedrock model id. |
| `knowledge_twins/scoring_profiles.py:148-182,383` | Profile weights hardcoded; `TODO: DB loading` — no DB backing. |
| `mua/v7/investigator.py:132-139` | `_MOCK_DEPENDENCIES`/`_MOCK_REVOKED` empty — "zombie MUA detection" advertised but is a no-op. |

---

## LOW / dead / verified-legitimate

| Location | Note |
|---|---|
| `mua/mua_generator.py:100-237` `_fake_retrieve()` | Canned mitigations w/ hardcoded scores — **DEAD** (no caller; `generate_mua` raises instead). Remove. |
| `core/search_engine.py:2082` `get_similar_materials` | Returns `0.5` for every material — **DEAD** (no caller). |
| `precedent_engine/utils/bedrock.py:91-135`, `core/narrator.py:232-274`, `utils/maptis.py:231-297` | Mock LLM / narrator / MAPTIS — test utilities, importable from prod (risk if mis-wired). |
| `forge_claude/scaffolder/mock_data.py` | `random.*` mock rows — dev scaffolding for generated frontends only. |
| `miul/models.py:326-394`, `miul/v2/assemble.py:427-481` | `create_sample_*` / `create_mock_page` in prod modules. |
| `galvanic/engine.py:213-221` | Surface modifiers 0.8/0.9/0.85 — **legitimate** NASA-STD-6012A values. |
| `o2/policy_engine.py:442-454` | Family authority gates — **legitimate** NASA-STD-6016 Table 4-1 values. |
| `precedent_engine/core/precedent_engine.py:441-496` | Binary 1.0/0.5 similarity — defensible design choice. |

---

---

## Remediation status (this branch)

### Fixed
| Item | What changed |
|---|---|
| `h2_knowledge_twin_v2.py` NameError | Imported `NI_PREDICTOR` / `ELEVATED_TEMP_PEAK_MATERIALS`. |
| `pipeline/boundary_check.py` H2 no-op | H2 boundary check now actually calls `evaluate_h2_compatibility`. |
| `pipeline/boundary_check.py` silent defaults | Default pressure/temp now logged and surfaced in the rationale ("Assumptions: …"), not silently substituted. |
| `mua_generator.py` fake intervals | Removed fabricated 68%/95% intervals; report mean retriever relevance + explicit "not a calibrated probability" note. Deleted dead `_fake_retrieve`. |
| `core/search_engine.py:get_similar_materials` | Raises `NotImplementedError` instead of returning uniform `0.5`. |
| `synthesis/synthesizer.py` template `confidence=1.0` | Template/boilerplate claim now `confidence=0.0` (branch on `template_fallback`). |
| `o2/engine.py` `np.random.seed(42)` | Removed; engine uses no RNG (deterministic TF-IDF only). |
| `mp_plan/data_acquisition.py` auto-mock | Mock MAPTIS no longer auto-engages on missing creds; requires `MIRA_ALLOW_MOCK_MAPTIS`, else raises. |
| `heritage_db.py`, `precedent_engine/utils/maptis.py` creds | Removed `postgres/postgres` fallback; route through production-guarded `db_config`. |
| `precedent_engine/cli.py` | Uses real `MAPTISClient` by default; mock only under `--use-mock-llm`. |

### Verified HONEST after reading (agents overstated — left as-is)
- `compliance/adapters/{o2,h2}_adapter.py` placeholder `confidence=1.0` — emits an explicit `MISSING_INPUT`/`UNKNOWN` gap ("engine unavailable, manual review required"); the 1.0 means "certain a gap exists," which is true.
- `chat/adapters/gpcm_adapter.py` stub — returns `Status.INSUFFICIENT_DATA` ("Pending Full Analysis") with `missing_inputs`; honest degradation, not a fake pass.
- `chat/adapters/am_adapter.py` — self-labels "Synthetic Demo Track output only … inert name-only placeholders."
- `oca/maptis_stub.py` — looks up a bundled reference pack and carries provenance (`data_source`, `source`, match-quality confidence); fallback clearly tagged `oca_standalone_heuristic`.
- `mp_plan/adapters/maptis_adapter.py:195` `confidence=0.95` — carries `confidence_basis="Direct MAPTIS database lookup"`; source-reliability value, not a fabricated computation.
- `core/db_config.py` — `postgres/postgres` fallback is dev-only and already blocked in production via `require_production_credentials()`.
- `galvanic/engine.py`, `o2/policy_engine.py` family gates — legitimate NASA-STD lookup values.

### NOT fixed — needs a real calibration project (do NOT churn the numbers)
These are pervasive fixed "rule strength" confidences keyed on a branch/category.
Most carry a `confidence_basis` or are the actual scoring scheme. Making them
genuinely evidence-derived is a calibration effort against the MUA corpus, not a
mechanical edit — and jittering the literals would just be more fabrication.
- `forge/compiler.py:1879-1940` + formulas `1121/1166/1439`; `forge_claude/question_gen/curator.py` value ladder.
- `mp_plan/engines/compliance_eval*.py`, `mp_plan/gap_resolution/*`, `compliance/conductor.py` confidence literals.
- `mua/classifier/classifier.py` confidence-by-type and 0-precedent requirements (changing these alters classification behavior — needs test coverage first).
- `mua/v7/confidence.py` quantizations, `mua/historic_retrieval.py` env boosts (this IS the scoring model; needs calibration, not deletion).
- `pipeline/materials_search.py` family→code dict, `o2/policy_engine.py:_compute_usage_score` — documented stopgaps awaiting Granta / MUA-DB integration.

---

## Suggested remediation priority
1. **Stop printing fabricated confidence.** Either compute it from evidence (precedent count, test recency, envelope overlap) or remove the field. At minimum, tag every non-computed value as `confidence_basis="heuristic"`.
2. **Fix the live crash:** import `NI_PREDICTOR` / `ELEVATED_TEMP_PEAK_MATERIALS` in `h2_knowledge_twin_v2.py`.
3. **Un-stub H2 boundary check**, or make it hard-fail rather than silently pass.
4. **Make defaults explicit failures:** boundary_check pressure/temp, env classification, `data_acquisition` mock mode — raise/flag instead of substituting.
5. **Surface stub/demo mode to the user:** OCA maptis_stub, gpcm stub response, am_adapter demo data must be unmistakably labeled or gated out of production.
6. **Kill dead fakery:** delete `_fake_retrieve`, `get_similar_materials` placeholder.
7. **Remove hardcoded `postgres/postgres` fallbacks;** require env vars.
