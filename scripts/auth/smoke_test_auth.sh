#!/usr/bin/env bash
set -euo pipefail

# Auth smoke tests for staging/prod.
#
# Required:
#   BASE_URL=https://mira.boundstate.ai ./scripts/auth/smoke_test_auth.sh
#
# Optional:
#   ACCESS_TOKEN=<valid standard token>
#   NON_ITAR_TOKEN=<valid non-itar token>
#   ITAR_TOKEN=<valid itar token>
#   ADMIN_TOKEN=<valid admin token>
#   PUBLIC_PATH=/health
#   PROTECTED_PATH=/api/mira/ping
#   ITAR_PATH=/miul/ping
#   ADMIN_PATH=/admin/ping

BASE_URL="${BASE_URL:-}"
PUBLIC_PATH="${PUBLIC_PATH:-/health}"
PROTECTED_PATH="${PROTECTED_PATH:-/api/mira/ping}"
ITAR_PATH="${ITAR_PATH:-/miul/ping}"
ADMIN_PATH="${ADMIN_PATH:-}"

ACCESS_TOKEN="${ACCESS_TOKEN:-}"
NON_ITAR_TOKEN="${NON_ITAR_TOKEN:-}"
ITAR_TOKEN="${ITAR_TOKEN:-}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

if [[ -z "${BASE_URL}" ]]; then
  echo "ERROR: BASE_URL is required (example: https://mira.boundstate.ai)" >&2
  exit 1
fi

http_status() {
  local url="$1"
  shift || true
  curl -sS -o /tmp/mira_smoke_body.txt -w "%{http_code}" "$url" "$@"
}

assert_status() {
  local got="$1"
  local want="$2"
  local label="$3"
  if [[ "${got}" != "${want}" ]]; then
    echo "FAIL: ${label} expected=${want} got=${got}" >&2
    echo "Response body:" >&2
    cat /tmp/mira_smoke_body.txt >&2 || true
    exit 1
  fi
  echo "PASS: ${label} -> ${got}"
}

echo "Running auth smoke tests against ${BASE_URL}"

status="$(http_status "${BASE_URL}${PUBLIC_PATH}")"
assert_status "${status}" "200" "public path ${PUBLIC_PATH}"

status="$(http_status "${BASE_URL}${PROTECTED_PATH}")"
assert_status "${status}" "401" "protected path without token ${PROTECTED_PATH}"

status="$(http_status "${BASE_URL}${ITAR_PATH}")"
assert_status "${status}" "401" "ITAR path without token ${ITAR_PATH}"

if [[ -n "${ACCESS_TOKEN}" ]]; then
  status="$(http_status "${BASE_URL}${PROTECTED_PATH}" -H "Authorization: Bearer ${ACCESS_TOKEN}")"
  if [[ "${status}" != "200" ]]; then
    echo "FAIL: protected path with ACCESS_TOKEN expected=200 got=${status}" >&2
    cat /tmp/mira_smoke_body.txt >&2 || true
    exit 1
  fi
  echo "PASS: protected path with ACCESS_TOKEN -> ${status}"
fi

if [[ -n "${NON_ITAR_TOKEN}" ]]; then
  status="$(http_status "${BASE_URL}${ITAR_PATH}" -H "Authorization: Bearer ${NON_ITAR_TOKEN}")"
  assert_status "${status}" "403" "ITAR path with NON_ITAR_TOKEN ${ITAR_PATH}"
fi

if [[ -n "${ITAR_TOKEN}" ]]; then
  status="$(http_status "${BASE_URL}${ITAR_PATH}" -H "Authorization: Bearer ${ITAR_TOKEN}")"
  if [[ "${status}" != "200" ]]; then
    echo "FAIL: ITAR path with ITAR_TOKEN expected=200 got=${status}" >&2
    cat /tmp/mira_smoke_body.txt >&2 || true
    exit 1
  fi
  echo "PASS: ITAR path with ITAR_TOKEN -> ${status}"
fi

if [[ -n "${ADMIN_PATH}" ]]; then
  status="$(http_status "${BASE_URL}${ADMIN_PATH}")"
  assert_status "${status}" "401" "admin path without token ${ADMIN_PATH}"
fi

if [[ -n "${ADMIN_PATH}" && -n "${ADMIN_TOKEN}" ]]; then
  status="$(http_status "${BASE_URL}${ADMIN_PATH}" -H "Authorization: Bearer ${ADMIN_TOKEN}")"
  if [[ "${status}" != "200" ]]; then
    echo "FAIL: admin path with ADMIN_TOKEN expected=200 got=${status}" >&2
    cat /tmp/mira_smoke_body.txt >&2 || true
    exit 1
  fi
  echo "PASS: admin path with ADMIN_TOKEN -> ${status}"
fi

echo "All requested checks passed."
