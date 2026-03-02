#!/usr/bin/env bash
set -euo pipefail

# Harden an existing Cognito pool/client for MIRA.
# - Enforces software-token MFA (authenticator app) as required
# - Restricts client write attributes to prevent privilege escalation

REGION="${COGNITO_REGION:-us-gov-west-1}"
USER_POOL_ID="${COGNITO_USER_POOL_ID:-}"
CLIENT_ID="${COGNITO_CLIENT_ID:-}"

# Keep privileged attributes read-only to clients.
READ_ATTRIBUTES="${COGNITO_READ_ATTRIBUTES:-[\"email\",\"custom:us_person_verified\",\"custom:itar_access\",\"custom:role\"]}"
WRITE_ATTRIBUTES="${COGNITO_WRITE_ATTRIBUTES:-[\"email\"]}"

if [[ -z "${USER_POOL_ID}" ]]; then
  echo "ERROR: COGNITO_USER_POOL_ID is required." >&2
  exit 1
fi

if [[ -z "${CLIENT_ID}" ]]; then
  echo "ERROR: COGNITO_CLIENT_ID is required." >&2
  exit 1
fi

echo "Hardening Cognito pool=${USER_POOL_ID} client=${CLIENT_ID} region=${REGION}"

echo "1) Enforcing required software-token MFA..."
aws cognito-idp set-user-pool-mfa-config \
  --user-pool-id "${USER_POOL_ID}" \
  --region "${REGION}" \
  --mfa-configuration ON \
  --software-token-mfa-configuration Enabled=true

echo "2) Restricting app client read/write attributes..."
aws cognito-idp update-user-pool-client \
  --user-pool-id "${USER_POOL_ID}" \
  --client-id "${CLIENT_ID}" \
  --region "${REGION}" \
  --write-attributes "${WRITE_ATTRIBUTES}" \
  --read-attributes "${READ_ATTRIBUTES}"

echo "3) Verification snapshot"
echo "- MFA configuration:"
aws cognito-idp describe-user-pool \
  --user-pool-id "${USER_POOL_ID}" \
  --region "${REGION}" \
  --query 'UserPool.{MfaConfiguration:MfaConfiguration,SoftwareTokenMfa:SoftwareTokenMfaConfiguration.Enabled}' \
  --output table

echo "- App client attributes:"
aws cognito-idp describe-user-pool-client \
  --user-pool-id "${USER_POOL_ID}" \
  --client-id "${CLIENT_ID}" \
  --region "${REGION}" \
  --query 'UserPoolClient.{WriteAttributes:WriteAttributes,ReadAttributes:ReadAttributes}' \
  --output json

echo "Done."

