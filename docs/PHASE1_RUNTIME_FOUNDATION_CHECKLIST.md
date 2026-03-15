# Phase 1 Runtime Foundation Checklist

Purpose: eliminate the runtime drift and hidden local-state problems that have
caused recent AWS breakages.

## Scope

Phase 1 covers only the foundational work:

- one canonical backend app builder
- explicit runtime asset validation
- `.gitignore` cleanup for required assets

Everything else depends on these three items being correct first.

## Deliverables

### 1. Canonical Runtime

- [x] Create one shared FastAPI app factory for middleware, router mounting,
  health endpoints, and startup instrumentation.
- [x] Convert [mira/api/app.py](/mnt/d/BoundState/boundstate_mira/mira/api/app.py)
  into a thin wrapper over the shared factory.
- [x] Convert [mira/api/app_codex.py](/mnt/d/BoundState/boundstate_mira/mira/api/app_codex.py)
  into a thin wrapper over the shared factory.
- [x] Update tests and runbooks to treat the shared factory as the single
  runtime source of truth.
- [x] Retire `app_codex.py` as an independent runtime surface by reducing it
  to a thin compatibility wrapper over the shared factory.

Acceptance criteria:

- `app.py` and `app_codex.py` expose the same mounted route inventory.
- Router drift between entrypoints becomes impossible without changing the
  shared factory.
- Health endpoints and startup route logging are emitted from the same codepath.

### 2. Runtime Asset Manifest

- [x] Add a module-level required asset manifest for every runtime data-backed
  domain.
- [x] Start with TOCR, H2, and M&P Plan as mandatory Phase 1 coverage.
- [x] Validate required assets at startup and fail hard when they are missing.
- [x] Add a clean-checkout validation step that proves required assets are
  tracked and readable before deploy.

Acceptance criteria:

- Missing runtime packs raise startup errors instead of surfacing later as
  `404`, `500`, `UNKNOWN`, or empty guidance.
- Clean detached checkouts contain every required asset for TOCR, H2, and
  M&P Plan.

### 3. Gitignore Cleanup

- [x] Replace blanket runtime-data ignore rules with narrow patterns.
- [x] Explicitly allow required tracked runtime assets.
- [x] Audit current runtime packs for any file that exists locally but is not
  guaranteed to ship in a clean AWS build.

Known files already proving this risk:

- `mira/compliance/data/mprs_6016c.yaml`
- `sentinel/tocr/data/guidance.json`
- `mira/data/h2_evidence_merged.json`

Acceptance criteria:

- Required production assets are never hidden by broad ignore rules.
- A clean git snapshot is sufficient to reproduce the runtime data surface.

## Execution Order

1. Canonical app factory
2. Required asset manifest
3. `.gitignore` cleanup
4. Clean-checkout verification

## Out Of Scope For Phase 1

- deploy gating in the AWS script
- frontend auth-client migration away from the fetch shim
- branch policy cleanup
- rollback receipts and release governance

Those stay blocked until the runtime and asset foundations are stable.
