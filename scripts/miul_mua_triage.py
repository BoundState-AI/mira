#!/usr/bin/env python3
"""Standalone MIUL -> MUA trigger triage tool.

Usage:
  py -3 scripts/miul_mua_triage.py "C:\\path\\MIUL.xlsx" --out-dir C:\\tmp\\triage
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.miul.mua_trigger_analyzer import analyze_miul_workbook, build_trigger_buckets


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="MIUL non-A trigger triage")
    parser.add_argument("workbook", help="Path to MIUL workbook (.xlsx)")
    parser.add_argument("--sheet", default="MIUL", help="Worksheet name (default: MIUL)")
    parser.add_argument(
        "--out-dir",
        default=str(Path("tmp_miul_triage_out").resolve()),
        help="Output directory",
    )
    args = parser.parse_args()

    workbook = Path(args.workbook)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    analysis = analyze_miul_workbook(workbook, sheet_name=args.sheet)
    buckets = build_trigger_buckets(analysis)

    # JSON outputs
    analysis_json = out_dir / "miul_analysis.json"
    buckets_json = out_dir / "miul_buckets.json"
    analysis_json.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    buckets_json.write_text(json.dumps(buckets, indent=2), encoding="utf-8")

    # CSV outputs for quick sorting/filtering
    _write_csv(
        out_dir / "non_a_parts.csv",
        analysis["part_triggers"],
        [
            "row",
            "material_code",
            "designation",
            "material_specification",
            "part_number",
            "part_description",
            "nomenclature",
            "nha",
            "environment",
            "max_temperature",
            "min_temperature",
            "max_pressure",
            "min_pressure",
            "fluid_type",
            "system",
            "subsystem",
            "criticality",
            "overall_evaluation",
            "mua_rationale",
            "remarks",
            "triggers",
        ],
    )
    _write_csv(
        out_dir / "material_buckets.csv",
        buckets["material_buckets"],
        [
            "material_code",
            "part_count",
            "risk_score_max",
            "risk_band",
            "issue_counts",
            "rating_counts",
            "environments",
            "nhas",
            "designations",
        ],
    )
    _write_csv(
        out_dir / "signature_buckets.csv",
        buckets["signature_buckets"],
        [
            "trigger_signature",
            "part_count",
            "material_code_count",
            "material_codes",
            "risk_score_max",
            "risk_band",
            "sample_parts",
        ],
    )
    _write_csv(
        out_dir / "material_signature_buckets.csv",
        buckets["material_signature_buckets"],
        [
            "bucket_id",
            "material_code",
            "trigger_signature",
            "environment",
            "part_count",
            "risk_score_max",
            "risk_band",
            "part_numbers",
            "nha_values",
            "designations",
            "temp_min_f",
            "temp_max_f",
            "pressure_min_psia",
            "pressure_max_psia",
        ],
    )

    summary = buckets["summary"]
    print("MIUL triage complete")
    print(f"Workbook: {workbook}")
    print(f"Total parts: {summary['total_parts']}")
    print(f"Non-A trigger parts: {summary['non_a_parts']}")
    print(f"No-trigger parts: {summary['no_trigger_parts']}")
    print(f"Material buckets: {summary['material_bucket_count']}")
    print(f"Signature buckets: {summary['signature_bucket_count']}")
    print(f"Material+signature buckets: {summary['material_signature_bucket_count']}")
    print(f"Output dir: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
