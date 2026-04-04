# MIRA Release Readiness Audit

Date: 2026-04-03  
Scope: Repo/code audit against the current live Git state  
Focus: Release readiness for scaled AWS deployment, multi-user correctness, runtime drift, and operational risk

## Summary

MIRA is in substantially better shape than it was before the recent scaling work. The major multi-user refactors are in place:

- Shared session storage exists and is wired into the core interactive modules
- OCA public routing regressions were fixed
- Guidance runtime assets are validated at startup
- Bedrock concurrency gating is in place across the active runtime paths that were audited
- MIUL v4 now has a code path for queue/worker execution with shared artifact storage instead of assuming local task disk
- Gunicorn, ECS sizing, autoscaling hooks, and rate-limit enablement are in repo

The repo is close to release-ready, but not fully there for scaled AWS operation. The remaining risks are concentrated in MIUL deployment topology and the durable shared-state layer.

### Strengthened finding

The shared-session problem is stronger than a simple "could fall back to memory" concern:

- In live GovCloud, the configured MIRA Postgres proxy host does not currently exist
- So durable runtime state is not merely misconfigured; the production endpoint/proxy is missing
- The real blocker is therefore: no valid MIRA Postgres endpoint/proxy plus any remaining fail-open behavior

Separately:

- localhost fallbacks remain Medium only while they stay out of active production runtime paths
- items 6-8 are watch items, not must-fix blockers for the next hardening slice

## Overall Assessment

Current recommendation: `Go for continued staging/hardening, not full scaled production rollout yet`

Reason:

1. Core app surfaces are in good shape
2. The remaining blockers are narrow and well understood
3. The highest-risk remaining items are operational, not broad architectural unknowns

## Must Fix Before Scaled AWS Deploy

Note: items 1-3 below are now addressed in repo code and deploy wiring, but they still require staged AWS validation before this can be considered closed operationally.

### 1. MIUL worker must be deployed and validated as a first-class service

Severity: High  
Impact: MIUL jobs will either pile up in SQS with no consumer or silently fall back to in-process execution

Evidence:

- Queue-backed MIUL v4 extraction is routed from [mira/api/routers/miul.py](../mira/api/routers/miul.py)
- Worker entrypoint exists in [mira/miul/worker.py](../mira/miul/worker.py)
- Deploy wiring now registers a dedicated MIUL worker task and ECS service in [scripts/aws/redeploy_mira_runtime_govcloud.sh](../scripts/aws/redeploy_mira_runtime_govcloud.sh)

Why this matters:

- If queue is enabled without a worker service, jobs never complete
- If queue is left disabled, the API keeps doing long-running extraction work locally, which defeats the point of the worker split

Proposed fix:

1. Add a dedicated MIUL worker ECS task/service to [redeploy_mira_runtime_govcloud.sh](d:/mira-main/scripts/aws/redeploy_mira_runtime_govcloud.sh)
2. Run `python -m mira.miul.worker`
3. Give the worker the same shared state env vars as the backend plus queue permissions
4. Set worker desired count explicitly, likely `1` to start
5. Add a worker health/log verification step to the deploy receipt or smoke path

Suggested acceptance criteria:

- A submitted MIUL v4 extraction transitions `queued -> extracting -> complete`
- Queue depth drains under load
- Worker logs are visible in CloudWatch
- API tasks no longer need to run extraction inline in production

### 2. MIUL inputs and v4 session artifacts must stay off task-local disk

Severity: High  
Impact: MIUL is not truly node-independent across separate ECS tasks unless storage is shared

Evidence:

- Shared MIUL input and session artifact storage now lives in [mira/miul/production/storage.py](../mira/miul/production/storage.py)
- MIUL v4 session state now routes through that shared storage layer in [mira/miul/production/session.py](../mira/miul/production/session.py)
- API staging and queue submission now happen in [mira/api/routers/miul.py](../mira/api/routers/miul.py)
- Worker downloads staged inputs and runs extraction in [mira/miul/worker.py](../mira/miul/worker.py)

Why this matters:

- This only works if API and worker share disk, such as EFS
- It is not safe if they run on independent ephemeral filesystems

Proposed fix:

1. Move uploaded MIUL PDFs to S3 before enqueue
2. Send S3 object references in the queue message instead of `temp_dir`
3. Have the worker download inputs to local scratch space
4. Clean up local scratch after processing
5. Keep status/results in the shared session store as they are now

Suggested acceptance criteria:

- API and worker can run on different ECS tasks with no shared filesystem
- Redelivered jobs can still access input documents
- Worker cleanup no longer risks deleting the only copy of inputs

### 3. Shared session store must fail closed in production

Severity: High  
Impact: Multi-worker/task state sharing can fail without making the app obviously unhealthy

Evidence:

- Shared-session factory and startup validation now live in [mira/core/session_store.py](../mira/core/session_store.py)
- Chat DB resolution remains in [mira/chat/db/connection.py](../mira/chat/db/connection.py)
- Session-manager fallback behavior is controlled in [mira/chat/db/session_manager.py](../mira/chat/db/session_manager.py)
- App startup now validates the requested session backend in [mira/api/app_factory.py](../mira/api/app_factory.py)

Why this matters:

- In development, fail-open to memory is convenient
- In scaled production, fail-open to memory can break cross-worker continuity while the service still looks healthy
- In live GovCloud today, there is also no valid MIRA Postgres proxy/endpoint, so durable runtime state is blocked at the infrastructure layer, not just by fallback code

Proposed fix:

1. Make production session backend fail closed
2. If `MIRA_SESSION_BACKEND=postgres` in production and Postgres init fails, abort startup
3. Keep memory fallback only for explicit `memory` mode or non-production dev/test paths
4. Emit a startup health signal that makes the backend state mode obvious in logs

Suggested acceptance criteria:

- Production cannot boot with an unavailable shared session backend
- Session mode is unambiguous in startup logs
- There is no silent downgrade from shared persistence to process-local persistence

## Safe To Defer Briefly

### 4. Some active DB helper paths still default to `localhost`

Severity: Medium  
Impact: Misconfiguration can be harder to diagnose, and some secondary paths may drift toward local defaults instead of failing fast

Evidence:

- [`pg_precedent_search.py`](d:/mira-main/mira/mua/v7/pg_precedent_search.py#L137)
- [`pg_precedent_search.py`](d:/mira-main/mira/mua/v7/pg_precedent_search.py#L605)
- [`maptis.py`](d:/mira-main/mira/precedent_engine/utils/maptis.py#L86)
- Core DB config resolves host from env with localhost fallback in [`db_config.py`](d:/mira-main/mira/core/db_config.py#L239)

Proposed fix:

1. Keep localhost defaults in clearly dev-only code only
2. In active runtime modules, prefer central DB config helpers
3. In production mode, fail fast when required DB env is absent

Qualification:

- This stays Medium only if these paths are outside the active production request path
- If any of them are exercised by the deployed runtime, raise this to High immediately

### 5. MIUL still has older non-v4 routes with temp-file and local-path behavior

Severity: Medium  
Impact: Not necessarily blocking if those routes are not central to the current rollout, but they remain operational debt

Examples:

- Multiple temp-dir based flows in [miul.py](d:/mira-main/mira/api/routers/miul.py)
- Old persistent export paths like `C:/BoundState/temp` in [miul.py](d:/mira-main/mira/api/routers/miul.py#L841) and [miul.py](d:/mira-main/mira/api/routers/miul.py#L1828)
- Legacy builder/session path in [session_endpoints.py](d:/mira-main/mira/miul/session_endpoints.py#L64)

Proposed fix:

1. Decide which MIUL surfaces are still officially supported
2. Mark old routes as legacy if they are not in active rollout scope
3. Bring remaining active routes onto the same storage/runtime rules as v4

## Watch In Production

These are watch items for rollout tuning, not must-fix blockers for the next hardening slice.

### 6. Per-process rate limiting is acceptable, but should be monitored

Status: Acceptable for current rollout  
Evidence: [rate_limit.py](d:/mira-main/mira/api/rate_limit.py)

Notes:

- Limiter is process-local by design
- This is acceptable for current scale, but effective fleet-wide behavior depends on task and worker counts
- Health and ping routes are exempt, which is the right shape for operations

What to watch:

- Burst behavior under load balancer distribution
- Whether protected-route throttling feels too strict or too loose in practice

### 7. Bedrock gating should be validated under real traffic

Status: Code path looks materially better  
Risk: Operational tuning rather than architectural uncertainty

What to watch:

- Whether current concurrency caps are too low for user experience
- Whether they are still too high for AWS throttling in practice
- Whether multi-worker memory footprint is acceptable with real concurrency

### 8. Gunicorn/ECS runtime should be verified with commit-to-image traceability

Status: Repo wiring exists  
Risk: Deploy drift rather than code shape

What to watch:

- Ensure running image tag maps to the intended Git commit
- Confirm task definition env vars match repo assumptions
- Confirm guidance/runtime assets are present in the live image

## Recommended Fix Order

1. Add MIUL worker ECS deployment path
2. Remove MIUL shared-filesystem dependency by moving input blobs to S3
3. Make shared session backend fail closed in production
4. Clean up active runtime localhost DB fallbacks
5. Re-audit MIUL legacy route surface and deprecate or align remaining paths

## Recommended Verification After Fixes

### Repo-level verification

- Targeted MIUL queue/worker tests
- Shared-session startup failure tests for production mode
- Regression tests for chat, OCA, MUA v7, MP Plan, Matchmaker

### AWS verification

- Deploy backend, frontend, and MIUL worker services
- Submit MIUL v4 extraction and confirm status transitions
- Confirm queue depth drains and CloudWatch logs show worker activity
- Confirm cross-worker session continuity by scaling backend tasks above 1
- Confirm task definition env vars match intended runtime settings

## Bottom Line

MIRA is in good shape. The repo reflects a large amount of hardening work, and it shows. The remaining problems are not broad “the architecture is wrong” problems; they are mostly concentrated in the last mile of MIUL operations and one fail-open behavior in the shared session backend.

That is a good place to be. The path to deploy-readiness is now short and specific.
