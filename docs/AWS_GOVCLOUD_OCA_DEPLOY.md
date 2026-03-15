# AWS GovCloud OCA Deploy

This is the deploy path for pushing the current `boundstate_mira` working tree, including the OCA module, to the GovCloud MIRA runtime.

Use this document as the default reference for future AWS deploy requests.

## Target Runtime

- AWS profile: `govcloud`
- Region: `us-gov-west-1`
- Account ID: `574823419003`
- Cognito user pool: `us-gov-west-1_nEpMTffMH`
- Cognito client ID: `1tklem8thjkg04ipupvcb1heal`
- ECS cluster: `mira-prod-cluster`
- Backend service: `mira-prod-backend`
- Frontend service: `mira-prod-frontend`
- Backend task family: `mira-prod-backend-task`
- Frontend task family: `mira-prod-frontend-task`
- Frontend URL: `https://mira.boundstate.ai`

## Source of Truth

- Main app repo: `/mnt/d/BoundState/boundstate_mira`
- Deploy script: `/mnt/d/BoundState/boundstate_mira/scripts/aws/redeploy_mira_runtime_govcloud.sh`
- Backend Dockerfile: `/mnt/d/BoundState/boundstate_mira/Dockerfile`
- Frontend Dockerfile: `/mnt/d/BoundState/boundstate_mira/frontend/Dockerfile`

This deploy path builds from the local machine. It does not require a Git push first.

## Required Local Preconditions

1. AWS CLI must already work with the GovCloud profile.
2. Docker Desktop Linux engine must be available from this machine.
3. The repo must contain the intended local changes.
4. If you are deploying from the live worktree, unrelated local edits should be committed or stashed first.

## Fast Verification

Run these first:

```bash
aws sts get-caller-identity --profile govcloud --region us-gov-west-1
```

Expected account:

```text
574823419003
```

Check Docker Desktop Linux engine:

```bash
powershell.exe -NoProfile -Command "docker version --format '{{.Server.Version}}'"
```

If that returns empty output or a daemon error, Docker is not ready for deploy.

## OCA-Specific Frontend Requirement

The frontend production build must use a relative API base for OCA System Builder.

Current required value:

```text
frontend/.env
VITE_API_URL=/api
```

Do not set this to `http://127.0.0.1:8000` for a GovCloud production build. That breaks browser-side OCA calls by sending them to the end user's localhost instead of the ALB-routed backend.

## Recommended Local Validation

Frontend build:

```bash
cd /mnt/d/BoundState/boundstate_mira/frontend
npm run build
```

OCA backend slice:

```bash
cd /mnt/d/BoundState/boundstate_mira
./.venv/bin/python -m pytest -q -s \
  tests/mira/test_oca_engine.py \
  tests/api/test_oca_endpoints.py \
  tests/mira/test_oca_system_engine.py \
  tests/api/test_oca_system_endpoints.py
```

Notes:

- The current OCA engine emits `18` mechanism assessments, not `12`.
- If tests fail on a hard-coded `12`, update the stale assertion before treating it as a runtime regression.

## Standard Redeploy Command

From anywhere:

```bash
AWS_PROFILE=govcloud \
AWS_REGION=us-gov-west-1 \
AWS_DEFAULT_REGION=us-gov-west-1 \
/mnt/d/BoundState/boundstate_mira/scripts/aws/redeploy_mira_runtime_govcloud.sh
```

The script now refuses to deploy from a dirty worktree by default.

## Safe Deploy Modes

Preferred: deploy a clean git revision

```bash
AWS_PROFILE=govcloud \
AWS_REGION=us-gov-west-1 \
AWS_DEFAULT_REGION=us-gov-west-1 \
DEPLOY_GIT_REF=<commit-or-tag> \
/mnt/d/BoundState/boundstate_mira/scripts/aws/redeploy_mira_runtime_govcloud.sh
```

Example:

```bash
AWS_PROFILE=govcloud \
AWS_REGION=us-gov-west-1 \
AWS_DEFAULT_REGION=us-gov-west-1 \
DEPLOY_GIT_REF=main \
/mnt/d/BoundState/boundstate_mira/scripts/aws/redeploy_mira_runtime_govcloud.sh
```

If you intentionally want to deploy the current local worktree, including uncommitted changes, you must opt in:

```bash
AWS_PROFILE=govcloud \
AWS_REGION=us-gov-west-1 \
AWS_DEFAULT_REGION=us-gov-west-1 \
ALLOW_DIRTY_DEPLOY=1 \
/mnt/d/BoundState/boundstate_mira/scripts/aws/redeploy_mira_runtime_govcloud.sh
```

This guard exists because the old behavior would silently ship unrelated local edits.

What the script does:

1. Logs into ECR in GovCloud.
2. Builds backend image from `/mnt/d/BoundState/boundstate_mira/Dockerfile`.
3. Builds frontend image from `/mnt/d/BoundState/boundstate_mira/frontend/Dockerfile`.
4. Tags and pushes both images to:
   - `574823419003.dkr.ecr.us-gov-west-1.amazonaws.com/mira-backend`
   - `574823419003.dkr.ecr.us-gov-west-1.amazonaws.com/mira-frontend`
5. Registers fresh ECS task definition revisions.
6. Updates `mira-prod-backend` and `mira-prod-frontend`.
7. Waits for both services to reach steady state.
8. Performs public verification against `https://mira.boundstate.ai`.

The script generates a timestamped runtime image tag automatically:

```text
runtime-YYYYMMDD-HHMMSS
```

## Manual Overrides

Useful overrides:

```bash
AWS_PROFILE=govcloud \
AWS_REGION=us-gov-west-1 \
IMAGE_TAG=runtime-20260312-083000 \
COGNITO_USER_POOL_ID=us-gov-west-1_nEpMTffMH \
COGNITO_CLIENT_ID=1tklem8thjkg04ipupvcb1heal \
/mnt/d/BoundState/boundstate_mira/scripts/aws/redeploy_mira_runtime_govcloud.sh
```

## Post-Deploy Verification

Health:

```bash
curl -I https://mira.boundstate.ai
curl -sS https://mira.boundstate.ai/health
curl -sS https://mira.boundstate.ai/api/health
```

ECS service state:

```bash
aws ecs describe-services \
  --profile govcloud \
  --region us-gov-west-1 \
  --cluster mira-prod-cluster \
  --services mira-prod-backend mira-prod-frontend
```

Recent logs:

```bash
aws logs tail /ecs/mira-prod-backend \
  --profile govcloud \
  --region us-gov-west-1 \
  --since 15m \
  --follow
```

```bash
aws logs tail /ecs/mira-prod-frontend \
  --profile govcloud \
  --region us-gov-west-1 \
  --since 15m \
  --follow
```

OCA smoke checks:

```bash
curl -sS https://mira.boundstate.ai/api/oca/ping
curl -sS https://mira.boundstate.ai/api/oca/systems/ping
```

Then verify in browser:

1. `https://mira.boundstate.ai/oca`
2. `https://mira.boundstate.ai/oca/system-builder`

## Docker Desktop Troubleshooting

The most common blocker on this machine is Docker Desktop not exposing the Linux engine pipe.

Check:

```bash
powershell.exe -NoProfile -Command "docker version --format '{{.Server.Version}}'"
```

If Docker is not ready, try:

```bash
powershell.exe -NoProfile -Command "& 'C:\\Program Files\\Docker\\Docker\\DockerCli.exe' -SwitchLinuxEngine"
powershell.exe -NoProfile -Command "& 'C:\\Program Files\\Docker\\Docker\\DockerCli.exe' -Start"
```

If the pipe still never appears:

- Open Docker Desktop interactively in Windows.
- Confirm it is running Linux containers.
- Wait until `docker version` returns a server version.
- Rerun the standard redeploy command.

Without a working local container engine, this deploy path cannot build or push the ECS images.

## Rollback

List task definition revisions:

```bash
aws ecs list-task-definitions \
  --profile govcloud \
  --region us-gov-west-1 \
  --family-prefix mira-prod-backend-task \
  --sort DESC
```

```bash
aws ecs list-task-definitions \
  --profile govcloud \
  --region us-gov-west-1 \
  --family-prefix mira-prod-frontend-task \
  --sort DESC
```

Move a service back to a known-good revision:

```bash
aws ecs update-service \
  --profile govcloud \
  --region us-gov-west-1 \
  --cluster mira-prod-cluster \
  --service mira-prod-backend \
  --task-definition arn:aws-us-gov:ecs:us-gov-west-1:574823419003:task-definition/mira-prod-backend-task:<REV>
```

```bash
aws ecs update-service \
  --profile govcloud \
  --region us-gov-west-1 \
  --cluster mira-prod-cluster \
  --service mira-prod-frontend \
  --task-definition arn:aws-us-gov:ecs:us-gov-west-1:574823419003:task-definition/mira-prod-frontend-task:<REV>
```

Then wait for steady state:

```bash
aws ecs wait services-stable \
  --profile govcloud \
  --region us-gov-west-1 \
  --cluster mira-prod-cluster \
  --services mira-prod-backend mira-prod-frontend
```

## Known Failure Modes

- `aws sts get-caller-identity` fails:
  - The local GovCloud profile is not authenticated.
- ECR login succeeds but `docker build` fails with `dockerDesktopLinuxEngine` pipe errors:
  - Docker Desktop Linux engine is not running.
- Frontend deploy succeeds but OCA System Builder calls localhost:
  - `frontend/.env` was built with a local `VITE_API_URL` instead of `/api`.
- OCA pytest fails only on mechanism count:
  - The test expectation is stale relative to the current engine output.

## Minimal Future Prompt

For future sessions, this is enough context:

```text
Deploy boundstate_mira to GovCloud using docs/AWS_GOVCLOUD_OCA_DEPLOY.md.
Profile: govcloud
Region: us-gov-west-1
Account: 574823419003
Cluster: mira-prod-cluster
Backend service: mira-prod-backend
Frontend service: mira-prod-frontend
Verify with aws sts get-caller-identity --profile govcloud --region us-gov-west-1
```
