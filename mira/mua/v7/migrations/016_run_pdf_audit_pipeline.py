"""
Run PDF Audit Pipeline (One Command)
===================================

Runs:
  013_generate_pdf_audit_sample.py
  015_auto_audit_pdf_sample.py
  014_evaluate_pdf_audit_confidence.py

Then writes a manual review queue CSV containing failed rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_PDF_ROOT = Path(r"C:\MIRA backup full\maptis-nlp\mira\data\mua_pdfs")


def _script_path(name: str) -> Path:
    return Path(__file__).resolve().parent / name


def _run(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"Command failed ({completed.returncode}): {' '.join(cmd)}")


def _latest_file(pattern: str, min_mtime: float = 0.0) -> Optional[Path]:
    reports_dir = Path(__file__).resolve().parent / "reports"
    files = [p for p in reports_dir.glob(pattern) if p.stat().st_mtime >= min_mtime]
    if not files:
        return None
    return sorted(files, key=lambda p: p.stat().st_mtime)[-1]


def _sample_row_count(sample_csv: Path) -> int:
    with sample_csv.open("r", newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def _infer_population(sample_csv: Path) -> str:
    with sample_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            group = (row.get("population_group", "") or "").strip().lower()
            if group in {"v7", "all"}:
                return group
    return "v7"


def _write_manual_queue(auto_csv: Path) -> Path:
    with auto_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    queue_rows = [
        row
        for row in rows
        if (row.get("audit_pass", "") or "").strip().lower() == "fail"
    ]

    out_path = auto_csv.with_name(auto_csv.stem + "_manual_queue.csv")
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(queue_rows)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MUA PDF audit pipeline end-to-end.")
    parser.add_argument(
        "--sample-csv",
        default="",
        help="Optional existing 013 sample CSV. If set, 013 generation is skipped.",
    )
    parser.add_argument(
        "--pdf-root",
        default=str(DEFAULT_PDF_ROOT),
        help="Root directory containing source MUA PDFs.",
    )
    parser.add_argument(
        "--population",
        choices=["v7", "all"],
        default="v7",
        help="Population basis for statistical sample.",
    )
    parser.add_argument("--confidence", type=float, default=0.95, help="Confidence level.")
    parser.add_argument("--margin", type=float, default=0.05, help="Margin of error.")
    parser.add_argument("--p-estimate", type=float, default=0.5, help="Estimated defect probability.")
    parser.add_argument("--seed", type=int, default=6016, help="Sampling seed.")
    parser.add_argument("--sample-size", type=int, default=0, help="Optional explicit sample size.")
    parser.add_argument(
        "--hash-policy",
        choices=["strict", "warn", "off"],
        default="warn",
        help="How hash mismatch is handled in auto-audit.",
    )
    parser.add_argument(
        "--target-max-defect",
        type=float,
        default=0.05,
        help="Pass threshold for confidence report.",
    )
    parser.add_argument(
        "--population-size",
        type=int,
        default=0,
        help="Optional population size override when using --sample-csv.",
    )
    args = parser.parse_args()

    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc).timestamp()
    manifest_path: Optional[Path] = None
    manifest: dict = {}

    effective_population = args.population

    if args.sample_csv:
        sample_csv = Path(args.sample_csv)
        if not sample_csv.exists():
            raise SystemExit(f"Sample CSV not found: {sample_csv}")

        if args.population_size > 0:
            population_n = int(args.population_size)
        else:
            candidate_manifest = sample_csv.with_suffix(".json")
            if candidate_manifest.exists():
                manifest_path = candidate_manifest
                manifest = json.loads(candidate_manifest.read_text(encoding="utf-8"))
                effective_population = str(manifest.get("population") or effective_population)
                population_n = int(manifest.get("population_n") or _sample_row_count(sample_csv))
            else:
                population_n = _sample_row_count(sample_csv)
        if not manifest_path:
            effective_population = _infer_population(sample_csv)
    else:
        cmd_013 = [
            sys.executable,
            str(_script_path("013_generate_pdf_audit_sample.py")),
            "--pdf-root",
            str(Path(args.pdf_root)),
            "--population",
            args.population,
            "--confidence",
            str(args.confidence),
            "--margin",
            str(args.margin),
            "--p-estimate",
            str(args.p_estimate),
            "--seed",
            str(args.seed),
        ]
        if args.sample_size > 0:
            cmd_013.extend(["--sample-size", str(args.sample_size)])
        _run(cmd_013)

        manifest_path = _latest_file("013_pdf_audit_sample_*.json", min_mtime=started)
        if not manifest_path:
            raise SystemExit("Could not locate 013 manifest output.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        sample_csv = Path(manifest["csv_path"])
        effective_population = str(manifest.get("population") or effective_population)
        population_n = int(manifest.get("population_n") or _sample_row_count(sample_csv))

    cmd_015 = [
        sys.executable,
        str(_script_path("015_auto_audit_pdf_sample.py")),
        "--sample-csv",
        str(sample_csv),
        "--hash-policy",
        args.hash_policy,
    ]
    _run(cmd_015)
    auto_summary_015 = _latest_file("015_auto_audit_summary_*.json", min_mtime=started)
    auto_scope = ""
    auto_scope_note = ""
    if auto_summary_015 and auto_summary_015.exists():
        try:
            auto_summary_json = json.loads(auto_summary_015.read_text(encoding="utf-8"))
            auto_scope = str(auto_summary_json.get("audit_scope") or "")
            auto_scope_note = str(auto_summary_json.get("scope_statement") or "")
        except Exception:
            auto_scope = ""
            auto_scope_note = ""

    auto_csv = sample_csv.with_name(sample_csv.stem + "_auto.csv")
    if not auto_csv.exists():
        raise SystemExit(f"Auto-audit output not found: {auto_csv}")

    cmd_014 = [
        sys.executable,
        str(_script_path("014_evaluate_pdf_audit_confidence.py")),
        "--audit-csv",
        str(auto_csv),
        "--population-size",
        str(population_n),
        "--confidence",
        str(args.confidence),
        "--target-max-defect",
        str(args.target_max_defect),
        "--target-margin",
        str(args.margin),
    ]
    _run(cmd_014)

    confidence_report = _latest_file("014_audit_confidence_*.json", min_mtime=started)
    queue_csv = _write_manual_queue(auto_csv)

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sample_manifest": str(manifest_path) if manifest_path else "",
        "sample_csv": str(sample_csv),
        "auto_csv": str(auto_csv),
        "manual_queue_csv": str(queue_csv),
        "confidence_report": str(confidence_report) if confidence_report else "",
        "auto_audit_summary_015": str(auto_summary_015) if auto_summary_015 else "",
        "auto_audit_scope": auto_scope,
        "auto_audit_scope_note": auto_scope_note,
        "population": effective_population,
        "population_n": population_n,
        "sample_n": manifest.get("sample_n"),
        "hash_policy": args.hash_policy,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = reports_dir / f"016_audit_pipeline_summary_{stamp}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("=" * 72)
    print("PDF AUDIT PIPELINE COMPLETE")
    print("=" * 72)
    print(f"Sample manifest:          {manifest_path}")
    print(f"Sample CSV:               {sample_csv}")
    print(f"Auto-audit CSV:           {auto_csv}")
    if auto_summary_015:
        print(f"Auto summary (015):       {auto_summary_015}")
    if auto_scope:
        print(f"Auto audit scope:         {auto_scope}")
    if auto_scope_note:
        print(f"Scope note:               {auto_scope_note}")
    print(f"Manual queue CSV:         {queue_csv}")
    print(f"Confidence report:        {confidence_report}")
    print(f"Summary:                  {summary_path}")


if __name__ == "__main__":
    main()
