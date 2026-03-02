# MUA Rationale Proof Pack v1

## Purpose

Demonstrate, with reproducible artifacts, that MUA V10 rationales are:

1. Deterministic for the same inputs.
2. Traceable to classifier state (`flag_type`, `hazard_applies`, `classification_reason`, `rating_semantics`).
3. Free of unsupported precedent claims.

## Inputs

- Proof cases: `docs/mua_audit/rationale_proof_cases_v1.json`
- Evaluator: `scripts/run_mua_rationale_proof.py`

## Run

```bash
cd /mnt/d/BoundState/boundstate_mira
python3 scripts/run_mua_rationale_proof.py --allow-failures
```

Artifacts are written to a timestamped directory under:

- `reports/mua_rationale_proof/proof_run_<UTCSTAMP>/`

## Output Artifacts

- `proof_summary.json`: machine-readable full check results per case.
- `proof_summary.md`: concise summary for review boards.
- `case_results.csv`: full exported rows with rationale/disposition hashes.
- `adjudication_template.csv`: reviewer sign-off sheet with hash-locked text.

## What Is Checked

Per case:

- Expected classification (`mua_type`, `flag_type`, `category`, `hazard_applies`, `automatable`).
- Non-empty `classification_reason` and `rating_semantics` where applicable.
- Determinism across two independent runs.
- Rationale/disposition phrase anchors for template-sensitive cases.
- Unsupported precedent-claim guardrail:
  - If rationale says `prior approved`, a precedent object must exist.

## Acceptance Thresholds

Recommended release gate:

1. Deterministic rate: **100%**.
2. Total pass rate: **>=95%**.
3. Unsupported precedent-claim failures: **0**.
4. Any failed case must have either:
   - defect ticket, or
   - written waiver with engineering rationale.

## Human Review Workflow

1. Open `adjudication_template.csv`.
2. For each row, reviewer marks:
   - `reviewer_genuine_rationale` (yes/no)
   - `reviewer_traceable_claims` (yes/no)
   - `reviewer_notes`
3. Reviewer signs name and timestamp fields.
4. Final approved sheet is archived with `proof_summary.json`.

## Notes

- This proof pack validates rationale integrity for curated high-signal cases.
- It is intentionally deterministic and does not require frontier-model calls.
- If precedent DB is unavailable, precedent-related checks degrade gracefully.
