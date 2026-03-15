#!/usr/bin/env python3
"""
Authenticated post-deploy smoke checks for the GovCloud runtime.

The default mode provisions a disposable Cognito user, completes software-token
MFA setup if challenged, runs a protected-route smoke slice, and then deletes
the user. This gives the deploy flow a real authenticated check without
depending on a long-lived human token.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import struct
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from urllib import error, request

import boto3


@dataclass(frozen=True)
class AuthRouteCheck:
    path: str
    description: str
    validate: Callable[[dict[str, object]], None]


def _validate_tocr_guidance(payload: dict[str, object]) -> None:
    if payload.get("pack_id") != "tocr-guidance-v1":
        raise RuntimeError(f"Unexpected TOCR guidance pack_id: {payload.get('pack_id')!r}")
    if not isinstance(payload.get("entries"), dict):
        raise RuntimeError("TOCR guidance payload missing entries map")


def _validate_ping(expected_domain: str) -> Callable[[dict[str, object]], None]:
    def _validator(payload: dict[str, object]) -> None:
        if payload.get("status") != "ok" or payload.get("domain") != expected_domain:
            raise RuntimeError(f"Unexpected ping payload: {payload!r}")

    return _validator


def _validate_h2_guidance(payload: dict[str, object]) -> None:
    materials = payload.get("materials") or []
    if not isinstance(materials, list) or len(materials) < 100:
        raise RuntimeError("H2 materials payload is unexpectedly small")
    if "Inconel 718" not in materials:
        raise RuntimeError("H2 materials payload missing Inconel 718")
    if int(payload.get("count") or 0) < len(materials):
        raise RuntimeError("H2 materials payload has invalid count metadata")


AUTH_ROUTE_CHECKS: tuple[AuthRouteCheck, ...] = (
    AuthRouteCheck("/api/tocr/guidance", "TOCR guidance pack", _validate_tocr_guidance),
    AuthRouteCheck("/api/forge/ping", "FORGE authenticated ping", _validate_ping("forge")),
    AuthRouteCheck("/api/mp-plan/v2/ping", "M&P Plan v2 authenticated ping", _validate_ping("mp_plan_v2_codex")),
    AuthRouteCheck("/api/mua/v10/ping", "MUA v10 authenticated ping", _validate_ping("mua-v10")),
    AuthRouteCheck("/api/mira/h2/materials", "H2 materials payload", _validate_h2_guidance),
)


def _totp(secret: str, digits: int = 6, period_seconds: int = 30) -> str:
    normalized = secret.strip().replace(" ", "").upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding, casefold=True)
    counter = int(time.time() // period_seconds)
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return f"{code:0{digits}d}"


def _fetch_json(base_url: str, path: str, access_token: str) -> tuple[int, dict[str, object]]:
    req = request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "mira-auth-smoke/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            status = response.getcode()
            body = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} returned non-JSON body: {body[:240]!r}") from exc
    return status, payload


def _run_route_checks(base_url: str, access_token: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for check in AUTH_ROUTE_CHECKS:
        status, payload = _fetch_json(base_url, check.path, access_token)
        if status != 200:
            raise RuntimeError(f"{check.path} returned HTTP {status}: {payload!r}")
        check.validate(payload)
        print(f"{check.path}: 200 ({check.description})")
        results.append(
            {
                "path": check.path,
                "status": status,
                "description": check.description,
                "payload_excerpt": json.dumps(payload, sort_keys=True)[:240],
            }
        )
    return results


def _cognito_client(region: str):
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.session.Session(profile_name=profile, region_name=region)
    return session.client("cognito-idp")


def _random_password() -> str:
    return f"TmpSmoke!{uuid.uuid4().hex[:10]}Aa9"


def _create_disposable_user(client, user_pool_id: str, *, group_name: str) -> tuple[str, str]:
    username = f"mira-deploy-smoke-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    password = _random_password()
    email = f"{username}@example.invalid"

    client.admin_create_user(
        UserPoolId=user_pool_id,
        Username=username,
        TemporaryPassword=password,
        MessageAction="SUPPRESS",
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ],
    )
    client.admin_set_user_password(
        UserPoolId=user_pool_id,
        Username=username,
        Password=password,
        Permanent=True,
    )
    if group_name:
        client.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName=group_name,
        )
    return username, password


def _respond_with_totp(client, client_id: str, username: str, session: str, secret: str) -> dict:
    return client.respond_to_auth_challenge(
        ClientId=client_id,
        ChallengeName="SOFTWARE_TOKEN_MFA",
        Session=session,
        ChallengeResponses={
            "USERNAME": username,
            "SOFTWARE_TOKEN_MFA_CODE": _totp(secret),
        },
    )


def _authenticate_with_password(
    client,
    *,
    client_id: str,
    username: str,
    password: str,
    totp_secret: str | None = None,
) -> tuple[str, str | None]:
    response = client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": password,
        },
    )

    if "AuthenticationResult" in response:
        return response["AuthenticationResult"]["AccessToken"], totp_secret

    challenge = response.get("ChallengeName")
    if challenge == "SOFTWARE_TOKEN_MFA":
        if not totp_secret:
            raise RuntimeError("SOFTWARE_TOKEN_MFA challenge received but no TOTP secret is available.")
        mfa_response = _respond_with_totp(client, client_id, username, response["Session"], totp_secret)
        return mfa_response["AuthenticationResult"]["AccessToken"], totp_secret

    if challenge != "MFA_SETUP":
        raise RuntimeError(f"Unsupported Cognito challenge during smoke auth: {challenge!r}")

    association = client.associate_software_token(Session=response["Session"])
    issued_secret = association["SecretCode"]
    verification = client.verify_software_token(
        Session=association["Session"],
        UserCode=_totp(issued_secret),
        FriendlyDeviceName="MIRA Deploy Smoke",
    )
    final = client.respond_to_auth_challenge(
        ClientId=client_id,
        ChallengeName="MFA_SETUP",
        Session=verification.get("Session") or association["Session"],
        ChallengeResponses={"USERNAME": username},
    )
    if "AuthenticationResult" in final:
        return final["AuthenticationResult"]["AccessToken"], issued_secret
    if final.get("ChallengeName") == "SOFTWARE_TOKEN_MFA":
        mfa_response = _respond_with_totp(client, client_id, username, final["Session"], issued_secret)
        return mfa_response["AuthenticationResult"]["AccessToken"], issued_secret
    raise RuntimeError(f"Unexpected Cognito response after MFA setup: {final!r}")


def _write_json(path: str, payload: dict[str, object]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://mira.boundstate.ai")
    parser.add_argument("--region", default=os.environ.get("COGNITO_REGION", "us-gov-west-1"))
    parser.add_argument("--user-pool-id", default=os.environ.get("COGNITO_USER_POOL_ID", ""))
    parser.add_argument("--client-id", default=os.environ.get("COGNITO_CLIENT_ID", ""))
    parser.add_argument("--group-name", default=os.environ.get("MIRA_SMOKE_GROUP", "mira-standard"))
    parser.add_argument("--access-token", default=os.environ.get("MIRA_SMOKE_ACCESS_TOKEN"))
    parser.add_argument("--username", default=os.environ.get("MIRA_SMOKE_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("MIRA_SMOKE_PASSWORD"))
    parser.add_argument("--totp-secret", default=os.environ.get("MIRA_SMOKE_TOTP_SECRET"))
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.client_id or not args.user_pool_id:
        print("Authenticated smoke failed: missing Cognito client or user pool configuration.", file=sys.stderr)
        return 1

    summary: dict[str, object] = {
        "ok": False,
        "base_url": args.base_url.rstrip("/"),
        "region": args.region,
        "user_pool_id": args.user_pool_id,
        "client_id": args.client_id,
    }

    client = _cognito_client(args.region)
    created_username: str | None = None
    access_token: str | None = None
    totp_secret = args.totp_secret
    auth_mode = "disposable_user"

    exit_code = 0
    try:
        if args.access_token:
            access_token = args.access_token
            auth_mode = "provided_token"
        else:
            if args.username and args.password:
                username = args.username
                password = args.password
                auth_mode = "provided_username_password"
            else:
                username, password = _create_disposable_user(client, args.user_pool_id, group_name=args.group_name)
                created_username = username
                auth_mode = "disposable_user"
            access_token, totp_secret = _authenticate_with_password(
                client,
                client_id=args.client_id,
                username=username,
                password=password,
                totp_secret=totp_secret,
            )

        route_results = _run_route_checks(summary["base_url"], access_token)
        summary.update(
            {
                "ok": True,
                "auth_mode": auth_mode,
                "route_checks": route_results,
                "totp_secret_issued": bool(totp_secret),
            }
        )
    except Exception as exc:  # pragma: no cover - CLI guard
        summary["error"] = str(exc)
        print(f"Authenticated smoke failed: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if created_username:
            try:
                client.admin_delete_user(UserPoolId=args.user_pool_id, Username=created_username)
                summary["disposable_user_deleted"] = True
            except Exception as cleanup_exc:  # pragma: no cover - cleanup best effort
                summary["disposable_user_deleted"] = False
                summary["cleanup_error"] = str(cleanup_exc)

    if args.json_out:
        _write_json(args.json_out, summary)
    if exit_code == 0:
        print("Authenticated protected-route smoke passed.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
