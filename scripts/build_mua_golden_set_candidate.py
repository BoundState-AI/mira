#!/usr/bin/env python3
"""
Build a reproducible MUA golden-set candidate from historic parsed corpora.

Default source:
  /mnt/c/maptis-nlp/output/historic_muas_v2_heavy_maptis_full.ndjson

Outputs:
  - data/mua_golden/golden_set_mua_v1_candidate.jsonl
  - data/mua_golden/golden_set_mua_v1_manifest.json
  - docs/mua_audit/golden_set_mua_v1_candidate.md
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ISSUE_MAP = {
    "FLAMM": "FLAM",
    "FS": "FS",
    "TOX": "TOX",
    "TVS": "TVS",
    "SCC": "SCC",
    "CORR": "CORR",
    "OC": "LEGACY_OC",
    "COMPAT": "LEGACY_COMPAT",
}

# Order matters for selecting a single representative issue per MUA row.
ISSUE_PRIORITY = ["FLAM", "FS", "TOX", "TVS", "SCC", "CORR", "LEGACY_OC", "LEGACY_COMPAT"]

TARGETS = {
    "v10.FLAM": 30,
    "v10.FS": 30,
    "v10.TOX": 30,
    "v10.TVS": 30,
    "v10.SCC": 30,
    "v10.CORR": 30,
    "legacy.OC": 20,
    "legacy.COMPAT": 20,
    "edge.no_material": 15,
    "edge.low_mapping_conf": 15,
    "edge.no_rationale": 20,
}


def _safe_text(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _safe_rating(val: Any) -> str:
    if isinstance(val, dict):
        val = val.get("rating")
    s = _safe_text(val).upper()
    if s in {"", "NONE", "NULL", "N/A", "NA"}:
        return ""
    return s


def _row_key(row: Dict[str, Any]) -> str:
    return f"{_safe_text(row.get('mua_id'))}|{_safe_text(row.get('source_file'))}|{_safe_text(row.get('file_hash'))}"


def _read_rows(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    bad = 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                bad += 1
    return rows, bad


def _normalized_ratings(row: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_issue, raw_value in (row.get("ratings") or {}).items():
        mapped = ISSUE_MAP.get(_safe_text(raw_issue).upper())
        if not mapped:
            continue
        rating = _safe_rating(raw_value)
        if rating:
            out[mapped] = rating
    return out


def _selected_issue(ratings: Dict[str, str]) -> str:
    for issue in ISSUE_PRIORITY:
        if issue in ratings:
            return issue
    return ""


def _pool(rows: Iterable[Dict[str, Any]], predicate) -> List[Dict[str, Any]]:
    return [r for r in rows if predicate(r)]


def _pick(pool: List[Dict[str, Any]], used: set[str], n: int, rng: random.Random) -> List[Dict[str, Any]]:
    candidates = [r for r in pool if _row_key(r) not in used]
    rng.shuffle(candidates)
    chosen = candidates[:n]
    for r in chosen:
        used.add(_row_key(r))
    return chosen


def _record_from_row(
    row: Dict[str, Any],
    golden_id: str,
    stratum: str,
    source_dataset: str,
    source_path: str,
    focus_issue: str = "",
) -> Dict[str, Any]:
    ratings = _normalized_ratings(row)
    selected_issue = focus_issue if focus_issue and focus_issue in ratings else _selected_issue(ratings)
    selected_rating = ratings.get(selected_issue, "")
    env = row.get("environment") or {}
    if not isinstance(env, dict):
        env = {}

    return {
        "golden_id": golden_id,
        "stratum": stratum,
        "selected_issue": selected_issue,
        "selected_rating": selected_rating,
        "mua_id": _safe_text(row.get("mua_id")),
        "material_name": _safe_text(row.get("material_name")),
        "maptis_code": _safe_text(row.get("maptis_code")),
        "category": _safe_text(row.get("category")),
        "environment": {
            "fluid_medium": _safe_text(env.get("fluid_medium")),
            "oxygen_pct": env.get("oxygen_pct"),
            "habitable_volume": env.get("habitable_volume"),
            "temperature_c_min": env.get("temperature_c_min"),
            "temperature_c_max": env.get("temperature_c_max"),
            "pressure_kpa_min": env.get("pressure_kpa_min"),
            "pressure_kpa_max": env.get("pressure_kpa_max"),
        },
        "ratings": ratings,
        "rationale": _safe_text(row.get("rationale")),
        "rationale_summary": _safe_text(row.get("rationale_summary")),
        "mapping_confidence": row.get("mapping_confidence"),
        "source_file": _safe_text(row.get("source_file")),
        "file_hash": _safe_text(row.get("file_hash")),
        "source_dataset": source_dataset,
        "source_path": source_path,
    }


def build(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)

    source = Path(args.source).resolve()
    if not source.exists():
        raise SystemExit(f"Source file not found: {source}")

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = Path(args.docs_dir).resolve()
    docs_dir.mkdir(parents=True, exist_ok=True)

    rows, bad_rows = _read_rows(source)

    annotated: List[Tuple[Dict[str, Any], Dict[str, str], str]] = []
    for r in rows:
        nr = _normalized_ratings(r)
        issue = _selected_issue(nr)
        annotated.append((r, nr, issue))

    # Base pools by issue (requires non-empty rating for that issue)
    issue_to_pool: Dict[str, List[Dict[str, Any]]] = {}
    for issue in ["FLAM", "FS", "TOX", "TVS", "SCC", "CORR", "LEGACY_OC", "LEGACY_COMPAT"]:
        issue_to_pool[issue] = [r for (r, nr, _) in annotated if issue in nr]

    # Edge pools
    no_material_pool = [r for (r, _, _) in annotated if not _safe_text(r.get("material_name"))]
    low_mapping_pool = [
        r
        for (r, _, _) in annotated
        if (r.get("mapping_confidence") is None) or (isinstance(r.get("mapping_confidence"), (int, float)) and r.get("mapping_confidence") < 0.60)
    ]
    no_rationale_pool = [r for (r, _, _) in annotated if not _safe_text(r.get("rationale"))]

    used: set[str] = set()
    selections: List[Tuple[str, Dict[str, Any], str]] = []

    def add(stratum: str, pool: List[Dict[str, Any]], count: int, focus_issue: str = ""):
        chosen = _pick(pool, used, count, rng)
        for row in chosen:
            selections.append((stratum, row, focus_issue))

    add("v10.FLAM", issue_to_pool["FLAM"], TARGETS["v10.FLAM"], focus_issue="FLAM")
    add("v10.FS", issue_to_pool["FS"], TARGETS["v10.FS"], focus_issue="FS")
    add("v10.TOX", issue_to_pool["TOX"], TARGETS["v10.TOX"], focus_issue="TOX")
    add("v10.TVS", issue_to_pool["TVS"], TARGETS["v10.TVS"], focus_issue="TVS")
    add("v10.SCC", issue_to_pool["SCC"], TARGETS["v10.SCC"], focus_issue="SCC")
    add("v10.CORR", issue_to_pool["CORR"], TARGETS["v10.CORR"], focus_issue="CORR")
    add("legacy.OC", issue_to_pool["LEGACY_OC"], TARGETS["legacy.OC"], focus_issue="LEGACY_OC")
    add("legacy.COMPAT", issue_to_pool["LEGACY_COMPAT"], TARGETS["legacy.COMPAT"], focus_issue="LEGACY_COMPAT")
    add("edge.no_material", no_material_pool, TARGETS["edge.no_material"])
    add("edge.low_mapping_conf", low_mapping_pool, TARGETS["edge.low_mapping_conf"])
    add("edge.no_rationale", no_rationale_pool, TARGETS["edge.no_rationale"])

    # Build final records
    records: List[Dict[str, Any]] = []
    for idx, (stratum, row, focus_issue) in enumerate(selections, start=1):
        gid = f"GOLD-V1-{idx:04d}"
        records.append(
            _record_from_row(
                row=row,
                golden_id=gid,
                stratum=stratum,
                source_dataset=source.name,
                source_path=str(source),
                focus_issue=focus_issue,
            )
        )

    # Stable order by golden_id (already sequential) and write JSONL
    jsonl_path = out_dir / "golden_set_mua_v1_candidate.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=True) + "\n")

    # Manifest JSON
    by_stratum = Counter(r["stratum"] for r in records)
    by_issue = Counter(r["selected_issue"] for r in records)
    by_rating = Counter(f"{r['selected_issue']}={r['selected_rating']}" for r in records if r["selected_issue"])

    manifest = {
        "name": "golden_set_mua_v1_candidate",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "source": {
            "dataset": source.name,
            "path": str(source),
            "total_valid_rows": len(rows),
            "total_bad_rows_skipped": bad_rows,
        },
        "targets": TARGETS,
        "actual_counts": {
            "total_records": len(records),
            "by_stratum": dict(by_stratum),
            "by_selected_issue": dict(by_issue),
            "top_selected_issue_rating": dict(by_rating.most_common(20)),
        },
        "output": {
            "jsonl": str(jsonl_path),
        },
        "notes": [
            "Candidate set only: requires engineering adjudication to become true golden set.",
            "Precedent rows are sampled without replacement across strata.",
            "Legacy issues OC/COMPAT intentionally retained for backward-compat mapping tests.",
        ],
    }

    manifest_path = out_dir / "golden_set_mua_v1_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Markdown report
    md_path = docs_dir / "golden_set_mua_v1_candidate.md"
    lines = [
        "# MUA Golden Set V1 Candidate",
        "",
        f"Generated: {manifest['generated_at_utc']}",
        "",
        "## Source",
        "",
        f"- Dataset: `{source.name}`",
        f"- Path: `{source}`",
        f"- Valid rows parsed: {len(rows):,}",
        f"- Bad rows skipped: {bad_rows:,}",
        "",
        "## Candidate Size",
        "",
        f"- Total candidate records: **{len(records):,}**",
        "",
        "## Strata Counts",
        "",
        "| Stratum | Count |",
        "|---|---:|",
    ]
    for k, v in sorted(by_stratum.items()):
        lines.append(f"| `{k}` | {v} |")

    lines += [
        "",
        "## Selected Issue Counts",
        "",
        "| Issue | Count |",
        "|---|---:|",
    ]
    for k, v in sorted(by_issue.items()):
        lines.append(f"| `{k or 'EMPTY'}` | {v} |")

    lines += [
        "",
        "## Output Files",
        "",
        f"- JSONL: `{jsonl_path}`",
        f"- Manifest: `{manifest_path}`",
        "",
        "## Promotion Criteria To True Golden Set",
        "",
        "1. Dual-review adjudication on each candidate row (pass/fail and correction notes).",
        "2. Freeze labels under versioned schema (e.g., `golden_set_mua_v1.0`).",
        "3. Add regression harness checks in CI for deterministic replay.",
    ]

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(records)} records -> {jsonl_path}")
    print(f"Wrote manifest -> {manifest_path}")
    print(f"Wrote report -> {md_path}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build MUA golden set candidate.")
    parser.add_argument(
        "--source",
        default="/mnt/c/maptis-nlp/output/historic_muas_v2_heavy_maptis_full.ndjson",
        help="Source NDJSON path",
    )
    parser.add_argument(
        "--out-dir",
        default="/mnt/d/BoundState/boundstate_mira/data/mua_golden",
        help="Output directory for JSONL + manifest",
    )
    parser.add_argument(
        "--docs-dir",
        default="/mnt/d/BoundState/boundstate_mira/docs/mua_audit",
        help="Output directory for markdown report",
    )
    parser.add_argument("--seed", type=int, default=6016, help="Sampling seed")
    args = parser.parse_args()
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
