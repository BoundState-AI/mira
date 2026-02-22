"""Anti-corruption adapter boundary between matchmaker v8 and v7 internals."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from mira.mua.v7.investigator import _PG_FAMILY_ALIAS_MAP as _V7_FAMILY_ALIAS_MAP
from mira.mua.v7.material_resolver import resolve_material as _v7_resolve_material
from mira.mua.v7.pg_precedent_search import search_precedents_pg as _v7_search_precedents_pg

from .models import (
    EnvironmentSpec,
    IssueCode,
    MaterialResolution,
    MaterialResolutionStatus,
    PrecedentMatch,
    normalize_issue_code,
)

logger = logging.getLogger(__name__)

_CANONICAL_TO_V7_ISSUE = {
    IssueCode.FLAM: "FLAM",
    IssueCode.TOX: "TOX",
    IssueCode.O2: "O2_COMPAT",
    IssueCode.HEE: "HEE",
    IssueCode.SCC: "SCC",
    IssueCode.CORR: "CORR",
    IssueCode.TVS: "TVS",
    IssueCode.FLUID: "FS",
}

_V7_TO_CANONICAL_ISSUE = {
    "FLAM": IssueCode.FLAM,
    "TOX": IssueCode.TOX,
    "OFFGAS": IssueCode.TOX,
    "O2_COMPAT": IssueCode.O2,
    "HEE": IssueCode.HEE,
    "SCC": IssueCode.SCC,
    "CORR": IssueCode.CORR,
    "TVS": IssueCode.TVS,
    "FS": IssueCode.FLUID,
}


def get_family_aliases() -> dict[str, str]:
    """Return v7 family aliases as a stable copy."""

    return dict(_V7_FAMILY_ALIAS_MAP)


def resolve_material(text: str) -> MaterialResolution:
    """Resolve material through v7 and return a v8-stable model."""

    resolved = _v7_resolve_material(text)
    status = _normalize_resolution_status(_read_attr(resolved, "status"))
    return MaterialResolution(
        input_text=_read_attr(resolved, "input_text", default=text),
        status=status,
        material_code=_read_attr(resolved, "material_code"),
        material_key=_read_attr(resolved, "material_key"),
        resolved_name=_read_attr(resolved, "resolved_name"),
        family=_read_attr(resolved, "family"),
        material_class=_string_or_none(_read_attr(resolved, "material_class")),
        is_process_sensitive=bool(_read_attr(resolved, "is_process_sensitive", default=False)),
        selection_method=_read_attr(resolved, "selection_method"),
        selection_confidence=_read_attr(resolved, "selection_confidence"),
    )


def search_precedents(
    material: MaterialResolution | str,
    environment: EnvironmentSpec,
    issue_code: str | IssueCode | None = None,
    max_results: int = 20,
) -> list[PrecedentMatch]:
    """Search v7 precedent store and map responses to canonical v8 shape."""

    canonical_issue = normalize_issue_code(issue_code) if issue_code else None
    material_model = resolve_material(material) if isinstance(material, str) else material
    lookup_key = material_model.resolved_name or material_model.input_text

    v7_issues = (
        [_CANONICAL_TO_V7_ISSUE[canonical_issue]]
        if canonical_issue
        else _derive_v7_issue_scope(environment)
    )
    family = _normalize_family(material_model.family)
    env_type = _derive_env_type(environment)

    try:
        raw_results = _v7_search_precedents_pg(
            material_designation=lookup_key,
            material_family=family,
            issues=v7_issues,
            env_type=env_type,
            o2_percent=environment.o2_percent,
            pressure_psia=environment.pressure_psia,
            temp_max_f=environment.temp_max_f,
            temp_min_f=environment.temp_min_f,
            is_habitable=environment.location == "habitable",
            max_results=max_results,
            include_rejected=True,
        )
    except Exception:
        logger.exception(
            "v7 precedent search failed for %r (family=%s, env=%s, issues=%s)",
            lookup_key,
            family,
            env_type,
            v7_issues,
        )
        return []

    return [
        _map_precedent_result(item, requested_issue=canonical_issue)
        for item in (raw_results or [])
    ]


def _map_precedent_result(
    raw: Any,
    requested_issue: IssueCode | None = None,
) -> PrecedentMatch:
    source_issues = _ensure_list(_read_attr(raw, "issues", default=[]))
    canonical_issues: list[IssueCode] = []
    for source in source_issues:
        mapped = _V7_TO_CANONICAL_ISSUE.get(str(source).strip().upper())
        if mapped and mapped not in canonical_issues:
            canonical_issues.append(mapped)

    if requested_issue and requested_issue not in canonical_issues:
        canonical_issues.append(requested_issue)

    determination = _normalize_determination(_read_attr(raw, "determination", default="unknown"))
    rationale_text = _read_attr(raw, "rationale")
    if not rationale_text:
        rationale_text = _read_attr(raw, "rationale_excerpt")

    environment_text = _read_attr(raw, "environment_description")
    if not environment_text:
        environment_text = _build_environment_text(raw)

    relevance = _read_attr(raw, "confidence")
    if relevance is None:
        relevance = _read_attr(raw, "relevance_score", default=0.0)

    return PrecedentMatch(
        mua_number=str(_read_attr(raw, "mua_number", default="UNKNOWN")),
        determination=determination,
        rationale_text=rationale_text,
        material_designation=_read_attr(raw, "material_designation"),
        material_family=_read_attr(raw, "material_family"),
        environment=environment_text or "",
        o2_percent=_read_attr(raw, "o2_percent"),
        pressure_psia=_read_attr(raw, "pressure_psia"),
        temp_min_f=_read_attr(raw, "temp_min_f"),
        temp_max_f=_read_attr(raw, "temp_max_f"),
        issue_codes=canonical_issues,
        source_issue_codes=[str(code) for code in source_issues],
        relevance_score=max(0.0, min(float(relevance or 0.0), 1.0)),
        category_label=_read_attr(raw, "category_label") or _read_attr(raw, "category"),
    )


def _normalize_family(family: Optional[str]) -> Optional[str]:
    if not family:
        return None
    family_key = family.strip().upper()
    return _V7_FAMILY_ALIAS_MAP.get(family_key, family_key)


def _derive_v7_issue_scope(environment: EnvironmentSpec) -> list[str]:
    issues: list[str] = ["FLAM"]
    medium = (environment.medium or "").upper()

    if medium in {"GOX", "LOX", "O2", "OXYGEN", "ENRICHED_AIR", "ENRICHED_O2"}:
        issues.append("O2_COMPAT")
    elif environment.o2_percent >= 23.5:
        issues.append("O2_COMPAT")

    if medium in {"GH2", "LH2", "HYDROGEN", "H2"}:
        issues.append("HEE")

    if environment.location == "habitable":
        issues.extend(["TOX", "OFFGAS"])

    if environment.temp_min_f <= -150.0:
        issues.append("FRACTURE")

    return _dedupe(issues)


def _derive_env_type(environment: EnvironmentSpec) -> str:
    medium = (environment.medium or "").upper()
    if medium in {"LOX", "GOX", "O2", "OXYGEN"}:
        return "LOX_GOX"
    if medium in {"ENRICHED_AIR", "ENRICHED_O2"} or environment.o2_percent >= 23.5:
        return "ENRICHED_O2"
    if medium in {"GH2", "LH2", "HYDROGEN", "H2"}:
        return "HYDROGEN"
    if environment.location == "habitable":
        return "CABIN_AIR"
    if medium in {"AIR", "AMBIENT", "STANDARD_AIR", ""}:
        return "STANDARD_AIR"
    return medium


def _normalize_resolution_status(raw_status: Any) -> MaterialResolutionStatus:
    value = str(getattr(raw_status, "value", raw_status) or "").strip().lower()
    if value not in {status.value for status in MaterialResolutionStatus}:
        return MaterialResolutionStatus.UNRESOLVED
    return MaterialResolutionStatus(value)


def _normalize_determination(value: Any) -> str:
    return str(getattr(value, "value", value) or "unknown").strip().lower()


def _read_attr(raw: Any, name: str, default: Any = None) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(name, default)
    return getattr(raw, name, default)


def _build_environment_text(raw: Any) -> str:
    env = _read_attr(raw, "env_type") or _read_attr(raw, "environment")
    o2 = _read_attr(raw, "o2_percent")
    pressure = _read_attr(raw, "pressure_psia")
    parts: list[str] = [str(env)] if env else []
    if o2 is not None:
        parts.append(f"{o2}% O2")
    if pressure is not None:
        parts.append(f"{pressure} psia")
    return " / ".join(parts)


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
