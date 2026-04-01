#!/usr/bin/env python3
"""
Structured audit logging to CloudWatch for auth and controlled-content access.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - exercised in lightweight test envs
    boto3 = None

    class ClientError(Exception):
        """Fallback exception type when botocore is unavailable."""

LOGGER = logging.getLogger("mira.audit")

AUDIT_LOG_GROUP = os.getenv("AUDIT_LOG_GROUP", "/mira/audit")
AUDIT_LOG_STREAM_PREFIX = os.getenv("AUDIT_LOG_STREAM_PREFIX", "mira-auth")
REGION = os.getenv("COGNITO_REGION", "us-gov-west-1")
RETENTION_DAYS = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "1827"))
ENABLE_AUDIT_LOGGING = os.getenv("ENABLE_AUDIT_LOGGING", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_cw_client = None
_sequence_tokens: dict[str, str] = {}
_warned_boto3_missing = False


def _get_cw_client():
    global _cw_client
    if boto3 is None:
        raise RuntimeError("boto3 is not installed; audit logging is unavailable")
    if _cw_client is None:
        _cw_client = boto3.client("logs", region_name=REGION)
        _ensure_log_group(_cw_client)
    return _cw_client


def _ensure_log_group(client) -> None:
    try:
        client.create_log_group(logGroupName=AUDIT_LOG_GROUP)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code != "ResourceAlreadyExistsException":
            raise
    try:
        client.put_retention_policy(
            logGroupName=AUDIT_LOG_GROUP,
            retentionInDays=RETENTION_DAYS,
        )
    except ClientError as exc:
        LOGGER.error("Failed setting retention policy on %s: %s", AUDIT_LOG_GROUP, exc)


def _stream_name() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{AUDIT_LOG_STREAM_PREFIX}/{today}"


def _ensure_log_stream(client, stream_name: str) -> None:
    try:
        client.create_log_stream(
            logGroupName=AUDIT_LOG_GROUP,
            logStreamName=stream_name,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code != "ResourceAlreadyExistsException":
            raise


def _extract_expected_sequence_token(exc: ClientError) -> Optional[str]:
    err = exc.response.get("Error", {})
    token = err.get("expectedSequenceToken")
    if token:
        return token
    message = err.get("Message", "") or ""
    marker = "expected sequenceToken is: "
    if marker in message:
        return message.split(marker, 1)[-1].strip()
    return None


def _put_log_event(payload: dict[str, Any]) -> None:
    global _warned_boto3_missing
    if not ENABLE_AUDIT_LOGGING:
        return
    if boto3 is None:
        if not _warned_boto3_missing:
            LOGGER.warning("Audit logging is enabled but boto3 is not installed; skipping CloudWatch audit events.")
            _warned_boto3_missing = True
        return

    try:
        client = _get_cw_client()
        stream_name = _stream_name()
        _ensure_log_stream(client, stream_name)
    except Exception as exc:  # pragma: no cover
        LOGGER.error("CloudWatch init failed: %s", exc)
        return

    args: dict[str, Any] = {
        "logGroupName": AUDIT_LOG_GROUP,
        "logStreamName": stream_name,
        "logEvents": [
            {
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(payload, default=str),
            }
        ],
    }

    token = _sequence_tokens.get(stream_name)
    if token:
        args["sequenceToken"] = token

    try:
        response = client.put_log_events(**args)
        next_token = response.get("nextSequenceToken")
        if next_token:
            _sequence_tokens[stream_name] = next_token
        return
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"InvalidSequenceTokenException", "DataAlreadyAcceptedException"}:
            LOGGER.error("CloudWatch put_log_events failed: %s", exc)
            return
        expected = _extract_expected_sequence_token(exc)
        if not expected:
            LOGGER.error("CloudWatch token error without expected token: %s", exc)
            return
        args["sequenceToken"] = expected
        try:
            response = client.put_log_events(**args)
            next_token = response.get("nextSequenceToken")
            if next_token:
                _sequence_tokens[stream_name] = next_token
        except ClientError as retry_exc:
            LOGGER.error("CloudWatch retry put_log_events failed: %s", retry_exc)


def log_auth_event(
    event_type: str,
    username: str,
    success: bool,
    ip_address: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    event = {
        "event_category": "AUTH",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "success": success,
        "ip_address": ip_address,
        "details": details or {},
    }
    _put_log_event(event)
    LOGGER.info("AUTH event=%s user=%s success=%s", event_type, username, success)


def log_itar_access(
    username: str,
    action: str,
    resource_type: str,
    resource_id: str,
    classification: str = "ITAR",
    granted: bool = True,
    details: Optional[dict[str, Any]] = None,
) -> None:
    event = {
        "event_category": "ITAR_ACCESS",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "classification": classification,
        "access_granted": granted,
        "details": details or {},
    }
    _put_log_event(event)

    level = logging.INFO if granted else logging.WARNING
    LOGGER.log(
        level,
        "ITAR action=%s resource=%s id=%s user=%s granted=%s",
        action,
        resource_type,
        resource_id,
        username,
        granted,
    )


def log_query(
    username: str,
    query_text: str,
    pipeline: str,
    response_contains_itar: bool = False,
    details: Optional[dict[str, Any]] = None,
) -> None:
    event = {
        "event_category": "QUERY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "query_text": query_text[:500],
        "pipeline": pipeline,
        "response_contains_itar": response_contains_itar,
        "details": details or {},
    }
    _put_log_event(event)


def log_admin_action(
    username: str,
    action: str,
    target: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    event = {
        "event_category": "ADMIN",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "action": action,
        "target": target,
        "details": details or {},
    }
    _put_log_event(event)
    LOGGER.info("ADMIN action=%s target=%s user=%s", action, target, username)
