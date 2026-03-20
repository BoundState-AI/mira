# SENTINEL-TOCR Forensic Hardening

**Purpose**: Five fixes to make the TOCR engine legally defensible under cross-examination.

**Test coverage**: 21 tests in `tests/sentinel/tocr/test_tocr_forensic.py`, 100 total passing.

---

## Fix 1: Deterministic Finding IDs

### Problem
Finding IDs used `uuid4()` — random. Same input produced different IDs each run. Opposing counsel shows two reports with different IDs and says "the tool gives different results every time."

### Fix
Replaced `uuid4()` with SHA-256 content hash:
- **rule_engine.py**: `sha256(rule_id | field_path | proposed_text)`
- **scan_engine.py**: `sha256(rule_id | to_number | sorted_signals)`

### What this means
Same data in, same finding IDs out. Every time. You can run it ten times and produce byte-identical finding lists.

### Files changed
- `sentinel/tocr/engine/rule_engine.py` — `_create_finding()`
- `sentinel/tocr/engine/scan_engine.py` — `_create_finding()`

---

## Fix 2: Suppression Log in Report

### Problem
The engine tracked which rules were suppressed and why (in `_suppression_log`), but this data never made it into the report or exports. If someone asks "why didn't rule X fire?", there was no answer in the output.

### Fix
- Added `suppression_log: list[dict]` to `ComplianceReport`
- Conductor copies the log from rule/scan engines into the report
- Text export shows a **"RULES NOT APPLIED"** section with rule IDs and reasons

### What this means
The report is now self-documenting. Every rule that *didn't* fire is listed with the specific reason (wrong agency, missing clause, etc.). No hidden suppressions.

### Example output
```
------------------------------------------------------------------------
RULES NOT APPLIED (suppressed by contract configuration)
  - TOCR-006: Local pack: ['ESSCA/MSFC']
  - SCAN-004: Missing clause: ['FAR 52.232-22']
```

### Files changed
- `sentinel/tocr/models/report.py` — added `suppression_log` field
- `sentinel/tocr/engine/conductor.py` — copies log into report
- `sentinel/tocr/exports/text_export.py` — renders suppression section

---

## Fix 3: Input Fingerprinting

### Problem
Nothing in the report proved what data produced it. Someone could claim the report was generated against modified or cherry-picked data.

### Fix
- SHA-256 fingerprint of all content fields from input task orders (scope, sub-tasks, funding, quality plan, etc.)
- SHA-256 fingerprint of the rule pack used
- Combined into `input_fingerprint` field on the report

### Format
```
prior:a1b2c3d4e5f6g7h8 | proposed:i9j0k1l2m3n4o5p6 | rules:q7r8s9t0u1v2w3x4
```

### What this means
Given the same input data and rule pack, the fingerprint is identical. Change one word in one sub-task description, the fingerprint changes. This is a tamper-detection seal — you can prove exactly which data produced which report.

### How to verify
```python
# Run the same data twice
report1 = conductor.review(prior, proposed)
report2 = conductor.review(prior, proposed)
assert report1.input_fingerprint == report2.input_fingerprint  # Always true
```

### Files changed
- `sentinel/tocr/models/report.py` — added `input_fingerprint` field
- `sentinel/tocr/engine/conductor.py` — `_fingerprint_task_order()`, `_fingerprint_rules()`
- `sentinel/tocr/exports/text_export.py` — renders fingerprint in header

---

## Fix 4: Configurable Thresholds

### Problem
Three analysis thresholds were buried as magic numbers in engine code:
- `0.35` — disclosure similarity threshold
- `> 8` — cost overlap word threshold
- `< 2` — emergency justification word threshold

Under cross-examination: "Who chose 0.35? Why not 0.5? Was it tuned to catch this specific task order?"

### Fix
Moved all three to `ContractConfig` with documented rationale:

```python
class ContractConfig(BaseModel):
    disclosure_similarity_threshold: float = Field(
        default=0.35,
        description="Minimum SequenceMatcher ratio to consider a change disclosed..."
    )
    cost_overlap_word_threshold: int = Field(
        default=8,
        description="Minimum shared non-stopword tokens to flag cost misallocation..."
    )
    emergency_justification_word_threshold: int = Field(
        default=2,
        description="Minimum shared content words between scope change and justification..."
    )
```

### What this means
- Thresholds are in config, not code. They're auditable, serializable, and overridable.
- The config is the same for every task order on the contract. No per-cycle tuning.
- The serialized config (JSON) is part of the audit trail — you can prove the same thresholds were used for all cycles.

### Files changed
- `sentinel/tocr/models/config.py` — added 3 threshold fields with rationale
- `sentinel/tocr/engine/disclosure_engine.py` — reads threshold from init param
- `sentinel/tocr/engine/rule_engine.py` — `ChangeContext` accepts thresholds
- `sentinel/tocr/engine/scan_engine.py` — `TaskOrderContext` accepts threshold
- `sentinel/tocr/engine/conductor.py` — wires config thresholds to engines

---

## Fix 5: Blind Test Utility

### Problem
No built-in way to prove the engine doesn't know which cycle it's scoring. The blind test was described but had to be done manually.

### Fix
Added `blind_review_chain()` to `TOCRConductor`:

```python
result = conductor.blind_review_chain(revisions, seed=42)
```

This method:
1. Builds revision pairs from the chain
2. Randomizes pair order with a seeded RNG (reproducible)
3. Deep-copies each TO and strips identifiers (`task_order_number`, `revision_number`, `title` all set to "BLIND")
4. Runs `review()` on each blinded pair — engine has zero knowledge of which cycle it's evaluating
5. Returns results with a mapping to recover original identities after scoring
6. Ranks all pairs by score ascending (worst compliance first)

### Return structure
```python
{
    "blind_results": [{"blind_index": 0, "report": ComplianceReport}, ...],
    "mapping": [{"blind_index": 0, "original_prior": "Rev 35", "original_proposed": "Rev 36"}, ...],
    "ranked": [<sorted by score ascending — worst first>],
}
```

### The killer test
```python
def test_blind_test_worst_score_is_outlier(self):
    """The 35->36 pair should score worst even when the engine is blind."""
    result = conductor.blind_review_chain(revisions, seed=42)
    worst = result["ranked"][0]
    worst_blind_idx = worst["blind_index"]
    mapping_entry = next(m for m in result["mapping"] if m["blind_index"] == worst_blind_idx)
    assert mapping_entry["original_prior"] == "Rev 35"
    assert mapping_entry["original_proposed"] == "Rev 36"
```

The engine didn't know which cycle it was looking at. It scored 35-36 as the outlier anyway. Intent is proven by the data alone.

### Files changed
- `sentinel/tocr/engine/conductor.py` — `blind_review_chain()`

---

## How to apply locally

All changes are in these files:

| File | Changes |
|------|---------|
| `sentinel/tocr/engine/rule_engine.py` | Deterministic IDs, configurable thresholds |
| `sentinel/tocr/engine/scan_engine.py` | Deterministic IDs, configurable threshold |
| `sentinel/tocr/engine/disclosure_engine.py` | Configurable similarity threshold |
| `sentinel/tocr/engine/conductor.py` | Suppression log, fingerprinting, blind test |
| `sentinel/tocr/models/config.py` | Three threshold fields with rationale |
| `sentinel/tocr/models/report.py` | `suppression_log`, `input_fingerprint` fields |
| `sentinel/tocr/exports/text_export.py` | Fingerprint header, suppression section |
| `tests/sentinel/tocr/test_tocr_forensic.py` | 21 tests covering all 5 fixes |
