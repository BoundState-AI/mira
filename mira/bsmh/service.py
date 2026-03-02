#!/usr/bin/env python3
"""
Temporary BSMH orchestration service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import os
import re
from uuid import uuid4

from mira.providers.llm_provider import complete as llm_complete, resolve_model
from mira.utils.json_extract import ExtractionError, extract_json

LOGGER = logging.getLogger(__name__)

from .bouncer import run_bouncer
from .bok_adapter import fetch_h2_bok_evidence
from .models import BSMHQueryRequest, BSMHQueryResponse
from .response_formatter import (
    format_decision_sonnet,
)
from .rules_engine import build_rule_decision


_TYPE_KEY_MAP = {
    "metal": 235,
    "polymer": 239,
    "adhesive": 229,
    "coating": 231,
    "composite": 232,
    "foam": 233,
    "thermal protection": 240,
    "minerals": 237,
}

_REQUESTED_MATERIAL_EXCLUDE = {
    "OXYGEN",
    "O2",
    "GOX",
    "LOX",
    "HYDROGEN",
    "H2",
    "GH2",
    "LH2",
    "VACUUM",
    "AIR",
    "MAPTIS",
    "MUA",
    "MIUL",
    "NASA",
    "ASTM",
    "PSI",
    "PSIA",
}

_ASSOCIATED_DESIGNATION_KEYWORDS = (
    "COUPLE",
    "BIMETAL",
    "BRAZE",
    "BRAZED",
    "WELD",
    "WELDED",
    "FILLER",
    "SOLDER",
    "ADHESIVE",
    "BONDED",
)


@dataclass
class _BSMHRetrievalResult:
    parsed_query: Dict[str, Any]
    materials: List[Dict[str, Any]]
    search_source: str
    gate_action: str
    confidence_score: Optional[float]
    lineage_id: Optional[str]


def _f_to_c(temperature_f: float) -> float:
    return (temperature_f - 32.0) * (5.0 / 9.0)


def _psi_to_kpa(pressure_psi: float) -> float:
    return pressure_psi * 6.89476


def _merge_v4_request(raw_request: BSMHQueryRequest, structured: Dict[str, Any]) -> Dict[str, Any]:
    merged = raw_request.model_dump(mode="python")
    # Strip BSMH-only fields before validating against V4QueryRequest.
    merged.pop("answer_mode", None)

    material = structured.get("material")
    materials = structured.get("materials")
    environment = structured.get("environment")
    pressure_psi = structured.get("pressure_psi")
    temperature_f = structured.get("temperature_f")
    o2_pct = structured.get("o2_pct")

    if merged.get("material_key") is None and material and not (
        isinstance(materials, list) and len(materials) > 1
    ):
        merged["material_key"] = str(material)
    if merged.get("fluid_medium") is None and environment:
        merged["fluid_medium"] = str(environment)
    if merged.get("pressure_kpa") is None and pressure_psi is not None:
        merged["pressure_kpa"] = round(_psi_to_kpa(float(pressure_psi)), 2)
    if merged.get("temperature_c") is None and temperature_f is not None:
        merged["temperature_c"] = round(_f_to_c(float(temperature_f)), 2)
    if merged.get("o2_pct") is None and o2_pct is not None:
        merged["o2_pct"] = float(o2_pct)

    return merged


def _dedupe_keep_order(values: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        v = value.strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(v)
    return ordered


def _normalize_safety_context(value: Any) -> str:
    if value is None:
        return "general"
    # Enums from v4 may arrive as SafetyContext.OXYGEN objects.
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str) and enum_value:
        return enum_value.strip().lower()

    text = str(value).strip().lower()
    if not text:
        return "general"
    if "." in text:
        text = text.split(".")[-1]

    if text in {"o2", "oxygen", "lox", "gox", "oxygen_service", "oxygen_enriched"}:
        return "oxygen"
    if text in {"h2", "hydrogen", "lh2", "gh2", "hydrogen_service"}:
        return "hydrogen"
    if text in {"cryo", "cryogenic"}:
        return "cryogenic"
    if text in {"highpressure", "high_pressure", "pressure"}:
        return "high_pressure"
    if text == "general":
        return "general"
    return "general"


def _infer_safety_context_from_query(query: str, structured_query: Dict[str, Any]) -> str:
    env = str(structured_query.get("environment") or "")
    candidate = f"{env} {query}".lower()
    if any(tok in candidate for tok in ("lox", "gox", "oxygen", "o2")):
        return "oxygen"
    if any(tok in candidate for tok in ("lh2", "gh2", "hydrogen", "h2")):
        return "hydrogen"
    if any(tok in candidate for tok in ("cryogenic", "cryo", "-423", "-320", "-297", "liquid hydrogen")):
        return "cryogenic"
    if re.search(r"\b\d+(?:\.\d+)?\s*(psi|psia)\b", candidate):
        return "high_pressure"
    return "general"


def _sanitize_requested_materials(values: List[str]) -> List[str]:
    sanitized: List[str] = []
    for value in values:
        v = re.sub(r"\s+", " ", str(value).strip())
        if not v:
            continue
        upper = v.upper()
        if upper in _REQUESTED_MATERIAL_EXCLUDE:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", upper):
            continue
        if re.search(r"\b\d+(?:\.\d+)?\s*(PSI|PSIA|F|C|K|%)\b", upper):
            continue
        sanitized.append(v)
    return _dedupe_keep_order(sanitized)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _material_matches_requested(material: Dict[str, Any], requested: str) -> bool:
    req = requested.strip().upper()
    if not req:
        return False
    req_norm = _normalize_text(req)

    fields = [
        str(material.get("designation") or ""),
        str(material.get("material_code") or ""),
        str(material.get("composition") or ""),
    ]
    fields_upper = [f.upper() for f in fields]
    fields_norm = [_normalize_text(f) for f in fields]

    for field in fields_upper:
        if req in field:
            return True
        req_tokens = [t for t in re.split(r"[\s\-_/]+", req) if t]
        if len(req_tokens) > 1 and all(tok in field for tok in req_tokens):
            return True
        if re.fullmatch(r"\d{3,4}L?", req) and re.search(rf"\b{re.escape(req)}\b", field):
            return True

    for field_norm in fields_norm:
        if req_norm and req_norm in field_norm:
            return True

    return False


def _expand_requested_material_patterns(requested: str) -> List[str]:
    req = re.sub(r"\s+", " ", requested.strip())
    if not req:
        return []

    patterns = [req]
    upper = req.upper()

    # Stainless shorthand expansions (e.g., 316L -> CRES 316L / SS 316L).
    grade_match = re.search(r"\b(\d{3,4}L?)\b", upper)
    if grade_match:
        grade = grade_match.group(1)
        patterns.extend(
            [
                grade,
                f"CRES {grade}",
                f"STAINLESS STEEL {grade}",
                f"SS {grade}",
            ]
        )
        if grade.endswith("L") and len(grade) >= 4:
            patterns.append(grade[:-1])

    # Nickel alloy spelling/format variants.
    inconel_match = re.search(r"\bINCONEL\s*-?\s*(\d{2,4}[A-Z]?)\b", upper)
    if inconel_match:
        grade = inconel_match.group(1)
        patterns.extend([f"INCONEL {grade}", f"INCONEL-{grade}"])

    # CRES aliases.
    cres_match = re.search(r"\bCRES\s+(\d{3,4}L?)\b", upper)
    if cres_match:
        grade = cres_match.group(1)
        patterns.extend([grade, f"STAINLESS STEEL {grade}", f"SS {grade}"])

    return _dedupe_keep_order(patterns)


def _looks_like_associated_designation(designation: str) -> bool:
    upper = designation.upper()
    if any(keyword in upper for keyword in _ASSOCIATED_DESIGNATION_KEYWORDS):
        return True
    if "/" in upper:
        return True
    if re.search(r"\b(?:WITH|TO|ON)\b", upper):
        return True
    return False


def _is_primary_requested_match(material: Dict[str, Any], requested: str) -> bool:
    if not _material_matches_requested(material, requested):
        return False
    designation = str(material.get("designation") or "").strip()
    if not designation:
        return True
    return not _looks_like_associated_designation(designation)


def _filter_materials_for_requested(
    materials: List[Dict[str, Any]],
    requested_materials: List[str],
) -> List[Dict[str, Any]]:
    if not requested_materials:
        return materials
    return [m for m in materials if any(_material_matches_requested(m, req) for req in requested_materials)]


def _partition_materials_for_requested(
    materials: List[Dict[str, Any]],
    requested_materials: List[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not requested_materials:
        return list(materials), []

    primary: List[Dict[str, Any]] = []
    associated: List[Dict[str, Any]] = []
    for material in materials:
        if any(_is_primary_requested_match(material, req) for req in requested_materials):
            primary.append(material)
        elif any(_material_matches_requested(material, req) for req in requested_materials):
            associated.append(material)
    return primary, associated


def _material_coverage_count(
    materials: List[Dict[str, Any]],
    requested: str,
) -> int:
    return sum(1 for m in materials if _is_primary_requested_match(m, requested))


def _material_sort_key(material: Dict[str, Any]) -> tuple[int, int, int, str]:
    total_tests = int(material.get("total_tests", 0) or 0)
    mua_count = int(material.get("mua_count", 0) or 0)
    latest_year = int(material.get("latest_test_year", 0) or 0)
    designation = str(material.get("designation") or "")
    return (total_tests, mua_count, latest_year, designation)


def _select_materials_for_determination(
    primary_materials: List[Dict[str, Any]],
    requested_materials: List[str],
    *,
    max_materials: int = 10,
) -> List[Dict[str, Any]]:
    if not primary_materials:
        return []

    ranked = sorted(primary_materials, key=_material_sort_key, reverse=True)
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _add(material: Dict[str, Any]) -> None:
        ident = _material_identity(material)
        if ident in seen or len(selected) >= max_materials:
            return
        seen.add(ident)
        selected.append(material)

    # Ensure each requested material can contribute at least one representative
    # when available, then fill the remainder by evidence strength.
    for req in requested_materials:
        for material in ranked:
            if _is_primary_requested_match(material, req):
                _add(material)
                break

    for material in ranked:
        _add(material)
        if len(selected) >= max_materials:
            break

    return selected


def _missing_requested_materials(
    materials: List[Dict[str, Any]],
    requested_materials: List[str],
) -> List[str]:
    if not requested_materials:
        return []
    missing: List[str] = []
    for req in requested_materials:
        if not any(_material_matches_requested(m, req) for m in materials):
            missing.append(req)
    return _dedupe_keep_order(missing)


def _material_identity(material: Dict[str, Any]) -> str:
    key = material.get("material_key")
    if key is not None:
        return f"key:{key}"
    designation = str(material.get("designation") or "").strip()
    if designation:
        return f"designation:{designation.upper()}"
    return f"fallback:{id(material)}"


def _merge_unique_materials(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for material in group:
            ident = _material_identity(material)
            if ident in seen:
                continue
            seen.add(ident)
            merged.append(material)
    return merged


def _normalize_search_patterns(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return _dedupe_keep_order([str(v).strip() for v in values if str(v).strip()])


def _db_batch_search(
    patterns: List[str],
    *,
    per_pattern_limit: int,
    type_filter_key: Optional[int],
) -> List[Dict[str, Any]]:
    import psycopg2
    from decimal import Decimal as _Decimal
    from psycopg2.extras import RealDictCursor

    from mira.core.db_config import get_db_connection_params

    if not patterns:
        return []

    all_rows: List[Dict[str, Any]] = []
    type_clause = "AND m.material_type_key = %s" if type_filter_key else ""

    conn = psycopg2.connect(**get_db_connection_params())
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for pattern in patterns:
                params: List[Any] = [f"%{pattern.lower()}%"]
                if type_filter_key:
                    params.append(type_filter_key)
                params.append(per_pattern_limit)

                cur.execute(
                    f"""
                    SELECT
                        m.material_key, m.material_code, m.designation,
                        m.composition, m.material_type_key, m.material_type_name,
                        m.use_temp_min_f, m.use_temp_max_f,
                        (SELECT COUNT(*) FROM flammability_tests ft
                         WHERE ft.material_code = m.material_key) AS flammability_tests,
                        (SELECT COUNT(*) FROM mechanical_impact_tests mt
                         WHERE mt.material_code = m.material_key) AS impact_tests,
                        (SELECT COUNT(*) FROM tvs_outgassing_tests tv
                         WHERE tv.material_code = m.material_key) AS outgassing_tests,
                        (SELECT COUNT(*) FROM toxicity_tests tx
                         WHERE tx.material_code = m.material_key) AS toxicity_tests,
                        (SELECT COUNT(*) FROM corrosion_tests ct
                         WHERE ct.material_code = m.material_key) AS corrosion_tests,
                        (SELECT COUNT(*) FROM tensile_strength_tests ts
                         WHERE ts.material_code = m.material_key) AS tensile_tests,
                        (SELECT COUNT(*) FROM fluid_compatibility_tests fc
                         WHERE fc.material_code = m.material_key) AS fluid_compat_tests,
                        (SELECT COUNT(*) FROM high_cycle_fatigue_tests hc
                         WHERE hc.material_code = m.material_key) AS fatigue_tests,
                        (SELECT MAX(dt) FROM (
                            SELECT MAX(date_tested) AS dt FROM flammability_tests
                                WHERE material_code = m.material_key
                            UNION ALL SELECT MAX(date_tested) FROM mechanical_impact_tests
                                WHERE material_code = m.material_key
                            UNION ALL SELECT MAX(date_tested) FROM tvs_outgassing_tests
                                WHERE material_code = m.material_key
                            UNION ALL SELECT MAX(date_tested) FROM toxicity_tests
                                WHERE material_code = m.material_key
                            UNION ALL SELECT MAX(date_tested) FROM corrosion_tests
                                WHERE material_code = m.material_key
                            UNION ALL SELECT MAX(date_tested) FROM tensile_strength_tests
                                WHERE material_code = m.material_key
                            UNION ALL SELECT MAX(date_tested) FROM fluid_compatibility_tests
                                WHERE material_code = m.material_key
                        ) sub) AS latest_test_date,
                        (SELECT COUNT(*) FROM public.mua_precedents_v7 mp
                         WHERE LOWER(mp.material_designation) LIKE
                               '%%' || LOWER(SPLIT_PART(m.designation, ' ', 1)) || '%%'
                         AND LENGTH(SPLIT_PART(m.designation, ' ', 1)) >= 4
                        ) AS mua_count,
                        COALESCE(
                            (SELECT bool_or(
                                nasa_6001_rating IN ('A', 'B')
                                OR nasa_6001b_rating IN ('A', 'B')
                             ) FROM flammability_tests
                             WHERE material_code = m.material_key
                            ),
                            (SELECT bool_or(
                                prom_rating IN ('A', 'B')
                                OR prom_rtg_6001b IN ('A', 'B')
                             ) FROM maptis.promoted_combustion_tests
                             WHERE CAST(materialkey AS INTEGER) = m.material_key
                            )
                        ) AS oxygen_flam_compatible,
                        COALESCE(
                            (SELECT bool_or(
                                nasa_6001_rating IS NOT NULL
                                OR nasa_6001b_rating IS NOT NULL
                             ) FROM flammability_tests
                             WHERE material_code = m.material_key
                            ),
                            (SELECT bool_or(
                                prom_rating IS NOT NULL
                                OR prom_rtg_6001b IS NOT NULL
                             ) FROM maptis.promoted_combustion_tests
                             WHERE CAST(materialkey AS INTEGER) = m.material_key
                            ),
                            FALSE
                        ) AS oxygen_rating_present
                    FROM materials m
                    WHERE LOWER(m.designation) LIKE %s
                    {type_clause}
                    ORDER BY m.designation
                    LIMIT %s
                    """,
                    params,
                )

                for r in cur.fetchall():
                    row = dict(r)
                    for k, v in row.items():
                        if isinstance(v, _Decimal):
                            row[k] = float(v)

                    test_counts = {
                        "flammability": row.pop("flammability_tests", 0) or 0,
                        "impact": row.pop("impact_tests", 0) or 0,
                        "outgassing": row.pop("outgassing_tests", 0) or 0,
                        "toxicity": row.pop("toxicity_tests", 0) or 0,
                        "corrosion": row.pop("corrosion_tests", 0) or 0,
                        "tensile": row.pop("tensile_tests", 0) or 0,
                        "fluid_compatibility": row.pop("fluid_compat_tests", 0) or 0,
                        "fatigue": row.pop("fatigue_tests", 0) or 0,
                    }

                    row["test_counts"] = test_counts
                    row["total_tests"] = sum(test_counts.values())
                    latest_date = row.pop("latest_test_date", None)
                    row["latest_test_year"] = latest_date.year if latest_date else None
                    mua_count = row.pop("mua_count", 0) or 0
                    row["mua_count"] = mua_count
                    row["has_mua_precedent"] = mua_count > 0
                    oxygen_compatible = bool(row.pop("oxygen_flam_compatible", False))
                    oxygen_rating_present = bool(row.pop("oxygen_rating_present", False))
                    row["oxygen_compatible"] = oxygen_compatible
                    row["oxygen_rating_present"] = oxygen_rating_present
                    if oxygen_compatible:
                        row["oxygen_rating"] = "A_OR_B"
                    elif oxygen_rating_present:
                        row["oxygen_rating"] = "RATING_PRESENT_NOT_AB"
                    else:
                        row["oxygen_rating"] = "NO_RATING"
                    row["use_temp_min_c"] = _f_to_c(row.get("use_temp_min_f")) if row.get("use_temp_min_f") is not None else None
                    row["use_temp_max_c"] = _f_to_c(row.get("use_temp_max_f")) if row.get("use_temp_max_f") is not None else None
                    all_rows.append(row)
    finally:
        conn.close()

    return all_rows


async def _run_bsmh_retrieval_only(v4_request: Any) -> _BSMHRetrievalResult:
    """
    Retrieval-only BSMH path:
    Sonnet parse -> DB retrieval (no FAISS) -> lineage confidence/gate.
    """
    from mira.api.routers import mira_v4 as mira_v4_router
    from mira_v4.decision_lineage import DecisionLineageBuilder
    from mira_v4.models import EvidenceRow

    sonnet_parsed = await mira_v4_router._parse_query_with_sonnet(v4_request.query)
    if not sonnet_parsed:
        raise RuntimeError("Sonnet parse failed; fallback parser is disabled for BSMH.")

    parsed_query_model = mira_v4_router._build_parsed_query(
        v4_request.query,
        sonnet_parsed,
        v4_request,
    )

    # Keep intent reconciliation aligned with v4 behavior.
    try:
        from mira_v4.intent_guardrail import IntentGuardrail

        guardrail = IntentGuardrail()
        resolved_intent, intent_disagreement = guardrail.validate(
            sonnet_intent=parsed_query_model.intent,
            raw_query=v4_request.query,
        )
        parsed_query_model = parsed_query_model.model_copy(
            update={
                "intent": resolved_intent,
                "heuristic_intent": (
                    resolved_intent if intent_disagreement else parsed_query_model.heuristic_intent
                ),
            }
        )
    except Exception:
        pass

    sonnet_material_type = sonnet_parsed.get("material_type")
    type_filter_key = (
        _TYPE_KEY_MAP.get(str(sonnet_material_type).lower())
        if sonnet_material_type
        else None
    )

    materials: List[Dict[str, Any]] = []
    evidence_rows: List[Any] = []
    seen_keys: set[Any] = set()
    search_source = "none"

    def _add_rows(rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            material_key = row.get("material_key")
            if material_key in seen_keys:
                continue
            seen_keys.add(material_key)
            materials.append(row)

            total_tests = int(row.get("total_tests", 0) or 0)
            latest_year = row.get("latest_test_year")
            try:
                latest_year = int(latest_year) if latest_year is not None else None
            except Exception:
                latest_year = None

            evidence_rows.append(
                EvidenceRow(
                    record_id=str(material_key),
                    source="MAPTIS",
                    data_class="direct_test" if total_tests > 0 else "derived",
                    dirty_flag=(total_tests == 0),
                    test_year=latest_year,
                )
            )

    candidate_materials = _normalize_search_patterns(sonnet_parsed.get("candidate_materials"))
    if candidate_materials:
        try:
            _add_rows(
                _db_batch_search(
                    candidate_materials,
                    per_pattern_limit=5,
                    type_filter_key=type_filter_key,
                )
            )
            if materials:
                search_source = "sonnet_candidates"
        except Exception:
            pass

    if not materials and parsed_query_model.material_key:
        try:
            _add_rows(
                _db_batch_search(
                    [str(parsed_query_model.material_key)],
                    per_pattern_limit=25,
                    type_filter_key=type_filter_key,
                )
            )
            if materials:
                search_source = "postgresql"
        except Exception:
            pass

    material_families = _normalize_search_patterns(sonnet_parsed.get("material_families"))
    if not materials and material_families:
        try:
            per_family = max(5, 25 // len(material_families))
            _add_rows(
                _db_batch_search(
                    material_families,
                    per_pattern_limit=per_family,
                    type_filter_key=type_filter_key,
                )
            )
            if materials:
                search_source = "postgresql_families"
        except Exception:
            pass

    materials.sort(key=lambda m: (-int(m.get("total_tests", 0) or 0), str(m.get("designation", ""))))

    gate_action = "ALLOW"
    confidence_score: Optional[float] = None
    lineage_id: Optional[str] = None

    try:
        lineage = DecisionLineageBuilder().build(
            parsed_query=parsed_query_model,
            evidence_rows=evidence_rows,
            schema_version="1.0.0",
        )
        gate_action = lineage.confidence.gate_action.value
        confidence_score = lineage.confidence.score
        lineage_id = lineage.lineage_id
    except Exception:
        if not materials:
            gate_action = "REFUSE"
            confidence_score = 0.0
        lineage_id = f"bsmh-{uuid4().hex[:12]}"

    return _BSMHRetrievalResult(
        parsed_query=parsed_query_model.model_dump(mode="json"),
        materials=materials,
        search_source=search_source,
        gate_action=gate_action,
        confidence_score=confidence_score,
        lineage_id=lineage_id,
    )


_FC_CONTEXT_PARSE_PROMPT = """You are a NASA fracture control engineer. Extract structured context from the user's query.

Return STRICT JSON only with these fields (use null for anything not explicitly stated):
{
  "material": "string or null — material designation exactly as stated",
  "part_name": "string or null — part or component name",
  "pressure_boundary": true/false/null,
  "consequence_of_failure": "catastrophic" | "critical" | "non_critical" | null,
  "inspectability": "inspectable" | "limited_access" | "non_inspectable" | null,
  "geometry_type": "pressure_vessel" | "fitting" | "line" | "structural" | "fastener" | "mechanism" | "other" | null,
  "material_condition": "wrought" | "cast" | "forged" | "welded" | "am_printed" | "powder_metallurgy" | null,
  "center_code": "MSFC" | "JSC" | "KSC" | "GRC" | null,
  "design_life_cycles": integer or null,
  "operating_pressure_psi": number or null,
  "operating_pressure_unit": "string or null — unit as stated (psi, psia, kPa, etc.)",
  "operating_temperature_f": number or null,
  "operating_temperature_unit": "string or null — unit as stated (F, C, K, etc.)",
  "proof_factor": number or null
}

Definitions (per NASA-STD-5019A):
- consequence_of_failure:
  • "catastrophic" = could result in loss of life, disabling injury, or loss of a major national asset (crew, vehicle, major station element)
  • "critical" = could result in loss of mission or major degradation requiring immediate corrective action
  • "non_critical" = failure does not meet critical or catastrophic criteria (part still requires classification rationale)
- "pressure_boundary" = the part contains, seals, or is integral to a pressurized system

Critical rules:
- Use null (not empty string "") for anything not explicitly stated in the query.
- Never infer or assume values the user did not provide.
- Extract numeric values and units exactly as stated; do not convert units.
- Only output JSON. No prose, no explanation, no markdown.

Respond with ONLY valid JSON. No markdown fences, preamble, or commentary.

Examples:

Query: "Classify this Ti-6Al-4V pressure vessel for the SLS upper stage"
Answer:
{"material": "Ti-6Al-4V", "part_name": "pressure vessel", "pressure_boundary": true, "consequence_of_failure": null, "inspectability": null, "geometry_type": "pressure_vessel", "material_condition": null, "center_code": null, "design_life_cycles": null, "operating_pressure_psi": null, "operating_pressure_unit": null, "operating_temperature_f": null, "operating_temperature_unit": null, "proof_factor": null}

Query: "Non-inspectable Inconel 718 turbopump bolt, catastrophic if it fails, 4000 cycles design life at MSFC"
Answer:
{"material": "Inconel 718", "part_name": "turbopump bolt", "pressure_boundary": null, "consequence_of_failure": "catastrophic", "inspectability": "non_inspectable", "geometry_type": "fastener", "material_condition": null, "center_code": "MSFC", "design_life_cycles": 4000, "operating_pressure_psi": null, "operating_pressure_unit": null, "operating_temperature_f": null, "operating_temperature_unit": null, "proof_factor": null}

Query: "Is a bracket fracture critical?"
Answer:
{"material": null, "part_name": "bracket", "pressure_boundary": null, "consequence_of_failure": null, "inspectability": null, "geometry_type": "structural", "material_condition": null, "center_code": null, "design_life_cycles": null, "operating_pressure_psi": null, "operating_pressure_unit": null, "operating_temperature_f": null, "operating_temperature_unit": null, "proof_factor": null}
"""


async def _parse_fracture_context_from_query(raw_query: str) -> FractureContextInput:
    """Use provider to extract structured fracture context from natural language.

    Falls back to empty context (which triggers CLARIFY) on any failure.
    """
    import asyncio as _asyncio

    model = os.environ.get("BSMH_SONNET_MODEL", resolve_model("sonnet"))

    def _call() -> FractureContextInput:
        response = llm_complete(
            system=_FC_CONTEXT_PARSE_PROMPT,
            user=raw_query,
            model=model,
            max_tokens=500,
            temperature=0.0,
            timeout_s=20,
        )
        try:
            parsed = extract_json(response.text, expect="object")
        except ExtractionError:
            LOGGER.warning("[FC] Provider did not return JSON; using empty context")
            return FractureContextInput()
        return FractureContextInput.model_validate(parsed)

    try:
        loop = _asyncio.get_running_loop()
        return await loop.run_in_executor(None, _call)
    except Exception as exc:
        LOGGER.error("[FC] Fracture context parse failed: %s", exc)
        return FractureContextInput()


async def run_bsmh_query(request: BSMHQueryRequest) -> BSMHQueryResponse:
    """
    Execute temporary BSMH flow:
    Bouncer -> Sonnet parse+DB retrieval -> deterministic rules -> formatter.
    """
    bouncer = await run_bouncer(request.query)
    if bouncer.status == "rejected":
        return BSMHQueryResponse(
            status="rejected",
            answer=bouncer.rejection_reason or "Query rejected by bouncer.",
            sonnet_calls_used=0,
            bouncer=bouncer,
            sonnet_metadata={"executed": False},
        )

    structured_query = (
        bouncer.structured_query.model_dump(mode="python")
        if bouncer.structured_query
        else {}
    )

    # =========================================================================
    # FRACTURE CONTROL EARLY EXIT
    # If query is fracture-domain, route to deterministic classification engine.
    # No materials retrieval needed — fracture is a rule engine, not search.
    # =========================================================================
    inferred_context_early = _infer_safety_context_from_query(request.query, structured_query)
    if inferred_context_early == "fracture_control":
        fc_sonnet_calls = 0
        try:
            fc_context = await _parse_fracture_context_from_query(request.query)
            fc_sonnet_calls += 1
            fc_result = build_fracture_decision(context=fc_context)
            fc_answer = await format_fracture_decision_sonnet(
                query=request.query,
                decision=fc_result,
            )
            fc_sonnet_calls += 1
            LOGGER.info(
                "[FC] classification=%s verdict=%s rules=%s sonnet_calls=%d",
                fc_result.classification.part_class if fc_result.classification else "NONE",
                fc_result.verdict,
                fc_result.rules_applied,
                fc_sonnet_calls,
            )
            return BSMHQueryResponse(
                status="ok",
                pipeline="B-FC-S",
                answer=fc_answer,
                answer_sonnet=fc_answer,
                answer_mode="sonnet",
                sonnet_calls_used=fc_sonnet_calls,
                bouncer=bouncer,
                fracture_result=fc_result,
                sonnet_metadata={
                    "executed": True,
                    "safety_context": "fracture_control",
                    "parsed_intent": "fracture_classification",
                    "fracture_verdict": fc_result.verdict,
                    "fracture_part_class": fc_result.classification.part_class if fc_result.classification else None,
                    "fracture_rules_applied": fc_result.rules_applied,
                },
                v4_gate_action="PASS" if fc_result.verdict == "CLASSIFIED" else "CLARIFY",
                v4_confidence_score=fc_result.classification.classification_confidence if fc_result.classification else 0.0,
            )
        except Exception as exc:
            LOGGER.error("[FC] Fracture control routing failed: %s", exc, exc_info=True)
            return BSMHQueryResponse(
                status="error",
                pipeline="B-FC-S",
                answer=f"Fracture control assessment encountered an error: {exc}",
                sonnet_calls_used=fc_sonnet_calls,
                bouncer=bouncer,
                sonnet_metadata={"safety_context": "fracture_control", "error": str(exc)},
                error=str(exc),
            )

    requested_materials = _dedupe_keep_order(
        [
            *(list(structured_query.get("materials") or [])),
            *([str(structured_query.get("material"))] if structured_query.get("material") else []),
            *([str(request.material_key)] if request.material_key else []),
        ]
    )
    requested_materials = _sanitize_requested_materials(requested_materials)
    merged_payload = _merge_v4_request(request, structured_query)
    sonnet_calls_used = 0

    try:
        from mira.api.routers.mira_v4 import V4QueryRequest

        v4_request = V4QueryRequest.model_validate(merged_payload)
        sonnet_calls_used = 1
        retrieval_result = await _run_bsmh_retrieval_only(v4_request)
    except Exception as exc:
        inferred_context = _infer_safety_context_from_query(request.query, structured_query)
        missing_for_fallback = list(requested_materials)
        fallback_rules = build_rule_decision(
            [],
            safety_context=inferred_context,
            min_evidence_rows=2,
            requested_materials=requested_materials,
            missing_requested_materials=missing_for_fallback,
        )
        fallback_answer = (
            "VERDICT_EXACT: INSUFFICIENT_DATA\n\n"
            "Unable to complete Sonnet + MAPTIS retrieval for this query. "
            "No recommendation can be issued without retrieved evidence. "
            "Provide additional context or retry the query."
        )
        if requested_materials:
            fallback_answer += f"\n\nRequested materials: {', '.join(requested_materials)}."
        return BSMHQueryResponse(
            status="ok",
            pipeline="B-S-M-S",
            answer=fallback_answer,
            answer_sonnet=fallback_answer,
            answer_mode="sonnet",
            sonnet_calls_used=sonnet_calls_used,
            bouncer=bouncer,
            rules=fallback_rules,
            materials=[],
            sonnet_metadata={
                "executed": False,
                "retrieval_error": str(exc),
                "search_source": "none",
                "material_count": 0,
                "faiss_fallback_enabled": False,
                "requested_materials": requested_materials,
                "missing_requested_materials": missing_for_fallback,
                "parsed_intent": structured_query.get("intent"),
                "safety_context": inferred_context,
            },
            raw_v4_answer=None,
            v4_lineage_id=None,
            v4_gate_action="CLARIFY",
            v4_confidence_score=0.1,
            error=str(exc),
        )

    parsed_query = dict(retrieval_result.parsed_query or {})
    safety_context = _normalize_safety_context(parsed_query.get("safety_context", "general"))
    bok_required = str(os.environ.get("BSMH_REQUIRE_H2_BOK", "1")).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    h2_bok_rows: List[Dict[str, Any]] = []
    h2_bok_error: Optional[str] = None
    if safety_context == "hydrogen":
        h2_bok_rows, h2_bok_error = fetch_h2_bok_evidence(
            query=request.query,
            requested_materials=requested_materials,
            k_per_query=3,
            max_total=8,
        )

    matched_materials = _filter_materials_for_requested(
        list(retrieval_result.materials or []),
        requested_materials,
    )
    primary_materials, associated_materials = _partition_materials_for_requested(
        matched_materials,
        requested_materials,
    )

    missing_requested = _missing_requested_materials(primary_materials, requested_materials)
    min_requested_coverage = 2 if len(requested_materials) > 1 else 1
    under_covered_requested = [
        req
        for req in requested_materials
        if _material_coverage_count(primary_materials, req) < min_requested_coverage
    ]
    fetch_targets = _dedupe_keep_order([*missing_requested, *under_covered_requested])

    targeted_fetch_attempts = 0
    targeted_added = 0
    if fetch_targets:
        targeted_patterns = _dedupe_keep_order(
            [
                pattern
                for req in fetch_targets
                for pattern in _expand_requested_material_patterns(req)
            ]
        )
        targeted_fetch_attempts = len(targeted_patterns)
        targeted_found: List[Dict[str, Any]] = []
        try:
            targeted_found = _db_batch_search(
                targeted_patterns,
                per_pattern_limit=15,
                type_filter_key=None,
            )
            targeted_found = _filter_materials_for_requested(
                targeted_found,
                requested_materials,
            )
        except Exception:
            targeted_found = []

        if targeted_found:
            before = len(matched_materials)
            matched_materials = _merge_unique_materials(matched_materials, targeted_found)
            targeted_added = len(matched_materials) - before

    primary_materials, associated_materials = _partition_materials_for_requested(
        matched_materials,
        requested_materials,
    )
    missing_requested = _missing_requested_materials(primary_materials, requested_materials)
    under_covered_requested = [
        req
        for req in requested_materials
        if _material_coverage_count(primary_materials, req) < min_requested_coverage
    ]

    rules = build_rule_decision(
        _select_materials_for_determination(primary_materials, requested_materials, max_materials=10),
        safety_context=safety_context,
        min_evidence_rows=2,
        aggregation_scope="primary_only",
        primary_material_count=len(primary_materials),
        associated_material_count=len(associated_materials),
        bok_evidence=h2_bok_rows,
        require_h2_bok=(bok_required and safety_context == "hydrogen"),
        requested_materials=requested_materials,
        missing_requested_materials=missing_requested,
    )

    answer_mode: str = "sonnet"
    try:
        answer_sonnet = await format_decision_sonnet(
            query=request.query,
            decision=rules,
            materials=matched_materials,
            primary_materials=primary_materials,
            associated_materials=associated_materials,
            bok_evidence=h2_bok_rows,
            requested_materials=requested_materials,
            missing_requested_materials=missing_requested,
        )
    except Exception as exc:
        return BSMHQueryResponse(
            status="error",
            pipeline="B-S-M-S",
            answer="BSMH failed during Sonnet presentation stage.",
            answer_mode=answer_mode,
            sonnet_calls_used=sonnet_calls_used,
            bouncer=bouncer,
            rules=rules,
            materials=matched_materials,
            sonnet_metadata={
                "executed": True,
                "sonnet_calls_used": sonnet_calls_used,
                "search_source": retrieval_result.search_source,
                "material_count": len(matched_materials),
                "primary_material_count": len(primary_materials),
                "associated_material_count": len(associated_materials),
                "determination_material_count": len(rules.materials),
                "determination_material_keys": list(rules.determination_material_keys),
                "determination_material_names": list(rules.determination_material_names),
                "h2_bok_required": bok_required if safety_context == "hydrogen" else False,
                "h2_bok_used": bool(h2_bok_rows),
                "h2_bok_evidence_count": len(h2_bok_rows),
                "h2_bok_sources": list(rules.bok_sources),
                "h2_bok_error": h2_bok_error,
                "faiss_fallback_enabled": False,
                "v4_sonnet_answer_generation_enabled": False,
                "requested_materials": requested_materials,
                "missing_requested_materials": missing_requested,
                "under_covered_requested_materials": under_covered_requested,
                "targeted_fetch_attempts": targeted_fetch_attempts,
                "targeted_materials_added": targeted_added,
                "parsed_intent": parsed_query.get("intent"),
                "safety_context": safety_context,
                "v4_gate_action": retrieval_result.gate_action,
            },
            raw_v4_answer=None,
            v4_lineage_id=retrieval_result.lineage_id,
            v4_gate_action=retrieval_result.gate_action,
            v4_confidence_score=retrieval_result.confidence_score,
            error=str(exc),
        )
    answer = answer_sonnet or ""

    return BSMHQueryResponse(
        status="ok",
        pipeline="B-S-M-S",
        answer=answer,
        answer_sonnet=answer_sonnet,
        answer_mode=answer_mode,
        sonnet_calls_used=sonnet_calls_used,
        bouncer=bouncer,
        rules=rules,
        materials=matched_materials,
        sonnet_metadata={
            "executed": True,
            "sonnet_calls_used": sonnet_calls_used,
            "search_source": retrieval_result.search_source,
            "material_count": len(matched_materials),
            "primary_material_count": len(primary_materials),
            "associated_material_count": len(associated_materials),
            "determination_material_count": len(rules.materials),
            "determination_material_keys": list(rules.determination_material_keys),
            "determination_material_names": list(rules.determination_material_names),
            "h2_bok_required": bok_required if safety_context == "hydrogen" else False,
            "h2_bok_used": bool(h2_bok_rows),
            "h2_bok_evidence_count": len(h2_bok_rows),
            "h2_bok_sources": list(rules.bok_sources),
            "h2_bok_error": h2_bok_error,
            "faiss_fallback_enabled": False,
            "v4_sonnet_answer_generation_enabled": False,
            "requested_materials": requested_materials,
            "missing_requested_materials": missing_requested,
            "under_covered_requested_materials": under_covered_requested,
            "targeted_fetch_attempts": targeted_fetch_attempts,
            "targeted_materials_added": targeted_added,
            "parsed_intent": parsed_query.get("intent"),
            "safety_context": safety_context,
            "v4_gate_action": retrieval_result.gate_action,
        },
        raw_v4_answer=None,
        v4_lineage_id=retrieval_result.lineage_id,
        v4_gate_action=retrieval_result.gate_action,
        v4_confidence_score=retrieval_result.confidence_score,
    )
