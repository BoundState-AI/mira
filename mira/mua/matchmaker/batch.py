"""Batch import and bulk-apply helpers for matchmaker sessions."""

from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any, Optional

import pandas as pd

from .models import IssueOutcome, IssueStatus, MatchmakerEvent, normalize_issue_code
from .session import MatchmakerSessionStore

logger = logging.getLogger(__name__)

_INVALID_TEXT = {"", "NAN", "NONE", "NULL", "N/A", "NA", "(MISSING)", "MISSING"}
_PASS_RATINGS = {"A", "B", "A-CURRENT", "B-CURRENT", "PASS", "P", "1", "2"}
_RATING_MAP = {"1": "A", "2": "B", "3": "C", "4": "D"}
_TRIGGER_COLUMNS = {
    "FLAM": ("flam", "flammability"),
    "SCC": ("scc", "stress corrosion"),
    "CORR": ("corr", "corrosion"),
    "TVS": ("tvs", "thermal vacuum"),
    "TOX": ("tox", "offgas", "offgassing"),
    "FS": ("fs", "fluid susceptibility", "fluid compat"),
}


def parse_miul_upload(contents: bytes, filename: str) -> list[dict[str, Any]]:
    """Parse MIUL upload into grouped session candidates.

    Primary path mirrors v7 behavior by using trigger buckets from
    ``mira.miul.mua_trigger_analyzer`` (non-A parts, material/signature/env buckets).
    If that path fails (missing columns/sheet shape), fallback to a generic
    material/environment grouping parser.
    """

    if not filename.lower().endswith((".xlsx", ".xls")):
        raise ValueError("MIUL upload must be an Excel file (.xlsx or .xls)")

    bucket_groups = _parse_with_trigger_buckets(contents, filename)
    if bucket_groups:
        return bucket_groups

    return _parse_generic_miul(contents)


def _parse_with_trigger_buckets(contents: bytes, filename: str) -> list[dict[str, Any]]:
    """v7-compatible bucket extraction for MIUL imports."""

    try:
        from mira.miul.mua_trigger_analyzer import analyze_miul_bytes, build_trigger_buckets
    except Exception:
        logger.exception("Unable to import MIUL trigger analyzer; falling back to generic parser.")
        return []

    try:
        analysis = analyze_miul_bytes(contents, workbook_name=filename, sheet_name="MIUL")
        bucket_result = build_trigger_buckets(analysis)
    except Exception:
        logger.info("Trigger-bucket MIUL parse failed; using generic parse fallback.")
        return []

    raw_buckets = list(bucket_result.get("material_signature_buckets") or [])
    if not raw_buckets:
        return []

    # Index part trigger rows by the exact bucket-id construction from analyzer.
    by_bucket_id: dict[str, list[dict[str, Any]]] = {}
    for part in analysis.get("part_triggers", []):
        triggers = part.get("triggers", [])
        signature = "|".join(sorted(f"{t['issue']}:{t['rating']}" for t in triggers))
        env = _clean_text(part.get("environment"))
        material_code = _clean_text(part.get("material_code")) or "(missing)"
        bucket_id = f"{material_code}::{signature}::{env}"
        by_bucket_id.setdefault(bucket_id, []).append(part)

    groups: list[dict[str, Any]] = []
    for bucket in raw_buckets:
        bucket_id = str(bucket.get("bucket_id") or "")
        bucket_parts = by_bucket_id.get(bucket_id, [])

        material_code = _clean_text(bucket.get("material_code"))
        designation = _top_designation(bucket.get("designations"))
        if not designation and bucket_parts:
            designation = _clean_text(bucket_parts[0].get("designation"))

        material_input = designation or material_code
        if not material_input:
            continue

        environment = _environment_from_bucket(bucket)
        sample_parts = _collect_unique(bucket_parts, "part_number", limit=8)
        sample_desc = _collect_unique(bucket_parts, "part_description", limit=3)

        groups.append(
            {
                "material_input": material_input,
                "environment": environment,
                "part_count": int(bucket.get("part_count") or len(bucket_parts) or 0),
                "sample_part_numbers": sample_parts,
                "sample_descriptions": sample_desc,
                "trigger_signature": str(bucket.get("trigger_signature") or ""),
            }
        )

    groups.sort(key=lambda g: (-int(g.get("part_count", 0)), str(g.get("material_input", "")).upper()))
    return groups


def _parse_generic_miul(contents: bytes) -> list[dict[str, Any]]:
    """Fallback parser for MIUL-like workbooks missing trigger columns."""

    workbook = pd.read_excel(BytesIO(contents), sheet_name=None, engine="openpyxl")
    if not workbook:
        return []

    # Prefer explicit MIUL sheet, otherwise first sheet.
    if "MIUL" in workbook:
        frame = workbook["MIUL"].copy()
    else:
        frame = next(iter(workbook.values())).copy()

    if frame.empty:
        return []

    material_code_col = _find_column(
        frame,
        "material code",
        "maptis code",
        "material_code",
    )
    designation_col = _find_column(
        frame,
        "material designation",
        "designation",
        "material",
    )
    fallback_material_col = _find_column(
        frame,
        "material_name",
        "material description",
        "item description",
        "nomenclature",
    )

    if not material_code_col and not designation_col and not fallback_material_col:
        raise ValueError("Could not locate a material/designation column in MIUL file.")

    medium_col = _find_column(frame, "medium", "environment", "env")
    location_col = _find_column(frame, "location", "habitable")
    o2_col = _find_column(frame, "o2", "o2_percent", "oxygen")
    pressure_col = _find_column(frame, "pressure", "psia")
    tmin_col = _find_column(frame, "temp_min", "tmin")
    tmax_col = _find_column(frame, "temp_max", "tmax")
    fluid_col = _find_column(frame, "fluid type", "fluid", "media")
    part_col = _find_column(frame, "part", "part_number", "pn")
    description_col = _find_column(frame, "description", "item description")
    trigger_cols = _detect_trigger_columns(frame)

    groups: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        material_code = _clean_text(row.get(material_code_col)) if material_code_col else ""
        designation = _clean_text(row.get(designation_col)) if designation_col else ""
        fallback_material = _clean_text(row.get(fallback_material_col)) if fallback_material_col else ""

        material_input = designation or material_code
        if not material_input and _looks_like_material_text(fallback_material):
            material_input = fallback_material
        if not material_input:
            continue
        if not material_code and not _looks_like_material_text(material_input):
            continue

        medium_text = _clean_text(row.get(medium_col)) if medium_col else ""
        fluid_text = _clean_text(row.get(fluid_col)) if fluid_col else ""
        medium = _normalize_medium(medium_text or fluid_text or "AIR")
        location = _normalize_location(_clean_text(row.get(location_col)) if location_col else "habitable")
        o2 = _to_float(row.get(o2_col), 21.0) if o2_col else 21.0
        pressure = _to_float(row.get(pressure_col), 14.7) if pressure_col else 14.7
        tmin = _to_float(row.get(tmin_col), 60.0) if tmin_col else 60.0
        tmax = _to_float(row.get(tmax_col), 85.0) if tmax_col else 85.0
        description = _clean_text(row.get(description_col)) if description_col else ""
        part = _clean_text(row.get(part_col)) if part_col else ""
        trigger_signature = _build_trigger_signature(row, trigger_cols)

        material_key = (material_code or material_input).upper()
        key = "|".join(
            [
                material_key,
                _medium_bucket(medium, o2),
                location,
                trigger_signature,
            ]
        )
        group = groups.setdefault(
            key,
            {
                "material_input": material_input,
                "environment": {
                    "o2_percent": o2,
                    "pressure_psia": pressure,
                    "temp_min_f": tmin,
                    "temp_max_f": tmax,
                    "medium": medium,
                    "location": location,
                    "application": description,
                },
                "part_count": 0,
                "sample_part_numbers": [],
                "sample_descriptions": [],
                "trigger_signature": trigger_signature,
            },
        )
        group["part_count"] += 1
        group_env = group["environment"]
        group_env["o2_percent"] = max(float(group_env["o2_percent"]), float(o2))
        group_env["pressure_psia"] = max(float(group_env["pressure_psia"]), float(pressure))
        group_env["temp_min_f"] = min(float(group_env["temp_min_f"]), float(tmin))
        group_env["temp_max_f"] = max(float(group_env["temp_max_f"]), float(tmax))
        if not _clean_text(group_env.get("application")) and description:
            group_env["application"] = description

        if part and part not in group["sample_part_numbers"] and len(group["sample_part_numbers"]) < 5:
            group["sample_part_numbers"].append(part)
        if description and description not in group["sample_descriptions"] and len(group["sample_descriptions"]) < 3:
            group["sample_descriptions"].append(description)

    grouped = list(groups.values())
    grouped.sort(key=lambda g: (-int(g.get("part_count", 0)), str(g.get("material_input", "")).upper()))
    return grouped


def bulk_apply_cat3_code(
    store: MatchmakerSessionStore,
    session_ids: list[str],
    issue: str,
    code: str,
    confirmation: str,
    rule_pack_version: str,
) -> dict[str, Any]:
    """Apply a Cat III code across multiple sessions with explicit confirmation."""

    issue_code = normalize_issue_code(issue)
    updated: list[str] = []
    skipped: list[dict[str, str]] = []

    for sid in session_ids:
        session = store.get(sid)
        if session is None:
            skipped.append({"session_id": sid, "reason": "session_not_found"})
            continue

        state = session.issues.get(issue_code.value)
        if state is None:
            skipped.append({"session_id": sid, "reason": "issue_not_present"})
            continue

        state.selected_code = code
        state.candidate_codes = [code]
        state.outcome = IssueOutcome.CAT_III
        state.status = IssueStatus.DONE
        state.warnings = [f"Bulk apply confirmation: {confirmation}"]
        session.issues[issue_code.value] = state
        session.events.append(
            MatchmakerEvent(
                action="bulk_code_applied",
                issue=issue_code.value,
                code=code,
                note=confirmation,
                rule_pack_version=rule_pack_version,
            )
        )
        store.save(session)
        updated.append(sid)

    return {
        "issue": issue_code.value,
        "code": code,
        "updated_sessions": updated,
        "skipped_sessions": skipped,
        "updated_count": len(updated),
        "skipped_count": len(skipped),
    }


def _find_column(frame: pd.DataFrame, *keywords: str) -> Optional[str]:
    lowered = {col: str(col).strip().lower() for col in frame.columns}
    for keyword in keywords:
        for original, lowered_name in lowered.items():
            if keyword in lowered_name:
                return original
    return None


def _to_float(value: Any, default: float) -> float:
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return default
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any) -> str:
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return ""
    except Exception:
        pass
    text = str(value or "").strip()
    if text.upper() in _INVALID_TEXT:
        return ""
    return text


def _normalize_location(location: str) -> str:
    text = _clean_text(location).lower()
    if not text:
        return "habitable"
    if "non" in text and "habit" in text:
        return "non-habitable"
    if "habit" in text:
        return "habitable"
    return text


def _normalize_medium(medium: str) -> str:
    text = _clean_text(medium).upper().replace(" ", "_")
    if not text:
        return "AIR"
    if any(token in text for token in ("GH2", "LH2", "HYDROGEN")):
        return "HYDROGEN"
    if any(token in text for token in ("GOX", "LOX", "OXYGEN", "ENRICHED_O2", "ENRICHED_AIR")):
        if "LOX" in text:
            return "LOX"
        if "GOX" in text:
            return "GOX"
        if "ENRICHED" in text:
            return "ENRICHED_AIR"
        return "OXYGEN"
    if "AIR" in text:
        return "AIR"
    return text


def _medium_bucket(medium: str, o2_percent: float) -> str:
    normalized = _normalize_medium(medium)
    if normalized in {"LOX", "GOX", "OXYGEN"}:
        return "OXYGEN"
    if normalized == "HYDROGEN":
        return "HYDROGEN"
    if o2_percent >= 23.5:
        return "ENRICHED_AIR"
    return normalized


def _looks_like_material_text(text: str) -> bool:
    value = _clean_text(text).upper()
    if not value:
        return False
    if "MATERIAL IDENTIFICATION USAGE LIST" in value:
        return False
    if _looks_like_part_number(value):
        return False
    known_tokens = (
        "ALUMIN",
        "STEEL",
        "A286",
        "INCONEL",
        "TITANIUM",
        "MONEL",
        "NICKEL",
        "COPPER",
        "BRASS",
        "PTFE",
        "TEFLON",
        "VITON",
        "SILICONE",
        "EPOXY",
        "ADHESIVE",
    )
    if any(token in value for token in known_tokens):
        return True
    if re.search(r"\b(AMS|ASTM|UNS|SAE|ALLOY|CRES|STAINLESS|TITANIUM|INCONEL)\b", value):
        return True
    if re.search(r"\b[A-Z]{1,4}\s*\d{3,4}([\-/.][A-Z0-9]+)?\b", value):
        return True
    return False


def _looks_like_part_number(value: str) -> bool:
    compact = value.replace(" ", "")
    return bool(re.fullmatch(r"[A-Z0-9]+(?:[-_/][A-Z0-9]+)+", compact))


def _detect_trigger_columns(frame: pd.DataFrame) -> dict[str, str]:
    columns: dict[str, str] = {}
    lowered = {col: str(col).strip().lower() for col in frame.columns}
    for issue, aliases in _TRIGGER_COLUMNS.items():
        for col, low in lowered.items():
            if any(alias in low for alias in aliases):
                columns[issue] = col
                break
    return columns


def _build_trigger_signature(row: pd.Series, trigger_cols: dict[str, str]) -> str:
    tokens: list[str] = []
    for issue, col in trigger_cols.items():
        rating = _normalize_trigger_rating(row.get(col))
        if rating and _is_trigger_rating(rating):
            tokens.append(f"{issue}:{rating}")
    tokens.sort()
    return "|".join(tokens)


def _normalize_trigger_rating(value: Any) -> str:
    text = _clean_text(value).upper()
    if not text:
        return ""
    text = text.replace("RATING", "").strip()
    parts = [part for part in re.split(r"[^A-Z0-9]+", text) if part]
    for part in parts:
        if part in _RATING_MAP:
            return _RATING_MAP[part]
        if part in {"A", "B", "C", "D", "U", "X"}:
            return part
    return text


def _is_trigger_rating(rating: str) -> bool:
    return rating.upper() not in _PASS_RATINGS


def _top_designation(raw_designations: Any) -> str:
    if not isinstance(raw_designations, dict):
        return ""
    if not raw_designations:
        return ""
    best_item = max(
        raw_designations.items(),
        key=lambda kv: (float(kv[1] or 0.0), len(str(kv[0]))),
    )
    return _clean_text(best_item[0])


def _collect_unique(rows: list[dict[str, Any]], field: str, limit: int) -> list[str]:
    values: list[str] = []
    for row in rows:
        cleaned = _clean_text(row.get(field))
        if cleaned and cleaned not in values:
            values.append(cleaned)
        if len(values) >= limit:
            break
    return values


def _environment_from_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    env_raw = _clean_text(bucket.get("environment")).upper()
    medium = "AIR"
    o2_percent = 21.0
    location = "habitable"

    if any(token in env_raw for token in ("GH2", "LH2", "HYDROGEN", "H2")):
        medium = "HYDROGEN"
        o2_percent = 0.0
        location = "non-habitable"
    elif "LOX" in env_raw:
        medium = "LOX"
        o2_percent = 99.5
        location = "non-habitable"
    elif "GOX" in env_raw:
        medium = "GOX"
        o2_percent = 99.5
        location = "non-habitable"
    elif any(token in env_raw for token in ("OXYGEN", "ENRICHED_O2", "ENRICHED_AIR")):
        medium = "ENRICHED_AIR"
        o2_percent = 30.0
        location = "non-habitable"

    temp_min_f = _to_float(bucket.get("temp_min_f"), 60.0)
    temp_max_f = _to_float(bucket.get("temp_max_f"), 85.0)
    if temp_min_f > temp_max_f:
        temp_min_f, temp_max_f = temp_max_f, temp_min_f

    pressure_psia = _to_float(bucket.get("pressure_max_psia"), 14.7)
    if pressure_psia <= 0:
        pressure_psia = 14.7

    return {
        "o2_percent": o2_percent,
        "pressure_psia": pressure_psia,
        "temp_min_f": temp_min_f,
        "temp_max_f": temp_max_f,
        "medium": medium,
        "location": location,
        "application": "",
    }
