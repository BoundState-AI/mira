#!/usr/bin/env python3
"""
Public post-deploy smoke checks for the GovCloud runtime.

This intentionally uses unauthenticated requests so it can prove both public
health wiring and that critical protected routes are mounted on the live app.
Protected routes are considered healthy when they return an auth status instead
of 404/5xx.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib import error, request


@dataclass(frozen=True)
class RouteCheck:
    path: str
    allowed_statuses: tuple[int, ...]
    description: str
    fallback_paths: tuple[str, ...] = ()


HEALTH_CHECKS: tuple[RouteCheck, ...] = (
    RouteCheck("/health", (200,), "public ALB health endpoint"),
    RouteCheck("/api/health", (200,), "public API health endpoint"),
)

CRITICAL_ROUTE_CHECKS: tuple[RouteCheck, ...] = (
    RouteCheck("/api/chat/ping", (200, 401, 403), "chat router mounted"),
    RouteCheck("/api/tocr/ping", (200, 401, 403), "TOCR router mounted"),
    RouteCheck("/api/forge/ping", (200, 401, 403), "FORGE router mounted"),
    RouteCheck("/api/mp-plan/v2/ping", (200, 401, 403), "M&P Plan v2 router mounted"),
    RouteCheck("/api/mua/v10/ping", (200, 401, 403), "MUA v10 router mounted"),
    RouteCheck(
        "/api/oca/ping",
        (200, 401, 403),
        "OCA router mounted",
        fallback_paths=("/api/oca/oca/ping",),
    ),
    RouteCheck("/api/mira/galvanic/ping", (200, 401, 403), "galvanic router mounted"),
    RouteCheck("/api/mira/fracture/ping", (200, 401, 403), "fracture router mounted"),
    RouteCheck("/api/mira/h2/ping", (200, 401, 403), "H2 router mounted"),
)


def _fetch(url: str, *, timeout: float = 20.0) -> tuple[int, str]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "mira-deploy-smoke/1.0",
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.getcode(), response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _check_health(base_url: str, check: RouteCheck) -> dict[str, object]:
    status, body = _fetch(f"{base_url}{check.path}")
    if status != 200:
        raise RuntimeError(f"{check.path} returned {status}, expected 200")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{check.path} returned non-JSON body: {body[:200]!r}") from exc
    if payload.get("status") != "ok":
        raise RuntimeError(f"{check.path} returned unexpected health payload: {payload!r}")
    print(f"{check.path}: 200 ok")
    return {
        "path": check.path,
        "status": status,
        "description": check.description,
        "payload": payload,
    }


def _check_route(base_url: str, check: RouteCheck) -> dict[str, object]:
    attempted_paths = (check.path, *check.fallback_paths)
    attempted_results: list[dict[str, int | str]] = []
    for candidate_path in attempted_paths:
        status, _ = _fetch(f"{base_url}{candidate_path}")
        attempted_results.append({"path": candidate_path, "status": status})
        if status in check.allowed_statuses:
            print(f"{candidate_path}: {status} ({check.description})")
            return {
                "path": candidate_path,
                "status": status,
                "description": check.description,
                "allowed_statuses": list(check.allowed_statuses),
                "attempted_paths": attempted_results,
            }

    allowed = ", ".join(str(code) for code in check.allowed_statuses)
    attempted_summary = ", ".join(
        f"{result['path']}={result['status']}" for result in attempted_results
    )
    raise RuntimeError(
        f"{check.description}: none of {list(attempted_paths)!r} returned one of [{allowed}]"
        f" (saw {attempted_summary})"
    )


def _run_checks(base_url: str, checks: Iterable[RouteCheck], *, health: bool) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for check in checks:
        if health:
            results.append(_check_health(base_url, check))
        else:
            results.append(_check_route(base_url, check))
    return results


def _write_json(path: str, payload: dict[str, object]) -> None:
    output_path = Path(path)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="https://mira.boundstate.ai",
        help="Base URL for the deployed runtime",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write structured smoke results as JSON.",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    try:
        health_results = _run_checks(base_url, HEALTH_CHECKS, health=True)
        route_results = _run_checks(base_url, CRITICAL_ROUTE_CHECKS, health=False)
    except Exception as exc:  # pragma: no cover - CLI guard
        if args.json_out:
            _write_json(
                args.json_out,
                {
                    "ok": False,
                    "base_url": base_url,
                    "error": str(exc),
                },
            )
        print(f"Post-deploy smoke failed: {exc}", file=sys.stderr)
        return 1

    summary = {
        "ok": True,
        "base_url": base_url,
        "health_checks": health_results,
        "critical_route_checks": route_results,
    }
    if args.json_out:
        _write_json(args.json_out, summary)
    print("Post-deploy public smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
