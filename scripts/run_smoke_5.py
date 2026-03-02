#!/usr/bin/env python3
"""
Run 5 staging smoke checks against MIRA API.

Usage:
  python scripts/run_smoke_5.py
  python scripts/run_smoke_5.py --base-url http://127.0.0.1:8000
  python scripts/run_smoke_5.py --token "$MIRA_BEARER_TOKEN"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


Classification = {"ok", "caution", "prohibited", "unknown"}


@dataclass(frozen=True)
class SmokeCase:
    case_id: str
    path: str
    payload: dict[str, Any]
    check: Callable[[dict[str, Any]], tuple[bool, str]]


def _post_json(base_url: str, path: str, payload: dict[str, Any], token: str | None) -> tuple[int, dict[str, Any]]:
    url = f"{base_url.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, json.loads(raw)


def _check_h2(body: dict[str, Any]) -> tuple[bool, str]:
    c = str(body.get("classification", "")).lower()
    if c in Classification:
        return True, f"classification={c}"
    return False, "missing/invalid classification"


def _check_oos(body: dict[str, Any]) -> tuple[bool, str]:
    status = body.get("status")
    bouncer = (body.get("bouncer") or {}).get("status")
    if status == "rejected" and bouncer == "rejected":
        return True, "properly rejected out-of-scope query"
    return False, f"expected rejected/rejected, got {status}/{bouncer}"


def _check_fracture(body: dict[str, Any]) -> tuple[bool, str]:
    if body.get("status") == "ok" and body.get("fracture_result"):
        return True, "fracture_result present"
    return False, "missing fracture_result or non-ok status"


def _check_condition_norm(body: dict[str, Any]) -> tuple[bool, str]:
    c = str(body.get("classification", "")).lower()
    if c in Classification and "needs_clarification" in body:
        return True, f"classification={c}, needs_clarification={body.get('needs_clarification')}"
    return False, "missing classification or needs_clarification"


def _check_comparison(body: dict[str, Any]) -> tuple[bool, str]:
    if body.get("status") != "ok":
        return False, f"unexpected status={body.get('status')}"
    answer = str(body.get("answer", "")).lower()
    if "a286" in answer and ("718" in answer or "inconel" in answer):
        return True, "comparison answer references both materials"
    return False, "answer missing expected comparison material mentions"


def build_cases() -> list[SmokeCase]:
    return [
        SmokeCase(
            case_id="SMK-001-H2",
            path="/mira/h2/compatibility-temp",
            payload={
                "question": "Can Inconel 718 be used in high-pressure gaseous hydrogen service?",
                "material_key": "Inconel 718",
                "pressure_psia": 6000,
                "temperature_k": 294,
                "phase": "gh2",
                "condition": "ST 1900F",
            },
            check=_check_h2,
        ),
        SmokeCase(
            case_id="SMK-002-OOS",
            path="/mira/query",
            payload={"query": "What's the best restaurant in Huntsville?"},
            check=_check_oos,
        ),
        SmokeCase(
            case_id="SMK-003-FRACTURE",
            path="/mira/query",
            payload={
                "query": "Classify this pressure-vessel fitting for fracture control per NASA-STD-5019A: wrought Inconel 718, catastrophic consequence of failure, limited access for inspection."
            },
            check=_check_fracture,
        ),
        SmokeCase(
            case_id="SMK-004-CONDITION",
            path="/mira/h2/compatibility-temp",
            payload={
                "question": "Evaluate A286 in GH2 at 5000 psia with aging 1325F/8h and uncertain shop notation.",
                "material_key": "A286",
                "pressure_psia": 5000,
                "temperature_k": 295,
                "phase": "gh2",
                "condition": "aged 1325f/8h ? HT-A",
            },
            check=_check_condition_norm,
        ),
        SmokeCase(
            case_id="SMK-005-COMPARISON",
            path="/mira/query",
            payload={"query": "Compare A286 and Inconel 718 for cryogenic hydrogen valve stems."},
            check=_check_comparison,
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 5 MIRA staging smoke checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=None, help="Bearer token for auth-enabled deployments")
    args = parser.parse_args()

    failures = 0
    cases = build_cases()
    print(f"Running {len(cases)} smoke cases against {args.base_url}")
    for case in cases:
        try:
            code, body = _post_json(args.base_url, case.path, case.payload, args.token)
            if code != 200:
                failures += 1
                print(f"[FAIL] {case.case_id}: HTTP {code}")
                continue
            ok, detail = case.check(body)
            if ok:
                print(f"[PASS] {case.case_id}: {detail}")
            else:
                failures += 1
                snippet = json.dumps(body, ensure_ascii=True)[:280]
                print(f"[FAIL] {case.case_id}: {detail} | body={snippet}")
        except urllib.error.HTTPError as exc:
            failures += 1
            raw = exc.read().decode("utf-8", errors="ignore")[:280]
            print(f"[FAIL] {case.case_id}: HTTPError {exc.code} body={raw}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {case.case_id}: {exc}")

    print("-" * 72)
    if failures:
        print(f"Smoke result: {len(cases) - failures}/{len(cases)} passed")
        return 1
    print(f"Smoke result: {len(cases)}/{len(cases)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
