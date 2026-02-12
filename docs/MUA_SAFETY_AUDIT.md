# MUA Module Flight-Critical Safety Audit

Last updated: 2026-02-07
Audit method: 3-agent concurrent sweep (determination logic, evidence scoring, data integrity)

## The Question
> If this system were used in a flight-critical review tomorrow, what part would most likely cause an incorrect determination, and why?

---

## Answer: The Evidence Scoring Pipeline

**The most likely source of an incorrect determination is the uncapped semantic boost multiplication in the relevance scorer, combined with the absence of conflicting-evidence detection across sources.** These two flaws work in concert: irrelevant documents get inflated to HIGH confidence, and when they contradict direct test data, no alarm fires.

Specifically: `mira/MIRA_V2/src/relevance_scorer.py` applies stacked 1.5x-2.0x multipliers to any document containing safety keywords like "prohibited" — regardless of whether the document is actually about the queried material. A weak semantic match (0.55) can be boosted to 2.47, reported as HIGH relevance, and flow into a determination unchallenged. Meanwhile, the verdict engine (`mira/knowledge_twins/verdict_engine.py`) only examines the **single best-matching record** — if evidence sources disagree, no one is told.

---

## Full Findings by Severity

### CRITICAL (5 findings) — Could directly cause wrong flight determination

| # | Module | File | Issue |
|---|--------|------|-------|
| C1 | Semantic Boost | `mira/MIRA_V2/src/relevance_scorer.py:161-201` | Uncapped 2.0-3.0x score multipliers. Weak matches (0.55) boosted past HIGH threshold (0.68) via stacked keyword boosts. Irrelevant docs rank above relevant evidence. |
| C2 | H2 Envelope Scoring | `mira/knowledge_twins/scoring.py:44-220` | Missing pressure/temperature data defaults to 0.5 (neutral) instead of 0.0 (unknown). For H2 service, pressure is physics-critical (embrittlement ~ pressure²). Gap penalty is only 0.05/dimension with a floor of 0.1. |
| C3 | Verdict Engine | `mira/knowledge_twins/verdict_engine.py:233-247` | Hard-reject rules checked against ONLY `matched_records[0]`. If FAISS ordering changes, a D-rated record may or may not trigger reject. No consensus across multiple records. |
| C4 | Envelope Matching | `mira/api/routers/mua_v6.py:297-306` | `precedent_temp_min` never passed to `compute_envelope_overlap()`. Lower temperature bound silently bypassed. Material tested to -40F could be approved for cryogenic (-100F) use. |
| C5 | EPL Column Extraction | `mira/miul/v3/extract.py:114-140` | Vision model column identification has zero post-validation. If columns swap (find_no ↔ part_number), entire EPL loads with wrong material-to-part mappings. |

### HIGH (13 findings) — Degrades determination quality without obvious signal

| # | Module | File | Issue |
|---|--------|------|-------|
| H1 | No Conflict Detection | Multiple files | NO multi-source consensus check. MAPTIS test data can contradict BOK authority, and system averages them instead of flagging disagreement. |
| H2 | Silent Fallback | `mira/mua/v6/draft_generator.py:143-150` | When no precedents meet 0.40 relevance threshold, silently uses top 3 regardless of score. No warning propagated. |
| H3 | Alloy Family Matching | `mira/mua/v6/draft_generator.py:243-263` | Regex matches aluminum by first digit only (2xxx series). 2024-T4 and 2014 treated as equivalent despite very different fracture/corrosion behavior. |
| H4 | Stainless Steel Matching | `mira/mua/v6/draft_generator.py:256-261` | 300-series (austenitic) and 400-series (martensitic/ferritic) lumped together. 316L and 430 considered same family. |
| H5 | O2 Tolerance | `mira/mua/v6/draft_generator.py:217-220` | 5% absolute O2 tolerance accepts 25% (enriched) as matching 21% (ambient). Crosses NASA enrichment thresholds. |
| H6 | Authority Over-weighted | `mira/o2/policy_engine.py:292-320` | CLASS_A (human-rated): authority = 45% of score. Dominates actual test data (25%). Single test with any rating scores same as 10 tests. |
| H7 | Expired Ratings Included | `mira/miul/maptis_ratings.py:186-188` | Comment says "don't filter - we include expired data now". Currency flag added but no enforcement that downstream consumers check it. |
| H8 | MAPTIS Rating Fallback | `mira/mua/v6/maptis_test_data.py:155-182` | Unknown ratings (typos, legacy codes) fall back to returning first unknown value with no warning. |
| H9 | LLM Single Point of Failure | `mira/api/routers/mua_v6.py:351-370` | Entire rationale validation rests on one LLM call. If validator misinterprets O2 percentages, no secondary check catches it. |
| H10 | Evidence Eval Thresholds | `mira/pipeline/stages/evidence_eval.py:87-123` | Single semantic "mention" of material counts as sufficient evidence. Substring match only. |
| H11 | Unit Normalizer | `mira/nlp/unit_normalizer.py:89-113` | Unknown unit strings assumed to be base unit with only a WARNING log. "15 psi" misread as "15 kV/mm" silently accepted. |
| H12 | OCR Correction | `mira/miul/v3/ocr_correction.py:21-71` | Context-free string.replace() OCR corrections. "COMPOSITE-A2B6-PART" silently becomes "COMPOSITE-A286-PART". |
| H13 | Hybrid Mode Merge | `mira/miul/mua_parser_v6.py:442-487` | When text says "316 SS" and vision says "TEFLON", vision wins silently. No conflict logged. |

### MEDIUM (8 findings) — Reduces precision or creates ambiguity

| # | Module | Issue |
|---|--------|-------|
| M1 | Confidence hardcoded | Decision engine uses fixed 0.0/0.3/0.6/0.85 confidence by decision path, not evidence quality |
| M2 | Envelope 2/3 rule | Pressure (explosion risk) treated equal to temperature in dimension counting |
| M3 | Confidence 0.3 floor | "No approved precedents" and "conflicting precedents" both score 0.3 |
| M4 | Conflict severity | REJECTED precedent in less-severe environment triggers same warning as contradictory evidence |
| M5 | Weak scores unpenalized | FAISS similarity score 2.0 (weak) doesn't reduce confidence |
| M6 | Semantic band thresholds | 0.68/0.60/0.55 hardcoded "based on empirical MiniLM performance" with no revalidation |
| M7 | Pressure unit ambiguity | psi vs psia vs psig not validated or converted |
| M8 | Typo corrections | UNS corrections (A07075→A97075) logged as WARNING only, original value lost |

---

## Failure Scenario: How These Combine

**Scenario:** Engineer queries "Inconel 718 for 30% oxygen service at 3000 psi"

1. **FAISS search** returns documents about Inconel 718 in ambient air (21% O2) with base score 0.58 (LOW band)
2. **Semantic boost** sees "oxygen" + "prohibited" keyword in a doc about titanium → boosts to 1.74 (appears HIGH) **(C1)**
3. **O2 tolerance** accepts 21% precedent as matching 30% query (within 5%) **(H5)**
4. **Authority score** dominates at 45%, uses material family "NICKEL_ALLOYS" → +0.9 authority **(H6)**
5. **Missing pressure data** for precedent → scored 0.5 (neutral) instead of flagged **(C2)**
6. **No conflict detection** between the titanium-prohibition doc and the Inconel-718 test data **(H1)**
7. **Verdict engine** uses only the first FAISS result, which may or may not have the D-rating **(C3)**
8. **Confidence reported**: 0.85 (hardcoded for "no blocking factors") **(M1)**

**Result:** APPROVED at 85% confidence for an environment never tested, based on boosted irrelevant evidence, with contradictory data masked.

---

## Recommended Mitigations (Priority Order)

### Immediate (before any flight-critical use)
1. **Cap all relevance boosts at 1.0** — `mira/MIRA_V2/src/relevance_scorer.py`
2. **Pass `precedent_temp_min`** — `mira/api/routers/mua_v6.py:305`
3. **Replace 0.5 neutral defaults with 0.0** for missing critical dimensions — `mira/knowledge_twins/scoring.py`
4. **Implement multi-record consensus** in verdict engine — `mira/knowledge_twins/verdict_engine.py`

### Short-term (within sprint)
5. Replace regex alloy matching with lookup table (MAPTIS family data)
6. Add O2 enrichment threshold check (23.5% OSHA, 30% ignition critical)
7. Make expired-data flag mandatory for consumers
8. Add secondary validation gate for LLM rationale checks
9. Log and flag hybrid-mode extraction conflicts
10. Add EPL column validation (sequential find_no, part number format)

### Medium-term (next review cycle)
11. Derive confidence scores from evidence quality, not decision path
12. Weight envelope dimensions by criticality (pressure > temperature for O2)
13. Implement proper conflicting-evidence escalation with severity matching
14. Add audit trail for all OCR corrections and material normalizations
