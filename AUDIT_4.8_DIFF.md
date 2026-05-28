# MIRA Audit Reconciliation — DIFF
## Date: 2026-05-28
## Auditor: Claude Opus 4.8
## Inputs
- **Blind pass:** `AUDIT_4.8_BLIND.md` (this session, against current `HEAD`)
- **Prior report:** the previous audit report produced last session (Claude Opus 4.7). It was never committed to disk; its full text exists in conversation history and is reconciled here from that source. Prior finding IDs (C1–C10, I1–I28, A1–A17) are referenced as published.

## How to read this
Each prior finding is bucketed: **(a) RESOLVED**, **(b) STILL OPEN**, **(c) FALSE POSITIVE on review**. A separate section lists **(d) NEW** findings the blind pass caught that the prior audit missed. The three explicitly-requested verifications (C2/C3/C4) are called out first.

---

## Priority verification: C2, C3, C4

| Prior finding | Status | Evidence at current HEAD |
|---|---|---|
| **C2 — silent exception swallows** | **OPEN** | `mira/bsmh/service.py:643, :657, :673` are still `except Exception: pass` (plus `:591` intent, `:691` lineage). No logging added. Blind B-C1 reproduces it independently. |
| **C3 — Sonnet hallucination risk** | **PARTIAL** | A NEW verdict-mismatch guard now exists — `response_formatter.py:253-257` raises if Sonnet's `VERDICT_EXACT:` label ≠ deterministic verdict (`_extract_reported_verdict` `:207-216`). This closes the *verdict-flip* vector. The *numeric-evidence fabrication* vector remains OPEN: no post-generation reconciliation of test/MUA counts against the payload (`:443`). Blind B-C3. |
| **C4 — false health endpoint** | **OPEN** | `app_factory.py:197-205` still returns `{"status":"ok"}` unconditionally; `Dockerfile:16-17` still curls `/health`; no `/ready` vs `/live` split; startup validation checks env-var presence only. Blind B-C4. |

**Net:** C2 and C4 are unaddressed. C3 is materially de-risked on the verdict axis but the evidence-fabrication axis — the one most likely to mislead a NASA engineer — is still open.

---

## (a) Prior findings now RESOLVED (with fixing code/commit)

- **I17 — GovCloud Bedrock region defaulted to `us-east-1`.** → **RESOLVED (with new caveat).** `llm_provider.py:38` adds `_DEFAULT_SONNET_MODEL_GOVCLOUD` and `:66-67` returns it when region starts with `us-gov-`. Region-aware resolution landed in commits `1161fec "harden runtime auth, rate limits, and db safety"` and `3677c85 "Implement multi-worker scaling and durable runtime state"`. **Caveat carried into NEW-1:** the `LLM_SONNET_MODEL` env override is checked *before* the region branch (`:56-58`), so a misconfigured override can still route GovCloud onto the commercial partition.
- **I6 / I9 (partial) — unsafe None handling and unbounded numeric coercion in scoring.** → **PARTIALLY RESOLVED.** `rules_engine.py:27-31` introduces `_safe_int` (used `:185-200`), landed under `baceec4 "fix(defensive): specific exceptions + bounds checking in safety paths"`. This removes the crash/`or 0` fragility the prior audit flagged. Still open: distinguishing "absent" vs "zero" (Blind B-I5) and user-input envelope bounds (Blind B-I3).
- **A-tier magic-number/intent documentation gaps** → **RESOLVED.** `0dc78f8 "docs(intent): add WHY comments to all flagged magic numbers"`.

## (b) Prior findings STILL OPEN

| Prior | Title | Current evidence |
|---|---|---|
| C1 | Bedrock calls unprotected (timeout/backoff/circuit breaker) | `llm_provider.py:170-178` — still no timeout/try/except/retry. Blind B-C2. |
| C2 | Silent exception swallow | `service.py:643/657/673`. Blind B-C1. |
| C3 | Sonnet hallucination (evidence axis) | `response_formatter.py:443`, no numeric validation. Blind B-C3. |
| C4 | Health endpoint no-op | `app_factory.py:197-205`. Blind B-C4. |
| C5 | File-upload ITAR endpoints middleware-only | `bom.py:42-45`, `miul.py:66-70`, `:244-248`. Blind B-C5. |
| C6 | Dockerfile runs as root; base not digest-pinned | `Dockerfile` — verified **no USER directive**. Blind B-C6. |
| C7 | No CI/CD / pre-commit / lockfile | No `.github/workflows/`, no `.pre-commit-config.yaml`, no lockfile present. |
| C8 | `python-jose` on the JWT hot path | `cognito.py:20-30` still imports `from jose import …`; still in requirements. |
| C9 | No observability (correlation IDs, metrics) | grep: no request-ID/EMF/prometheus. Blind B-I6, B-I7. |
| C10 | Postgres dev-credential fallback only gated in prod | `core/db_config.py` `require_production_credentials()` still keyed on `MIRA_ENV=production`. |
| I1 | (see false-positive list) | — |
| I2 | No request-level deadline on `/query` | `bsmh.py:26-29`. Blind B-I1. |
| I3 | Bouncer retry without backoff | `bouncer.py:633-645`, `:574-592`. Blind B-I2. |
| I8 | Material constraints not validated vs query | `service.py:546-547` fields populated, never checked. Blind B-I3. |
| I15 | CORS localhost origins unconditional | `app_factory.py:96-114`. Blind B-I9. |
| I16 | X-Forwarded-For trusted without proxy validation | `cognito.py:274-280`. Blind B-A2. |
| I26/I27 | Logging hygiene (rules_applied / raw key logging) | not addressed; compounded by orphaned logging config (NEW-3). |
| A5 | No logout / token revocation | no revocation path in `cognito.py`. |

## (c) Prior findings that look like FALSE POSITIVES on review

- **I1 — "DB connection not rolled back on exception."** The blind pass verified `service.py:422-550` uses try/finally `conn.close()` and the queries are **read-only SELECTs** — there is no open write transaction to roll back. The prior "missing rollback" concern was a non-issue; the only real residual is that an exception during row processing is swallowed by C2 (a different finding). Downgrade to non-finding.
- **I23 — "boto3 client created per-request."** Not substantiated at current HEAD: the Bedrock client is constructed in provider `__init__` (`llm_provider.py:132/229/295` resolve a default model at construction), not per call. Whether a provider is re-instantiated per request depends on caller caching, which the prior audit did not demonstrate. Re-classify as **unverified**, not a confirmed finding.
- **C3 severity framing (partial).** The prior report treated material-identity hallucination and evidence hallucination together. The blind pass confirms identity is strictly DB-bound (cannot be invented) and that a verdict guard now exists — so the "the LLM's word stands" framing overstated the current verdict risk. The genuine residual is narrower: numeric-evidence fabrication. Not a false positive, but a scope correction.

---

## (d) NEW findings the blind pass caught that the prior audit MISSED

- **NEW-1 (IMPORTANT) — GovCloud model routing override bypass.** `llm_provider.py:56-58` consults `LLM_SONNET_MODEL` before the `us-gov-` region branch; `response_formatter.py:446-452` and `service.py:765` add further overrides. A commercial model ID in any of these silently defeats the region-aware default the prior audit assumed would protect GovCloud. ITAR/FedRAMP exposure. *(The prior I17 noted the region default but not this override path.)*
- **NEW-2 (ADVISORY→IMPORTANT) — JWT `verify_aud` disabled.** `cognito.py:303` `options={"verify_aud": False}`, compensated by a manual `client_id` check (`:312-314`). Functionally sound but non-standard and not flagged by the prior auth review. Recommend `audience=` so the library enforces it.
- **NEW-3 (IMPORTANT) — Central logging config is orphaned.** `mira/utils/logging_config.py:511-565` defines env-tiered, structured logging and `initialize_logging()`, but it is never imported under `mira/api/`. Production therefore logs at Python defaults (WARNING+, unstructured), so INFO breadcrumbs never reach CloudWatch — invisible until an error. The prior audit assumed logging existed but flowed through these helpers.
- **NEW-4 (IMPORTANT) — Lineage build swallow fabricates a synthetic lineage ID.** `service.py:691` bare-excepts `DecisionLineageBuilder().build(...)` and falls back to `lineage_id = f"bsmh-{uuid4().hex[:12]}"`. A failed build silently yields a fabricated audit ID, breaking end-to-end GovCloud traceability — distinct from C2's *search* swallows.
- **NEW-5 (CRITICAL-adjacent) — Wrong-material match without intent cross-check.** Even though materials are DB-bound, a Sonnet-parsed candidate (`service.py:564`) that happens to LIKE-match a *different* real material (e.g., "Inconel" when the user asked "Hastelloy X") is presented with no verification that the retrieved designation matches the user's original request. The prior audit's C3 framed hallucination as fabrication; this is mis-binding to a real-but-wrong record.
- **NEW-6 (ADVISORY) — Auth/ITAR audit logging is fire-and-forget over blocking boto3.** `audit.py:104-159` `put_log_events` un-awaited from middleware; AUTH_FAILURE/ITAR-deny events can be dropped under CloudWatch throttling — a compliance-trail gap the prior audit did not surface.

---

## Bottom line

The team has made real, verifiable progress since the prior audit: **region-aware GovCloud model resolution (I17), defensive numeric coercion (I6/I9), and a Sonnet verdict-mismatch guard** are all live and credited above. However, **8 of 10 prior CRITICALs remain open** (C1, C2, C4, C5, C6, C7, C8, C9; C3 partial, C10 unchanged), and the blind pass surfaced **six new findings** — most notably the GovCloud model-override bypass (NEW-1), the orphaned logging config (NEW-3), and synthetic-lineage / wrong-material-binding integrity gaps (NEW-4, NEW-5). The procurement-readiness verdict is unchanged from the prior audit: **not ready until the CRITICAL set is closed**, with the silent-failure trio (C2 + C4 + the C3 evidence axis) as the highest-leverage fixes for NASA decision correctness.
