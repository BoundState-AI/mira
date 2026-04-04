# FORGE + IC Integration Execution Spec

## Goal

Build FORGE as the shared query/platform spine, build IC as the compiler and
ingestion layer that turns messy inputs into FORGEable artifacts, then
integrate them behind flags before any AWS rollout.

This plan explicitly rejects two long-term parallel cores.

## Architecture

- FORGE owns:
  - versioned chat/query contracts
  - cheap compiled-map router
  - capability-family read model
  - workspace summary and version pinning
  - provider abstraction and debug/admin split
- IC owns:
  - document ingestion
  - normalization and canonicalization
  - hybrid docs+DB compile
  - provenance and conflict-aware evidence preparation

## Execution Order

### 1. FORGE Shared Spine

Acceptance:
- One canonical response contract family for chat/query.
- Provider abstraction is the only runtime LLM boundary.
- Unsupported and partial states are explicit and test-covered.
- Workspace version is present in every contract.

### 2. IC Artifact Refactor

Acceptance:
- `compile()` returns explicit `compilation_id` and `workspace_version`.
- `query()` can target a specific compile artifact.
- No query path depends on implicit `last_*` state for correctness.
- Document evidence can be filtered by compilation scope.

### 3. IC Emits FORGE-Compatible Artifacts

Acceptance:
- IC compile outputs expose FORGE-compatible capability metadata.
- IC routes can return the same contract family as FORGE.
- Capability derivation does not require frontend-specific transforms.

### 4. Integrated Query Path Behind Flags

Acceptance:
- Docs-only and docs+DB flows can execute through the shared spine.
- IC hybrid evidence feeds the same query contract family.
- Legacy paths remain available behind flags until parity is proven.

### 4.5. Full-Build Gate Before AWS

No production deploys before this gate passes.

Required signoff:
- end-to-end local compile -> artifact -> query works
- contract tests pass
- regression/eval harness passes
- unsupported/out-of-coverage UX behaves correctly
- provenance/version pinning is present in answers
- debug/admin responses are server-gated
- rollout flags and rollback path are documented
- no known blocker is deferred to production

Validation runner:
- `/mnt/d/BoundState/boundstate_mira/scripts/run_forge_ic_45_gate.sh`

Predeploy checklist:
- docs compile path returns `compilation_id`, `workspace_version`, `workspace_summary`, and `capability_families`
- upload compile path returns the same artifact metadata
- artifact lookup survives process restart via canonical store
- v2 status/capabilities/artifact/query surfaces succeed for docs and hybrid workspaces
- version mismatch returns `409`
- rejected queries surface `status=rejected`
- legacy `/ic/chat/query` and `/ic/capabilities` are explicitly compatibility-only
- FORGE UI can switch between v2 and legacy IC query paths via `VITE_FORGE_IC_V2`
- no AWS deploy until all of the above passes

### 5. AWS Rollout

Acceptance:
- staged flag rollout only
- canary validation on integrated paths
- rollback hooks verified before cutover

## Current Implementation Slice

This change set starts step 2 and part of step 3:
- compilation-scoped IC artifacts
- compilation-tagged document records and chunks
- document evidence filtering by artifact scope
- IC query routes that can execute by `compilation_id`
- FORGE-compatible capability-family projection for IC workspaces
- FORGE-compatible workspace summary generation for IC compile artifacts
- IC v2 endpoints:
  - `/ic/v2/status`
  - `/ic/v2/capabilities`
  - `/ic/v2/chat/query`
  - `/ic/v2/chat/stream`
- FORGE standalone proxy support for the new IC v2 surfaces

It does not yet complete the integrated FORGE+IC query contract migration.

Additional progress in the current build:
- canonical IC artifact records are now persisted in the canonical store and reloadable after restart
- active-module routing now resolves through artifact scope instead of whichever compile happened last
- standalone FORGE upload responses now carry IC artifact metadata
- standalone FORGE frontend queries IC through the artifact-aware v2 contract by default
- legacy IC endpoints are kept, but are explicitly marked compatibility-only and deprecated
