# Repo Boundaries

Effective date: 2026-02-19
Status: Active
Last reviewed by: Codex (GPT-5), 2026-02-19

## Purpose

Prevent duplicated systems, cross-repo drift, and accidental implementation in the wrong codebase.

## Canonical Ownership

| Repo | Owns | Must Not Own |
|---|---|---|
| `D:\BoundState\boundstate_aegis` | AEGIS PFAS engines, AEGIS API routes, AEGIS data/config, SENTINEL-for-AEGIS features | MIRA product code, standalone GPTL service runtime |
| `D:\BoundState\mira-dev` | MIRA platform code (frontend/backend), MIRA workflows | AEGIS production modules, AEGIS route implementations |
| `D:\BoundState\boundstate_mira` | MIRA production codebase (if designated active) | AEGIS and SENTINEL service ownership without explicit migration decision |
| `D:\BoundState\mira-ui` | MIRA UI-only iteration/sandbox work | Backend/service domain ownership (AEGIS, GPTL, SENTINEL-DC) |
| `D:\BoundState\gptl` or `sentinel-main` | Standalone SENTINEL/GPTL service | AEGIS in-process route logic, MIRA product features |
| `D:\BoundState\sentinel_dc` | SENTINEL-DC defense compliance engine (current observed contents); final disposition pending Dr. Wilde decision | AEGIS SENTINEL monitoring ownership unless explicitly reassigned |
| `D:\BoundState\boundstate_athena` | ATHENA ingestion/indexing/extraction pipeline and ATHENA domain logic | AEGIS or MIRA product-specific route/business logic |
| `D:\BoundState\boundstate_core` | Shared libraries and platform utilities | Product-specific business logic for AEGIS, MIRA, or ATHENA |

## Non-Negotiable Rules

1. Build new AEGIS SENTINEL monitoring in `boundstate_aegis` only.
2. `mira-dev` cannot be used as the target for AEGIS implementation work.
3. Shared functionality must be versioned and imported from a shared package, never copy-pasted.
4. Cross-repo interaction must happen through explicit APIs/contracts, not direct source imports.
5. Every PR must declare `TARGET_REPO` and affected bounded context.

## Integration Contracts

1. AEGIS <-> SENTINEL/GPTL: API/event interface only.
2. MIRA <-> AEGIS: API interface only.
3. MIRA <-> SENTINEL/GPTL: API interface only.
4. No relative path imports that reach outside the current repository.

## Sentinel-main Disposition

1. `sentinel-main` remains a standalone SENTINEL/GPTL service codebase.
2. New SENTINEL-for-AEGIS in-process monitoring work is owned by `boundstate_aegis`, not `mira-dev` and not `sentinel-main`.
3. Any overlap between `sentinel-main` and AEGIS monitoring must be resolved through API contracts or a formal migration decision before implementation.

## Sentinel-DC Disposition

1. `sentinel_dc` currently appears to be a standalone product/service codebase (Defense Contractor Compliance workflow engine).
2. Final fate is explicitly decision-gated by Dr. Wilde: remain standalone, merge, or deprecate.
3. Until decided, no feature duplication between `sentinel_dc` and other SENTINEL codebases.

## Forbidden Patterns

1. Implementing the same feature in two repos in parallel without a migration plan.
2. Adding `aegis` production modules into `mira-dev`.
3. Adding MIRA product routes/UI into `boundstate_aegis` backend package.
4. Copying files from one repo to another to "move fast."
5. Treating `mira-ui` as a backend owner.
6. Treating root-level `engine/`, `exploratory/`, or `_sandbox/` as production owners.

## PR Checklist (Required)

1. Confirm this PR is in the correct target repo for the feature.
2. Confirm no duplicated implementation exists in sibling repos.
3. Confirm all cross-repo dependencies are API-level, documented, and versioned.
4. Confirm boundaries file was reviewed.

## CI Guardrails (Required)

1. Fail PR if forbidden directories/files appear in the wrong repo.
2. Fail PR if import scanning detects disallowed cross-boundary imports.
3. Require CODEOWNERS approval for boundary-touching changes.
4. Require architecture-checklist completion in PR template.

## Ownership Decision Rule

If ownership is unclear, do not code. Open a short architecture decision note that states:

1. Feature name
2. Proposed owning repo
3. Integration points
4. Why alternatives are rejected

## Immediate Decision for Current Work

SENTINEL continuous monitoring for AEGIS is owned by:

`D:\BoundState\boundstate_aegis`

Not owned by:

`D:\BoundState\mira-dev`

## Document Placement

1. Canonical copy lives in each repo root as `REPO_BOUNDARIES.md`.
2. A central architecture index may link to each repo's canonical file, but ownership rules are enforced from the repo-local file.

## Root-Level Directory Policy (`D:\BoundState`)

| Directory | Role | Policy |
|---|---|---|
| `engine/` | Legacy/prototype engine components | Non-canonical; changes require explicit migration target |
| `exploratory/` | Research and experiments | Non-production; no direct product ownership |
| `schema/` | Shared schema prototypes/artifacts | Treat as source material; canonical runtime schemas belong in owning repo |
| `packs/` | Authority/rule pack assets | Allowed shared asset staging; consuming service owns integration behavior |
| `_sandbox/` | Temporary staging, backups, experiments | Never a production source-of-truth |
