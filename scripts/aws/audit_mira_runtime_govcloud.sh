#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-govcloud}"
AWS_REGION="${AWS_REGION:-us-gov-west-1}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
AWS_PAGER=""
export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION AWS_PAGER

BASE_URL="${BASE_URL:-https://mira.boundstate.ai}"
CLUSTER="${CLUSTER:-mira-prod-cluster}"
BACKEND_SERVICE="${BACKEND_SERVICE:-mira-prod-backend}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-mira-prod-frontend}"
BACKEND_TG_ARN="${BACKEND_TG_ARN:-arn:aws-us-gov:elasticloadbalancing:us-gov-west-1:574823419003:targetgroup/mira-prod-be-8080-tg/412b1d1aab416cad}"
FRONTEND_TG_ARN="${FRONTEND_TG_ARN:-arn:aws-us-gov:elasticloadbalancing:us-gov-west-1:574823419003:targetgroup/mira-prod-fe-tg/4807e900d8b0dd14}"
SINCE="${SINCE:-15m}"

echo "== Public Edge =="
curl -sS -D - --connect-timeout 10 --max-time 20 "${BASE_URL}/health" -o /tmp/mira_audit_health.out
sed -n '1,12p' /tmp/mira_audit_health.out
curl -sS -D - --connect-timeout 10 --max-time 20 "${BASE_URL}/api/health" -o /tmp/mira_audit_api_health.out
sed -n '1,12p' /tmp/mira_audit_api_health.out

echo
echo "== ECS Services =="
aws ecs describe-services \
  --cluster "${CLUSTER}" \
  --services "${BACKEND_SERVICE}" "${FRONTEND_SERVICE}" \
  --query 'services[].{service:serviceName,status:status,desired:desiredCount,running:runningCount,pending:pendingCount,taskDef:taskDefinition,events:events[0:4].[createdAt,message]}' \
  --output json

echo
echo "== Target Health =="
aws elbv2 describe-target-health \
  --target-group-arn "${FRONTEND_TG_ARN}" \
  --query 'TargetHealthDescriptions[].{id:Target.Id,port:Target.Port,state:TargetHealth.State,reason:TargetHealth.Reason,description:TargetHealth.Description}' \
  --output json
aws elbv2 describe-target-health \
  --target-group-arn "${BACKEND_TG_ARN}" \
  --query 'TargetHealthDescriptions[].{id:Target.Id,port:Target.Port,state:TargetHealth.State,reason:TargetHealth.Reason,description:TargetHealth.Description}' \
  --output json

echo
echo "== Recent Backend 5xx / Exceptions =="
aws logs tail /ecs/mira-prod-backend --since "${SINCE}" --format short \
  | rg ' 500 |Traceback|ERROR|Exception' || true

echo
echo "== Recent Frontend Logs =="
aws logs tail /ecs/mira-prod-frontend --since "${SINCE}" --format short | tail -n 40 || true
