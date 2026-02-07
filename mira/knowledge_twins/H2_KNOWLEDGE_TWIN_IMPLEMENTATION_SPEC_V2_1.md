# H2 Knowledge Twin (Hydrogen Compatibility) – Implementation Spec v2.1

Goal
- Answer: “Can I use this material in this hydrogen environment?”
- Return: verdict + confidence + why + what would change the answer.
- Deterministic, evidence-first, auditable.

Non‑negotiables
- No “ALLOWED” without at least one PRIMARY_TEST evidence object that strongly matches the query envelope.
- Never silently extrapolate outside the evidence envelope. If we are extrapolating, the system must say so and downgrade the verdict.
- Separate missing inputs (gaps) from envelope mismatches (conflicts between query conditions and evidence conditions).
- Every claim must trace to EvidenceObject provenance or be labeled as a “guideline” and kept from upgrading the verdict.

---

1) Inputs

Minimum viable query
- material_name (string, required)
- environment:
  - phase (GH2, LH2, UNKNOWN)
  - pressure_mpa (float or None)
  - temperature_c (float or None)

Strongly recommended query fields
- condition (HeatTreatCondition enum) and/or heat_treatment (structured object)
- strength (yield_mpa, uts_mpa)
- product_form (bar/plate/forging/etc)
- weld_state (BASE_METAL, WELD_METAL, HAZ)
- loading_mode (STATIC/CYCLIC)
- has_notch (bool)

Options
- consequence_class: low | medium | high (drives conservatism when evidence conflicts)
- prefer_conservative: bool

---

2) Evidence model

The system reasons from EvidenceObject only.

EvidenceObject (unit of truth)
- evidence_id (unique)
- material_key (canonical ID)
- material_family (enum)
- heat_treatment (structured)
- environment (HydrogenEnvironment: phase, pressure_mpa, temperature_c)
- loading (LoadingState: mode)
- specimen_type (SMOOTH / NOTCHED / PRECRACKED)
- metric (MetricValue: NTS_ratio, RA_ratio, KIH_ratio, etc)
- hee_band (NEGLIGIBLE/SMALL/HIGH/SEVERE/EXTREME)
- grade:
  - PRIMARY_TEST (best)
  - SECONDARY_SUMMARY
  - GUIDELINE_STATEMENT (never upgrades verdict)
- extraction_confidence (0–1)
- provenance:
  - doc_id, doc_title, page, figure/table id, authors (as available)

Why this shape
- It maps cleanly to NASA/Sandia tables and to future ingestion from MAPTIS/MUA snippets.
- It keeps “facts” separate from scoring logic.

---

3) Decision pipeline

Step A: candidate retrieval
- Retrieve candidate EvidenceObject by material_key matching.
- For now: token overlap + substring fallback.
- Next: add explicit synonym table + UNS/spec-to-key mapping.

Step B: envelope scoring (per evidence)
- Compute per-dimension scores in [0,1].
- Dimensions (current): pressure, temperature, phase, loading, condition, notch, strength.
- Compute weighted average total score and apply a small penalty per missing input.

Pressure scoring rule (must be symmetric)
- Use absolute log-distance of pressure ratio:
  - d = abs(log10(query_p / evidence_p))
  - d <= 0.05 (~12%): 1.0
  - d <= 0.20 (~1.6x): 0.8
  - d <= 0.50 (~3.2x): 0.6
  - else: 0.3

Temperature scoring rule
- Cryogenic boundary at ~ −150°C is treated as a regime change.
- Crossing that boundary heavily penalizes the score.

Step C: “credible” evidence filter
- Keep evidence with envelope_match_score >= 0.4.

Step D: dominant evidence selection (conservative, without letting weak matches dominate)
- Evidence weight = envelope_score * grade_weight * extraction_confidence.
- Risk score = severity_rank(hee_band) * evidence_weight.
- Dominant evidence = max risk score (this is the evidence that drives the conservative floor).

Step E: rule gates
- R001: Severe/Extreme HEE with strong envelope match triggers NOT_RECOMMENDED.
- R002: HAZ weld state triggers a warning + qualification constraint.
- R003: Aged condition triggers warning only if no aged-specific evidence was found.
- R004: High strength triggers a max-strength constraint.

Step F: verdict assignment
- Base verdict floor comes from dominant evidence’s hee_band.
- Upgrade to ALLOWED only if:
  - best_score >= 0.8
  - no gaps
  - dominant band is NEGLIGIBLE or SMALL
  - at least one PRIMARY_TEST evidence with score >= 0.8

Additional guardrails
- If query is outside NASA envelope and dominant evidence is inside, treat as extrapolation: never emit ALLOWED.
- If conflicting evidence exists at similar envelope match (bands differ by >=2 ranks within 0.10 score), never emit ALLOWED.

Step G: response generation
- decision_summary: 3–6 sentences, includes dominant band and the main “why”.
- drivers: failure-mode explanations + evidence IDs.
- constraints: actionable constraints, not “be careful”.
- gaps: missing inputs the user could supply.
- mismatches: explicit condition mismatches between query and best evidence comparator.
- recommended_tests: what would close the gaps or resolve mismatches.
- evidence: top matched evidence objects.
- audit: match stats, rule triggers, confidence calculation.

---

4) Output contract

H2Response
- verdict: allowed | allowed_with_constraints | not_recommended | unknown
- confidence: 0–1
- decision_summary
- drivers[]
- constraints[]
- gaps[]
- mismatches[]
- recommended_tests[]
- evidence[]
- warnings[]
- audit (full traceability)

Interpretation rules
- allowed: strongly supported by primary data at matching conditions.
- allowed_with_constraints: usable, but condition-specific risks remain.
- not_recommended: data indicates high risk at matching conditions.
- unknown: insufficiently matched evidence.

---

5) Evidence ingestion plan (practical)

Phase 1: seed corpus (fast)
- Parse NASA/TM-2016-218602 (and similar) tables/figures into EvidenceObject rows.
- Include: material_key normalization, heat treatment description, pressure/temp, metric ratios.

Phase 2: scale corpus
- MAPTIS + MUAs: extract any explicit H2 test condition + metric data into EvidenceObject.
- Add a “material alias map” layer:
  - UNS
  - AMS spec
  - common synonyms (316L vs 316)

Phase 3: tighten retrieval
- Replace token overlap with:
  - canonical material registry
  - fuzzy match with explainable link to canonical key
  - family-based fallback only when explicitly marked as “family guidance” (never upgrades verdict)

---

6) Verification and tests

Unit tests (must)
- Pressure scorer symmetry and monotonicity:
  - score(p, p) == 1.0
  - score(p, 2p) == score(2p, p)
- Aged rule behavior:
  - R003 triggers only when query is aged and aged-specific evidence is absent
- Verdict guardrails:
  - query outside envelope + dominant evidence inside => cannot be ALLOWED
  - conflict => cannot be ALLOWED

Regression tests (recommended)
- Known 316 SS case returns allowed/allowed_with_constraints depending on envelope and evidence grade.
- Inconel 718 aged case returns not_recommended with R001 driver.

---

7) What’s intentionally not in v2.1

- Predictive inference for “similar alloys” (too risky without calibrated datasets).
- Universal HE susceptibility predictors used to upgrade verdict.
- Chemistry-based decomposition reasoning (belongs in PFAS-style engines, not here).

---

8) Files

- h2_knowledge_twin_v2_1.py
  - Patched reference implementation aligned to this spec.
- H2_KNOWLEDGE_TWIN_IMPLEMENTATION_SPEC_V2_1.md
  - This document.

Change log (v2.0 -> v2.1)
- Fixed pressure matching to use symmetric log10(p_query/p_evidence) distance (avoids negative-log artifacts below 1 MPa).
- Dominant evidence selection now uses severity_rank * evidence_weight so weak matches can’t dominate.
- Added explicit mismatches[] and stopped conflating mismatches with missing inputs (gaps).
- R003 (aged-condition) triggers only when aged-specific evidence is absent.
- Added ALLOWED guardrails for NASA envelope extrapolation and for conflicting evidence at similar envelope match.
