#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-govcloud}"
AWS_REGION="${AWS_REGION:-us-gov-west-1}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
AWS_PAGER=""
export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION AWS_PAGER

if [[ "${AWS_REGION}" == us-gov-* ]]; then
  AWS_PARTITION="${AWS_PARTITION:-aws-us-gov}"
else
  AWS_PARTITION="${AWS_PARTITION:-aws}"
fi

ACCOUNT_ID="${ACCOUNT_ID:-574823419003}"
CLUSTER="${CLUSTER:-mira-prod-cluster}"
BACKEND_SERVICE="${BACKEND_SERVICE:-mira-prod-backend}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-mira-prod-frontend}"
ALB_ARN="${ALB_ARN:-arn:aws-us-gov:elasticloadbalancing:us-gov-west-1:574823419003:loadbalancer/app/mira-prod-alb/9ec816e886a401b7}"
ALB_DIMENSION="${ALB_ARN#*loadbalancer/}"
BACKEND_LOG_GROUP="${BACKEND_LOG_GROUP:-/ecs/mira-prod-backend}"
FRONTEND_LOG_GROUP="${FRONTEND_LOG_GROUP:-/ecs/mira-prod-frontend}"
CONTAINER_INSIGHTS_LEVEL="${CONTAINER_INSIGHTS_LEVEL:-enabled}"
USAGE_LOG_BUCKET="${USAGE_LOG_BUCKET:-mira-prod-usage-logs-${ACCOUNT_ID}-${AWS_REGION}}"
ALB_ACCESS_LOG_PREFIX="${ALB_ACCESS_LOG_PREFIX:-alb-access}"
USAGE_DASHBOARD_NAME="${USAGE_DASHBOARD_NAME:-Mira-Prod-Usage}"
ALB_LOG_RETENTION_DAYS="${ALB_LOG_RETENTION_DAYS:-90}"

require_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_bin aws

ensure_usage_log_bucket() {
  if ! aws s3api head-bucket --bucket "${USAGE_LOG_BUCKET}" >/dev/null 2>&1; then
    aws s3api create-bucket \
      --bucket "${USAGE_LOG_BUCKET}" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}" >/dev/null
  fi

  aws s3api put-public-access-block \
    --bucket "${USAGE_LOG_BUCKET}" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" >/dev/null

  aws s3api put-bucket-encryption \
    --bucket "${USAGE_LOG_BUCKET}" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null

  aws s3api put-bucket-lifecycle-configuration \
    --bucket "${USAGE_LOG_BUCKET}" \
    --lifecycle-configuration \
    "{\"Rules\":[{\"ID\":\"ExpireAlbAccessLogs\",\"Status\":\"Enabled\",\"Filter\":{\"Prefix\":\"${ALB_ACCESS_LOG_PREFIX}/\"},\"Expiration\":{\"Days\":${ALB_LOG_RETENTION_DAYS}}}]}" >/dev/null

  local policy_file
  policy_file="$(mktemp)"
  cat > "${policy_file}" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSLogDeliveryAclCheck",
      "Effect": "Allow",
      "Principal": {
        "Service": "logdelivery.elasticloadbalancing.amazonaws.com"
      },
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:${AWS_PARTITION}:s3:::${USAGE_LOG_BUCKET}"
    },
    {
      "Sid": "AWSLogDeliveryWrite",
      "Effect": "Allow",
      "Principal": {
        "Service": "logdelivery.elasticloadbalancing.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:${AWS_PARTITION}:s3:::${USAGE_LOG_BUCKET}/${ALB_ACCESS_LOG_PREFIX}/AWSLogs/${ACCOUNT_ID}/*"
    }
  ]
}
JSON
  aws s3api put-bucket-policy --bucket "${USAGE_LOG_BUCKET}" --policy "file://${policy_file}" >/dev/null
  rm -f "${policy_file}"
}

enable_container_insights() {
  aws ecs update-cluster-settings \
    --cluster "${CLUSTER}" \
    --settings "name=containerInsights,value=${CONTAINER_INSIGHTS_LEVEL}" >/dev/null
}

enable_alb_access_logs() {
  aws elbv2 modify-load-balancer-attributes \
    --load-balancer-arn "${ALB_ARN}" \
    --attributes \
      "Key=access_logs.s3.enabled,Value=true" \
      "Key=access_logs.s3.bucket,Value=${USAGE_LOG_BUCKET}" \
      "Key=access_logs.s3.prefix,Value=${ALB_ACCESS_LOG_PREFIX}" >/dev/null
}

upsert_query_definition() {
  local name="$1"
  local query_string="$2"
  local existing_id
  existing_id="$(
    aws logs describe-query-definitions \
      --query-definition-name-prefix "${name}" \
      --query "queryDefinitions[?name==\`${name}\`].queryDefinitionId | [0]" \
      --output text
  )"
  if [ "${existing_id}" = "None" ] || [ -z "${existing_id}" ]; then
    aws logs put-query-definition \
      --name "${name}" \
      --log-group-names "${BACKEND_LOG_GROUP}" \
      --query-string "${query_string}" >/dev/null
    return
  fi

  aws logs put-query-definition \
    --query-definition-id "${existing_id}" \
    --name "${name}" \
    --log-group-names "${BACKEND_LOG_GROUP}" \
    --query-string "${query_string}" >/dev/null
}

put_usage_queries() {
  upsert_query_definition \
    "Mira Usage - Top Pages" \
    $'fields @timestamp, @message\n| filter @message like /MIRA_USAGE/\n| parse @message /MIRA_USAGE (?<usage_json>\\{.*\\})/\n| fields jsonParse(usage_json) as usage\n| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"\n| stats count() as pageviews, count_distinct(usage.client_session_id) as sessions by usage.path, usage.module_id\n| sort pageviews desc\n| limit 50'

  upsert_query_definition \
    "Mira Usage - Top Visitors" \
    $'fields @timestamp, @message\n| filter @message like /MIRA_USAGE/\n| parse @message /MIRA_USAGE (?<usage_json>\\{.*\\})/\n| fields jsonParse(usage_json) as usage\n| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"\n| stats count() as pageviews, count_distinct(usage.path) as distinct_pages by usage.client_ip, usage.auth_user.username\n| sort pageviews desc\n| limit 50'

  upsert_query_definition \
    "Mira Usage - Pageviews Over Time" \
    $'fields @timestamp, @message\n| filter @message like /MIRA_USAGE/\n| parse @message /MIRA_USAGE (?<usage_json>\\{.*\\})/\n| fields jsonParse(usage_json) as usage\n| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"\n| stats count() as pageviews, count_distinct(usage.client_session_id) as sessions by bin(1h)\n| sort bin(1h) asc'

  upsert_query_definition \
    "Mira Usage - Recent Pageviews" \
    $'fields @timestamp, @message\n| filter @message like /MIRA_USAGE/\n| parse @message /MIRA_USAGE (?<usage_json>\\{.*\\})/\n| fields jsonParse(usage_json) as usage\n| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"\n| display @timestamp, usage.path, usage.module_id, usage.client_ip, usage.auth_user.username, usage.client_session_id, usage.user_agent\n| sort @timestamp desc\n| limit 100'
}

put_usage_dashboard() {
  local dashboard_body
  dashboard_body="$(cat <<JSON
{
  "widgets": [
    {
      "type": "metric",
      "x": 0,
      "y": 0,
      "width": 12,
      "height": 6,
      "properties": {
        "region": "${AWS_REGION}",
        "title": "ALB Requests and Latency",
        "view": "timeSeries",
        "stacked": false,
        "metrics": [
          ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", "${ALB_DIMENSION}", {"stat": "Sum", "label": "Requests"}],
          [".", "TargetResponseTime", ".", ".", {"stat": "Average", "label": "Target Response Time"}]
        ]
      }
    },
    {
      "type": "metric",
      "x": 12,
      "y": 0,
      "width": 12,
      "height": 6,
      "properties": {
        "region": "${AWS_REGION}",
        "title": "ALB Error Rates",
        "view": "timeSeries",
        "stacked": false,
        "metrics": [
          ["AWS/ApplicationELB", "HTTPCode_Target_4XX_Count", "LoadBalancer", "${ALB_DIMENSION}", {"stat": "Sum", "label": "Target 4XX"}],
          [".", "HTTPCode_Target_5XX_Count", ".", ".", {"stat": "Sum", "label": "Target 5XX"}],
          [".", "HTTPCode_ELB_5XX_Count", ".", ".", {"stat": "Sum", "label": "ALB 5XX"}]
        ]
      }
    },
    {
      "type": "metric",
      "x": 0,
      "y": 6,
      "width": 12,
      "height": 6,
      "properties": {
        "region": "${AWS_REGION}",
        "title": "ECS Service CPU",
        "view": "timeSeries",
        "stacked": false,
        "metrics": [
          ["AWS/ECS", "CPUUtilization", "ClusterName", "${CLUSTER}", "ServiceName", "${BACKEND_SERVICE}", {"stat": "Average", "label": "Backend CPU"}],
          [".", "CPUUtilization", ".", ".", "ServiceName", "${FRONTEND_SERVICE}", {"stat": "Average", "label": "Frontend CPU"}]
        ]
      }
    },
    {
      "type": "metric",
      "x": 12,
      "y": 6,
      "width": 12,
      "height": 6,
      "properties": {
        "region": "${AWS_REGION}",
        "title": "ECS Service Memory",
        "view": "timeSeries",
        "stacked": false,
        "metrics": [
          ["AWS/ECS", "MemoryUtilization", "ClusterName", "${CLUSTER}", "ServiceName", "${BACKEND_SERVICE}", {"stat": "Average", "label": "Backend Memory"}],
          [".", "MemoryUtilization", ".", ".", "ServiceName", "${FRONTEND_SERVICE}", {"stat": "Average", "label": "Frontend Memory"}]
        ]
      }
    },
    {
      "type": "log",
      "x": 0,
      "y": 12,
      "width": 12,
      "height": 8,
      "properties": {
        "region": "${AWS_REGION}",
        "title": "Top Mira Pages",
        "view": "table",
        "query": "SOURCE '${BACKEND_LOG_GROUP}' | filter @message like /MIRA_USAGE/ | parse @message /MIRA_USAGE (?<usage_json>\\\\{.*\\\\})/ | fields jsonParse(usage_json) as usage | filter usage.record_type = \\"mira_usage\\" and usage.event_type = \\"pageview\\" | stats count() as pageviews, count_distinct(usage.client_session_id) as sessions by usage.path, usage.module_id | sort pageviews desc | limit 20"
      }
    },
    {
      "type": "log",
      "x": 12,
      "y": 12,
      "width": 12,
      "height": 8,
      "properties": {
        "region": "${AWS_REGION}",
        "title": "Recent Mira Visitors",
        "view": "table",
        "query": "SOURCE '${BACKEND_LOG_GROUP}' | filter @message like /MIRA_USAGE/ | parse @message /MIRA_USAGE (?<usage_json>\\\\{.*\\\\})/ | fields jsonParse(usage_json) as usage, @timestamp | filter usage.record_type = \\"mira_usage\\" and usage.event_type = \\"pageview\\" | display @timestamp, usage.path, usage.client_ip, usage.auth_user.username, usage.client_session_id | sort @timestamp desc | limit 50"
      }
    }
  ]
}
JSON
)"
  aws cloudwatch put-dashboard \
    --dashboard-name "${USAGE_DASHBOARD_NAME}" \
    --dashboard-body "${dashboard_body}" >/dev/null
}

ensure_usage_log_bucket
enable_container_insights
enable_alb_access_logs
put_usage_queries
put_usage_dashboard

echo "Usage observability configured:"
echo "  ALB access log bucket: ${USAGE_LOG_BUCKET}"
echo "  Dashboard: ${USAGE_DASHBOARD_NAME}"
echo "  Logs Insights queries: Mira Usage - *"
