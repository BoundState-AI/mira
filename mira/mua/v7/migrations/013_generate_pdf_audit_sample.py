"""
MUA PDF Audit Sampler (Statistical)
===================================

Generates a reproducible random sample for manual PDF audit using finite
population sample-size math.

Supports two populations:
  - v7: PDFs referenced by `mua_precedents_v7.source_file` and resolved
        against a filesystem root (recommended for data-quality audit).
  - all: every PDF under the provided root (coverage audit).

Usage
-----
Default (v7 population, 95% confidence, +/-5% margin):
    py -3 mira/mua/v7/migrations/013_generate_pdf_audit_sample.py

Against specific root:
    py -3 mira/mua/v7/migrations/013_generate_pdf_audit_sample.py \\
      --pdf-root \"C:\\MIRA backup full\\maptis-nlp\\mira\\data\\mua_pdfs\"
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

import psycopg2


DEFAULT_PDF_ROOT = Path(r"C:\MIRA backup full\maptis-nlp\mira\data\mua_pdfs")


def _load_db_params() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params()


def _required_sample_size(
    *,
    population_n: int,
    confidence: float,
    margin: float,
    p_estimate: float = 0.5,
) -> int:
    """Finite-population corrected sample size."""
    if population_n <= 0:
        return 0
    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    n0 = (z * z * p_estimate * (1 - p_estimate)) / (margin * margin)
    n = n0 / (1.0 + ((n0 - 1.0) / population_n))
    return max(1, min(population_n, math.ceil(n)))


def _build_pdf_index(pdf_root: Path) -> tuple[dict[str, list[Path]], int]:
    by_name: dict[str, list[Path]] = {}
    total = 0
    for pdf in pdf_root.rglob("*.pdf"):
        total += 1
        by_name.setdefault(pdf.name.lower(), []).append(pdf)
    return by_name, total


def _fetch_v7_rows() -> list[dict[str, Any]]:
    conn = psycopg2.connect(**_load_db_params())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id,
                mua_number,
                source_file,
                source_hash,
                material_designation,
                material_family,
                env_type,
                determination,
                category,
                appendix_b_code,
                closure_path,
                temp_min_f,
                temp_max_f
            FROM mua_precedents_v7
            WHERE source_file IS NOT NULL
              AND trim(source_file) <> ''
            ORDER BY id
            """
        )
        out = []
        for row in cur.fetchall():
            out.append(
                {
                    "v7_id": row[0],
                    "v7_mua_number": row[1],
                    "source_file": row[2],
                    "source_hash": row[3],
                    "v7_material_designation": row[4],
                    "v7_material_family": row[5],
                    "v7_env_type": row[6],
                    "v7_determination": row[7],
                    "v7_category": row[8],
                    "v7_appendix_b_code": row[9],
                    "v7_closure_path": row[10],
                    "v7_temp_min_f": row[11],
                    "v7_temp_max_f": row[12],
                }
            )
        cur.close()
        return out
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate statistically valid MUA PDF audit sample.")
    parser.add_argument(
        "--pdf-root",
        default=str(DEFAULT_PDF_ROOT),
        help="Root directory containing MUA PDFs.",
    )
    parser.add_argument(
        "--population",
        choices=["v7", "all"],
        default="v7",
        help="Population basis: v7-referenced PDFs or all PDFs under root.",
    )
    parser.add_argument("--confidence", type=float, default=0.95, help="Confidence level (e.g., 0.95).")
    parser.add_argument("--margin", type=float, default=0.05, help="Margin of error (e.g., 0.05 for +/-5%).")
    parser.add_argument("--p-estimate", type=float, default=0.5, help="Estimated defect probability for sizing.")
    parser.add_argument("--seed", type=int, default=6016, help="Random seed for reproducibility.")
    parser.add_argument("--sample-size", type=int, default=0, help="Optional explicit sample size override.")
    args = parser.parse_args()

    pdf_root = Path(args.pdf_root)
    if not pdf_root.exists():
        raise SystemExit(f"PDF root does not exist: {pdf_root}")

    by_name, total_pdfs = _build_pdf_index(pdf_root)
    records: list[dict[str, Any]] = []
    missing_paths = 0
    ambiguous_paths = 0

    if args.population == "v7":
        v7_rows = _fetch_v7_rows()
        for row in v7_rows:
            name = Path(str(row["source_file"])).name.lower()
            paths = by_name.get(name, [])
            if not paths:
                missing_paths += 1
                continue
            if len(paths) > 1:
                ambiguous_paths += 1
                # deterministic pick for sample generation; ambiguity tracked in manifest
                chosen = sorted(paths)[0]
            else:
                chosen = paths[0]

            rec = dict(row)
            rec["pdf_filename"] = chosen.name
            rec["pdf_path"] = str(chosen)
            rec["population_group"] = "v7"
            records.append(rec)
    else:
        for paths in by_name.values():
            for pdf in paths:
                records.append(
                    {
                        "v7_id": "",
                        "v7_mua_number": "",
                        "source_file": "",
                        "source_hash": "",
                        "v7_material_designation": "",
                        "v7_material_family": "",
                        "v7_env_type": "",
                        "v7_determination": "",
                        "v7_category": "",
                        "v7_appendix_b_code": "",
                        "v7_closure_path": "",
                        "v7_temp_min_f": "",
                        "v7_temp_max_f": "",
                        "pdf_filename": pdf.name,
                        "pdf_path": str(pdf),
                        "population_group": "all",
                    }
                )

    population_n = len(records)
    if population_n == 0:
        raise SystemExit("No records available for sampling.")

    if args.sample_size and args.sample_size > 0:
        sample_n = min(args.sample_size, population_n)
    else:
        sample_n = _required_sample_size(
            population_n=population_n,
            confidence=args.confidence,
            margin=args.margin,
            p_estimate=args.p_estimate,
        )

    rng = random.Random(args.seed)
    sampled = rng.sample(records, sample_n)

    out_dir = Path(__file__).resolve().parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"013_pdf_audit_sample_{stamp}.csv"
    manifest_path = out_dir / f"013_pdf_audit_sample_{stamp}.json"

    fieldnames = [
        "sample_id",
        "pdf_filename",
        "pdf_path",
        "population_group",
        "v7_id",
        "v7_mua_number",
        "source_file",
        "source_hash",
        "v7_material_designation",
        "v7_material_family",
        "v7_env_type",
        "v7_determination",
        "v7_category",
        "v7_appendix_b_code",
        "v7_closure_path",
        "v7_temp_min_f",
        "v7_temp_max_f",
        "audit_done",
        "audit_pass",
        "finding_severity",
        "error_fields",
        "corrected_material_family",
        "corrected_env_type",
        "corrected_determination",
        "corrected_category",
        "corrected_appendix_b_code",
        "corrected_closure_path",
        "notes",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, rec in enumerate(sampled, start=1):
            row = {k: rec.get(k, "") for k in fieldnames}
            row["sample_id"] = i
            writer.writerow(row)

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pdf_root": str(pdf_root),
        "population": args.population,
        "population_n": population_n,
        "total_pdfs_under_root": total_pdfs,
        "v7_missing_paths": missing_paths,
        "v7_ambiguous_paths": ambiguous_paths,
        "confidence": args.confidence,
        "margin": args.margin,
        "p_estimate": args.p_estimate,
        "seed": args.seed,
        "sample_n": sample_n,
        "csv_path": str(csv_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("=" * 72)
    print("PDF AUDIT SAMPLE GENERATED")
    print("=" * 72)
    print(f"PDF root:                {pdf_root}")
    print(f"Population mode:         {args.population}")
    print(f"Population N:            {population_n}")
    print(f"Total PDFs under root:   {total_pdfs}")
    if args.population == "v7":
        print(f"V7 rows missing path:    {missing_paths}")
        print(f"V7 rows ambiguous path:  {ambiguous_paths}")
    print(f"Confidence / margin:     {args.confidence:.3f} / +/-{args.margin:.3f}")
    print(f"Sample size:             {sample_n}")
    print(f"Seed:                    {args.seed}")
    print(f"Sample CSV:              {csv_path}")
    print(f"Manifest JSON:           {manifest_path}")


if __name__ == "__main__":
    main()
