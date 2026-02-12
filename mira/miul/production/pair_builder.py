#!/usr/bin/env python3
"""
Codex v4 pair-row MIUL builder.

Design goals:
1) Keep extracted material rows at (Part Number, Drawing Source) granularity.
2) Build assembly structure directly from DT JSON (deterministic skeleton-first).
3) Keep rollback controls for safe operations:
   - MIUL_V4_STRUCTURAL_TREE_MODE=legacy
   - MIUL_V4_USE_DRAWING_PACKAGES=0
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from mira.miul.v3.builder import MIUL_COLUMNS


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _blank(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def _norm_part_number(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text in {"", "NAN", "<NA>", "NONE", "NULL"}:
        return ""
    # OCR noise: trailing separator dash on EPL rows ("PN -")
    text = re.sub(r"\s*[-–—]+\s*$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+\d+\.$", "", text)
    return text


_VARIANT_SUFFIX_RE = re.compile(r"^(?:[A-Z]|[A-Z]?\d+(?:/\d+)?)$")
_DRAWING_TOKEN_RE = re.compile(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)+")


def _part_number_match_keys(value: Any) -> set[str]:
    """Return generic match keys for part-number variant matching.

    Keys always include the full normalized part number, plus progressively
    trimmed variants when trailing segments look like variant/revision tokens
    (e.g., ``-A``, ``-1``, ``-1/2``).
    """
    pn = _norm_part_number(value)
    if not pn:
        return set()

    keys: set[str] = {pn}
    parts = pn.split("-")

    # Keep trimming trailing variant-like tokens, but only while at least two
    # core segments remain. This avoids collapsing core IDs like MER07543-001.
    while len(parts) >= 3 and _VARIANT_SUFFIX_RE.fullmatch(parts[-1]):
        parts = parts[:-1]
        keys.add("-".join(parts))

    return {k for k in keys if k}


def _leading_root_key(value: Any) -> str:
    """
    Extract a stable leading key (letters+digits) for drawing/part matching.

    Examples:
      - IMER07756-001 -> IMER07756
      - IMER07781A -> IMER07781
      - NAS1351N5-12 -> NAS1351
    """
    token = _norm_part_number(value)
    if not token:
        return ""
    # Use the first dashed/space-separated token to avoid swallowing suffixes
    # like "-001" into the root identifier.
    lead = re.split(r"[\s\-_\/]+", token)[0]
    match = re.match(r"^([A-Z]+\d+)", lead)
    return match.group(1) if match else ""


def _part_matches_drawing(part_number: str, drawing_number: str) -> bool:
    """
    Heuristic: determine whether a part references the same underlying drawing.

    This is intentionally permissive for revision/variant formatting differences
    (e.g. IMER07615-001 A vs IMER07615A).
    """
    pn = _norm_part_number(part_number)
    dwg = _norm_part_number(drawing_number)
    if not pn or not dwg:
        return False
    if pn == dwg:
        return True
    if _part_number_match_keys(pn) & _part_number_match_keys(dwg):
        return True
    pn_root = _leading_root_key(pn)
    dwg_root = _leading_root_key(dwg)
    if not (pn_root and dwg_root and pn_root == dwg_root):
        return False

    # Conservative fallback: treat "-001" drawing references as aliases
    # of the base drawing number (often with optional trailing revision letter).
    return bool(re.fullmatch(r"[A-Z]+\d+-001(?:\s+[A-Z])?", pn))


def _source_drawing_candidates(source_file: str) -> List[str]:
    if not source_file:
        return []

    stem = Path(source_file).stem
    upper_stem = _norm_part_number(stem)
    if not upper_stem:
        return []

    candidates: List[str] = []

    for sep in (".DRW", "_DRW", "_DRW_", "_DRW-"):
        if sep in upper_stem:
            prefix = _norm_part_number(upper_stem.split(sep)[0])
            if prefix:
                candidates.append(prefix)

    for token in _DRAWING_TOKEN_RE.findall(upper_stem):
        norm = _norm_part_number(token)
        if norm:
            candidates.append(norm)

    first_underscore = _norm_part_number(upper_stem.split("_")[0])
    if first_underscore:
        candidates.append(first_underscore)

    candidates.append(upper_stem)

    unique: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _source_drawing_from_file(source_file: str, dt_lookup: Optional[set[str]] = None) -> str:
    candidates = _source_drawing_candidates(source_file)
    if not candidates:
        return ""

    if dt_lookup:
        # Prefer exact DT-node names first.
        for candidate in candidates:
            if candidate in dt_lookup:
                return candidate

        # Then allow a unique key-overlap match (handles revision/variant
        # suffix differences like "-A" vs "-1" vs "-1/2").
        dt_nodes = sorted(dt_lookup)
        dt_keys = {node: _part_number_match_keys(node) for node in dt_nodes}
        for candidate in candidates:
            candidate_keys = _part_number_match_keys(candidate)
            if not candidate_keys:
                continue
            matches = [node for node in dt_nodes if candidate_keys & dt_keys[node]]
            if len(matches) == 1:
                return matches[0]

    return candidates[0]


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


def _material_get(material: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(material, dict):
        return material.get(field_name, default)
    return getattr(material, field_name, default)


def _material_confidence(material: Any) -> Dict[str, Any]:
    conf = _material_get(material, "confidence", None) or {}
    return conf if isinstance(conf, dict) else {}


def _material_worst_confidence(material: Any) -> float:
    confidence = _material_confidence(material)
    if not confidence:
        return 0.0
    try:
        return min(float(v or 0.0) for v in confidence.values())
    except (TypeError, ValueError):
        return 0.0


def _choose_best_field(materials: List[Any], field_name: str) -> str:
    best_value = ""
    best_score = -1.0
    for material in materials:
        raw_value = _material_get(material, field_name)
        if _blank(raw_value):
            continue
        try:
            score = float((_material_confidence(material) or {}).get(field_name, 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score > best_score:
            best_score = score
            best_value = str(raw_value).strip()
    return best_value


def _build_review_overrides(review_data: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    overrides: Dict[str, Dict[str, str]] = {}
    if not review_data:
        return overrides
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


def _has_identity_payload(row: Dict[str, Any]) -> bool:
    """True when a row carries identity-grade material evidence.

    Material form alone is not enough because assemblies often infer form
    without a concrete designation/spec.
    """
    for field_name in ("designation", "material_spec", "process_spec"):
        if not _blank(row.get(field_name, "")):
            return True
    return False


def _infer_miul_number(dt_json: Dict[str, Any], project: str) -> str:
    top_level = _norm_part_number(dt_json.get("top_level", ""))
    match = re.match(r"^([A-Z]+\d+)", top_level)
    if match:
        return match.group(1)
    if project:
        return _norm_part_number(project)
    return top_level or "MIUL_V4"


def _iter_materials_with_source(
    extraction_result: Any,
    dt_lookup: set,
) -> Iterable[Tuple[Any, str]]:
    """Yield (material, source_drawing) from packages or legacy flat materials."""
    use_packages = _env_flag("MIUL_V4_USE_DRAWING_PACKAGES", True)
    packages = getattr(extraction_result, "drawing_packages", None) or []
    if use_packages and packages:
        for pkg in packages:
            source_drawing_pkg = _norm_part_number(pkg.get("drawing_number", ""))
            for material in pkg.get("materials", []):
                source_drawing = source_drawing_pkg
                if not source_drawing:
                    source_drawing = _source_drawing_from_file(
                        str(_material_get(material, "source_file", "") or ""),
                        dt_lookup=dt_lookup,
                    )
                if not source_drawing:
                    source_drawing = _norm_part_number(_material_get(material, "nha", ""))
                yield material, source_drawing
        return

    for material in extraction_result.materials:
        source_drawing = _source_drawing_from_file(
            str(_material_get(material, "source_file", "") or ""),
            dt_lookup=dt_lookup,
        )
        pn = _norm_part_number(_material_get(material, "part_number", ""))
        if not source_drawing and pn in dt_lookup:
            source_drawing = pn
        if not source_drawing:
            source_drawing = _norm_part_number(_material_get(material, "nha", ""))
        yield material, source_drawing


def _known_drawing_numbers(
    extraction_result: Any,
    dt_json: Optional[Dict[str, Any]],
) -> set[str]:
    """Collect normalized drawing numbers available in this extraction."""
    known: set[str] = set()

    for node in (dt_json or {}).get("tree", []) or []:
        drawing_number = _norm_part_number(node.get("drawing_number", ""))
        if drawing_number:
            known.add(drawing_number)

    for pkg in getattr(extraction_result, "drawing_packages", None) or []:
        drawing_number = _norm_part_number(pkg.get("drawing_number", ""))
        if drawing_number:
            known.add(drawing_number)

    return known


def _variant_family_key(part_number: Any) -> str:
    """Collapse simple trailing revision letters (e.g. '-001 A' -> '-001')."""
    pn = _norm_part_number(part_number)
    if not pn:
        return ""
    return re.sub(r"\s+[A-Z]$", "", pn)


def _resolve_linked_drawing(part_number: str, known_drawings: set[str]) -> str:
    """Return a unique matched drawing for this part number, if any."""
    if not known_drawings:
        return ""
    matches = [
        drawing for drawing in known_drawings
        if _part_matches_drawing(part_number, drawing)
    ]
    if len(matches) == 1:
        return matches[0]
    return ""


def _row_quality_score(row: Dict[str, Any]) -> Tuple[int, int, int]:
    """Rank rows for dedupe preference."""
    return (
        1 if _has_identity_payload(row) else 0,
        int(row.get("sighting_count", 0) or 0),
        len(_norm_part_number(row.get("part_number", ""))),
    )


def build_pair_rows_from_v4_extraction(
    extraction_result: Any,
    review_data: Optional[Dict[str, Any]],
    dt_json: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Convert extraction result into material pair rows keyed by (Part Number, Drawing Source).
    """
    grouped: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
    review_overrides = _build_review_overrides(review_data)
    known_drawings = _known_drawing_numbers(extraction_result, dt_json)

    dt_nodes = (dt_json or {}).get("tree", [])
    dt_lookup = {
        _norm_part_number(node.get("drawing_number", ""))
        for node in dt_nodes
        if node.get("drawing_number")
    }

    for material, source_drawing in _iter_materials_with_source(extraction_result, dt_lookup):
        pn = _norm_part_number(_material_get(material, "part_number", ""))
        desc = str(_material_get(material, "part_description", "") or "")
        if _is_noise_material(pn, desc):
            continue
        grouped[(pn, _norm_part_number(source_drawing))].append(material)

    pair_rows: List[Dict[str, Any]] = []
    for (pn, source_drawing), sightings in grouped.items():
        sightings_sorted = sorted(sightings, key=_material_worst_confidence, reverse=True)
        primary = sightings_sorted[0]

        designation = _choose_best_field(sightings_sorted, "designation")
        material_spec = _choose_best_field(sightings_sorted, "material_spec")
        process_spec = _choose_best_field(sightings_sorted, "process_spec")
        material_form = _choose_best_field(sightings_sorted, "material_form")

        override = review_overrides.get(pn, {})
        if not _blank(override.get("designation")):
            designation = override["designation"]
        if not _blank(override.get("material_spec")):
            material_spec = override["material_spec"]
        if not _blank(override.get("process_spec")):
            process_spec = override["process_spec"]
        if not _blank(override.get("material_form")):
            material_form = override["material_form"]

        source_pages = sorted(
            {
                f"{str(_material_get(s, 'source_file', '') or '')} p"
                f"{int(_material_get(s, 'source_page', 0) or 0)}"
                for s in sightings
            }
        )

        pair_rows.append(
            {
                "part_number": pn,
                "source_drawing": source_drawing,
                "part_description": str(_material_get(primary, "part_description", "") or "").strip(),
                "quantity": _material_get(primary, "quantity", ""),
                "designation": designation,
                "material_spec": material_spec,
                "process_spec": process_spec,
                "material_form": material_form,
                "source_pages": source_pages,
                "sighting_count": len(sightings),
            }
        )

    # Suppress blank assembly-source duplicates when the same part has a
    # stronger identity row from another source drawing.
    by_pn: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        by_pn[_norm_part_number(row.get("part_number", ""))].append(row)

    pruned_rows: List[Dict[str, Any]] = []
    for pn, rows_for_pn in by_pn.items():
        _ = pn
        has_identity = any(_has_identity_payload(r) for r in rows_for_pn)
        if not has_identity:
            pruned_rows.extend(rows_for_pn)
            continue
        pruned_rows.extend([r for r in rows_for_pn if _has_identity_payload(r)])

    # Prefer rows that are anchored to their own drawing when available.
    # Also collapse same-source trailing revision duplicates (-001 vs -001 A).
    linked_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    no_link_rows: List[Dict[str, Any]] = []

    for row in pruned_rows:
        pn = _norm_part_number(row.get("part_number", ""))
        linked = _resolve_linked_drawing(pn, known_drawings)
        if linked:
            linked_groups[linked].append(row)
        else:
            no_link_rows.append(row)

    deduped_rows: List[Dict[str, Any]] = list(no_link_rows)

    for linked_drawing, rows_for_link in linked_groups.items():
        self_rows = [
            r for r in rows_for_link
            if _norm_part_number(r.get("source_drawing", "")) == linked_drawing
            and _part_matches_drawing(r.get("part_number", ""), linked_drawing)
        ]

        if self_rows:
            # If we have a true self-drawing row, keep only that best self row.
            if any(_has_identity_payload(r) for r in self_rows):
                self_rows = [r for r in self_rows if _has_identity_payload(r)]
            deduped_rows.append(max(self_rows, key=_row_quality_score))
            continue

        # No self row available: only collapse trivial trailing-letter variants
        # on the SAME source drawing (keeps intentional multi-assembly usage).
        buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for row in rows_for_link:
            source = _norm_part_number(row.get("source_drawing", ""))
            family = _variant_family_key(row.get("part_number", ""))
            buckets[(source, family)].append(row)

        for bucket_rows in buckets.values():
            deduped_rows.append(max(bucket_rows, key=_row_quality_score))

    return deduped_rows


def build_parts_json_for_summary(
    pair_rows: List[Dict[str, Any]],
    dt_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build summary payload consumed by v3 Excel exporter summary sheet.
    """
    drawings: Dict[str, Dict[str, Any]] = {}
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
        pn = _norm_part_number(row.get("part_number", ""))
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


def _build_base_headers(
    rows: List[Dict[str, Any]],
    miul_number: str,
    project: str,
) -> None:
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


def _make_data_row(
    next_index: int,
    pn: str,
    source: str,
    row: Dict[str, Any],
    part_description: str,
    nha: str,
    parent_ref: str,
    project: str,
    miul_number: str,
    env: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "Index": next_index,
        "Parent": 0,
        "_Parent Ref": parent_ref,
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
        "Environment": env["environment"],
        "Material Code": "",
        "Standard Part Number": "",
        "Contractor": "",
        "System": "",
        "Subsystem": "",
        "Max Temperature": env["max_temp"],
        "Min Temperature": env["min_temp"],
        "Fluid Type": env["fluid_type"],
        "Associate Contractor": "",
        "Project": project or miul_number,
        "Document Title": part_description,
        "Criticality": "",
        "Line Number": next_index,
        "Overall Evaluation": "",
        "Configuration Test": "",
        "Max Pressure": env["max_pressure"],
        "Min Pressure": env["min_pressure"],
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


def _has_material_payload(row: Dict[str, Any]) -> bool:
    for field_name in ("designation", "material_spec", "process_spec", "material_form"):
        if not _blank(row.get(field_name, "")):
            return True
    return False


def _extract_env_fields(environment: Optional[Any]) -> Dict[str, Any]:
    return {
        "fluid_type": getattr(environment, "fluid_type", "") if environment else "",
        "environment": getattr(environment, "environment", "") if environment else "",
        "max_temp": getattr(environment, "max_temp", "") if environment else "",
        "min_temp": getattr(environment, "min_temp", "") if environment else "",
        "max_pressure": getattr(environment, "max_pressure", "") if environment else "",
        "min_pressure": getattr(environment, "min_pressure", "") if environment else "",
    }


def _resolve_subpart_parent_ref(
    pn: str,
    source: str,
    dt_nodes: set,
    dt_parent: Dict[str, str],
    miul_number: str,
) -> str:
    if source in dt_nodes:
        return source
    if source:
        parent = _norm_part_number(dt_parent.get(source, ""))
        if parent:
            return parent
        source_keys = _part_number_match_keys(source)
        if source_keys:
            for node in dt_nodes:
                if source_keys & _part_number_match_keys(node):
                    return node
    parent = _norm_part_number(dt_parent.get(pn, ""))
    if parent:
        return parent
    pn_keys = _part_number_match_keys(pn)
    if pn_keys:
        for node in dt_nodes:
            if pn_keys & _part_number_match_keys(node):
                return node
    return miul_number


def _finalize_dataframe(rows: List[Dict[str, Any]], project: str, miul_number: str) -> pd.DataFrame:
    for row in rows:
        idx = int(row.get("Index", 0) or 0)
        if idx <= 2:
            row["Parent"] = 0

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


def _build_miul_from_pair_rows_legacy(
    pair_rows: List[Dict[str, Any]],
    dt_json: Dict[str, Any],
    project: str,
    environment: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Legacy pair-row builder for operational rollback.

    Uses pair rows directly without forcing DT skeleton completeness.
    """
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
    dt_nodes = set(dt_parent.keys())

    miul_number = _infer_miul_number(dt_json, project)
    env = _extract_env_fields(environment)

    rows: List[Dict[str, Any]] = []
    _build_base_headers(rows, miul_number, project)

    sortable = []
    has_dt_nodes = bool(dt_nodes)
    for original_idx, row in enumerate(pair_rows):
        pn = _norm_part_number(row.get("part_number", ""))
        source = _norm_part_number(row.get("source_drawing", ""))
        if has_dt_nodes:
            sort_key = (
                tree_order.get(source, 9999),
                0 if source != pn else 1,
                tree_order.get(pn, 9999),
                source,
                pn,
                original_idx,
            )
        else:
            # No DT hierarchy available: keep rows grouped by source drawing.
            sort_key = (source or "~", pn, original_idx)
        sortable.append((sort_key, pn, source, row))
    sortable.sort(key=lambda item: item[0])

    pn_to_first_index: Dict[str, int] = {miul_number: 2}
    next_index = 3
    for _, pn, source, row in sortable:
        is_tree_assembly = pn in dt_nodes
        if is_tree_assembly:
            parent_ref = dt_parent.get(pn) or miul_number
            nha = miul_number
        else:
            parent_ref = _resolve_subpart_parent_ref(pn, source, dt_nodes, dt_parent, miul_number)
            nha = ""

        part_description = str(row.get("part_description", "") or dt_title.get(pn, "")).strip()
        miul_row = _make_data_row(
            next_index=next_index,
            pn=pn,
            source=source,
            row=row,
            part_description=part_description,
            nha=nha,
            parent_ref=parent_ref,
            project=project,
            miul_number=miul_number,
            env=env,
        )
        rows.append(miul_row)
        if pn and pn not in pn_to_first_index:
            pn_to_first_index[pn] = next_index
        next_index += 1

    for row in rows:
        idx = int(row.get("Index", 0) or 0)
        if idx <= 2:
            continue
        parent_ref = _norm_part_number(row.get("_Parent Ref"))
        row["Parent"] = pn_to_first_index.get(parent_ref, 2)

    return _finalize_dataframe(rows, project, miul_number)


def _build_miul_from_pair_rows_structured(
    pair_rows: List[Dict[str, Any]],
    dt_json: Dict[str, Any],
    project: str,
    environment: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Deterministic builder:
    1) Build one assembly node for every DT drawing node (skeleton-first).
    2) Attach non-DT rows as subparts/material rows under resolved assemblies.
    3) Keep NHA semantics: assemblies=MIUL acronym, subparts=blank.
    """
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
    dt_ordered = [
        _norm_part_number(node.get("drawing_number", ""))
        for node in tree
        if _norm_part_number(node.get("drawing_number", ""))
    ]
    dt_nodes = set(dt_ordered)

    miul_number = _infer_miul_number(dt_json, project)
    env = _extract_env_fields(environment)

    rows: List[Dict[str, Any]] = []
    _build_base_headers(rows, miul_number, project)
    pn_to_first_index: Dict[str, int] = {miul_number: 2}
    next_index = 3

    normalized_entries: List[Dict[str, Any]] = []
    for i, row in enumerate(pair_rows):
        pn = _norm_part_number(row.get("part_number", ""))
        if not pn:
            continue
        source = _norm_part_number(row.get("source_drawing", ""))
        pn_keys = _part_number_match_keys(pn)
        source_keys = _part_number_match_keys(source)
        normalized_entries.append(
            {
                "entry_idx": i,
                "pn": pn,
                "pn_keys": pn_keys,
                "source": source,
                "source_keys": source_keys,
                "row": row,
            }
        )

    candidates_by_pn: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    candidates_by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in normalized_entries:
        if entry["pn"] in dt_nodes:
            candidates_by_pn[entry["pn"]].append(entry)
        for key in entry.get("pn_keys", set()):
            candidates_by_key[key].append(entry)

    consumed_entry_ids: set = set()

    # Phase 1: deterministic DT skeleton rows.
    for pn in dt_ordered:
        candidates = candidates_by_pn.get(pn, [])
        if not candidates:
            dt_keys = _part_number_match_keys(pn)
            seen_entry_ids: set[int] = set()
            merged: List[Dict[str, Any]] = []
            for key in dt_keys:
                for entry in candidates_by_key.get(key, []):
                    entry_id = int(entry["entry_idx"])
                    if entry_id in consumed_entry_ids or entry_id in seen_entry_ids:
                        continue
                    seen_entry_ids.add(entry_id)
                    merged.append(entry)
            candidates = merged
        chosen: Optional[Dict[str, Any]] = None
        if candidates:
            dt_keys = _part_number_match_keys(pn)
            candidates_sorted = sorted(
                candidates,
                key=lambda e: (
                    0 if e["pn"] == pn else 1,
                    -len((e.get("pn_keys") or set()) & dt_keys),
                    0 if _has_identity_payload(e["row"]) else 1,
                    -len((e.get("source_keys") or set()) & dt_keys),
                    tree_order.get(e["source"], 9999),
                    e["entry_idx"],
                ),
            )
            chosen = candidates_sorted[0]
            # Only consume exact DT-node rows; alias-derived non-DT part rows
            # should still flow as supplemental entries.
            if chosen.get("pn") in dt_nodes:
                consumed_entry_ids.add(chosen["entry_idx"])

        source = (chosen or {}).get("source", "") or pn
        source_row = (chosen or {}).get("row", {}) or {}
        part_description = str(source_row.get("part_description", "") or dt_title.get(pn, "")).strip()
        miul_row = _make_data_row(
            next_index=next_index,
            pn=pn,
            source=source,
            row=source_row,
            part_description=part_description,
            nha=miul_number,
            parent_ref=dt_parent.get(pn) or miul_number,
            project=project,
            miul_number=miul_number,
            env=env,
        )
        rows.append(miul_row)
        if pn not in pn_to_first_index:
            pn_to_first_index[pn] = next_index
        next_index += 1

    # Phase 2: material/subpart rows that are not consumed as skeleton rows.
    supplemental_entries: List[Dict[str, Any]] = []
    for entry in normalized_entries:
        if entry["entry_idx"] in consumed_entry_ids:
            continue
        if entry["pn"] in dt_nodes and not _has_material_payload(entry["row"]):
            continue
        supplemental_entries.append(entry)

    if dt_nodes:
        supplemental_entries.sort(
            key=lambda e: (
                tree_order.get(_resolve_subpart_parent_ref(e["pn"], e["source"], dt_nodes, dt_parent, miul_number), 9999),
                tree_order.get(e["source"], 9999),
                e["pn"],
                e["source"],
                e["entry_idx"],
            )
        )
    else:
        # Degraded no-DT mode: deterministic grouping by drawing source.
        supplemental_entries.sort(
            key=lambda e: (
                e["source"] or "~",
                e["pn"],
                e["entry_idx"],
            )
        )

    for entry in supplemental_entries:
        pn = entry["pn"]
        source = entry["source"]
        row = entry["row"]
        if pn in dt_nodes:
            parent_ref = pn
        else:
            parent_ref = _resolve_subpart_parent_ref(pn, source, dt_nodes, dt_parent, miul_number)
        part_description = str(row.get("part_description", "") or dt_title.get(pn, "")).strip()

        miul_row = _make_data_row(
            next_index=next_index,
            pn=pn,
            source=source,
            row=row,
            part_description=part_description,
            nha="",
            parent_ref=parent_ref,
            project=project,
            miul_number=miul_number,
            env=env,
        )
        rows.append(miul_row)
        if pn not in pn_to_first_index:
            pn_to_first_index[pn] = next_index
        next_index += 1

    for row in rows:
        idx = int(row.get("Index", 0) or 0)
        if idx <= 2:
            continue
        parent_ref = _norm_part_number(row.get("_Parent Ref"))
        row["Parent"] = pn_to_first_index.get(parent_ref, 2)

    return _finalize_dataframe(rows, project, miul_number)


def build_miul_from_pair_rows(
    pair_rows: List[Dict[str, Any]],
    dt_json: Dict[str, Any],
    project: str,
    environment: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Build MIUL dataframe from pair rows.

    `MIUL_V4_STRUCTURAL_TREE_MODE=legacy` switches back to pre-skeleton behavior.
    """
    mode = str(os.getenv("MIUL_V4_STRUCTURAL_TREE_MODE", "deterministic")).strip().lower()
    if mode == "legacy":
        return _build_miul_from_pair_rows_legacy(pair_rows, dt_json, project, environment)
    return _build_miul_from_pair_rows_structured(pair_rows, dt_json, project, environment)


def validate_miul_tree_against_dt(
    miul_df: pd.DataFrame,
    dt_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate that collapsed MIUL assembly structure matches DT hierarchy.

    Returns a structured result with mismatch details for API gating/logging.
    """
    tree = (dt_json or {}).get("tree", [])
    dt_parent = {
        _norm_part_number(node.get("drawing_number", "")): _norm_part_number(node.get("parent") or "")
        for node in tree
        if _norm_part_number(node.get("drawing_number", ""))
    }
    dt_nodes = list(dt_parent.keys())
    dt_node_set = set(dt_nodes)

    if "Index" not in miul_df.columns or "Part Number" not in miul_df.columns:
        return {
            "valid": False,
            "error": "MIUL dataframe missing required columns for tree validation.",
            "missing_nodes": dt_nodes,
            "extra_tree_nodes": [],
            "parent_mismatches": [],
            "tree_nha_mismatches": [],
            "subpart_nha_mismatches": [],
        }

    work = miul_df.copy()
    work = work[work["Index"].fillna(0).astype(int) != -1]
    data = work[work["Index"].fillna(0).astype(int) >= 3].copy()
    data["PN"] = data["Part Number"].map(_norm_part_number)
    data["NHA_N"] = data["NHA"].map(_norm_part_number) if "NHA" in data.columns else ""

    row2 = work[work["Index"].fillna(0).astype(int) == 2]
    miul_number = ""
    if not row2.empty:
        miul_number = _norm_part_number(row2.iloc[0].get("NHA", ""))

    pn_to_first_index: Dict[str, int] = {}
    idx_to_pn: Dict[int, str] = {}
    rows_by_index: Dict[int, Dict[str, Any]] = {}
    for _, row in data.sort_values("Index").iterrows():
        idx = int(row.get("Index") or 0)
        pn = _norm_part_number(row.get("PN", ""))
        rows_by_index[idx] = row.to_dict()
        idx_to_pn[idx] = pn
        if pn and pn not in pn_to_first_index:
            pn_to_first_index[pn] = idx

    miul_tree_nodes = {
        _norm_part_number(row.get("PN", ""))
        for _, row in data.iterrows()
        if _norm_part_number(row.get("NHA_N", "")) == miul_number
    }

    missing_nodes = sorted([pn for pn in dt_nodes if pn not in pn_to_first_index])
    extra_tree_nodes = sorted([pn for pn in miul_tree_nodes if pn and pn not in dt_node_set])

    tree_nha_mismatches: List[Dict[str, Any]] = []
    subpart_nha_mismatches: List[Dict[str, Any]] = []
    # Enforce tree-NHA semantics on the first (assembly) row for each DT node.
    for pn in dt_nodes:
        idx = pn_to_first_index.get(pn)
        if idx is None:
            continue
        row = rows_by_index.get(idx, {})
        nha = _norm_part_number(row.get("NHA_N", ""))
        if nha != miul_number:
            tree_nha_mismatches.append(
                {"index": idx, "part_number": pn, "actual_nha": nha, "expected_nha": miul_number}
            )
    for idx, row in rows_by_index.items():
        pn = _norm_part_number(row.get("PN", ""))
        nha = _norm_part_number(row.get("NHA_N", ""))
        if pn in dt_node_set:
            continue
        if nha:
            subpart_nha_mismatches.append(
                {"index": idx, "part_number": pn, "actual_nha": nha, "expected_nha": ""}
            )

    parent_mismatches: List[Dict[str, Any]] = []
    for pn in dt_nodes:
        idx = pn_to_first_index.get(pn)
        if idx is None:
            continue
        row = rows_by_index.get(idx, {})
        actual_parent_idx = int(row.get("Parent") or 0)
        actual_parent_pn = idx_to_pn.get(actual_parent_idx, "")
        actual_parent_norm = actual_parent_pn if actual_parent_pn in dt_node_set else "__ROOT__"
        expected_parent_pn = _norm_part_number(dt_parent.get(pn, ""))
        expected_parent_norm = expected_parent_pn if expected_parent_pn in dt_node_set else "__ROOT__"
        if actual_parent_norm != expected_parent_norm:
            parent_mismatches.append(
                {
                    "part_number": pn,
                    "index": idx,
                    "actual_parent_index": actual_parent_idx,
                    "actual_parent_part_number": actual_parent_norm,
                    "expected_parent_part_number": expected_parent_norm,
                }
            )

    valid = not (
        missing_nodes
        or extra_tree_nodes
        or parent_mismatches
        or tree_nha_mismatches
        or subpart_nha_mismatches
    )

    return {
        "valid": valid,
        "miul_number": miul_number,
        "dt_node_count": len(dt_nodes),
        "miul_data_rows": int(len(data)),
        "missing_nodes": missing_nodes,
        "extra_tree_nodes": extra_tree_nodes,
        "parent_mismatches": parent_mismatches,
        "tree_nha_mismatches": tree_nha_mismatches,
        "subpart_nha_mismatches": subpart_nha_mismatches,
    }
