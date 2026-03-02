# MIRA Cognito Hardening Runbook

Run in AWS GovCloud (`us-gov-west-1`) after creating your user pool/client.

## 1) Enforce authenticator-app MFA (required)

```bash
aws cognito-idp set-user-pool-mfa-config \
  --user-pool-id "$COGNITO_USER_POOL_ID" \
  --region us-gov-west-1 \
  --mfa-configuration ON \
  --software-token-mfa-configuration Enabled=true
```

## 2) Lock app client write access for privileged custom attributes

Do not allow frontend clients to write:
- `custom:us_person_verified`
- `custom:itar_access`
- `custom:role`

Use `update-user-pool-client` and explicitly set `--write-attributes` to safe fields only.

```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id "$COGNITO_USER_POOL_ID" \
  --client-id "$COGNITO_CLIENT_ID" \
  --region us-gov-west-1 \
  --write-attributes '["email"]' \
  --read-attributes '["email","custom:us_person_verified","custom:itar_access","custom:role"]'
```

## 3) Verify MFA and client hardening

```bash
aws cognito-idp describe-user-pool \
  --user-pool-id "$COGNITO_USER_POOL_ID" \
  --region us-gov-west-1

aws cognito-idp describe-user-pool-client \
  --user-pool-id "$COGNITO_USER_POOL_ID" \
  --client-id "$COGNITO_CLIENT_ID" \
  --region us-gov-west-1
```

Confirm:
- `MfaConfiguration` is `ON`
- software token MFA is enabled
- app client write attributes do not include privileged custom attributes

## 4) Backend env vars

```bash
MIRA_AUTH_MODE=cognito
COGNITO_REGION=us-gov-west-1
COGNITO_USER_POOL_ID=<pool-id>
COGNITO_CLIENT_ID=<client-id>
ITAR_PATH_PREFIXES=/miul,/bom
ADMIN_PATH_PREFIXES=/admin
AUDIT_LOG_GROUP=/mira/audit
AUDIT_LOG_STREAM_PREFIX=mira-auth
AUDIT_LOG_RETENTION_DAYS=1827
ENABLE_AUDIT_LOGGING=true
COGNITO_HOSTED_UI_ORIGIN=https://<your-domain>
```

## 5) Frontend env vars (Vite)

```bash
VITE_COGNITO_USER_POOL_ID=<pool-id>
VITE_COGNITO_CLIENT_ID=<client-id>
VITE_API_AUTH_HOSTS=127.0.0.1:8000,localhost:8000
```

