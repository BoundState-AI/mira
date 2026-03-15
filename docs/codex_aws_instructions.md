# Codex AWS Access Instructions (GovCloud)

## Purpose
How to get Codex terminal sessions authenticated into the BoundState MIRA GovCloud account.

## 1) Required Local Setup
- AWS CLI v2 installed
- `~/.aws/config` and `~/.aws/credentials` present
- GovCloud region: `us-gov-west-1`

## 2) Preferred Access Path (SSO)
Use an IAM Identity Center profile (example name: `govcloud-sso`):

```ini
[sso-session govcloud]
sso_start_url = https://start.us-gov-home.awsapps.com/directory/d-98676ae9e0
sso_region = us-gov-west-1
sso_registration_scopes = sso:account:access

[profile govcloud-sso]
sso_session = govcloud
sso_account_id = 574823419003
sso_role_name = AdministratorAccess
region = us-gov-west-1
output = json
```

Login:

```bash
aws sso login --profile govcloud-sso --no-browser --use-device-code
```

Verify:

```bash
AWS_PROFILE=govcloud-sso AWS_REGION=us-gov-west-1 aws sts get-caller-identity
```

## 3) Fallback Access Path (Named Key Profile)
If SSO is unavailable, use a key-based profile (example: `govcloud`) that already has valid credentials configured in `~/.aws/credentials`.

Verify:

```bash
AWS_PROFILE=govcloud AWS_REGION=us-gov-west-1 aws sts get-caller-identity
```

## 4) Session Defaults for Codex Commands
Use this prefix for all commands in a terminal session:

```bash
export AWS_PROFILE=govcloud
export AWS_REGION=us-gov-west-1
export AWS_DEFAULT_REGION=us-gov-west-1
export AWS_PAGER=""
```

Then test:

```bash
aws ecs list-clusters
aws rds describe-db-instances
aws logs describe-log-groups
```

## 5) Known MIRA Resource Names (GovCloud)
- ECS cluster: `mira-prod-cluster`
- ECS services: `mira-prod-backend`, `mira-prod-frontend`
- Account: `574823419003`

## 6) If Auth Fails
- Run `aws sso logout` then re-run SSO login.
- Confirm account assignment/role in IAM Identity Center.
- Ensure the terminal has no conflicting `AWS_*` environment variables.
