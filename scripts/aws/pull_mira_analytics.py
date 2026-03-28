#!/usr/bin/env python3
"""Pull live MIRA usage and auth analytics from AWS.

This script reads the current production telemetry surfaces already in use:
- CloudWatch Logs Insights on /ecs/mira-prod-backend for MIRA_USAGE pageviews
- CloudWatch Logs Insights on /mira/audit for auth failures / ITAR audit events
- CloudTrail Cognito events for signup and auth lifecycle visibility

It does not require any repo-local state. It shells out to the AWS CLI so it
works anywhere the existing GovCloud CLI workflow already works.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = "govcloud"
DEFAULT_REGION = "us-gov-west-1"
DEFAULT_BACKEND_LOG_GROUP = "/ecs/mira-prod-backend"
DEFAULT_AUDIT_LOG_GROUP = "/mira/audit"


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    rows: list[dict[str, Any]]
    columns: list[str]
    note: str | None = None


def _run_aws(
    args: list[str],
    *,
    profile: str,
    region: str,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["AWS_PROFILE"] = profile
    env["AWS_REGION"] = region
    env["AWS_DEFAULT_REGION"] = region
    env["AWS_PAGER"] = ""
    command = ["aws", *args, "--output", "json"]
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"AWS CLI command failed ({' '.join(command)}):\n{completed.stderr.strip()}"
        )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}


def _start_logs_query(
    *,
    profile: str,
    region: str,
    log_group: str,
    start_time: int,
    end_time: int,
    query: str,
) -> str:
    response = _run_aws(
        [
            "logs",
            "start-query",
            "--log-group-name",
            log_group,
            "--start-time",
            str(start_time),
            "--end-time",
            str(end_time),
            "--query-string",
            query,
        ],
        profile=profile,
        region=region,
    )
    query_id = response.get("queryId")
    if not query_id:
        raise RuntimeError(f"CloudWatch Logs query did not return queryId for {log_group}")
    return query_id


def _await_logs_query(
    *,
    profile: str,
    region: str,
    query_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_response: dict[str, Any] = {}
    while time.time() < deadline:
        response = _run_aws(
            ["logs", "get-query-results", "--query-id", query_id],
            profile=profile,
            region=region,
        )
        last_response = response
        status = response.get("status")
        if status == "Complete":
            return response
        if status in {"Failed", "Cancelled", "Timeout", "Unknown"}:
            raise RuntimeError(f"CloudWatch Logs query {query_id} ended with status={status}")
        time.sleep(1)
    raise RuntimeError(
        f"CloudWatch Logs query {query_id} timed out after {timeout_seconds}s. "
        f"Last status={last_response.get('status')}"
    )


def _flatten_logs_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in response.get("results", []):
        item: dict[str, Any] = {}
        for cell in row:
            field = cell.get("field")
            if not field or field == "@ptr":
                continue
            item[field] = cell.get("value")
        rows.append(item)
    return rows


def _logs_insights_rows(
    *,
    profile: str,
    region: str,
    log_group: str,
    start_time: int,
    end_time: int,
    query: str,
) -> list[dict[str, Any]]:
    query_id = _start_logs_query(
        profile=profile,
        region=region,
        log_group=log_group,
        start_time=start_time,
        end_time=end_time,
        query=query,
    )
    response = _await_logs_query(profile=profile, region=region, query_id=query_id)
    return _flatten_logs_rows(response)


def _cloudtrail_events(
    *,
    profile: str,
    region: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    next_token: str | None = None
    interesting_names = {
        "SignUp",
        "ConfirmSignUp",
        "InitiateAuth",
        "RespondToAuthChallenge",
        "ForgotPassword",
        "ConfirmForgotPassword",
        "ResendConfirmationCode",
    }

    while len(events) < limit:
        args = [
            "cloudtrail",
            "lookup-events",
            "--lookup-attributes",
            "AttributeKey=EventSource,AttributeValue=cognito-idp.amazonaws.com",
            "--start-time",
            start.isoformat(),
            "--end-time",
            end.isoformat(),
            "--max-results",
            "50",
        ]
        if next_token:
            args.extend(["--next-token", next_token])

        response = _run_aws(args, profile=profile, region=region)
        for event in response.get("Events", []):
            event_name = event.get("EventName")
            if event_name not in interesting_names:
                continue
            detail_raw = event.get("CloudTrailEvent") or "{}"
            try:
                detail = json.loads(detail_raw)
            except json.JSONDecodeError:
                detail = {}
            request_parameters = detail.get("requestParameters") or {}
            events.append(
                {
                    "time": event.get("EventTime"),
                    "name": event_name,
                    "source_ip": detail.get("sourceIPAddress"),
                    "user_agent": detail.get("userAgent"),
                    "client_id": request_parameters.get("clientId"),
                    "username": request_parameters.get("username"),
                }
            )
            if len(events) >= limit:
                break

        next_token = response.get("NextToken")
        if not next_token:
            break

    return events


def _pageview_sections(
    *,
    profile: str,
    region: str,
    log_group: str,
    start_time: int,
    end_time: int,
    limit: int,
) -> list[Section]:
    expanded_limit = max(limit * 20, 250)

    recent_pageviews_query = f"""
fields @timestamp, @message
| filter @message like /MIRA_USAGE/
| parse @message /MIRA_USAGE (?<usage_json>\\{{.*\\}})/
| fields jsonParse(usage_json) as usage
| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"
| display @timestamp, usage.path, usage.module_id, usage.auth_user.username, usage.auth_user.email, usage.client_ip, usage.client_session_id
| sort @timestamp desc
| limit {expanded_limit}
""".strip()

    top_pages_query = f"""
fields @message
| filter @message like /MIRA_USAGE/
| parse @message /MIRA_USAGE (?<usage_json>\\{{.*\\}})/
| fields jsonParse(usage_json) as usage
| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"
| stats count() as pageviews, count_distinct(usage.client_session_id) as sessions by usage.path, usage.module_id
| sort pageviews desc
| limit {limit}
""".strip()

    top_visitors_query = f"""
fields @message
| filter @message like /MIRA_USAGE/
| parse @message /MIRA_USAGE (?<usage_json>\\{{.*\\}})/
| fields jsonParse(usage_json) as usage
| filter usage.record_type = "mira_usage" and usage.event_type = "pageview"
| stats count() as pageviews, count_distinct(usage.path) as distinct_pages by usage.auth_user.username, usage.auth_user.email, usage.client_ip
| sort pageviews desc
| limit {limit}
""".strip()

    signup_events_query = f"""
fields @timestamp, @message
| filter @message like /MIRA_USAGE/
| parse @message /MIRA_USAGE (?<usage_json>\\{{.*\\}})/
| fields jsonParse(usage_json) as usage
| filter usage.record_type = "mira_usage" and usage.event_type = "signup_complete"
| display @timestamp, usage.auth_user.username, usage.auth_user.email, usage.client_ip, usage.client_session_id, usage.path
| sort @timestamp desc
| limit {limit}
""".strip()

    recent_pageviews = _logs_insights_rows(
        profile=profile,
        region=region,
        log_group=log_group,
        start_time=start_time,
        end_time=end_time,
        query=recent_pageviews_query,
    )
    top_pages = _logs_insights_rows(
        profile=profile,
        region=region,
        log_group=log_group,
        start_time=start_time,
        end_time=end_time,
        query=top_pages_query,
    )
    top_visitors = _logs_insights_rows(
        profile=profile,
        region=region,
        log_group=log_group,
        start_time=start_time,
        end_time=end_time,
        query=top_visitors_query,
    )
    signup_events = _logs_insights_rows(
        profile=profile,
        region=region,
        log_group=log_group,
        start_time=start_time,
        end_time=end_time,
        query=signup_events_query,
    )
    signup_journeys = _signup_journeys(signup_events=signup_events, pageviews=recent_pageviews)

    return [
        Section(
            key="recent_pageviews",
            title="Recent Pageviews",
            rows=recent_pageviews[:limit],
            columns=[
                "@timestamp",
                "usage.path",
                "usage.module_id",
                "usage.auth_user.username",
                "usage.auth_user.email",
                "usage.client_ip",
                "usage.client_session_id",
            ],
        ),
        Section(
            key="top_pages",
            title="Top Pages",
            rows=top_pages,
            columns=["usage.path", "usage.module_id", "pageviews", "sessions"],
        ),
        Section(
            key="top_visitors",
            title="Top Visitors",
            rows=top_visitors,
            columns=[
                "usage.auth_user.username",
                "usage.auth_user.email",
                "usage.client_ip",
                "pageviews",
                "distinct_pages",
            ],
        ),
        Section(
            key="signup_complete_events",
            title="Signup Complete Events",
            rows=signup_events,
            columns=[
                "@timestamp",
                "usage.auth_user.username",
                "usage.auth_user.email",
                "usage.client_ip",
                "usage.client_session_id",
                "usage.path",
            ],
            note=(
                "These require app-side signup telemetry. If this section is empty, "
                "Cognito signup is still only visible through CloudTrail below."
            ),
        ),
        Section(
            key="signup_journeys",
            title="Signup Journeys",
            rows=signup_journeys,
            columns=[
                "signup_time",
                "username",
                "email",
                "page_path",
                "module_id",
                "pageviews",
                "first_pageview",
                "last_pageview",
            ],
            note=(
                "This is the direct answer for beta operations: each confirmed signup "
                "and the pages that account hit inside the selected window."
            ),
        ),
    ]


def _audit_sections(
    *,
    profile: str,
    region: str,
    log_group: str,
    start_time: int,
    end_time: int,
    limit: int,
) -> list[Section]:
    auth_failures_query = f"""
fields @timestamp, jsonParse(@message) as evt
| filter evt.event_category = "AUTH"
| display @timestamp, evt.event_type, evt.username, evt.ip_address, evt.details.path, evt.details.reason, evt.details.status
| sort @timestamp desc
| limit {limit}
""".strip()

    itar_access_query = f"""
fields @timestamp, jsonParse(@message) as evt
| filter evt.event_category = "ITAR_ACCESS"
| display @timestamp, evt.username, evt.action, evt.resource_type, evt.resource_id, evt.access_granted
| sort @timestamp desc
| limit {limit}
""".strip()

    auth_failures = _logs_insights_rows(
        profile=profile,
        region=region,
        log_group=log_group,
        start_time=start_time,
        end_time=end_time,
        query=auth_failures_query,
    )
    itar_access = _logs_insights_rows(
        profile=profile,
        region=region,
        log_group=log_group,
        start_time=start_time,
        end_time=end_time,
        query=itar_access_query,
    )

    return [
        Section(
            key="recent_auth_events",
            title="Recent Auth Audit Events",
            rows=auth_failures,
            columns=[
                "@timestamp",
                "evt.event_type",
                "evt.username",
                "evt.ip_address",
                "evt.details.path",
                "evt.details.reason",
                "evt.details.status",
            ],
            note="This log is strongest for failures / probes. Successful sign-in is better sourced from CloudTrail.",
        ),
        Section(
            key="recent_itar_access",
            title="Recent ITAR Access Audit Events",
            rows=itar_access,
            columns=[
                "@timestamp",
                "evt.username",
                "evt.action",
                "evt.resource_type",
                "evt.resource_id",
                "evt.access_granted",
            ],
        ),
    ]


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _format_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "(no rows)"

    widths: dict[str, int] = {}
    for column in columns:
        widths[column] = len(column)
    for row in rows:
        for column in columns:
            widths[column] = min(max(widths[column], len(_format_cell(row.get(column)))), 80)

    def render_row(row: dict[str, Any] | None = None) -> str:
        cells = []
        for column in columns:
            value = column if row is None else _format_cell(row.get(column))
            if len(value) > widths[column]:
                value = value[: widths[column] - 3] + "..."
            cells.append(value.ljust(widths[column]))
        return " | ".join(cells)

    header = render_row(None)
    divider = "-+-".join("-" * widths[column] for column in columns)
    lines = [header, divider]
    for row in rows:
        lines.append(render_row(row))
    return "\n".join(lines)


def _normalized_signup_key(row: dict[str, Any]) -> tuple[str, str]:
    username = (row.get("usage.auth_user.username") or "").strip().lower()
    email = (row.get("usage.auth_user.email") or "").strip().lower()
    return username, email


def _signup_journeys(
    *,
    signup_events: list[dict[str, Any]],
    pageviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pageview_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for pageview in pageviews:
        key = _normalized_signup_key(pageview)
        if not any(key):
            continue
        pageview_index.setdefault(key, []).append(pageview)

    journeys: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for signup in signup_events:
        key = _normalized_signup_key(signup)
        signup_time = signup.get("@timestamp") or ""
        username = signup.get("usage.auth_user.username") or ""
        email = signup.get("usage.auth_user.email") or ""
        matches = pageview_index.get(key, [])

        if not matches:
            journeys.append(
                {
                    "signup_time": signup_time,
                    "username": username,
                    "email": email,
                    "page_path": "",
                    "module_id": "",
                    "pageviews": 0,
                    "first_pageview": "",
                    "last_pageview": "",
                }
            )
            continue

        per_path: dict[tuple[str, str], dict[str, Any]] = {}
        for match in matches:
            event_time = match.get("@timestamp") or ""
            if signup_time and event_time and event_time < signup_time:
                continue
            path = match.get("usage.path") or ""
            module_id = match.get("usage.module_id") or ""
            bucket = per_path.setdefault(
                (path, module_id),
                {
                    "signup_time": signup_time,
                    "username": username,
                    "email": email,
                    "page_path": path,
                    "module_id": module_id,
                    "pageviews": 0,
                    "first_pageview": match.get("@timestamp") or "",
                    "last_pageview": match.get("@timestamp") or "",
                },
            )
            bucket["pageviews"] += 1
            if event_time and (
                not bucket["first_pageview"] or event_time < bucket["first_pageview"]
            ):
                bucket["first_pageview"] = event_time
            if event_time and (
                not bucket["last_pageview"] or event_time > bucket["last_pageview"]
            ):
                bucket["last_pageview"] = event_time

        if not per_path:
            journeys.append(
                {
                    "signup_time": signup_time,
                    "username": username,
                    "email": email,
                    "page_path": "",
                    "module_id": "",
                    "pageviews": 0,
                    "first_pageview": "",
                    "last_pageview": "",
                }
            )
            continue

        for row in per_path.values():
            dedupe_key = (
                row["signup_time"],
                row["username"],
                row["email"],
                row["page_path"],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            journeys.append(row)

    journeys.sort(
        key=lambda row: (
            row.get("signup_time") or "",
            row.get("pageviews") or 0,
            row.get("page_path") or "",
        ),
        reverse=True,
    )
    return journeys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull live MIRA analytics from AWS.")
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE", DEFAULT_PROFILE))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days.")
    parser.add_argument("--limit", type=int, default=25, help="Row limit per section.")
    parser.add_argument(
        "--backend-log-group",
        default=DEFAULT_BACKEND_LOG_GROUP,
        help="CloudWatch log group containing MIRA_USAGE events.",
    )
    parser.add_argument(
        "--audit-log-group",
        default=DEFAULT_AUDIT_LOG_GROUP,
        help="CloudWatch log group containing auth/ITAR audit events.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text tables.",
    )
    parser.add_argument(
        "--write-json",
        type=Path,
        help="Optional path to write the full JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=args.days)
    start_epoch = int(start.timestamp())
    end_epoch = int(now.timestamp())

    sections: list[Section] = []
    sections.extend(
        _pageview_sections(
            profile=args.profile,
            region=args.region,
            log_group=args.backend_log_group,
            start_time=start_epoch,
            end_time=end_epoch,
            limit=args.limit,
        )
    )
    sections.extend(
        _audit_sections(
            profile=args.profile,
            region=args.region,
            log_group=args.audit_log_group,
            start_time=start_epoch,
            end_time=end_epoch,
            limit=args.limit,
        )
    )

    cognito_events = _cloudtrail_events(
        profile=args.profile,
        region=args.region,
        start=start,
        end=now,
        limit=args.limit,
    )
    sections.append(
        Section(
            key="recent_cognito_events",
            title="Recent Cognito Events",
            rows=cognito_events,
            columns=["time", "name", "source_ip", "user_agent", "client_id", "username"],
            note=(
                "CloudTrail is the source of truth for signup/auth lifecycle events, "
                "but Cognito often redacts usernames in auth event payloads."
            ),
        )
    )

    report = {
        "generated_at": now.isoformat(),
        "profile": args.profile,
        "region": args.region,
        "lookback_days": args.days,
        "backend_log_group": args.backend_log_group,
        "audit_log_group": args.audit_log_group,
        "sections": [
            {
                "key": section.key,
                "title": section.title,
                "note": section.note,
                "columns": section.columns,
                "rows": section.rows,
            }
            for section in sections
        ],
    }

    if args.write_json:
        args.write_json.parent.mkdir(parents=True, exist_ok=True)
        args.write_json.write_text(json.dumps(report, indent=2))

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(
        f"MIRA analytics report | profile={args.profile} region={args.region} "
        f"window={start.isoformat()} -> {now.isoformat()}"
    )
    print()
    for section in sections:
        print(f"== {section.title} ==")
        if section.note:
            print(section.note)
        print(_format_table(section.rows, section.columns))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
