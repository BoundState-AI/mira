# Phase 3 Scaling Plan: MIRA to 50+ Concurrent Users

**Date:** 2026-03-31
**Author:** Claude Opus 4.6 + Dr. Joseph Wilde
**Status:** Approved for implementation
**Architecture:** BSMH (Bouncer-Sonnet-MIRA-Haiku), PostgreSQL-backed, no FAISS

---

## Executive Summary

MIRA currently runs as a single ECS Fargate task with a single uvicorn worker,
storing all session state in process-local Python dicts and ephemeral filesystem.
This plan externalizes state to DynamoDB, adds horizontal scaling behind the ALB,
and hardens operational readiness for 50+ concurrent users.

**Key architectural advantage:** The move from FAISS to BSMH/PostgreSQL eliminates
per-worker ML model memory (~400MB each), making workers lightweight and I/O-bound.
This halves infrastructure cost versus the FAISS baseline.

---

## BSMH Query Cost Model

Each BSMH query flows through 4 stages:

| Stage | Model | Latency | Cost/call | Role |
|-------|-------|---------|-----------|------|
| Bouncer | **Haiku** | ~200ms | ~$0.00003 | Domain gate (cheap, fast) |
| Parser | **Sonnet** | ~800ms | ~$0.003 | Intent extraction (the real work) |
| Rules | **PostgreSQL** | ~10ms | $0 | Deterministic rule evaluation |
| Formatter | **Haiku** | ~300ms | ~$0.00005 | Answer grounded in DB results |

**Per-query cost:** ~$0.003 (1 Sonnet + 2 Haiku)
**At 50 users × 20 queries/day:** ~$3/day Bedrock, ~$90/month

---

## Inventory of In-Memory State (Must Externalize)

| Location | Variable | Content |
|----------|----------|---------|
| `mira/miul/session_endpoints.py:64-70` | `_sessions`, `_session_parts`, `_session_files` | MIUL sessions + binary files |
| `mira/mp_plan/session_manager.py:56` | `_sessions` dict + file persistence | MP Plan sessions |
| `mira/api/routers/oca_systems.py:52` | `_systems` | OCA system assemblies |
| `mira/mua/v7/session.py:230` | `_sessions` | MUA v7 sessions |
| `mira/api/routers/mua_v7.py:86` | `_investigation_progress` | Ephemeral progress |
| `mira/chat/router.py:68` | `_session_store` (500-cap) | Chat engine context |
| `mira/mua/matchmaker/session.py` | Disk-backed | Matchmaker sessions |
| `mira/miul/production/session.py:34` | File-based (`C:/BoundState/temp/`) | MIUL v4 extraction results |

**Safe to keep process-local** (read-only caches):
- `_PACK_CACHE` / `_AUTHORITY_CACHE` (guidance — static JSON files)
- `_MEM_CACHE` (condition resolver — PostgreSQL-backed cache)
- `_sequence_tokens` (audit — per-CloudWatch-stream)

---

## DynamoDB Single-Table Design

**Table:** `mira-sessions` (on-demand capacity, ~$1/month)

| Key | Pattern | Example |
|-----|---------|---------|
| PK | `MODULE#<module>` | `MODULE#mp_plan` |
| SK | `SESSION#<id>` | `SESSION#93fe25a6` |
| GSI1PK | `USER#<username>` | `USER#jwilde` |
| GSI1SK | `MODULE#<mod>#SESSION#<id>` | `MODULE#miul#SESSION#abc` |

**Attributes:**
- `data` — Pydantic `.model_dump(mode="json")`
- `ttl` — Unix epoch for DynamoDB TTL auto-deletion
- `owner` — Cognito username
- `version` — Optimistic concurrency control

**TTL by module:**

| Module | TTL |
|--------|-----|
| chat | 1 hour |
| investigation_progress | 30 minutes |
| miul_extraction | 24 hours |
| oca_systems | 7 days |
| mp_plan, mua_v7, matchmaker | 30 days |

**Large objects (>400KB):** Store in S3 (`mira-session-blobs-govcloud`),
DynamoDB item holds S3 pointer.

---

## 7 Steps, 3-Week Rollout

### Step 0: Infrastructure (Day 1, no code)
**Size: S**

Hard requirements — all must exist before code ships:

1. **DynamoDB table** `mira-sessions` in GovCloud (on-demand capacity)
2. **S3 bucket** `mira-session-blobs-govcloud`
3. **RDS Proxy** — **hard requirement**, not optional. Without it, auto-scaling
   to 4 tasks hits 100 PG connections with zero headroom. Create in GovCloud VPC,
   point at existing RDS. Update ECS `POSTGRES_HOST` to proxy endpoint.
   Cost: ~$0.015/hr per vCPU.
4. **IAM policies** on ECS task role for DynamoDB + S3 + RDS Proxy
5. **Readiness endpoint** `GET /health/ready` — returns 200 only when:
   - PostgreSQL pool has ≥1 live connection
   - Authority pack cache is warm
   - Bedrock client can instantiate
   Point ALB health check at `/health/ready` instead of `/health`.
6. **Second ALB target group** `mira-prod-chat-tg` for SSE/chat stickiness
   (see Step 6).
7. Enable `pg_stat_statements` on RDS for query profiling under load.

---

### Step 1: Session Store Abstraction Layer
**Size: L | 3-4 days | No dependencies**

Create `mira/core/session_store.py`:

```
class DynamoSessionStore:
    def __init__(self, table_name, module_name, ttl_seconds, s3_bucket=None)
    async def put(session_id, data: dict, owner: str) -> None
    async def get(session_id) -> Optional[dict]
    async def delete(session_id) -> bool
    async def list_by_user(username, limit=50) -> list[dict]
    async def list_by_module(limit=100) -> list[dict]
    async def put_large_blob(session_id, key, data: bytes) -> None  # S3 overflow
    async def get_large_blob(session_id, key) -> Optional[bytes]
```

- Use `aioboto3` for async DynamoDB (fits existing async FastAPI)
- `MIRA_SESSION_BACKEND` env var: `"memory"` (dev) or `"dynamodb"` (prod)
- `InMemorySessionStore` fallback for local dev (no DynamoDB needed)

**Testing:** Unit tests with moto. Integration test with DynamoDB Local.
Verify round-trip serialization for every Pydantic session model.

---

### Step 2: Migrate 7 Session Stores (parallelizable)
**Size: L | 5-7 days | Depends on Step 1**

Each follows the same pattern: replace the global dict with `DynamoSessionStore`,
verify Pydantic round-trip, keep local fallback for dev.

| Sub-step | Module | Files | Size |
|----------|--------|-------|------|
| 2a | MIUL sessions | `mira/miul/session_endpoints.py` (3 dicts, binary files → S3) | M |
| 2b | MP Plan | `mira/mp_plan/session_manager.py` (dict + file I/O) | M |
| 2c | OCA Systems | `mira/api/routers/oca_systems.py` | M |
| 2d | MUA v7 | `mira/mua/v7/session.py` + `mira/api/routers/mua_v7.py` | M |
| 2e | Chat | `mira/chat/router.py` (500-cap becomes unnecessary) | S |
| 2f | Matchmaker | `mira/mua/matchmaker/session.py` | S |
| 2g | MIUL Production | `mira/miul/production/session.py` (hardcoded Windows path) | M |

**Testing per module:** Create session → retrieve from a different store instance
(simulating different worker) → verify data integrity. Use moto for unit tests.

---

### Step 3: Gunicorn + Uvicorn Workers
**Size: S | 1 day | Depends on Step 2**

Dockerfile CMD:
```
gunicorn mira.api.app:app -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8080 --workers ${GUNICORN_WORKERS:-5} \
  --timeout 120 --graceful-timeout 30 \
  --max-requests 1000 --max-requests-jitter 50
```

Without FAISS/sentence-transformers, each worker is ~150-200MB (not ~600MB).
On a 4096MB task, **5 workers** fit comfortably.

| Setting | With FAISS (old) | With BSMH (new) |
|---------|-----------------|-----------------|
| Memory per worker | ~600MB | ~150-200MB |
| Max workers on 4096MB | 2-3 | **5** |
| Bottleneck | CPU (embeddings) | **I/O (Bedrock + PG)** |

**CRITICAL PREREQUISITE:** Steps 1-2 must be complete. Multiple workers with
in-memory dicts = split-brain session loss.

---

### Step 4: Bedrock + PostgreSQL Backpressure
**Size: M | 2-3 days | Can run in parallel with Steps 1-3**

#### 4a. Bedrock Semaphores

Create `mira/core/bedrock_semaphore.py`. Gate at the provider level in
`mira/providers/llm_provider.py` so ALL callers share one pool.

**Semaphores are per-process, not fleet-wide.** Set conservatively:

| Env var | Default | Fleet-wide (10 processes) |
|---------|---------|--------------------------|
| `MIRA_BEDROCK_SONNET_CONCURRENCY` | **3** | ~30 |
| `MIRA_BEDROCK_HAIKU_CONCURRENCY` | **6** | ~60 |
| `MIRA_BEDROCK_VISION_CONCURRENCY` | **2** | ~20 (MIUL only) |

Haiku is cheap/fast enough for a higher per-process cap. Sonnet is the
bottleneck — 3 per process × 10 processes = 30 fleet-wide, which leaves
headroom under Bedrock account limits.

#### 4b. PostgreSQL Connection Pool

| Scenario | Workers | Tasks | Pool/worker | Total |
|----------|---------|-------|-------------|-------|
| Current | 1 | 1 | 10 | 10 |
| Phase 3 | 5 | 2 | 5 | 50 |
| Phase 3 auto-scaled | 5 | 4 | 5 | 100 |

Set `MIRA_DB_POOL_MAX_CONNECTIONS=5`. RDS Proxy (Step 0) absorbs connection
spikes — the proxy pools hundreds of app connections to a smaller PG backend pool.

#### 4c. Async Batch Inserts for Write-Heavy Tables (committed deliverable)

`classification_trace` and `fc_query_log` are append-only audit tables. At
50 users × queries/min × 3 BSMH stages logging per query = hundreds of
inserts/minute.

**Implementation:**
- Accumulate rows in a per-process list
- Flush every **500ms or 50 rows** (whichever first) via `asyncio.create_task`
- Non-blocking to the request path
- Acceptable data loss: last ≤500ms of trace rows on process crash
  (safety-critical decisions are committed synchronously in the rules engine)

**Files:** `mira/core/batch_writer.py` (new), integrated into
`mira/bsmh/fracture_engine.py` and BSMH rules stage.

---

### Step 5: SQS Queue for Long-Running MIUL Extractions
**Size: L | 3-4 days | Depends on Steps 2g, 4**

MIUL extraction (5-15 min Sonnet Vision) blocks the HTTP thread. Move to async:

1. `POST /miul/extract` → enqueue to SQS `mira-extraction-tasks`, return 202
2. Worker polls SQS, runs 3-phase extraction, writes results to DynamoDB
3. Frontend polls `GET /miul/extract/{id}/status` (reads DynamoDB)

**SQS config:** Standard queue, 900s visibility timeout, DLQ after 3 retries.

**Note:** BSMH queries are fast (1 Sonnet + 2 Haiku + PG ≈ 1-2s). They do NOT
need SQS. Only MIUL extraction needs async offloading.

---

### Step 6: Scale ECS to Multiple Tasks
**Size: M | 1-2 days | Depends on Steps 2, 3**

#### Task Definition

| Setting | Value | Rationale |
|---------|-------|-----------|
| CPU | 1024 | I/O-bound (BSMH), not CPU-bound |
| Memory | 4096 | No ML models in memory |
| Workers/task | 5 | ~200MB each, fits in 4096 |
| Desired count | 2 (start), auto-scale to 4 | 10 workers handles 50 users with 2x headroom |

#### Auto-Scaling

- Target: 60% CPU utilization
- Min: 2 tasks, Max: 4 tasks
- Scale-in cooldown: 300s

#### SSE/Chat Session Affinity

ALB stickiness is OFF for all routes (DynamoDB handles state). **Exception:**
chat SSE streams will break on reconnect to a different task.

**Fix:** Path-based ALB rule:
- `/api/chat/*` → `mira-prod-chat-tg` with **cookie stickiness** (1hr duration)
- All other paths → `mira-prod-be-8080-tg` with **no stickiness** (round-robin)

Requires second target group created in Step 0.

#### New Environment Variables

```json
{"name": "MIRA_SESSION_BACKEND", "value": "dynamodb"},
{"name": "MIRA_DYNAMODB_TABLE", "value": "mira-sessions"},
{"name": "GUNICORN_WORKERS", "value": "5"},
{"name": "MIRA_BEDROCK_SONNET_CONCURRENCY", "value": "3"},
{"name": "MIRA_BEDROCK_HAIKU_CONCURRENCY", "value": "6"},
{"name": "MIRA_BEDROCK_VISION_CONCURRENCY", "value": "2"},
{"name": "MIRA_DB_POOL_MAX_CONNECTIONS", "value": "5"},
{"name": "MIRA_RATE_LIMIT_ENABLED", "value": "true"},
{"name": "MIRA_RATE_LIMIT_REQUESTS", "value": "40"}
```

---

### Step 7: Enable Rate Limiting
**Size: S | 1 day | Depends on Step 6**

Per-process rate limiting (existing `mira/api/rate_limit.py`). With 10
processes (2 tasks × 5 workers), effective fleet limit ≈ 400 req/min.

```
MIRA_RATE_LIMIT_ENABLED=true
MIRA_RATE_LIMIT_REQUESTS=40        # per process per window
MIRA_RATE_LIMIT_WINDOW_SECONDS=60
```

Per-process is approximate but sufficient at 50 users. True fleet-wide
coordination (DynamoDB atomic counter) is a Phase 4 item if needed.

---

## Deployment Rollout (Zero-Downtime)

| Week | What Ships | Rollback |
|------|-----------|----------|
| **Week 1** | Step 0 (infra), Step 1 (abstraction), Step 4 (semaphores + batch writer) | Revert code, no data impact |
| **Week 2** | Step 2 (all migrations) with `MIRA_SESSION_BACKEND=memory` then flip to `dynamodb`. Step 3 (gunicorn). | Set env var back to `memory` |
| **Week 3** | Step 6 (scale to 2 tasks + chat stickiness), Step 7 (rate limiting), Step 5 (SQS for MIUL) | Scale back to 1 task + single uvicorn |

**Rollback at any phase:**
- Week 1: Revert image tag
- Week 2: `MIRA_SESSION_BACKEND=memory` (instant, users lose active sessions)
- Week 3: `desired-count 1`, revert gunicorn to uvicorn

---

## Parallelization (2 Engineers)

```
Engineer A: Step 1 → 2a, 2b, 2c, 2d → Step 3 → Step 6
Engineer B: Step 4 → 2e, 2f, 2g      → Step 5 → Step 7
```

**Critical path:** Steps 1 → 2 → 3 → 6 ≈ 10-12 days

---

## Cost Model

| Component | Monthly Cost |
|-----------|-------------|
| ECS (2 tasks × 1024 CPU / 4096 MB) | ~$75 |
| Bedrock (Sonnet + Haiku, 50 users) | ~$90 |
| DynamoDB (on-demand) | ~$1 |
| RDS Proxy | ~$11 |
| S3 (session blobs) | <$1 |
| **Total** | **~$178/month** |

Versus FAISS baseline: ~$300/month (2048 CPU / 8192 MB tasks needed).

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| PG connection exhaustion at 4 tasks | Low | High | RDS Proxy (hard req in Step 0) |
| `classification_trace` write contention | Medium | Medium | Async batch inserts (Step 4c) |
| Bedrock throttling under load | Medium | Medium | Per-process semaphores (Step 4a) + quota increase request |
| OCA sessions exceed 400KB DynamoDB limit | Medium | Low | S3 overflow in Step 1 |
| SSE reconnect hits wrong task | Medium | Medium | Chat path stickiness (Step 6) |
| Memory pressure with 5 gunicorn workers | Low | Medium | Profile in staging; reduce to 4 if needed |
| Session loss during memory→DynamoDB cutover | Low | High | `MIRA_SESSION_BACKEND` env var toggle |
| ALB 60s timeout kills MIUL extractions | High | High | SQS (Step 5); interim: increase ALB timeout to 300s |
| Fresh task serves 500s before cache warm | Medium | Medium | `/health/ready` probe (Step 0) |

---

## Out of Scope (Phase 4 Candidates)

- Fleet-wide distributed rate limiting (DynamoDB atomic counters)
- PgBouncer or connection multiplexing beyond RDS Proxy
- Multi-region failover
- WebSocket replacement for SSE
- Session migration tooling (backfill old sessions into DynamoDB)
