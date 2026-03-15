# Phase 2 Deploy Gating Checklist

Purpose: make a "green deploy" mean more than `/health` returning `200`.

## Scope

Phase 2 builds on the Phase 1 runtime foundation:

- deploy from a clean git snapshot by default
- run changed-path-aware local checks before image build
- validate required runtime assets against the actual build root
- verify critical live routes after ECS reaches steady state
- verify protected routes with a real authenticated Cognito session
- run the AWS audit automatically as part of the deploy flow
- write deploy receipts with git/task/smoke evidence

## Deliverables

### 1. Clean-SHA Deploy Source

- [x] Default clean-worktree deploys to a git-archived snapshot of `HEAD`.
- [x] Resolve and print the exact git commit used for deploys.
- [x] Preserve `DEPLOY_GIT_REF=<sha>` for explicit clean-ref deploys.
- [x] Refuse dirty-worktree deploys unless `ALLOW_DIRTY_DEPLOY=1`.

Acceptance criteria:

- Non-dirty deploys always build from a reproducible git snapshot.
- The deploy log records the exact commit being shipped.

### 2. Build-Root Preflight

- [x] Run runtime asset validation against the actual deploy build root.
- [x] Fail before image build if required runtime packs are missing or drifted.

Acceptance criteria:

- A bad asset pack never survives long enough to build and push images.

### 3. Changed-Path Predeploy Checks

- [x] Select pytest targets from the actual changed-path set being deployed.
- [x] Always include the runtime foundation tests.
- [x] Run a frontend build when frontend sources are part of the changed set.

Acceptance criteria:

- Deploys fail before image build when the relevant local test slice or frontend build is broken.

### 4. Post-Deploy Smoke

- [x] Validate `/health` and `/api/health` for `{"status":"ok"}`.
- [x] Probe critical protected routes and treat `401/403` as healthy wiring.
- [x] Fail the deploy if critical routes return `404` or `5xx`.
- [x] Run an authenticated protected-route smoke using a disposable Cognito user.

Initial critical route set:

- `/api/tocr/ping`
- `/api/forge/ping`
- `/api/mp-plan/v2/ping`
- `/api/mua/v10/ping`
- `/api/oca/ping`
- `/api/mira/galvanic/ping`
- `/api/mira/fracture/ping`
- `/api/mira/h2/ping`

Acceptance criteria:

- A deploy cannot report success when a critical router is missing from the live runtime.
- A deploy cannot report success when protected routes are mounted but fail under a real authenticated session.

### 5. Automatic Audit

- [x] Run `scripts/aws/audit_mira_runtime_govcloud.sh` automatically after smoke passes.

Acceptance criteria:

- Every deploy leaves behind service, target health, and recent log visibility without a second manual step.

### 6. Deploy Receipts

- [x] Write a structured receipt after successful deploy.
- [x] Capture git SHA, task definitions, smoke results, and audit log path together.

Acceptance criteria:

- Every successful deploy leaves behind a machine-readable receipt showing what shipped and what verification passed.
