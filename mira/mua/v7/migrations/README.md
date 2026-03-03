# MUA v7 Migration Runbook

This folder contains the canonical migration/enrichment flow for `mua_precedents_v7`.

## Execution Order

1. `001_create_mua_precedents_v7.sql`
2. `002_load_mua_precedents.py`
3. `003_rename_table_to_v7.sql` (only if table naming is still legacy)
4. `004_backfill_traceability.py --apply`
5. `005_backfill_unknowns.py --apply`
6. `006_extract_temp_min.py --apply`
7. `007_backfill_umbrella.py --apply`
8. `008_enforce_traceability_constraints.sql`
9. `009_backfill_appendix_b_and_closure.py --apply`
10. `010_backfill_category.py --apply`
11. `011_audit_consistency.py` (read-only validation)
12. `012_backfill_determination_strict.py --apply`
13. `013_generate_pdf_audit_sample.py` (statistical sample generation)
14. `014_evaluate_pdf_audit_confidence.py` (CI + additional sample planning)
15. `015_auto_audit_pdf_sample.py` (deterministic pre-audit)
16. `016_run_pdf_audit_pipeline.py` (one-command sampler + auto-audit + confidence + queue)

## Why This Matters

- `002` loads structured v6 data quickly, but intentionally leaves enrichment fields sparse.
- `004` enforces PDF traceability by hydrating `source_hash` directly from raw files.
- `005/006/007` convert raw extracted text into searchable canonical fields.
- `008` makes traceability a hard DB constraint, so regressions fail fast.

## Verification Queries

```sql
-- Traceability completeness
SELECT COUNT(*) AS missing_hash
FROM mua_precedents_v7
WHERE source_hash IS NULL OR trim(source_hash) = '';

-- Remaining unknowns
SELECT
  COUNT(*) FILTER (WHERE material_family IS NULL) AS material_family_null,
  COUNT(*) FILTER (WHERE env_type IS NULL OR env_type = 'UNKNOWN') AS env_unknown,
  COUNT(*) FILTER (WHERE temp_min_f IS NULL) AS temp_min_null,
  COUNT(*) FILTER (WHERE COALESCE(is_umbrella, FALSE)) AS umbrella_true
FROM mua_precedents_v7;
```

## Report Artifacts

Python backfill scripts emit JSON reports into:

`mira/mua/v7/migrations/reports/`

Use these reports as run evidence for change-control and audit trails.

## One-Command PDF Audit

For high-volume manual review runs:

```powershell
py -3 mira/mua/v7/migrations/016_run_pdf_audit_pipeline.py `
  --pdf-root "C:\MIRA backup full\maptis-nlp\mira\data\mua_pdfs" `
  --population all `
  --confidence 0.95 `
  --margin 0.05 `
  --hash-policy warn
```

Outputs:
- sample CSV (`013_*`)
- auto-audited CSV (`*_auto.csv`)
- confidence report (`014_*`)
- manual review queue (`*_manual_queue.csv`)
- pipeline summary (`016_*`)

Use an existing sample (for example your 372-line CSV) without re-sampling:

```powershell
py -3 mira/mua/v7/migrations/016_run_pdf_audit_pipeline.py `
  --sample-csv "C:\BoundState\mira\mua\v7\migrations\reports\013_pdf_audit_sample_20260210T201543Z.csv" `
  --population-size 10355 `
  --hash-policy warn
```

## Claim Language (Use This)

Coverage run (`population=all`):
- Safe to say: "We audited sampled PDF coverage/readability and found no failures in the sample."
- Do not say: "We validated DB field correctness against PDFs."

v7 run (`population=v7`):
- Safe to say: "We audited sampled v7 traceability and deterministic consistency checks (hash-policy, determination/category rules)."
- Do not say: "We performed full semantic PDF re-extraction and field-level truth validation."
