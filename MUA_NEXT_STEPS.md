# MUA Engine — Next Steps

Status after PRs #7 (safety fixes) and #8 (precedent-grounded `generate_mua`, v8/final deleted).

The public `mira.mua.generate_mua` is now wired to the real v7 precedent retriever
(`search_precedents_pg` over `mua_precedents_v7`). v8/`final` are gone. This doc is
the punch list to take it from "wired" to "trusted in production."

---

## 0. Verify the merge against a live DB (DO FIRST)

PR #8 was verified by `compileall` + tracing only — there is **no Postgres or
pydantic** in the CI container, so it has not actually run. Before relying on it:

- [ ] **Happy path**: call `generate_mua` for a material that has corpus precedents
      (e.g. A-286 / 6061-T6 in GOX). Confirm `precedent_backed=True`, real
      `cited_precedents`, `precedent_count > 0`, and confidence == the retriever's
      relevance.
- [ ] **No-match path**: an obscure material. Confirm `precedent_backed=False`,
      `confidence_score=0.0`, mitigation text says "standards-only."
- [ ] **DB-down path**: stop Postgres. Confirm `precedent_corpus_available=False`,
      no crash, warning surfaced.
- [ ] **Routers**: smoke `mua.py` (`/generate`) and `mua_v7.py` wizard end-to-end.
- [ ] Confirm `get_precedent_stats()` returns sane counts (total ≈ 5,650,
      `has_family`, `has_env`, `has_category`).

---

## 1. Family inference is heuristic — make it real

`service._infer_pg_family()` is regex-based (good enough to pick a search tier, but
coarse — e.g. any `3\d{2}` token → STAINLESS_STEEL).

- [ ] Replace with the canonical resolver: `mira.mua.v7.material_resolver.get_material_family()`
      (DB-backed) with the regex as a fallback only.
- [ ] Add a unit test table: designation/spec → expected canonical family for the
      top ~30 materials in the corpus.

---

## 2. Issue mapping coverage

`service._TEST_CLASS_TO_ISSUE` maps the 6 request test classes → corpus issue codes.
The corpus also carries `O2_COMPAT`, `HEE`, `OFFGAS`, `FRACTURE` that the simple
request schema can't express.

- [ ] When `env_type` is `LOX_GOX`/`ENRICHED_O2`, add `O2_COMPAT` to the issue set
      for FLAMM gaps (the retriever's `_RELATED_ISSUES` already widens FLAM↔O2_COMPAT,
      so this is mostly belt-and-suspenders).
- [ ] When `env_type` is `HYDROGEN`, derive `HEE`.
- [ ] When habitable, ensure `OFFGAS`+`TOX` for TVS/TOX gaps.
  (Mirror `investigator._derive_issues_from_env`; consider extracting that logic to a
  shared module so service.py and the investigator can't drift.)

---

## 3. Confidence is honest but not yet *calibrated*

Current confidence = the retriever's envelope-scored relevance. That is honest
(no fabrication) but the envelope boost weights (+0.10 env, +0.05 O2, etc.) and the
base `confidence` column are heuristics, not validated against outcomes.

- [ ] **Calibration project**: take a held-out set of historic MUAs, run the
      retriever, and check whether "high relevance" precedents actually match the
      ground-truth disposition. Tune boosts / add a logistic calibration layer.
- [ ] Until calibrated, keep labelling the number as "retriever relevance," not
      "probability of approval." (Already done in `estimate_confidence` docstring;
      keep that discipline.)

---

## 4. Fold the v8 "80/20 review" UX into the v7 wizard (don't resurrect v8)

v8's only unique value was the section-by-section review model
(`PrecedentAttribution`, accept/edit/override/flag-for-testing). v7's wizard already
has review decisions, but confirm parity:

- [ ] Each rendered section exposes which precedent(s) informed it (per-section
      attribution), matching v8's `MUADraftSection.attributions`.
- [ ] `FLAG_FOR_TESTING` action exists in the v7 review flow.
- [ ] If anything is missing, port it into `mira.mua.v7` — do **not** rebuild a v8.

---

## 5. Consolidate the version sprawl

The module still carries `v6/`, `v7/`, plus `classifier/`, `synthesis/`,
`matchmaker/`, `precedent/`, `evidence/`, `historic_retrieval.py`, `mua_generator.py`,
and multiple routers (`mua.py`, `mua_v6.py`, `mua_v7.py`, `mua_v10.py`).

- [ ] Map which routers are actually mounted in the production FastAPI app.
- [ ] Deprecate/delete unmounted versions the same way v8 was removed (verify no
      imports first).
- [ ] Decide whether `mua_generator.py` (FAISS-era, now precedent-cleaned) and
      `historic_retrieval.py` are still needed now that `search_precedents_pg` is the
      retriever, or archive them under `v1_archive/`.
- [ ] Target: one public entrypoint (`generate_mua`) + one wizard router (`mua_v7`).

---

## 6. Zombie-MUA (dependency/revocation) detection

`investigator._check_dependencies` is inactive — `_MUA_DEPENDENCY_GRAPH` /
`_REVOKED_MUAS` are empty because the corpus has no parent-linkage column.

- [ ] Add a `parent_mua_number` / `superseded_by` column to `mua_precedents_v7`
      (new migration) and backfill from source PDFs where available.
- [ ] Populate the registry from that column so rejected/superseded precedents
      actually raise the existing `DependencyWarning`.

---

## 7. Tests to add (none exist for the new path)

- [ ] `tests/mua/test_service_grounding.py`: mock `search_precedents_pg` to return
      crafted `PGPrecedentResult`s; assert grounding, citations, CAUTION on rejected,
      and the standards-only / corpus-unavailable degradation branches.
- [ ] `tests/mua/test_family_inference.py` and `test_env_type_mapping.py`.
- [ ] An integration test (DB-gated, skip if no `MIRA_DB_URL`) hitting the real corpus.

---

## Quick reference — key files

| Concern | File |
|---|---|
| Public entrypoint (now grounded) | `mira/mua/service.py` |
| Real retriever (tiered + envelope) | `mira/mua/v7/pg_precedent_search.py` |
| Orchestrator | `mira/mua/v7/investigator.py` |
| 7-section draft (template + LLM polish) | `mira/mua/v7/draft_renderer.py` |
| Wizard router (the "80/20" workflow) | `mira/api/routers/mua_v7.py` (+ `_helpers`) |
| Corpus schema | `mira/mua/v7/migrations/001_create_mua_precedents_v7.sql` |
| Corpus loader | `mira/mua/v7/migrations/002_load_mua_precedents.py` |
