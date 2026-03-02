#!/usr/bin/env python3
"""Run reproducible rationale-proof evaluation for MUA V10 classifier.

Outputs (timestamped under reports/mua_rationale_proof/):
- proof_summary.json
- proof_summary.md
- case_results.csv
- adjudication_template.csv

This script is designed to generate evidence that rationale generation is:
1) Deterministic (repeatable)
2) Structurally grounded (traceable to classifier outputs)
3) Free of unsupported precedent claims
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as a standalone script from repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.mua.classifier.pipeline import process_miul_row
from mira.mua.classifier.rationale import render_rationale, render_disposition

# Keep proof-run output readable when local precedent DB is unavailable.
logging.getLogger("mira.mua.precedent.lookup").setLevel(logging.ERROR)
logging.getLogger("mira.core.db_config").setLevel(logging.ERROR)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _load_cases(path: Path) -> list[dict[str, Any]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, list):
        raise ValueError("Cases file must contain a JSON array")
    return obj


def _find_classification(result, issue_key: str):
    issue_upper = _norm(issue_key).upper()
    for c in result.classifications:
        if c.issue_key.upper() == issue_upper:
            return c
    if result.classifications:
        return result.classifications[0]
    return None


def _find_form(result, issue_key: str):
    issue_upper = _norm(issue_key).upper()
    for f in result.forms:
        if f.issue.upper() == issue_upper:
            return f
    if result.forms:
        return result.forms[0]
    return None


def _run_single_case(case: dict[str, Any]) -> dict[str, Any]:
    cid = case["id"]
    desc = case.get("description", "")
    inp = case["input"]
    exp = case["expected"]

    run_kwargs = {
        "ratings": inp.get("ratings", {}),
        "maptis_code": _norm(inp.get("maptis_code")),
        "material_designation": _norm(inp.get("material_designation")),
        "material_class": inp.get("material_class"),
        "media": _norm(inp.get("media")),
        "environment": _norm(inp.get("environment")) or "non-habitable",
        "o2_percent": inp.get("o2_percent"),
        "batch_verified": bool(inp.get("batch_verified", False)),
        "part_numbers": inp.get("part_numbers") or None,
        "part_count": int(inp.get("part_count", 1)),
        "project": _norm(inp.get("project")),
        "system": _norm(inp.get("system")),
        "material_specification": inp.get("material_specification"),
        "pressure": _norm(inp.get("pressure")),
        "temperature": _norm(inp.get("temperature")),
    }

    first = process_miul_row(**run_kwargs)
    second = process_miul_row(**run_kwargs)

    target_issue = next(iter(inp.get("ratings", {}).keys()), "")
    c1 = _find_classification(first, target_issue)
    c2 = _find_classification(second, target_issue)

    checks: list[CheckResult] = []

    if c1 is None:
        checks.append(CheckResult("classification_exists", False, "No classification returned"))
        return {
            "case_id": cid,
            "description": desc,
            "passed": False,
            "checks": [c.__dict__ for c in checks],
            "fail_reasons": [c.detail or c.name for c in checks if not c.passed],
        }

    # Core expected checks
    checks.append(CheckResult("mua_type", c1.mua_type.value == exp.get("mua_type"), f"expected={exp.get('mua_type')} actual={c1.mua_type.value}"))
    checks.append(CheckResult("automatable", c1.automatable == exp.get("automatable"), f"expected={exp.get('automatable')} actual={c1.automatable}"))

    expected_category = exp.get("category")
    actual_category = c1.category.value if c1.category else None
    checks.append(CheckResult("category", actual_category == expected_category, f"expected={expected_category} actual={actual_category}"))

    expected_flag = exp.get("flag_type")
    actual_flag = c1.flag_type.value if c1.flag_type else None
    checks.append(CheckResult("flag_type", actual_flag == expected_flag, f"expected={expected_flag} actual={actual_flag}"))

    expected_hazard = exp.get("hazard_applies")
    checks.append(CheckResult("hazard_applies", c1.hazard_applies == expected_hazard, f"expected={expected_hazard} actual={c1.hazard_applies}"))

    if "screening_applicable" in exp:
        checks.append(
            CheckResult(
                "screening_applicable",
                c1.screening_applicable == exp["screening_applicable"],
                f"expected={exp['screening_applicable']} actual={c1.screening_applicable}",
            )
        )

    # Traceability checks
    checks.append(CheckResult("classification_reason_nonempty", bool(_norm(c1.classification_reason)), "classification_reason is empty"))

    if c1.flag_type is not None:
        checks.append(CheckResult("rating_semantics_present", c1.rating_semantics is not None, "rating_semantics missing"))

    # Determinism checks
    deterministic = True
    if c2 is None:
        deterministic = False
    else:
        deterministic = (
            c1.mua_type.value == c2.mua_type.value
            and _norm(c1.classification_reason) == _norm(c2.classification_reason)
        )
    checks.append(CheckResult("deterministic_classification", deterministic, "First and second run diverged"))

    form1 = _find_form(first, target_issue)
    form2 = _find_form(second, target_issue)

    rationale_text = ""
    disposition_text = ""
    rationale_hash = ""
    disposition_hash = ""

    if c1.automatable:
        checks.append(CheckResult("form_exists", form1 is not None, "Automatable case missing Form551"))
        if form1 is not None:
            rationale_text = _norm(form1.rationale)
            disposition_text = _norm(form1.disposition)
            rationale_hash = _sha256_text(rationale_text)
            disposition_hash = _sha256_text(disposition_text)

            checks.append(CheckResult("rationale_nonempty", bool(rationale_text), "Rationale text is empty"))
            checks.append(CheckResult("disposition_nonempty", bool(disposition_text), "Disposition text is empty"))

            # Deterministic text output
            if form2 is None:
                checks.append(CheckResult("deterministic_rationale", False, "Second run missing form"))
            else:
                r2 = _norm(form2.rationale)
                d2 = _norm(form2.disposition)
                checks.append(CheckResult("deterministic_rationale", rationale_text == r2, "Rationale text changed across runs"))
                checks.append(CheckResult("deterministic_disposition", disposition_text == d2, "Disposition text changed across runs"))

            # Must-contain and must-not-contain checks
            for needle in exp.get("rationale_must_contain", []):
                ok = needle.lower() in rationale_text.lower()
                checks.append(CheckResult(f"rationale_contains:{needle}", ok, f"Missing rationale phrase: {needle}"))

            for needle in exp.get("disposition_must_contain", []):
                ok = needle.lower() in disposition_text.lower()
                checks.append(CheckResult(f"disposition_contains:{needle}", ok, f"Missing disposition phrase: {needle}"))

            for needle in exp.get("rationale_must_not_contain", []):
                ok = needle.lower() not in rationale_text.lower()
                checks.append(CheckResult(f"rationale_excludes:{needle}", ok, f"Forbidden phrase present: {needle}"))

            # Unsupported precedent-claim guardrail
            mentions_prior_approved = "prior approved" in rationale_text.lower()
            if mentions_prior_approved and c1.precedent is None:
                checks.append(
                    CheckResult(
                        "unsupported_precedent_claim",
                        False,
                        "Rationale mentions 'prior approved' but precedent object is None",
                    )
                )
            else:
                checks.append(CheckResult("unsupported_precedent_claim", True, ""))
        else:
            checks.append(CheckResult("rationale_nonempty", False, "Rationale unavailable because form is missing"))
            checks.append(CheckResult("disposition_nonempty", False, "Disposition unavailable because form is missing"))
    else:
        # For non-automatable, still verify renderer can produce deterministic rationale string.
        r1 = _norm(render_rationale(c1, material_name=_norm(inp.get("material_designation")) or c1.maptis_code))
        d1 = _norm(render_disposition(c1))
        r2 = _norm(render_rationale(c2, material_name=_norm(inp.get("material_designation")) or c2.maptis_code)) if c2 else ""
        d2 = _norm(render_disposition(c2)) if c2 else ""
        rationale_text = r1
        disposition_text = d1
        rationale_hash = _sha256_text(r1)
        disposition_hash = _sha256_text(d1)

        checks.append(CheckResult("rendered_rationale_nonempty", bool(r1), "Rendered rationale is empty"))
        checks.append(CheckResult("rendered_disposition_nonempty", bool(d1), "Rendered disposition is empty"))
        checks.append(CheckResult("deterministic_rendered_rationale", r1 == r2, "Rendered rationale changed across runs"))
        checks.append(CheckResult("deterministic_rendered_disposition", d1 == d2, "Rendered disposition changed across runs"))

    passed = all(c.passed for c in checks)

    return {
        "case_id": cid,
        "description": desc,
        "passed": passed,
        "checks": [c.__dict__ for c in checks],
        "fail_reasons": [c.detail or c.name for c in checks if not c.passed],
        "actual": {
            "mua_type": c1.mua_type.value,
            "automatable": c1.automatable,
            "category": c1.category.value if c1.category else None,
            "flag_type": c1.flag_type.value if c1.flag_type else None,
            "hazard_applies": c1.hazard_applies,
            "screening_applicable": c1.screening_applicable,
            "classification_reason": _norm(c1.classification_reason),
            "precedent_ring": c1.precedent_ring,
            "has_precedent": c1.precedent is not None,
            "rationale": rationale_text,
            "disposition": disposition_text,
            "rationale_sha256": rationale_hash,
            "disposition_sha256": disposition_hash,
        },
        "expected": exp,
        "input": inp,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "passed",
        "fail_reasons",
        "expected_mua_type",
        "actual_mua_type",
        "expected_flag_type",
        "actual_flag_type",
        "expected_category",
        "actual_category",
        "expected_hazard",
        "actual_hazard",
        "automatable",
        "has_precedent",
        "precedent_ring",
        "rationale_sha256",
        "disposition_sha256",
        "rationale",
        "disposition",
        "classification_reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            a = r.get("actual", {})
            e = r.get("expected", {})
            w.writerow(
                {
                    "case_id": r.get("case_id"),
                    "passed": r.get("passed"),
                    "fail_reasons": " | ".join(r.get("fail_reasons", [])),
                    "expected_mua_type": e.get("mua_type"),
                    "actual_mua_type": a.get("mua_type"),
                    "expected_flag_type": e.get("flag_type"),
                    "actual_flag_type": a.get("flag_type"),
                    "expected_category": e.get("category"),
                    "actual_category": a.get("category"),
                    "expected_hazard": e.get("hazard_applies"),
                    "actual_hazard": a.get("hazard_applies"),
                    "automatable": a.get("automatable"),
                    "has_precedent": a.get("has_precedent"),
                    "precedent_ring": a.get("precedent_ring"),
                    "rationale_sha256": a.get("rationale_sha256"),
                    "disposition_sha256": a.get("disposition_sha256"),
                    "rationale": a.get("rationale"),
                    "disposition": a.get("disposition"),
                    "classification_reason": a.get("classification_reason"),
                }
            )


def _write_adjudication_template(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "description",
        "expected_mua_type",
        "actual_mua_type",
        "rationale_sha256",
        "rationale",
        "disposition_sha256",
        "disposition",
        "auto_checks_passed",
        "reviewer_genuine_rationale",
        "reviewer_traceable_claims",
        "reviewer_notes",
        "reviewer_name",
        "reviewed_at_utc",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            a = r.get("actual", {})
            e = r.get("expected", {})
            w.writerow(
                {
                    "case_id": r.get("case_id"),
                    "description": r.get("description", ""),
                    "expected_mua_type": e.get("mua_type"),
                    "actual_mua_type": a.get("mua_type"),
                    "rationale_sha256": a.get("rationale_sha256"),
                    "rationale": a.get("rationale"),
                    "disposition_sha256": a.get("disposition_sha256"),
                    "disposition": a.get("disposition"),
                    "auto_checks_passed": r.get("passed"),
                    "reviewer_genuine_rationale": "",
                    "reviewer_traceable_claims": "",
                    "reviewer_notes": "",
                    "reviewer_name": "",
                    "reviewed_at_utc": "",
                }
            )


def _write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# MUA Rationale Proof Summary",
        "",
        f"Generated: {summary['generated_at_utc']}",
        "",
        "## Overall",
        "",
        f"- Cases: {summary['total_cases']}",
        f"- Passed: {summary['passed_cases']}",
        f"- Failed: {summary['failed_cases']}",
        f"- Pass rate: {summary['pass_rate']:.1f}%",
        f"- Deterministic case rate: {summary['deterministic_rate']:.1f}%",
        f"- Bundle hash: `{summary['bundle_hash']}`",
        "",
        "## Failed Cases",
        "",
        "| Case | Fail Reasons |",
        "|---|---|",
    ]

    failed = [r for r in summary["results"] if not r["passed"]]
    if not failed:
        lines.append("| _(none)_ | _(all passed)_ |")
    else:
        for row in failed:
            reasons = " ; ".join(row.get("fail_reasons", []))
            lines.append(f"| `{row['case_id']}` | {reasons} |")

    lines += [
        "",
        "## Acceptance Recommendation",
        "",
        "- Recommended threshold for release evidence: 100% deterministic + >=95% total pass rate.",
        "- Any failed case must be triaged with explicit defect or expected-behavior waiver.",
    ]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    cases_path = Path(args.cases).resolve()
    cases = _load_cases(cases_path)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir).resolve() / f"proof_run_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = [_run_single_case(case) for case in cases]

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    deterministic_checks = 0
    deterministic_passes = 0
    rationale_hashes: list[str] = []
    for r in results:
        for c in r.get("checks", []):
            if c["name"].startswith("deterministic"):
                deterministic_checks += 1
                if c["passed"]:
                    deterministic_passes += 1
        ah = r.get("actual", {})
        if ah.get("rationale_sha256"):
            rationale_hashes.append(ah["rationale_sha256"])

    bundle_hash = _sha256_text("\n".join(sorted(rationale_hashes))) if rationale_hashes else ""

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cases_file": str(cases_path),
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": failed,
        "pass_rate": (passed / total * 100.0) if total else 0.0,
        "deterministic_rate": (deterministic_passes / deterministic_checks * 100.0) if deterministic_checks else 0.0,
        "bundle_hash": bundle_hash,
        "results": results,
    }

    summary_json = out_dir / "proof_summary.json"
    summary_md = out_dir / "proof_summary.md"
    results_csv = out_dir / "case_results.csv"
    adjudication_csv = out_dir / "adjudication_template.csv"

    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_markdown(summary_md, summary)
    _write_csv(results_csv, results)
    _write_adjudication_template(adjudication_csv, results)

    print(f"Wrote: {summary_json}")
    print(f"Wrote: {summary_md}")
    print(f"Wrote: {results_csv}")
    print(f"Wrote: {adjudication_csv}")
    print(f"Pass rate: {summary['pass_rate']:.1f}% ({passed}/{total})")
    print(f"Deterministic rate: {summary['deterministic_rate']:.1f}%")
    print(f"Bundle hash: {bundle_hash}")

    # Non-zero exit if any failures, unless explicitly allowed
    if failed and not args.allow_failures:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MUA rationale proof evaluation.")
    parser.add_argument(
        "--cases",
        default="docs/mua_audit/rationale_proof_cases_v1.json",
        help="Path to proof-cases JSON file",
    )
    parser.add_argument(
        "--out-dir",
        default="reports/mua_rationale_proof",
        help="Directory under which run artifacts are written",
    )
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="Return exit code 0 even if some cases fail",
    )
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
