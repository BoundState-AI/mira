"""
Auto-Audit MUA PDF Sample
=========================

Automatically evaluates sampled audit rows and pre-populates:
  - audit_done
  - audit_pass
  - finding_severity
  - error_fields
  - corrected_* suggestions
  - notes

This is a deterministic pre-audit pass to reduce manual workload.
It does NOT replace final human review for safety-critical decisions.

Usage
-----
Generate side-by-side reviewed CSV:
    py -3 mira/mua/v7/migrations/015_auto_audit_pdf_sample.py \\
      --sample-csv "C:\\BoundState\\mira\\mua\\v7\\migrations\\reports\\013_pdf_audit_sample_20260210T201414Z.csv"

In-place update:
    py -3 mira/mua/v7/migrations/015_auto_audit_pdf_sample.py \\
      --sample-csv "<csv_path>" --in-place
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2
from pypdf import PdfReader


CANONICAL_DET_MAP = {
    "APPROVED": "APPROVED",
    "CONDITIONAL": "APPROVED_WITH_LIMITS",
    "APPROVED_WITH_LIMITS": "APPROVED_WITH_LIMITS",
    "REJECTED": "REJECTED",
    "DEFERRED": "DEFERRED",
    "CANCELLED": "CANCELLED",
    "UNKNOWN": "UNKNOWN",
}

CAT1_ENV_TYPES = {"LOX_GOX", "ENRICHED_O2", "HYDROGEN", "CRYOGENIC"}
CAT1_ISSUES = {"O2_COMPAT", "HEE", "FRACTURE_CONTROL"}

APPENDIX_TO_CLOSURE = {
    "103": "CONFIG_ANALYSIS",
    "104": "HEAT_SINK",
    "105": "MINOR_QUANTITY",
    "106": "CONFIG_ANALYSIS",
    "107": "HEAT_SINK",
    "108": "CONFIG_ANALYSIS",
}

PLACEHOLDER_DESIGNATION_TOKENS = {
    "SEE",
    "ATTACHED",
    "LIST",
    "VARIOUS",
    "SEVERAL",
    "TBD",
    "UNKNOWN",
    "NA",
    "N/A",
    "BELOW",
    "PAGE",
}


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _safe_int(value: str) -> Optional[int]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _normalize_det(value: Optional[str]) -> str:
    key = str(value or "").strip().upper()
    return CANONICAL_DET_MAP.get(key, key or "UNKNOWN")


def _has_cat1_trigger(env_type: Optional[str], issues: list[str]) -> bool:
    env = (env_type or "UNKNOWN").upper()
    issue_set = {str(i).upper() for i in (issues or [])}
    return env in CAT1_ENV_TYPES or bool(issue_set.intersection(CAT1_ISSUES))


def _extract_pdf_text(path: Path, max_pages: int = 6, max_chars: int = 25000) -> str:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    chunks: list[str] = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            chunks.append(text)
        if sum(len(c) for c in chunks) >= max_chars:
            break
    joined = "\n".join(chunks)
    return joined[:max_chars]


def _designation_tokens(designation: str) -> list[str]:
    raw = (designation or "").upper()
    out: list[str] = []
    token = ""
    for ch in raw:
        if ch.isalnum():
            token += ch
        else:
            if token:
                out.append(token)
                token = ""
    if token:
        out.append(token)
    filtered: list[str] = []
    for t in out:
        if len(t) < 3:
            continue
        if t in PLACEHOLDER_DESIGNATION_TOKENS:
            continue
        filtered.append(t)
    return filtered


def _fetch_v7_rows_by_id() -> dict[int, dict[str, Any]]:
    conn = psycopg2.connect(**_load_db_params())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, source_file, source_hash, material_designation, material_family,
                env_type, determination, category, appendix_b_code, closure_path, issues
            FROM mua_precedents_v7
            """
        )
        out: dict[int, dict[str, Any]] = {}
        for row in cur.fetchall():
            out[int(row[0])] = {
                "id": int(row[0]),
                "source_file": row[1],
                "source_hash": row[2],
                "material_designation": row[3],
                "material_family": row[4],
                "env_type": row[5],
                "determination": row[6],
                "category": row[7],
                "appendix_b_code": row[8],
                "closure_path": row[9],
                "issues": row[10] or [],
            }
        cur.close()
        return out
    finally:
        conn.close()


def _fetch_bok_strict_det_map() -> dict[str, str]:
    conn = psycopg2.connect(**_load_db_params())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            WITH dets AS (
              SELECT
                lower(filename) AS filename_key,
                COUNT(DISTINCT upper(determination))
                  FILTER (WHERE upper(determination) <> 'UNKNOWN') AS non_unknown_distinct_count,
                MAX(upper(determination))
                  FILTER (WHERE upper(determination) <> 'UNKNOWN') AS chosen_non_unknown
              FROM bok.mua_normalized
              GROUP BY lower(filename)
            )
            SELECT filename_key, chosen_non_unknown
            FROM dets
            WHERE non_unknown_distinct_count = 1
              AND chosen_non_unknown IS NOT NULL
            """
        )
        out: dict[str, str] = {}
        for filename_key, chosen in cur.fetchall():
            out[str(filename_key)] = _normalize_det(chosen)
        cur.close()
        return out
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-audit sampled PDF CSV rows.")
    parser.add_argument("--sample-csv", required=True, help="Input sample CSV from 013.")
    parser.add_argument("--output-csv", default="", help="Output CSV path. Default: input + _auto.")
    parser.add_argument("--in-place", action="store_true", help="Overwrite input CSV.")
    parser.add_argument("--max-pages", type=int, default=6, help="Max PDF pages to text-scan.")
    parser.add_argument("--max-chars", type=int, default=25000, help="Max extracted chars per PDF.")
    parser.add_argument("--overwrite-existing", action="store_true", help="Overwrite rows already reviewed.")
    parser.add_argument(
        "--hash-policy",
        choices=["strict", "warn", "off"],
        default="strict",
        help="How to treat source_hash mismatches: strict=fail, warn=warning, off=ignore.",
    )
    args = parser.parse_args()

    sample_csv = Path(args.sample_csv)
    if not sample_csv.exists():
        raise SystemExit(f"Sample CSV not found: {sample_csv}")

    if args.in_place:
        out_csv = sample_csv
    elif args.output_csv:
        out_csv = Path(args.output_csv)
    else:
        out_csv = sample_csv.with_name(sample_csv.stem + "_auto.csv")

    v7_map = _fetch_v7_rows_by_id()
    bok_det_map = _fetch_bok_strict_det_map()
    hash_cache: dict[str, str] = {}
    text_cache: dict[str, str] = {}

    total = 0
    auto_scored = 0
    pass_count = 0
    fail_count = 0
    skipped_existing = 0

    issue_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    population_counts: dict[str, int] = {}

    rows_out: list[dict[str, str]] = []

    with sample_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            total += 1
            existing_done = (row.get("audit_done", "") or "").strip().lower()
            if existing_done and not args.overwrite_existing:
                skipped_existing += 1
                rows_out.append(row)
                continue

            issues: list[str] = []
            warnings: list[str] = []
            corrected: dict[str, str] = {}

            sample_id = row.get("sample_id", "")
            pdf_path = Path(str(row.get("pdf_path", "")).strip())
            v7_id = _safe_int(str(row.get("v7_id", "")))
            filename_key = str(row.get("pdf_filename", "")).lower()
            population_group = (row.get("population_group", "") or "").strip().lower()
            if not population_group:
                population_group = "unknown"
            population_counts[population_group] = population_counts.get(population_group, 0) + 1

            v7 = v7_map.get(v7_id or -1)
            if not pdf_path.exists():
                issues.append("pdf_missing")
            elif population_group == "all" and not row.get("source_hash"):
                # Coverage-only sample: keep checks lightweight and deterministic.
                warnings.append("coverage_only_sample")

            if not v7 and population_group != "all":
                issues.append("v7_row_missing")
            elif v7:
                # Hash integrity checks.
                if not v7.get("source_hash"):
                    if args.hash_policy == "strict":
                        issues.append("source_hash_missing")
                    elif args.hash_policy == "warn":
                        warnings.append("source_hash_missing")
                if pdf_path.exists():
                    cache_key = str(pdf_path)
                    computed_hash = hash_cache.get(cache_key)
                    if not computed_hash:
                        computed_hash = _sha256_file(pdf_path)
                        hash_cache[cache_key] = computed_hash
                    expected_hash = str(v7.get("source_hash", "")).lower()
                    if expected_hash and computed_hash.lower() != expected_hash:
                        if args.hash_policy == "strict":
                            issues.append("source_hash_mismatch")
                        elif args.hash_policy == "warn":
                            warnings.append("source_hash_mismatch")

                # Determination strict match to BOK normalized.
                strict_det = bok_det_map.get(filename_key)
                current_det = _normalize_det(v7.get("determination"))
                if current_det == "UNKNOWN":
                    issues.append("determination_unknown")
                    if strict_det and strict_det != "UNKNOWN":
                        corrected["corrected_determination"] = strict_det
                elif strict_det and current_det != strict_det:
                    issues.append("determination_mismatch_bok")
                    corrected["corrected_determination"] = strict_det

                # Category consistency.
                category = (v7.get("category") or "").strip().upper()
                appendix = (v7.get("appendix_b_code") or "").strip()
                closure = (v7.get("closure_path") or "").strip()
                has_cat1 = _has_cat1_trigger(v7.get("env_type"), v7.get("issues", []))

                if not category:
                    issues.append("category_missing")
                if category == "III" and not appendix:
                    issues.append("cat3_missing_appendix")
                    corrected["corrected_category"] = "II"
                if category == "III" and has_cat1:
                    issues.append("cat3_cat1_trigger_conflict")
                    corrected["corrected_category"] = "I"

                if appendix and not closure:
                    issues.append("appendix_without_closure")
                    suggestion = APPENDIX_TO_CLOSURE.get(appendix)
                    if suggestion:
                        corrected["corrected_closure_path"] = suggestion

                # Optional completeness warnings (not hard fails).
                if not v7.get("material_family"):
                    warnings.append("material_family_missing")
                if (v7.get("env_type") or "UNKNOWN").upper() == "UNKNOWN":
                    warnings.append("env_type_unknown")

                # Light text check: material designation tokens appear in PDF text.
            if pdf_path.exists():
                cache_key = str(pdf_path)
                pdf_text = text_cache.get(cache_key)
                if pdf_text is None:
                    pdf_text = _extract_pdf_text(
                        pdf_path,
                        max_pages=max(1, args.max_pages),
                        max_chars=max(1000, args.max_chars),
                    )
                    text_cache[cache_key] = pdf_text
                if pdf_text and v7:
                    tokens = _designation_tokens(str(v7.get("material_designation") or ""))
                    if len(tokens) >= 2:
                        txt_upper = pdf_text.upper()
                        hits = sum(1 for t in tokens if t in txt_upper)
                        if hits == 0:
                            warnings.append("designation_not_seen_in_pdf_text")
                elif not pdf_text:
                    warnings.append("pdf_text_unavailable")

            is_fail = len(issues) > 0
            audit_pass = "fail" if is_fail else "pass"
            if is_fail:
                sev = "high" if any(
                    x in {
                        "pdf_missing",
                        "source_hash_missing",
                        "source_hash_mismatch",
                        "determination_unknown",
                        "determination_mismatch_bok",
                        "cat3_missing_appendix",
                        "cat3_cat1_trigger_conflict",
                    }
                    for x in issues
                ) else "medium"
            else:
                sev = "low" if not warnings else "medium"

            row["audit_done"] = "auto"
            row["audit_pass"] = audit_pass
            row["finding_severity"] = sev
            all_fields = issues + warnings
            row["error_fields"] = ",".join(all_fields)
            row["corrected_material_family"] = corrected.get("corrected_material_family", row.get("corrected_material_family", ""))
            row["corrected_env_type"] = corrected.get("corrected_env_type", row.get("corrected_env_type", ""))
            row["corrected_determination"] = corrected.get("corrected_determination", row.get("corrected_determination", ""))
            row["corrected_category"] = corrected.get("corrected_category", row.get("corrected_category", ""))
            row["corrected_appendix_b_code"] = corrected.get("corrected_appendix_b_code", row.get("corrected_appendix_b_code", ""))
            row["corrected_closure_path"] = corrected.get("corrected_closure_path", row.get("corrected_closure_path", ""))

            notes_parts = []
            if issues:
                notes_parts.append("auto_fail:" + ",".join(issues))
            if warnings:
                notes_parts.append("auto_warn:" + ",".join(warnings))
            if corrected:
                notes_parts.append(
                    "suggested:" + ",".join(f"{k}={v}" for k, v in corrected.items())
                )
            row["notes"] = "; ".join(notes_parts)

            for issue in all_fields:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

            auto_scored += 1
            if is_fail:
                fail_count += 1
            else:
                pass_count += 1
            rows_out.append(row)

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    groups_present = {k for k, v in population_counts.items() if v > 0}
    if groups_present == {"all"}:
        audit_scope = "coverage_only"
        scope_statement = "Coverage audit only: verifies sampled PDFs are present/readable; not a field-level PDF-vs-DB validation."
        supported_claims = [
            "Sampled PDFs exist at the specified root unless explicitly flagged (pdf_missing).",
            "Sampled PDFs were machine-readable where text extraction succeeded.",
        ]
        unsupported_claims = [
            "Material, environment, category, and determination values are not validated against extracted PDF semantics in this mode.",
            "This run does not prove row-level correctness of mua_precedents_v7 fields.",
        ]
    elif groups_present == {"v7"}:
        audit_scope = "v7_traceability_precheck"
        scope_statement = "v7 traceability precheck: verifies structural consistency and trace links, not full semantic re-extraction."
        supported_claims = [
            "Sampled v7 rows map to PDFs and pass configured hash-policy checks.",
            "Sampled rows pass deterministic consistency checks (determination/category/appendix/closure rules).",
        ]
        unsupported_claims = [
            "This run is not a full semantic PDF re-parse and field-by-field truth audit.",
            "Passing rows can still contain extraction/classification errors not covered by deterministic rules.",
        ]
    else:
        audit_scope = "mixed"
        scope_statement = "Mixed-scope audit: combines coverage checks and v7 structural checks; not full semantic PDF-vs-DB validation."
        supported_claims = [
            "Coverage checks were run for all-scope rows.",
            "Deterministic v7 consistency checks were run for v7-linked rows where available.",
        ]
        unsupported_claims = [
            "This run does not prove full field-level semantic equivalence between PDFs and DB records.",
        ]

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_csv": str(sample_csv),
        "output_csv": str(out_csv),
        "total_rows": total,
        "auto_scored_rows": auto_scored,
        "skipped_existing_rows": skipped_existing,
        "auto_pass": pass_count,
        "auto_fail": fail_count,
        "population_counts": population_counts,
        "audit_scope": audit_scope,
        "scope_statement": scope_statement,
        "supported_claims": supported_claims,
        "unsupported_claims": unsupported_claims,
        "severity_counts": severity_counts,
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda x: (-x[1], x[0]))),
    }
    out_dir = Path(__file__).resolve().parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = out_dir / f"015_auto_audit_summary_{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 72)
    print("AUTO AUDIT COMPLETE")
    print("=" * 72)
    print(f"Input CSV:               {sample_csv}")
    print(f"Output CSV:              {out_csv}")
    print(f"Rows:                    {total}")
    print(f"Auto-scored:             {auto_scored}")
    print(f"Auto pass / fail:        {pass_count} / {fail_count}")
    print(f"Scope:                   {audit_scope}")
    print(f"Scope note:              {scope_statement}")
    print(f"Skipped existing:        {skipped_existing}")
    print(f"Summary report:          {report_path}")


if __name__ == "__main__":
    main()
