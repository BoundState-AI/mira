#!/usr/bin/env python3
"""
Codex MIUL pipeline:
1) Extract materials/specs/process specs into JSON
2) Build MIUL using DT JSON NHA as authority
3) Identify MIUL gaps
4) Emit correction package for user review
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Ensure workspace root is importable when executed as a script.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mira.miul.v3.builder import MIUL_COLUMNS, _export_miul_excel
from mira.miul.workflow import get_miul_workflow


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blank(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def _norm_part_number(part_number: Any) -> str:
    text = str(part_number or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+\d+\.$", "", text)
    return text


def _source_drawing_from_file(source_file: str) -> str:
    if not source_file:
        return ""
    stem = Path(source_file).stem
    for sep in (".DRW", "_DRW", "_drw", "_Drw"):
        if sep in stem:
            return stem.split(sep)[0].upper()
    return (stem.split("_")[0] if "_" in stem else stem).upper()


def _is_noise_material(part_number: str, description: str) -> bool:
    pn = _norm_part_number(part_number)
    desc = str(description or "").upper()
    if not pn:
        return True
    if re.fullmatch(r"\d+\.?", pn):
        return True
    if pn.startswith("NOTE") or re.fullmatch(r"NOTE-?\d+", pn):
        return True
    if "REFERENCE ONLY" in desc:
        return True
    return False


def _material_worst_confidence(material: Dict[str, Any]) -> float:
    confidence = material.get("confidence") or {}
    if not confidence:
        return 0.0
    try:
        return min(float(v or 0.0) for v in confidence.values())
    except (TypeError, ValueError):
        return 0.0


def _choose_best_field(materials: List[Dict[str, Any]], field_name: str) -> Tuple[str, float]:
    best_value = ""
    best_score = -1.0
    for material in materials:
        raw_value = material.get(field_name)
        if _blank(raw_value):
            continue
        score = float((material.get("confidence") or {}).get(field_name, 0.0) or 0.0)
        if score > best_score:
            best_score = score
            best_value = str(raw_value).strip()
    return best_value, (best_score if best_score >= 0.0 else 0.0)


def _infer_miul_number(dt_json: Dict[str, Any], project: str) -> str:
    top_level = _norm_part_number(dt_json.get("top_level", ""))
    match = re.match(r"^([A-Z]+\d+)", top_level)
    if match:
        return match.group(1)
    if project:
        return _norm_part_number(project)
    return top_level or "MIUL_CODEX"


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_from_session(session_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from mira.miul.production.session import V4Session

    session = V4Session(session_id)
    extraction = session.load_extraction()
    if extraction is None:
        raise RuntimeError(f"Session {session_id} has no extraction data")
    review = session.load_review() or {}
    return extraction.to_dict(), review


def _run_extraction(drawings_dir: Path, dt_json: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from mira.miul.production.extractor import MIULVisionExtractor, identify_review_items

    extractor = MIULVisionExtractor()
    result = extractor.extract_drawing_set(drawings_dir, dt_json)
    review = identify_review_items(result)
    return result.to_dict(), review


def _build_review_overrides(review_data: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    overrides: Dict[str, Dict[str, str]] = {}
    for item in review_data.get("review_items", []):
        pn = _norm_part_number(item.get("part_number", ""))
        if not pn:
            continue
        fields = item.get("fields") or {}
        overrides[pn] = {
            "designation": str((fields.get("designation") or {}).get("value") or "").strip(),
            "material_spec": str((fields.get("material_spec") or {}).get("value") or "").strip(),
            "process_spec": str((fields.get("process_spec") or {}).get("value") or "").strip(),
            "material_form": str((fields.get("material_form") or {}).get("value") or "").strip(),
        }
    return overrides


def _group_materials_for_json(
    extraction_data: Dict[str, Any],
    review_data: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Counter]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    pn_candidates: Dict[str, Dict[str, Counter]] = defaultdict(
        lambda: {
            "designation": Counter(),
            "material_spec": Counter(),
            "process_spec": Counter(),
            "material_form": Counter(),
        }
    )

    review_overrides = _build_review_overrides(review_data)

    for material in extraction_data.get("materials", []):
        pn = _norm_part_number(material.get("part_number"))
        desc = str(material.get("part_description") or "")
        if _is_noise_material(pn, desc):
            continue
        source_drawing = _source_drawing_from_file(str(material.get("source_file") or ""))
        grouped[(pn, source_drawing)].append(material)

    pair_rows: List[Dict[str, Any]] = []
    for (pn, source_drawing), sightings in grouped.items():
        sightings_sorted = sorted(sightings, key=_material_worst_confidence, reverse=True)
        primary = sightings_sorted[0]

        designation, _ = _choose_best_field(sightings_sorted, "designation")
        material_spec, _ = _choose_best_field(sightings_sorted, "material_spec")
        process_spec, _ = _choose_best_field(sightings_sorted, "process_spec")
        material_form, _ = _choose_best_field(sightings_sorted, "material_form")

        override = review_overrides.get(pn, {})
        if not _blank(override.get("designation")):
            designation = override["designation"]
        if not _blank(override.get("material_spec")):
            material_spec = override["material_spec"]
        if not _blank(override.get("process_spec")):
            process_spec = override["process_spec"]
        if not _blank(override.get("material_form")):
            material_form = override["material_form"]

        for field, value in (
            ("designation", designation),
            ("material_spec", material_spec),
            ("process_spec", process_spec),
            ("material_form", material_form),
        ):
            if not _blank(value):
                pn_candidates[pn][field][str(value).strip()] += 1

        source_pages = sorted(
            {f"{str(s.get('source_file') or '')} p{int(s.get('source_page') or 0)}" for s in sightings}
        )

        pair_rows.append(
            {
                "part_number": pn,
                "source_drawing": source_drawing,
                "part_description": str(primary.get("part_description") or "").strip(),
                "quantity": primary.get("quantity"),
                "designation": designation,
                "material_spec": material_spec,
                "process_spec": process_spec,
                "material_form": material_form,
                "source_pages": source_pages,
                "sighting_count": len(sightings),
            }
        )

    return pair_rows, pn_candidates


def _build_miul_from_pair_rows(
    pair_rows: List[Dict[str, Any]],
    dt_json: Dict[str, Any],
    project: str,
) -> pd.DataFrame:
    tree = dt_json.get("tree", [])
    tree_order = {
        _norm_part_number(node.get("drawing_number", "")): i for i, node in enumerate(tree)
    }
    dt_parent = {
        _norm_part_number(node.get("drawing_number", "")): _norm_part_number(node.get("parent") or "")
        for node in tree
    }
    dt_title = {
        _norm_part_number(node.get("drawing_number", "")): str(node.get("title") or "").strip()
        for node in tree
    }

    miul_number = _infer_miul_number(dt_json, project)

    rows: List[Dict[str, Any]] = []
    rows.append(
        {
            "Index": 1,
            "Parent": 0,
            "Part Number": miul_number,
            "Part Description": f"{miul_number} Material Identification Usage List",
            "Nomenclature": f"{miul_number} MIUL",
            "NHA": "",
            "Drawing Source": "",
            "Project": project or miul_number,
        }
    )
    rows.append(
        {
            "Index": 2,
            "Parent": 0,
            "Part Number": miul_number,
            "Part Description": f"{miul_number} Material Identification Usage List",
            "Nomenclature": f"{miul_number} MIUL",
            "NHA": miul_number,
            "Drawing Source": "",
            "Project": project or miul_number,
        }
    )

    sortable = []
    for row in pair_rows:
        pn = _norm_part_number(row["part_number"])
        source = _norm_part_number(row["source_drawing"])
        sortable.append(
            (
                tree_order.get(source, 9999),
                0 if source != pn else 1,
                tree_order.get(pn, 9999),
                pn,
                source,
                row,
            )
        )
    sortable.sort()

    pn_to_first_index: Dict[str, int] = {miul_number: 2}
    next_index = 3
    for _, _, _, _, _, row in sortable:
        pn = _norm_part_number(row["part_number"])
        source = _norm_part_number(row["source_drawing"])

        if pn in dt_parent and source == pn:
            nha = dt_parent.get(pn) or miul_number
        else:
            nha = source or dt_parent.get(pn) or miul_number

        part_description = row["part_description"] or dt_title.get(pn, "")

        miul_row = {
            "Index": next_index,
            "Parent": 0,  # Filled later
            "Part Number": pn,
            "Part Description": part_description,
            "Nomenclature": part_description,
            "NHA": nha,
            "Change Letter": "",
            "Drawing Source": source,
            "Material Form": row.get("material_form", ""),
            "Material Manufacturer": "",
            "Designation": row.get("designation", ""),
            "Material Specification": row.get("material_spec", ""),
            "Process Specification": row.get("process_spec", ""),
            "Environment": "",
            "Material Code": "",
            "Standard Part Number": "",
            "Contractor": "",
            "System": "",
            "Subsystem": "",
            "Max Temperature": "",
            "Min Temperature": "",
            "Fluid Type": "",
            "Associate Contractor": "",
            "Project": project or miul_number,
            "Document Title": part_description,
            "Criticality": "",
            "Line Number": next_index,
            "Overall Evaluation": "",
            "Configuration Test": "",
            "Max Pressure": "",
            "Min Pressure": "",
            "MUA Rationale": "",
            "Cure Codes": "",
            "FLAM": "",
            "SCC": "",
            "CORR": "",
            "TVS": "",
            "TOX": "",
            "FS": "",
            "Remarks": "",
        }
        rows.append(miul_row)
        if pn not in pn_to_first_index:
            pn_to_first_index[pn] = next_index
        next_index += 1

    for row in rows:
        idx = int(row.get("Index", 0) or 0)
        if idx <= 2:
            row["Parent"] = 0
            continue
        nha = _norm_part_number(row.get("NHA"))
        row["Parent"] = pn_to_first_index.get(nha, 2)

    rows.append(
        {
            "Index": -1,
            "Parent": "",
            "Part Number": "",
            "Part Description": "",
            "Nomenclature": "",
            "NHA": "",
            "Drawing Source": "",
            "Project": project or miul_number,
        }
    )

    df = pd.DataFrame(rows)
    for column in MIUL_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[[column for column in MIUL_COLUMNS if column in df.columns]]


def _identify_gaps(
    miul_df: pd.DataFrame,
    dt_json: Dict[str, Any],
    pair_rows: List[Dict[str, Any]],
    pn_candidates: Dict[str, Dict[str, Counter]],
) -> List[Dict[str, Any]]:
    dt_type = {
        _norm_part_number(node.get("drawing_number", "")): str(node.get("type") or "").upper()
        for node in dt_json.get("tree", [])
    }
    pair_lookup = {
        (_norm_part_number(row["part_number"]), _norm_part_number(row["source_drawing"])): row
        for row in pair_rows
    }

    gaps: List[Dict[str, Any]] = []
    for _, row in miul_df.iterrows():
        index_value = int(row.get("Index", 0) or 0)
        if index_value <= 2 or index_value == -1:
            continue
        part_number = _norm_part_number(row.get("Part Number"))
        if not part_number:
            continue
        source_drawing = _norm_part_number(row.get("Drawing Source"))
        is_assembly_self_row = (
            source_drawing == part_number and dt_type.get(part_number, "") == "ASSEMBLY"
        )

        missing_fields: List[str] = []
        if _blank(row.get("NHA")):
            missing_fields.append("NHA")
        if not is_assembly_self_row and _blank(row.get("Designation")):
            missing_fields.append("Designation")
        if not _blank(row.get("Designation")) and _blank(row.get("Material Specification")):
            missing_fields.append("Material Specification")
        if _blank(row.get("Process Specification")):
            missing_fields.append("Process Specification")

        if not missing_fields:
            continue

        severity = "low"
        if any(field in {"NHA", "Designation"} for field in missing_fields):
            severity = "high"
        elif "Material Specification" in missing_fields:
            severity = "medium"

        candidates = pn_candidates.get(part_number, {})
        suggestion = {
            "designation": [value for value, _ in candidates.get("designation", Counter()).most_common(3)],
            "material_spec": [
                value for value, _ in candidates.get("material_spec", Counter()).most_common(3)
            ],
            "process_spec": [
                value for value, _ in candidates.get("process_spec", Counter()).most_common(3)
            ],
        }

        pair_key = (part_number, source_drawing)
        source_pages = (pair_lookup.get(pair_key) or {}).get("source_pages", [])

        gaps.append(
            {
                "index": index_value,
                "part_number": part_number,
                "drawing_source": source_drawing,
                "nha": str(row.get("NHA") or "").strip(),
                "missing_fields": missing_fields,
                "severity": severity,
                "current_values": {
                    "designation": str(row.get("Designation") or "").strip(),
                    "material_spec": str(row.get("Material Specification") or "").strip(),
                    "process_spec": str(row.get("Process Specification") or "").strip(),
                },
                "suggested_values": suggestion,
                "source_pages": source_pages,
            }
        )

    return gaps


def _build_parts_json_for_summary(
    pair_rows: List[Dict[str, Any]],
    dt_json: Dict[str, Any],
) -> Dict[str, Any]:
    drawings = {}
    for node in dt_json.get("tree", []):
        drawing_number = _norm_part_number(node.get("drawing_number", ""))
        if not drawing_number:
            continue
        drawings[drawing_number] = {
            "title": str(node.get("title") or "").strip(),
            "drawing_type": str(node.get("type") or "").upper(),
            "revision": "",
        }

    parts: Dict[str, Dict[str, Any]] = {}
    for row in pair_rows:
        pn = _norm_part_number(row.get("part_number"))
        if not pn or pn in parts:
            continue
        parts[pn] = {
            "description": row.get("part_description", ""),
            "material": row.get("designation", ""),
            "material_spec": row.get("material_spec", ""),
            "process_spec": row.get("process_spec", ""),
            "source_drawing": _norm_part_number(row.get("source_drawing", "")),
        }

    return {"parts": parts, "drawings": drawings}


def run_pipeline(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    dt_json = _load_json(args.dt_json)

    if args.session_id:
        extraction_data, review_data = _load_from_session(args.session_id)
    elif args.extraction_json:
        extraction_data = _load_json(args.extraction_json)
        if args.review_json and args.review_json.exists():
            review_data = _load_json(args.review_json)
        else:
            review_data = {}
    else:
        extraction_data, review_data = _run_extraction(args.drawings_dir, dt_json)

    extraction_out = output_dir / "materials_extracted_codex.json"
    extraction_out.write_text(json.dumps(extraction_data, indent=2), encoding="utf-8")

    review_out = output_dir / "review_items_codex.json"
    review_out.write_text(json.dumps(review_data, indent=2), encoding="utf-8")

    pair_rows, pn_candidates = _group_materials_for_json(extraction_data, review_data)
    pair_rows_out = output_dir / "materials_by_drawing_codex.json"
    pair_rows_payload = {
        "generated_at": _now_iso(),
        "pair_row_count": len(pair_rows),
        "pair_rows": pair_rows,
    }
    pair_rows_out.write_text(json.dumps(pair_rows_payload, indent=2), encoding="utf-8")

    project = args.project or _infer_miul_number(dt_json, "")
    miul_df = _build_miul_from_pair_rows(pair_rows, dt_json, project)

    enrich_stats = {"enabled": not args.no_enrich}
    if not args.no_enrich:
        workflow = get_miul_workflow()
        miul_df, codes_found, quarantine = workflow.lookup_material_codes(miul_df)
        miul_df, rating_stats = workflow.fetch_ratings(miul_df)
        enrich_stats.update(
            {
                "codes_found": codes_found,
                "quarantine_count": len(quarantine),
                "rating_stats": rating_stats,
            }
        )

    miul_json_out = output_dir / "miul_rows_codex.json"
    miul_json_out.write_text(
        json.dumps(
            {
                "generated_at": _now_iso(),
                "project": project,
                "rows": miul_df.to_dict(orient="records"),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    miul_xlsx_out = output_dir / "MIUL_codex.xlsx"
    parts_json_for_summary = _build_parts_json_for_summary(pair_rows, dt_json)
    _export_miul_excel(miul_df, miul_xlsx_out, project, dt_json, parts_json_for_summary)

    gaps = _identify_gaps(miul_df, dt_json, pair_rows, pn_candidates)
    gaps_out = output_dir / "miul_gaps_codex.json"
    gaps_out.write_text(
        json.dumps(
            {
                "generated_at": _now_iso(),
                "project": project,
                "gap_count": len(gaps),
                "gaps": gaps,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    correction_df = pd.DataFrame(
        [
            {
                "Index": gap["index"],
                "Part Number": gap["part_number"],
                "Drawing Source": gap["drawing_source"],
                "NHA": gap["nha"],
                "Missing Fields": ", ".join(gap["missing_fields"]),
                "Severity": gap["severity"],
                "Current Designation": gap["current_values"]["designation"],
                "Current Material Specification": gap["current_values"]["material_spec"],
                "Current Process Specification": gap["current_values"]["process_spec"],
                "Suggested Designations": "; ".join(gap["suggested_values"]["designation"]),
                "Suggested Material Specs": "; ".join(gap["suggested_values"]["material_spec"]),
                "Suggested Process Specs": "; ".join(gap["suggested_values"]["process_spec"]),
                "Source Pages": "; ".join(gap["source_pages"]),
            }
            for gap in gaps
        ]
    )
    correction_out = output_dir / "miul_correction_queue_codex.xlsx"
    correction_df.to_excel(correction_out, index=False)

    summary = {
        "project": project,
        "outputs": {
            "extraction_json": str(extraction_out),
            "review_json": str(review_out),
            "materials_by_drawing_json": str(pair_rows_out),
            "miul_json": str(miul_json_out),
            "miul_excel": str(miul_xlsx_out),
            "gaps_json": str(gaps_out),
            "correction_queue_excel": str(correction_out),
        },
        "counts": {
            "raw_extracted_materials": len(extraction_data.get("materials", [])),
            "pair_rows": len(pair_rows),
            "miul_rows": len(miul_df),
            "gaps": len(gaps),
        },
        "enrichment": enrich_stats,
    }

    summary_out = output_dir / "pipeline_summary_codex.json"
    summary_out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Codex MIUL 4-step pipeline using DT JSON as NHA authority.",
    )
    parser.add_argument(
        "--drawings-dir",
        type=Path,
        default=Path(r"C:\Users\jwilde2\Desktop\DMLLV"),
        help="Directory containing drawing PDFs (used when running extraction).",
    )
    parser.add_argument(
        "--dt-json",
        type=Path,
        required=True,
        help="Corrected DT JSON from DT editor.",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default="",
        help="Use an existing v4 session extraction_id instead of re-extracting.",
    )
    parser.add_argument(
        "--extraction-json",
        type=Path,
        default=None,
        help="Path to previously saved extraction JSON (alternative to session-id).",
    )
    parser.add_argument(
        "--review-json",
        type=Path,
        default=None,
        help="Path to review JSON to apply human corrections (optional).",
    )
    parser.add_argument(
        "--project",
        type=str,
        default="",
        help="Project identifier for output workbook.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("miul_codex"),
        help="Output directory for all _codex artifacts.",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip material code and rating enrichment.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    summary = run_pipeline(args)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
