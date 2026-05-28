# MIRA Production Readiness Audit — BLIND PASS
## Date: 2026-05-28
## Auditor: Claude Opus 4.8
## Method: Independent audit of current `HEAD` (branch `claude/mira-audit-zW9XT`). No prior audit report consulted during this phase. Every finding is anchored to a verified current `file:line` with a concrete failure scenario. Findings that turned out to be handled correctly are recorded as such.

---

## Executive Summary

This blind pass audited the current production code across six focus areas: silent failure modes, error handling, health/readiness signal honesty, model-routing correctness (Sonnet hallucination exposure), authentication/authorization, observability, and data integrity. The codebase shows **controlled-degradation discipline** (template/heuristic fallbacks, a verdict-mismatch guard, multi-factor ITAR checks, RS256-restricted JWT verification, region-aware model resolution) but retains several production-blocking gaps.

**Tally: 6 CRITICAL, 9 IMPORTANT, 7 ADVISORY.** The critical cluster is unchanged in character from what one would expect of a fast-moving pre-procurement system: (1) silent DB/retrieval exception swallows that make "database down" indistinguishable from "no data"; (2) unprotected Bedrock calls (no timeout, no backoff); (3) Sonnet synthesis can fabricate *numeric evidence* even though the verdict label is now guarded; (4) the `/health` endpoint is a static stub that will keep a dead container in the ALB pool; (5) file-upload ITAR endpoints protected only by path-prefix middleware; (6) container runs as root. **Verdict: NOT production-ready for expanded/procurement deployment until the CRITICAL items are closed.** Several items the prior generation of this system would have flagged are now demonstrably improved (region-aware GovCloud model resolution, `_safe_int` coercion, a verdict-mismatch guard) and are credited below.

---

## CRITICAL Findings (🔴)

### B-C1. Silent DB/retrieval exception swallows
**Evidence:** `mira/bsmh/service.py:643`, `:657`, `:673` — three consecutive `except Exception: pass` blocks wrapping `_db_batch_search(...)` for candidate-material, material-key, and material-family searches. Also `:591` (intent guardrail) and `:691` (lineage build) swallow broadly.
**Failure scenario:** Postgres is unreachable (network partition, revoked creds, lock contention). All three searches raise and are silently discarded; `materials` stays empty; the pipeline returns `VERDICT_EXACT: INSUFFICIENT_DATA`. A NASA engineer asking "Is 316L compatible with LOX?" cannot tell whether 316L has no test data or the database simply failed — and may commission redundant qualification testing for a material MAPTIS already covers. No log line is emitted at the swallow site.
**Fix:** Replace each `except Exception: pass` with `except Exception as exc: LOGGER.warning("<path> search failed: %s", exc, exc_info=True)` and surface a `retrieval_error_detail` in `sonnet_metadata` so the failure mode is honest.

### B-C2. Bedrock `converse()` has no explicit timeout and no retry/backoff
**Evidence:** `mira/providers/llm_provider.py:170-178` — `self._client.converse(...)` is called inside `bedrock_limiter_sync("sonnet")` with `inferenceConfig` for tokens/temperature only; no `timeout`, no try/except, no exponential backoff.
**Failure scenario:** During Bedrock degradation a single call blocks for the boto3 default (~60s) while holding one of the 6 default Sonnet semaphore slots. A burst of queries exhausts all slots; subsequent requests queue until the gunicorn 120s worker timeout (`Dockerfile:21`) kills them. A `ThrottlingException` propagates unhandled. The engineer sees a 502/504 with no typed cause.
**Fix:** Wrap in `botocore.exceptions.ClientError` handling; pass an explicit per-call timeout; retry `ThrottlingException`/`ServiceUnavailableException` with exponential backoff + jitter (cap ~3); emit typed errors.

### B-C3. Sonnet synthesis can fabricate numeric evidence (verdict label is guarded; evidence is not)
**Evidence:** Guard present — `mira/bsmh/response_formatter.py:253-257` raises `RuntimeError` if Sonnet's `VERDICT_EXACT:` label (`_extract_reported_verdict`, `:207-216`) disagrees with the deterministic `decision.verdict`. **Gap:** the synthesis prompt receives the evidence as `json.dumps(payload, ...)` (`:443`) and there is **no post-generation validation of numeric claims** — test counts, MUA precedent counts, ages.
**Failure scenario:** Payload says `total_tests=0, mua_count=25` and verdict `CONDITIONAL`. Sonnet writes "316L shows 45 direct hydrogen compatibility tests…" and still emits `VERDICT_EXACT: CONDITIONAL`. The verdict-match guard passes; the fabricated "45 tests" reaches the engineer, who relies on it for a flight-hardware decision.
**Fix:** Post-generation validator that extracts integers/claims from the answer and reconciles them against the evidence struct; below a confidence floor or with zero materials, bypass Sonnet and return the deterministic template (`:148-190`).

### B-C4. `/health` is a static stub — dead containers stay in the ALB pool
**Evidence:** `mira/api/app_factory.py:197-205` — `/health` and `/api/health` both `return {"status": "ok"}` unconditionally. `Dockerfile:16-17` HEALTHCHECK curls `/health` only. No `/ready` / `/live` split (grep: none). Startup validation (`app_factory.py:236, 250` → `_validate_runtime_environment`) checks env-var presence only — no TCP to Postgres, no Bedrock call, no JWKS fetch.
**Failure scenario:** Bedrock IAM role revoked post-deploy. `/health` returns 200; ALB keeps the target healthy; every query fails at inference. Combined with B-C1's silence, the failure is both invisible to ops and smoothed-over to users.
**Fix:** Add `/health/ready` that does a 5s-timeout Bedrock stub call and `SELECT 1`; return 503 on failure and point the container HEALTHCHECK at it; keep `/health/live` for liveness.

### B-C5. ITAR file-upload endpoints rely solely on path-prefix middleware
**Evidence:** `mira/api/routers/bom.py:42-45` (`/convert-to-miul`), `mira/api/routers/miul.py:66-70` (`/extract-dt`), `:244-248` (`/enrich`) — none declare `Depends(require_itar_user)`. Protection is entirely from `ITAR_PATH_PREFIXES` middleware (`mira/api/auth/cognito.py:75`, enforced `:459-474`).
**Failure scenario:** `ITAR_PATH_PREFIXES` is cleared/misconfigured, or a route mount path changes, or middleware ordering is edited — any one flips these to unauthenticated ITAR-controlled data ingest. No second line of defense at the handler.
**Fix:** Add explicit `Depends(require_itar_user)` to all upload handlers (defense-in-depth) and validate `Content-Type == application/pdf`, not just the filename extension.

### B-C6. Container runs as root; base image not pinned by digest
**Evidence:** `Dockerfile` — verified **no `USER`/`useradd`/`adduser` directive**; process runs as UID 0. Base is `python:3.11-slim` (mutable tag, not a `@sha256:` digest); single-stage `COPY . .` leaves pip/build artifacts in the final image.
**Failure scenario:** An RCE in a native dependency (pdfplumber/pymupdf/FAISS) executes as root inside the container — a CIS-Docker / GovCloud least-privilege violation. Tag drift makes two builds a week apart non-reproducible for FedRAMP evidence.
**Fix:** Add a non-root user + `USER`; pin base to digest; adopt a multi-stage build.

---

## IMPORTANT Findings (🟡)

### B-I1. No request-level deadline on `/query`
**Evidence:** `mira/api/routers/bsmh.py:26-29` — `query_bsmh` simply `await run_bsmh_query(request)`; no `asyncio.timeout(...)`. **Fix:** wrap in `async with asyncio.timeout(45):` returning a typed 504.

### B-I2. Bouncer JSON-retry loops have no backoff/jitter
**Evidence:** `mira/bsmh/bouncer.py:633-645` (Haiku) and `:574-592` (local LLM) loop `for attempt in range(retries+1)` with zero delay between attempts. **Failure:** if invalid-JSON is caused by transient throttling, back-to-back retries hit the same congestion, then degrade to the weaker heuristic parser. **Fix:** exponential backoff + jitter.

### B-I3. Operating temperature/pressure never validated against material limits
**Evidence:** `mira/bsmh/service.py:546-547` populates `use_temp_min_c`/`use_temp_max_c` on each row, but neither `rules_engine.py` nor `response_formatter.py` reference them. User inputs are unit-converted without bounds at `service.py:110-115` (`float(pressure_psi)`, `float(temperature_f)`).
**Failure:** "aluminum at 5000 °F" converts to 2760 °C; the retrieved alloy rated to ~260 °C is scored purely on test counts/heritage and may return CONDITIONAL/COMPATIBLE for an impossible service envelope. **Fix:** add an envelope check in `_classify_material`; downgrade to INCOMPATIBLE/CONDITIONAL on breach; bound user inputs via Pydantic validators.

### B-I4. GovCloud model routing can be silently overridden onto the commercial partition
**Evidence:** `mira/providers/llm_provider.py:46-68` — `resolve_model("sonnet")` checks `LLM_SONNET_MODEL` **first** (`:56-58`) and returns it before the `us-gov-` region branch (`:66-67`). Callers add further overrides: `response_formatter.py:446-452` (`BSMH_SONNET_BEDROCK_MODEL`), `service.py:765` (`BSMH_SONNET_MODEL`).
**Failure:** GovCloud deploy with `BEDROCK_REGION=us-gov-west-1` but `LLM_SONNET_MODEL=us.anthropic.claude-sonnet-4-5-…` (copy-pasted from commercial config) routes ITAR-bearing prompts to the commercial Bedrock partition — a FedRAMP/ITAR breach with no guardrail. **Fix:** at startup, reject a commercial model ID when the region is `us-gov-*`.

### B-I5. Silent numeric coercion masks MAPTIS linkage failures
**Evidence:** `mira/bsmh/rules_engine.py:27-31` (`_safe_int`), used at `:185-200`. `total_tests`/`mua_count` default to `0` on any coercion failure; `latest_test_year` is squashed to `None` when 0.
**Failure:** a partial/failed SQL join returns `total_tests=None` for a material that actually has 15 H₂ tests; it scores as untested (`test_component=0`, `rules_engine.py:151-157`) and the verdict degrades to CONDITIONAL — the engineer may reject a qualified material. **Fix:** distinguish "absent" from "zero"; log a data-integrity event when a critical field is missing.

### B-I6. No correlation/request ID across pipeline stages or into logs
**Evidence:** grep across `mira/api` finds no `X-Request-ID`, `request_id`, `correlation`, or `contextvars.ContextVar`. Middleware stack (`app_factory.py:250-267`) adds none.
**Failure:** under concurrency, Bouncer/parse/synthesis log lines from different requests interleave with no shared key; a Bedrock 5xx logs its own request ID, unlinked to the caller. Root-causing a prod incident is guesswork. **Fix:** request-ID middleware via `ContextVar`, propagated into every log record and the response.

### B-I7. No request/cost/latency metrics emitted
**Evidence:** grep finds no `prometheus`, `put_metric_data`, EMF, or statsd in the API layer. `LLMResponse` (`llm_provider.py:76-84`) captures `input_tokens`/`output_tokens` but nothing aggregates, budgets, or alerts on them. **Failure:** no p50/p99 latency, no per-model token spend, no Bedrock error-rate SLI; a runaway loop over a large material set can burn significant Bedrock spend invisibly. **Fix:** CloudWatch EMF for `{stage, latency_ms, input_tokens, output_tokens, model_id, status}`.

### B-I8. Central logging config is orphaned — API runs at default level, unstructured
**Evidence:** `mira/utils/logging_config.py:511-565` defines per-environment levels and `initialize_logging()`, but grep shows **no import of it anywhere under `mira/api/`**. Routers use bare `logging.getLogger(__name__)`. **Failure:** production logs fall back to Python's default (WARNING+), non-JSON, no NASA compliance filter, so INFO-level pipeline breadcrumbs never reach CloudWatch. **Fix:** import/apply `logging_config` in the API entrypoint.

### B-I9. CORS allows localhost origins unconditionally (incl. production)
**Evidence:** `mira/api/app_factory.py:96-114` — `_build_cors_origins()` always seeds `http://localhost:{8080,8081,5173,3000}` + `127.0.0.1:8080`; wildcard is correctly rejected (`:109`) but localhost is not environment-gated. **Failure:** a VPN-connected developer running an SSH tunnel (`ssh -L 8080:localhost:8080 prod`) gets browser CORS access to prod as if it were the prod UI; amplifies a compromised-dev-account scenario. **Fix:** gate localhost origins behind `MIRA_ENV != "production"`.

---

## ADVISORY Findings (🟢)

### B-A1. JWT `verify_aud` disabled, compensated by manual `client_id` check
`mira/api/auth/cognito.py:303` sets `options={"verify_aud": False, ...}`; `:312-314` manually rejects on `client_id` mismatch. Functionally equivalent to audience verification but non-standard/less auditable. **Fix:** pass `audience=config["client_id"]` and let the library verify (RFC 7519 §4.1.3). *(Positive: algorithms restricted to RS256 `:301`, issuer verified `:302`, `token_use=="access"` enforced `:308-310`, `exp` verified by default.)*

### B-A2. `X-Forwarded-For` trusted without proxy validation
`mira/api/auth/cognito.py:274-280` takes the first XFF hop unconditionally for audit IPs; also in `rate_limit.py`. Behind GovCloud ALB this is normally safe, but direct exposure/misconfig enables audit-log IP spoofing. **Fix:** trust XFF only from configured proxy CIDRs.

### B-A3. Exception strings leak into user-facing responses
`mira/bsmh/service.py:865`, `:915`/`:928`, `:1072` embed `str(exc)` in `BSMHQueryResponse.error` — can surface DB host/driver details. **Fix:** generic client message; full detail to logs only.

### B-A4. `/api/query/health` leaks internal state
`mira/api/routers/hybrid_query.py:267-307` returns `database`, `semantic_search`, `db_url_configured`. Low-risk (booleans, no secrets) but unnecessary surface for an authenticated diagnostic. **Fix:** gate behind admin or trim.

### B-A5. Auth/ITAR audit logging is fire-and-forget over blocking boto3
`mira/api/auth/audit.py:104-159` (`put_log_events`) is invoked un-awaited from middleware; under CloudWatch throttling, AUTH_FAILURE/ITAR-deny events can be dropped — a compliance-trail gap. **Fix:** durable/awaited emission with retry.

### B-A6. No timeout on the formatter Sonnet call
`mira/bsmh/response_formatter.py:456-469` calls `llm_complete(...)` without `timeout_s`. Lower impact (final stage, template fallback exists) but should fail fast. **Fix:** `timeout_s=30`.

### B-A7. Missing-material notice depends on Sonnet's exact wording
`mira/bsmh/response_formatter.py:193-204` skips prepending the "not found in MAPTIS evidence" notice if a similar phrase already appears (case-insensitive substring match). If Sonnet phrases it differently the deterministic notice may be suppressed. **Fix:** prepend deterministically whenever `primary_materials` is empty, regardless of answer text.

---

## Verified-Correct (not findings)

- **Material identity cannot be hallucinated into existence.** `service.py:631-674` only presents materials returned by `_db_batch_search`; a hallucinated candidate with no DB match yields `INSUFFICIENT_DATA` (`:895-902`), not a synthetic material. *(Residual risk B-C3/your-intent-match noted separately.)*
- **DB connection lifecycle is correct.** `service.py:422-550` uses try/finally `conn.close()`; queries are read-only so no rollback is required — not a leak.
- **Verdict-mismatch guard works** (`response_formatter.py:253-257`) — Sonnet cannot flip the deterministic verdict.
- **Bedrock concurrency gating** (`bedrock_semaphore.py`) prevents unbounded parallel Bedrock calls.
- **Region-aware GovCloud model default exists** (`llm_provider.py:38, 66-67`) — correct when env is not overridden (see B-I4).
- **Security headers, RS256 JWT, multi-factor ITAR, prod docs-disable, wildcard-CORS rejection** all present and correct (`app_factory.py:118-130, 241-248`; `cognito.py:220-227, 301-310`).

---

## Metrics
- Focus areas: 6 (silent failures, error handling, health honesty, model routing/hallucination, auth, observability, data integrity)
- Files verified at current HEAD: `mira/providers/llm_provider.py`, `mira/bsmh/{service,bouncer,response_formatter,rules_engine,material_resolver}.py`, `mira/api/routers/{bsmh,bom,miul,hybrid_query}.py`, `mira/api/app_factory.py`, `mira/api/app.py`, `mira/api/auth/{cognito,audit}.py`, `mira/api/rate_limit.py`, `mira/utils/logging_config.py`, `mira/core/bedrock_semaphore.py`, `Dockerfile`, `Procfile`
- Findings: **22** (🔴 6 / 🟡 9 / 🟢 7)
- Remediation estimate: CRITICAL ≈ 2.5 eng-weeks; IMPORTANT ≈ 3 eng-weeks; ADVISORY ≈ 1.5 eng-weeks.
