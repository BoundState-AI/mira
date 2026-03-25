# Mira Usage Observability

Mira is a single-page application. That matters for analytics:

- ALB access logs tell you who hit the site and raw request paths at the load balancer.
- They do **not** tell you which internal React page a user navigated to after the initial `/` page load.
- App-side page telemetry fills that gap by logging route-level pageviews to the backend log stream.

## What is captured

App-side usage events log:

- `path`
- `module_id`
- `page_label`
- `navigation_type`
- `client_session_id`
- `client_ip`
- `user_agent`
- `auth_user` when Cognito auth is enabled

The telemetry intentionally excludes query strings and entered form values.

## AWS resources

`scripts/aws/ensure_mira_usage_observability.sh` configures:

- ECS Container Insights on `mira-prod-cluster`
- ALB access logs for `mira-prod-alb`
- S3 bucket for ALB access logs
- CloudWatch dashboard `Mira-Prod-Usage`
- Saved CloudWatch Logs Insights queries named `Mira Usage - *`

## Where to look

High-level traffic and health:

- CloudWatch dashboard: `Mira-Prod-Usage`

Route-level page analytics:

- CloudWatch Logs Insights over `/ecs/mira-prod-backend`
- Saved queries:
  - `Mira Usage - Top Pages`
  - `Mira Usage - Top Visitors`
  - `Mira Usage - Pageviews Over Time`
  - `Mira Usage - Recent Pageviews`

Raw request logs at the edge:

- S3 bucket created by the usage-observability script
- Prefix: `alb-access/AWSLogs/<account-id>/...`

## Useful ad hoc query

```sql
fields @timestamp, @message
| filter @message like /MIRA_USAGE/
| parse @message /MIRA_USAGE (?<usage_json>\{.*\})/
| fields jsonParse(usage_json) as usage
| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"
| stats count() as pageviews, count_distinct(usage.client_session_id) as sessions by usage.path, usage.module_id
| sort pageviews desc
| limit 50
```
