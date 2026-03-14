#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-govcloud}"
AWS_REGION="${AWS_REGION:-us-gov-west-1}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
AWS_PAGER=""
export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION AWS_PAGER

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOCKER_BIN="${DOCKER_BIN:-/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe}"
DATE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_TAG="${IMAGE_TAG:-runtime-${DATE_TAG}}"
ALLOW_DIRTY_DEPLOY="${ALLOW_DIRTY_DEPLOY:-0}"
DEPLOY_GIT_REF="${DEPLOY_GIT_REF:-}"
BUILD_ROOT="${ROOT_DIR}"
STAGING_DIR=""
BACKEND_TASK_JSON=""
FRONTEND_TASK_JSON=""

ACCOUNT_ID="${ACCOUNT_ID:-574823419003}"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

CLUSTER="${CLUSTER:-mira-prod-cluster}"
BACKEND_SERVICE="${BACKEND_SERVICE:-mira-prod-backend}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-mira-prod-frontend}"
BACKEND_REPO="${BACKEND_REPO:-mira-backend}"
FRONTEND_REPO="${FRONTEND_REPO:-mira-frontend}"

BACKEND_IMAGE="${REGISTRY}/${BACKEND_REPO}:${IMAGE_TAG}"
FRONTEND_IMAGE="${REGISTRY}/${FRONTEND_REPO}:${IMAGE_TAG}"

BACKEND_TASK_FAMILY="${BACKEND_TASK_FAMILY:-mira-prod-backend-task}"
FRONTEND_TASK_FAMILY="${FRONTEND_TASK_FAMILY:-mira-prod-frontend-task}"

BACKEND_TG_ARN="${BACKEND_TG_ARN:-arn:aws-us-gov:elasticloadbalancing:us-gov-west-1:574823419003:targetgroup/mira-prod-be-8080-tg/412b1d1aab416cad}"
FRONTEND_TG_ARN="${FRONTEND_TG_ARN:-arn:aws-us-gov:elasticloadbalancing:us-gov-west-1:574823419003:targetgroup/mira-prod-fe-tg/4807e900d8b0dd14}"

PRIVATE_SUBNETS="${PRIVATE_SUBNETS:-subnet-01df5b02d7d7f65e8,subnet-0415246982e26c04f}"
BACKEND_SECURITY_GROUP="${BACKEND_SECURITY_GROUP:-sg-0ecdc2af444ce6b45}"
FRONTEND_SECURITY_GROUP="${FRONTEND_SECURITY_GROUP:-sg-04ed4a32c58123c21}"

COGNITO_REGION="${COGNITO_REGION:-us-gov-west-1}"
COGNITO_USER_POOL_ID="${COGNITO_USER_POOL_ID:-us-gov-west-1_nEpMTffMH}"
COGNITO_CLIENT_ID="${COGNITO_CLIENT_ID:-1tklem8thjkg04ipupvcb1heal}"
BASE_URL="${BASE_URL:-https://mira.boundstate.ai}"
JWT_SECRET_KEY="${JWT_SECRET_KEY:-mira-runtime-${DATE_TAG}}"
BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-sonnet-4-5-20250929-v1:0}"
NO_DATA_RUNTIME="${NO_DATA_RUNTIME:-1}"

BACKEND_CPU="${BACKEND_CPU:-256}"
BACKEND_MEMORY="${BACKEND_MEMORY:-512}"
FRONTEND_CPU="${FRONTEND_CPU:-256}"
FRONTEND_MEMORY="${FRONTEND_MEMORY:-512}"

BACKEND_TASK_ROLE_ARN="${BACKEND_TASK_ROLE_ARN:-arn:aws-us-gov:iam::${ACCOUNT_ID}:role/mira-prod-ecs-task}"
EXECUTION_ROLE_ARN="${EXECUTION_ROLE_ARN:-arn:aws-us-gov:iam::${ACCOUNT_ID}:role/mira-prod-ecs-execution}"

require_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_bin aws
require_bin curl
require_bin rg
require_bin git
[ -x "${DOCKER_BIN}" ] || {
  echo "Docker binary not found: ${DOCKER_BIN}" >&2
  exit 1
}

cleanup() {
  if [ -n "${STAGING_DIR}" ] && [ -d "${STAGING_DIR}" ]; then
    rm -rf "${STAGING_DIR}"
  fi
  if [ -n "${BACKEND_TASK_JSON}" ] && [ -f "${BACKEND_TASK_JSON}" ]; then
    rm -f "${BACKEND_TASK_JSON}"
  fi
  if [ -n "${FRONTEND_TASK_JSON}" ] && [ -f "${FRONTEND_TASK_JSON}" ]; then
    rm -f "${FRONTEND_TASK_JSON}"
  fi
}

trap cleanup EXIT

json_array_from_csv() {
  local csv="$1"
  local out=""
  IFS=',' read -r -a parts <<<"${csv}"
  for part in "${parts[@]}"; do
    part="${part// /}"
    [ -n "${part}" ] || continue
    if [ -n "${out}" ]; then
      out+=", "
    fi
    out+="\"${part}\""
  done
  printf '%s' "${out}"
}

ensure_repo() {
  local repo="$1"
  aws ecr describe-repositories --repository-names "${repo}" >/dev/null 2>&1 || \
    aws ecr create-repository --repository-name "${repo}" >/dev/null
}

ensure_service() {
  local service_name="$1"
  aws ecs describe-services --cluster "${CLUSTER}" --services "${service_name}" \
    --query 'services[0].status' --output text 2>/dev/null | rg -q 'ACTIVE'
}

prepare_build_root() {
  if [ -n "${DEPLOY_GIT_REF}" ]; then
    STAGING_DIR="$(mktemp -d)"
    echo "== Build source =="
    echo "Preparing clean snapshot from git ref: ${DEPLOY_GIT_REF}"
    git -C "${ROOT_DIR}" archive "${DEPLOY_GIT_REF}" | tar -xf - -C "${STAGING_DIR}"
    BUILD_ROOT="${STAGING_DIR}"
    return
  fi

  local dirty_files
  dirty_files="$(git -C "${ROOT_DIR}" status --porcelain)"
  if [ -n "${dirty_files}" ] && [ "${ALLOW_DIRTY_DEPLOY}" != "1" ]; then
    echo "Refusing to deploy from a dirty worktree." >&2
    echo "Use one of the following:" >&2
    echo "  1. Commit/stash unrelated changes and rerun" >&2
    echo "  2. Set DEPLOY_GIT_REF=<commit-or-tag> to deploy a clean git revision" >&2
    echo "  3. Set ALLOW_DIRTY_DEPLOY=1 only when you intentionally want the current local worktree" >&2
    echo >&2
    echo "First 20 dirty paths:" >&2
    printf '%s\n' "${dirty_files}" | sed -n '1,20p' >&2
    exit 1
  fi
}

prepare_build_root

echo "== ECR login =="
ensure_repo "${BACKEND_REPO}"
ensure_repo "${FRONTEND_REPO}"
aws ecr get-login-password | "${DOCKER_BIN}" login --username AWS --password-stdin "${REGISTRY}"

echo
echo "== Build backend =="
pushd "${BUILD_ROOT}" >/dev/null
"${DOCKER_BIN}" build -t "mira-backend:${IMAGE_TAG}" -f Dockerfile .
popd >/dev/null
"${DOCKER_BIN}" tag "mira-backend:${IMAGE_TAG}" "${BACKEND_IMAGE}"
"${DOCKER_BIN}" push "${BACKEND_IMAGE}"

echo
echo "== Build frontend =="
pushd "${BUILD_ROOT}/frontend" >/dev/null
"${DOCKER_BIN}" build \
  --build-arg "VITE_COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}" \
  --build-arg "VITE_COGNITO_CLIENT_ID=${COGNITO_CLIENT_ID}" \
  --build-arg "VITE_API_AUTH_HOSTS=mira.boundstate.ai" \
  -t "mira-frontend:${IMAGE_TAG}" \
  -f Dockerfile \
  .
popd >/dev/null
"${DOCKER_BIN}" tag "mira-frontend:${IMAGE_TAG}" "${FRONTEND_IMAGE}"
"${DOCKER_BIN}" push "${FRONTEND_IMAGE}"

echo
echo "== Cluster / Logs =="
aws ecs describe-clusters --clusters "${CLUSTER}" --query 'clusters[0].status' --output text 2>/dev/null | rg -q 'ACTIVE' || \
  aws ecs create-cluster --cluster-name "${CLUSTER}" >/dev/null
aws logs create-log-group --log-group-name /ecs/mira-prod-backend >/dev/null 2>&1 || true
aws logs create-log-group --log-group-name /ecs/mira-prod-frontend >/dev/null 2>&1 || true
aws logs put-retention-policy --log-group-name /ecs/mira-prod-backend --retention-in-days 30 >/dev/null
aws logs put-retention-policy --log-group-name /ecs/mira-prod-frontend --retention-in-days 30 >/dev/null

BACKEND_TASK_JSON="$(mktemp)"
FRONTEND_TASK_JSON="$(mktemp)"

cat > "${BACKEND_TASK_JSON}" <<JSON
{
  "family": "${BACKEND_TASK_FAMILY}",
  "taskRoleArn": "${BACKEND_TASK_ROLE_ARN}",
  "executionRoleArn": "${EXECUTION_ROLE_ARN}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "${BACKEND_CPU}",
  "memory": "${BACKEND_MEMORY}",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "${BACKEND_IMAGE}",
      "essential": true,
      "portMappings": [
        {"containerPort": 8080, "hostPort": 8080, "protocol": "tcp"}
      ],
      "environment": [
        {"name": "PORT", "value": "8080"},
        {"name": "RELOAD", "value": "false"},
        {"name": "ITAR_PATH_PREFIXES", "value": "/miul,/bom"},
        {"name": "ENVIRONMENT", "value": "production"},
        {"name": "AWS_DEFAULT_REGION", "value": "${AWS_REGION}"},
        {"name": "CORS_EXTRA_ORIGINS", "value": "${BASE_URL}"},
        {"name": "ENABLE_DEBUG_ENDPOINTS", "value": "false"},
        {"name": "COGNITO_USER_POOL_ID", "value": "${COGNITO_USER_POOL_ID}"},
        {"name": "DEBUG", "value": "false"},
        {"name": "ALLOWED_ORIGINS", "value": "${BASE_URL}"},
        {"name": "MIRA_AUTH_MODE", "value": "cognito"},
        {"name": "ADMIN_PATH_PREFIXES", "value": "/admin"},
        {"name": "COGNITO_REGION", "value": "${COGNITO_REGION}"},
        {"name": "ENABLE_AUDIT_LOGGING", "value": "false"},
        {"name": "BEDROCK_MODEL_ID", "value": "${BEDROCK_MODEL_ID}"},
        {"name": "COGNITO_CLIENT_ID", "value": "${COGNITO_CLIENT_ID}"},
        {"name": "JWT_SECRET_KEY", "value": "${JWT_SECRET_KEY}"},
        {"name": "MIRA_DISABLE_HERITAGE_DB", "value": "${NO_DATA_RUNTIME}"},
        {"name": "MIRA_NO_DATA_RUNTIME", "value": "${NO_DATA_RUNTIME}"},
        {"name": "POSTGRES_HOST", "value": "localhost"},
        {"name": "POSTGRES_PORT", "value": "5432"},
        {"name": "POSTGRES_DB", "value": "mira_h2"},
        {"name": "POSTGRES_USER", "value": "restored"},
        {"name": "POSTGRES_PASSWORD", "value": "restored"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/mira-prod-backend",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}
JSON

cat > "${FRONTEND_TASK_JSON}" <<JSON
{
  "family": "${FRONTEND_TASK_FAMILY}",
  "executionRoleArn": "${EXECUTION_ROLE_ARN}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "${FRONTEND_CPU}",
  "memory": "${FRONTEND_MEMORY}",
  "containerDefinitions": [
    {
      "name": "frontend",
      "image": "${FRONTEND_IMAGE}",
      "essential": true,
      "portMappings": [
        {"containerPort": 80, "hostPort": 80, "protocol": "tcp"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/mira-prod-frontend",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:80/ || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 30
      }
    }
  ]
}
JSON

echo
echo "== Register task definitions =="
BACKEND_TD_ARN="$(aws ecs register-task-definition --cli-input-json "file://${BACKEND_TASK_JSON}" --query 'taskDefinition.taskDefinitionArn' --output text)"
FRONTEND_TD_ARN="$(aws ecs register-task-definition --cli-input-json "file://${FRONTEND_TASK_JSON}" --query 'taskDefinition.taskDefinitionArn' --output text)"
echo "Backend task:  ${BACKEND_TD_ARN}"
echo "Frontend task: ${FRONTEND_TD_ARN}"

SUBNET_JSON="$(json_array_from_csv "${PRIVATE_SUBNETS}")"

echo
echo "== ECS service deploy =="
if ensure_service "${BACKEND_SERVICE}"; then
  aws ecs update-service \
    --cluster "${CLUSTER}" \
    --service "${BACKEND_SERVICE}" \
    --task-definition "${BACKEND_TD_ARN}" \
    --desired-count 1 >/dev/null
else
  aws ecs create-service \
    --cluster "${CLUSTER}" \
    --service-name "${BACKEND_SERVICE}" \
    --task-definition "${BACKEND_TD_ARN}" \
    --desired-count 1 \
    --launch-type FARGATE \
    --health-check-grace-period-seconds 120 \
    --load-balancers "targetGroupArn=${BACKEND_TG_ARN},containerName=backend,containerPort=8080" \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_JSON}],securityGroups=[\"${BACKEND_SECURITY_GROUP}\"],assignPublicIp=DISABLED}" >/dev/null
fi

if ensure_service "${FRONTEND_SERVICE}"; then
  aws ecs update-service \
    --cluster "${CLUSTER}" \
    --service "${FRONTEND_SERVICE}" \
    --task-definition "${FRONTEND_TD_ARN}" \
    --desired-count 1 >/dev/null
else
  aws ecs create-service \
    --cluster "${CLUSTER}" \
    --service-name "${FRONTEND_SERVICE}" \
    --task-definition "${FRONTEND_TD_ARN}" \
    --desired-count 1 \
    --launch-type FARGATE \
    --health-check-grace-period-seconds 60 \
    --load-balancers "targetGroupArn=${FRONTEND_TG_ARN},containerName=frontend,containerPort=80" \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_JSON}],securityGroups=[\"${FRONTEND_SECURITY_GROUP}\"],assignPublicIp=DISABLED}" >/dev/null
fi

echo
echo "== Wait for steady state =="
aws ecs wait services-stable --cluster "${CLUSTER}" --services "${BACKEND_SERVICE}" "${FRONTEND_SERVICE}"

echo
echo "== Public verification =="
curl -I -L --max-redirs 3 --connect-timeout 10 --max-time 20 "${BASE_URL}"
curl -sS --connect-timeout 10 --max-time 20 "${BASE_URL}/health"
echo
