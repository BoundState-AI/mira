# MIRA CI/CD Plan

**Status:** Proposal
**Owner:** BoundState Platform Team
**Last updated:** 2026-04-29

This document proposes a CI/CD pipeline for the MIRA monorepo (Python FastAPI
backend + React/Vite frontend) targeting **AWS GovCloud (US-West) —
`us-gov-west-1`**. There is no `.github/` workflow directory yet, so this plan
is greenfield and intended to be rolled out in phases.

**Deployment surface (target):**
- Backend API: ECS Fargate behind an internal ALB, in a GovCloud VPC.
- Frontend: S3 static site fronted by an ALB / API Gateway (CloudFront is
  *not* in GovCloud — see §7).
- Container registry: ECR private in `us-gov-west-1`.
- Auth: Cognito User Pool in `us-gov-west-1` (already wired in code).
- Database: RDS PostgreSQL in `us-gov-west-1`.
- Secrets: AWS Secrets Manager + SSM Parameter Store.

---

## 1. Goals & Non-Goals

### Goals
- Catch regressions before merge: lint, type check, and unit tests on every PR.
- Block broken deploys: build artifacts and run smoke tests before promotion.
- Provide a single, scripted path from commit → staging → production, all
  inside GovCloud.
- Keep ITAR/CUI-sensitive material out of commercial AWS, public registries,
  and CI logs.
- Minimize PR feedback time (target: < 8 min for lint/type/unit on backend PRs).

### Non-Goals (for v1)
- Auto-merge / auto-rebase bots.
- Canary / blue-green deploys. ECS rolling deploys (with circuit breaker
  rollback) are sufficient for v1.
- Cross-region DR. `us-gov-west-1` only for v1.

---

## 2. Repository & Branch Model

- `main` — protected; production-deployable at all times.
- `develop` (optional, defer to v2) — integration branch for feature work.
- `feat/*`, `fix/*`, `chore/*`, `claude/*` — feature branches; PR into `main`.

### Branch protection (to enable on `main`)
- Require PR review (1 reviewer minimum).
- Require status checks to pass: `backend-ci`, `frontend-ci`, `secrets-scan`.
- Require branches to be up to date.
- Disallow force-pushes; disallow deletions.

---

## 3. Pipeline Topology

Two top-level workflows, scoped by `paths:` filters so PRs that touch only
frontend don't pay backend costs and vice versa.

```
.github/
└── workflows/
    ├── backend-ci.yml        # Python lint/type/test (PR + main)
    ├── frontend-ci.yml       # JS lint/build (PR + main)
    ├── secrets-scan.yml      # gitleaks (PR + main)
    ├── build-and-push.yml    # Build images, push to GovCloud ECR (main)
    ├── deploy-staging.yml    # ECS deploy + S3 sync (main, post build)
    ├── deploy-prod.yml       # ECS deploy + S3 sync (tag v*, gated)
    └── post-deploy-smoke.yml # Hits staging/prod ALB + auth roundtrip
```

**Runner strategy:**
- **GitHub-hosted runners** (`ubuntu-latest`) for lint, unit tests, builds,
  and image push (push uses GitHub OIDC → AWS GovCloud IAM; no long-lived AWS
  keys in GitHub).
- **Self-hosted runners inside the GovCloud VPC** for deploy jobs that touch
  private ECS services / RDS / internal ALBs and for any test that requires
  ITAR-classified fixtures. Tagged `runs-on: [self-hosted, govcloud, deploy]`.

### Trigger matrix

| Workflow | PR | Push to `main` | Tag `v*` | Manual |
|---|---|---|---|---|
| `backend-ci` | ✅ (paths) | ✅ | — | ✅ |
| `frontend-ci` | ✅ (paths) | ✅ | — | ✅ |
| `secrets-scan` | ✅ | ✅ | — | — |
| `build-and-push` | — | ✅ | ✅ | ✅ |
| `deploy-staging` | — | ✅ | — | ✅ |
| `deploy-prod` | — | — | ✅ | ✅ |
| `post-deploy-smoke` | — | (after staging deploy) | (after prod deploy) | ✅ |

---

## 4. Backend Pipeline (`backend-ci.yml`)

**Runtime:** `ubuntu-latest`, Python 3.11.

**Stages (in one job, fail-fast):**

1. **Setup**
   - `actions/checkout@v4`
   - `actions/setup-python@v5` with `python-version: '3.11'` and pip cache keyed
     on `requirements*.txt` and `pyproject.toml`.
   - `pip install -e ".[dev]"` (uses `pyproject.toml` `dev` extra).

2. **Lint** — `ruff check .` (config already in `pyproject.toml`, line-length 100).

3. **Format check** — `ruff format --check .` (advisory in v1, blocking in v2).

4. **Type check** — `mypy mira core services` (advisory in v1; codebase isn't
   fully typed yet — see §10 rollout).

5. **Unit tests** — `pytest tests/ -v --tb=short --cov=mira --cov=core
   --cov-report=xml --cov-report=term-missing`.
   - 147 tests today; baseline runtime ≈ TBD on first run.
   - Upload `coverage.xml` to Codecov (or attach as artifact for v1).

6. **Test data isolation** — exclude `tests/model_eval/` runs by default
   (long-running ML eval; gate behind `[full-test]` PR label).

**Required env at job level:**
```yaml
env:
  MIRA_AUTH_MODE: none    # bypass Cognito for unit tests
  PYTHONPATH: ${{ github.workspace }}
```

**Caches:**
- pip wheel cache (`~/.cache/pip`).
- HuggingFace / sentence-transformers model cache (`~/.cache/huggingface`) —
  significant: `sentence-transformers` downloads ~100MB on first run.

---

## 5. Frontend Pipeline (`frontend-ci.yml`)

**Runtime:** `ubuntu-latest`, Node 20.

**Stages:**

1. **Setup** — `actions/setup-node@v4` with `cache: 'npm'`,
   `cache-dependency-path: frontend/package-lock.json`.

2. **Install** — `npm ci` (working-directory: `frontend`).

3. **Lint** — `npm run lint` (eslint flat config already in place).

4. **Type check** — `npx tsc --noEmit -p tsconfig.app.json`.

5. **Build** — `npm run build`. Catches Vite build errors before deploy.

6. **E2E (conditional)** — `npm run test:e2e` (Playwright).
   - Run on PRs labelled `e2e` and on push to `main`.
   - Skip on every PR by default — Playwright spins up a Vite dev server +
     needs a backend; defer full e2e to staging post-deploy smoke (§8).
   - In CI, install browsers via `npx playwright install --with-deps chromium`.

---

## 6. Container Build & Push (`build-and-push.yml`)

**Trigger:** push to `main`, tag `v*`, manual.

**Steps (GitHub-hosted runner):**
1. `actions/checkout@v4`, `docker/setup-buildx-action@v3`.
2. **AWS auth via OIDC** (no static keys):
   ```yaml
   - uses: aws-actions/configure-aws-credentials@v4
     with:
       role-to-assume: arn:aws-us-gov:iam::<acct>:role/gha-mira-ecr-push
       aws-region: us-gov-west-1
   - uses: aws-actions/amazon-ecr-login@v2
   ```
   The IAM role's trust policy restricts `sub` to
   `repo:boundstate-ai/mira:ref:refs/heads/main` and `refs/tags/v*`.
3. Build `Dockerfile` (root) → tag
   `<acct>.dkr.ecr.us-gov-west-1.amazonaws.com/mira-api:sha-${{ github.sha }}`
   and `:latest` (staging) or `:vX.Y.Z` (prod).
4. Build `frontend/Dockerfile` → push `mira-frontend` similarly. *Note:* if
   we go with the S3 static-site path (§7), the frontend image is optional —
   the build artifact (`frontend/dist/`) is what we deploy.
5. Buildx cache (`type=gha`) to keep build < 4 min on warm cache.
6. **Local smoke** of the API image before promotion: `docker run` on the
   runner, poll `/health` for 60s, fail if unhealthy.
7. **Image scan**: `aws ecr start-image-scan` (or Trivy as a gate before push).
   Fail on `CRITICAL` findings.
8. SBOM: `anchore/sbom-action`, attach as workflow artifact and (on tag) as
   an OCI referrer to the image.

**Drift check:** `Dockerfile` uses `requirements.api.txt`, not
`pyproject.toml`. Add a CI step that diffs critical pins (`anthropic`,
`fastapi`, `pydantic`, `boto3`) between the two files and fails on
divergence.

---

## 7. Deployment (GovCloud `us-gov-west-1`)

### Backend → ECS Fargate
- **Cluster:** `mira-staging` and `mira-prod` (separate clusters per
  environment for blast-radius isolation).
- **Service:** `mira-api`, 2× Fargate tasks (min) behind an internal ALB.
  Health check: `GET /health` (already implemented; matches `Dockerfile`
  HEALTHCHECK).
- **Task def** stored in repo: `infra/ecs/mira-api.taskdef.json`. CI renders
  the new image tag into it via `aws-actions/amazon-ecs-render-task-definition`,
  then `amazon-ecs-deploy-task-definition` performs a rolling deploy with
  `wait-for-service-stability: true` and the deployment circuit breaker
  enabled (auto-rollback on health-check failure).
- **Networking:** tasks run in private subnets with no public IP. Egress for
  `anthropic.com` and `huggingface.co` (model downloads) routed via NAT
  gateway with an explicit allow-list at the VPC endpoint / firewall layer.
- **Secrets:** `MIRA_AUTH_MODE`, `COGNITO_*`, `ANTHROPIC_API_KEY`, DB URLs
  delivered as ECS task `secrets` referencing AWS Secrets Manager ARNs.
  Never as plain `environment` entries.
- **Logs:** CloudWatch Logs group `/mira/api/<env>`, 30-day retention
  (staging) / 1827-day retention (prod, matches existing
  `AUDIT_LOG_RETENTION_DAYS`).

### Frontend → S3 + ALB origin
- **CloudFront is not available in `us-gov-west-1`.** Two acceptable patterns:
  1. **S3 + ALB rule** (recommended): the same internal ALB serves the
     frontend by routing `/` to an S3 origin via an S3-VPC endpoint behind a
     small Lambda@-or-Nginx shim, OR the frontend container runs as a second
     ECS service (Nginx serving `/usr/share/nginx/html` from
     `frontend/Dockerfile`). For an internal-only ITAR app, this is simpler.
  2. **S3 static website + WAF**: only works if the bucket is reachable from
     authorized networks. Use a private API Gateway with a VPC endpoint for
     authorized network access.
- **Recommended for v1:** keep the existing `frontend/Dockerfile` (Nginx) and
  deploy it as a second ECS service `mira-frontend` behind the same ALB.
  CI builds the image with the right `VITE_*` build args per environment and
  pushes to ECR. Same deploy mechanism as the API.
- The `frontend/vercel.json` rewrite rule is replaced by an Nginx
  `proxy_pass` from `/api/*` → `mira-api.<env>.local:8080` (already wired in
  `frontend/nginx.conf` — verify and adjust upstream).

### Environments & secrets

| Environment | AWS account / region | Cognito pool | DNS | Trigger |
|---|---|---|---|---|
| `dev` (local) | n/a | `MIRA_AUTH_MODE=none` | localhost | feature branches |
| `staging` | gov-acct-staging / us-gov-west-1 | `us-gov-west-1_STG` | `staging.mira.boundstate.ai` (private) | push to `main` |
| `production` | gov-acct-prod / us-gov-west-1 | `us-gov-west-1_PRD` | `mira.boundstate.ai` (private/PIV) | tag `v*` |

GitHub Environments (`staging`, `production`) gate the deploy jobs and hold
the IAM role ARNs to assume. `production` requires manual approval from the
designated reviewer team and runs on a `self-hosted, govcloud, deploy`
runner inside the prod VPC.

### Rollback
- **Automatic:** ECS deployment circuit breaker rolls back if the new task
  set fails health checks during the deployment window.
- **Manual:** re-run `deploy-prod.yml` with `workflow_dispatch` and the
  previous `v*` tag as input. The task def + image tag fully describe a
  release.

---

## 8. Post-Deploy Smoke

Triggered by `workflow_run` on successful staging or prod deploy. Runs on a
**self-hosted runner inside the relevant VPC** so it can hit the internal
ALB.

1. Health check: `GET https://<env-alb>/health` (5×30s retry).
2. MUA V10 happy-path: `POST /api/mua/v10/classify` with a fixture payload.
   In staging this can use `MIRA_AUTH_MODE=none`; in prod, mint a short-lived
   Cognito token via a service-account client credential held in Secrets
   Manager and used only by the smoke runner.
3. Frontend: `GET https://<env-alb>/` returns 200 and serves `index.html`.
4. Auth round-trip: login flow against the staging Cognito pool with a test
   user (staging only; do not store prod test creds).
5. Optional: a tiny Playwright run (`tests/e2e/smoke.spec.ts`) — single test,
   ~30s — hitting the deployed staging URL.

Failures open a GitHub issue via `gh issue create` and notify
`#mira-deploys` via a Slack webhook hosted in the GovCloud-permitted
notification path. v1 does **not** auto-rollback beyond what ECS already
does.

---

## 9. Security & Compliance

- **gitleaks** on every PR (`secrets-scan.yml`). The `auth.env.example` and
  `MIRA_v5_ORACLE_BRIEF.md` patterns must be allowlisted.
- **Dependabot** (`.github/dependabot.yml`) for `pip`, `npm`, `docker`, and
  `github-actions` ecosystems. Group minor/patch updates weekly to reduce noise.
- **CodeQL** (`github/codeql-action`) for Python + JS, weekly schedule.
- **SBOM**: `anchore/sbom-action` on `build-and-push.yml`, attached to the
  release and stored as an OCI referrer in ECR.
- **Image scanning**: ECR scan-on-push (`enhanced` mode via Inspector) +
  Trivy gate in CI. Block deploy on `CRITICAL` findings.
- **ITAR / CUI boundary**:
  - Training data files at the repo root (`mua_*.jsonl`, ~13 MB) are tracked
    but must not be copied into the API image — `.dockerignore` already
    excludes them. Enforce with a CI step that runs
    `docker run --rm <image> sh -c 'ls /app/mua_*.jsonl 2>/dev/null'` and
    fails if any match.
  - All deploy targets, container registry, secrets, logs, and DB live in
    `us-gov-west-1`. No production data passes through commercial AWS.
  - Source code itself is non-ITAR; GitHub.com (commercial) is acceptable as
    the SCM. Anything classified or CUI-bound (test fixtures, golden sets
    derived from controlled docs) stays in GovCloud S3 and is fetched at
    runtime by self-hosted GovCloud runners — never committed.
- **OIDC, not static keys**: GitHub Actions assumes IAM roles via OIDC with
  per-environment trust conditions on `sub` (`ref:refs/heads/main` for
  staging, `ref:refs/tags/v*` for prod). No `AWS_ACCESS_KEY_ID` in GitHub
  Secrets.
- **Secret scope**: never echo `${{ secrets.* }}` values; runtime secrets are
  in AWS Secrets Manager and surfaced to ECS tasks at start, not via env in
  CI. Use `::add-mask::` for any value that must transit the runner.
- **Audit**: deploy events emit to CloudWatch Logs group `/mira/audit`
  (already specified in `auth.env.example`), retention 1827 days for prod.

---

## 10. Rollout Phases

### Phase 0 — GovCloud foundations (prerequisite, ops-led)
- [ ] Two AWS GovCloud accounts (staging, prod) with VPC, private subnets,
      NAT, internal ALB.
- [ ] ECR repos: `mira-api`, `mira-frontend` in each account.
- [ ] ECS clusters `mira-staging`, `mira-prod` (Fargate).
- [ ] RDS PostgreSQL per environment.
- [ ] Cognito User Pools per environment (already partly defined in
      `auth.env.example`).
- [ ] IAM OIDC provider for GitHub Actions, plus per-env roles
      (`gha-mira-ecr-push`, `gha-mira-ecs-deploy-staging`,
      `gha-mira-ecs-deploy-prod`) with least-privilege trust conditions.
- [ ] Secrets Manager entries for Cognito, Anthropic, DB.
- [ ] One self-hosted runner per VPC (ASG, label
      `[self-hosted, govcloud, deploy]`).

### Phase 1 — CI on PRs (week 1)
- [ ] `.github/workflows/backend-ci.yml` (lint + unit tests; mypy advisory).
- [ ] `.github/workflows/frontend-ci.yml` (lint + build).
- [ ] `.github/workflows/secrets-scan.yml` (gitleaks).
- [ ] Enable branch protection on `main` requiring those three checks.
- [ ] Add `.github/dependabot.yml`.

### Phase 2 — Build & push to ECR (week 2)
- [ ] `build-and-push.yml` using OIDC → `gha-mira-ecr-push`.
- [ ] Trivy + ECR scan gates.
- [ ] SBOM upload as OCI referrer.
- [ ] Local-runner `/health` smoke before push.

### Phase 3 — Staging deploy (week 3)
- [ ] `infra/ecs/mira-api.taskdef.json` + `mira-frontend.taskdef.json`
      checked in.
- [ ] `deploy-staging.yml` rendering image tag and rolling ECS service.
- [ ] `post-deploy-smoke.yml` running on the staging self-hosted runner.

### Phase 4 — Prod deploy (week 4)
- [ ] `deploy-prod.yml` gated by `production` GitHub Environment with manual
      approval and tag (`v*`) trigger.
- [ ] Runbook in `docs/runbooks/deploy-prod.md` covering rollback.

### Phase 5 — Quality gates (week 5+)
- [ ] Promote mypy from advisory → blocking on `mira/api/` first, then expand.
- [ ] Promote `ruff format --check` → blocking.
- [ ] Coverage enforcement (Codecov or self-hosted equivalent — Codecov SaaS
      is acceptable since it only sees code, not runtime data).
- [ ] CodeQL scans on PR + weekly.

### Phase 6 — Hardening (later)
- [ ] Canary / blue-green via ECS CodeDeploy for the API service.
- [ ] Performance budget for `mira/api/` p95 latency tracked across deploys
      (CloudWatch RUM/X-Ray).
- [ ] DR replica in `us-gov-east-1`.

---

## 11. Open Questions

1. **Frontend hosting pattern** — second ECS service behind the same ALB
   (recommended, simplest) vs. S3 static website + private API Gateway.
   Decision driver: do we need PIV/CAC enforcement at the edge for the
   frontend, or does the SPA + Cognito flow suffice?
2. **Anthropic API egress** — `anthropic.com` is commercial. Confirm the
   ATO/ITAR posture allows this egress from `us-gov-west-1`, or whether we
   need a Bedrock GovCloud equivalent. This shapes which secrets and which
   network controls CI must wire up.
3. **Long-running ML eval tests** (`tests/model_eval/`) — keep on-demand
   only, or run nightly on a schedule on a self-hosted runner with access to
   GovCloud-stored fixtures? Recommend nightly on `main` with results posted
   as a PR comment.
4. **Frontend e2e in CI** — Playwright needs a live backend. Run against
   staging post-deploy (recommended) or stand up the API in a Docker service
   container in CI?
5. **Self-hosted runner topology** — single ASG per env, or per-job
   ephemeral runners (e.g., `actions-runner-controller` on EKS)? Ephemeral
   is more secure but adds ops overhead.
6. **Secret rotation cadence** — Cognito client secrets, Anthropic keys, DB
   creds. Propose 90-day rotation via Secrets Manager rotation lambdas; out
   of scope for the CI pipeline itself but tracked here.
7. **Removing legacy deploy artifacts** — `Procfile`, `railway.json`,
   `nixpacks.toml`, and `frontend/vercel.json` are stale once we cut over to
   ECS. Plan: keep them until Phase 4 completes, then delete in a single PR
   to avoid mid-rollout confusion.

---

## 12. Reference: Local equivalents

Each CI step should be runnable locally so contributors aren't surprised:

```bash
# Backend
ruff check .
ruff format --check .
mypy mira core services
pytest tests/ -v --tb=short

# Frontend
cd frontend
npm ci
npm run lint
npx tsc --noEmit -p tsconfig.app.json
npm run build
npm run test:e2e   # needs backend running on :8000
```

These mirror what `verify_mua_v10.bat` does today; the goal is for CI to be
"the same checks, on every commit".
