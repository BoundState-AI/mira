#!/usr/bin/env python3
"""
Module: Compliance Evaluation Engine (Codex)
Purpose: Full-index, citation-first compliance determinations for M&P Plan v2
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

from mira.compliance.models.enums import FailureMode, GapSeverity, SourceType
from mira.compliance.models.evidence import EvidenceRef

from ..models import (
    DeficiencySignal,
    MaterialEntry,
    MaterialResolutionResult,
    NonconformanceSignal,
    PlanGeneratorSession,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.1.0-codex"
__safety_critical__ = False

STATUS_COMPLIANT = "compliant"
STATUS_CONSTRAINED = "compliant_with_constraints"
STATUS_UNKNOWN = "unknown"
STATUS_NONCOMPLIANT = "noncompliant"

STATUS_RANK = {
    STATUS_COMPLIANT: 0,
    STATUS_CONSTRAINED: 1,
    STATUS_UNKNOWN: 2,
    STATUS_NONCOMPLIANT: 3,
}

PRIMARY_MODE_ORDER = (
    "flam",
    "o2_prohibited",
    "o2_restricted",
    "offgas",
    "tvs",
    "tox",
    "hee",
    "scc",
    "corr",
    "fs",
)

FAILURE_MODE_MAP = {
    "flam": FailureMode.FLAM,
    "offgas": FailureMode.OFFGAS,
    "tvs": FailureMode.TVS,
    "tox": FailureMode.TOX,
    "hee": FailureMode.HEE,
    "he": FailureMode.HEE,
    "scc": FailureMode.SCC,
    "corr": FailureMode.CORR,
    "fs": FailureMode.FS,
    "o2_prohibited": FailureMode.O2_PROHIBITED,
    "o2_restricted": FailureMode.O2_RESTRICTED,
}

SECTION_FAMILY_HINTS = {
    "4.1": "general_controls",
    "4.2.1": "flammability_offgassing_compatibility",
    "4.2.2": "metals",
    "4.2.3": "nonmetals",
    "4.2.4": "processes",
    "4.2.5": "nde",
    "4.2.6": "special_materials",
}


def _hash_id(prefix: str, value: str, length: int = 24) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:length]}"


def _to_failure_mode(mode: str) -> FailureMode:
    return FAILURE_MODE_MAP.get(mode, FailureMode.MISSING_INPUT)


def _to_gap_severity(value: str) -> GapSeverity:
    if value == "critical":
        return GapSeverity.CRITICAL
    if value == "high":
        return GapSeverity.HIGH
    if value == "low":
        return GapSeverity.LOW
    return GapSeverity.MEDIUM


def _standard_evidence(section: str) -> EvidenceRef:
    return EvidenceRef(
        source_type=SourceType.STANDARD,
        source_id="NASA-STD-6016C",
        source_version="Rev C w/CHANGE 2",
        locator=section,
        confidence=1.0,
        confidence_basis="Normative standard citation",
        retrieved_at=datetime.now(),
        retrieval_method="compliance_eval_codex",
    )


def _maptis_evidence(resolution: MaterialResolutionResult) -> EvidenceRef:
    return EvidenceRef(
        source_type=SourceType.MAPTIS,
        source_id=f"MAPTIS:{resolution.maptis_code}",
        locator="ratings",
        confidence=0.95,
        confidence_basis="Direct MAPTIS material-code lookup",
        retrieved_at=datetime.now(),
        retrieval_method="compliance_eval_codex",
        maptis_record_id=resolution.maptis_code,
    )


def _section_family(section: str) -> str:
    sec = (section or "").strip()
    for prefix, family in SECTION_FAMILY_HINTS.items():
        if sec.startswith(prefix):
            return family
    return "general"


def _unknown_action_by_section(section: str, related_modes: list[str]) -> str:
    family = _section_family(section)
    modes = set(related_modes or [])

    if family == "flammability_offgassing_compatibility" or modes.intersection(
        {"flam", "offgas", "tvs", "tox", "o2_prohibited", "o2_restricted"}
    ):
        return (
            "Attach a use-condition test citation (NASA-STD-6001 style data at relevant O2/"
            "pressure/temperature), or route to closure path with rationale."
        )
    if family == "metals" or modes.intersection({"hee", "scc", "corr", "fs"}):
        return (
            "Attach material cert plus SCC/HEE/corrosion analysis or test evidence for the "
            "exact alloy/condition and environment."
        )
    if family == "nonmetals":
        return (
            "Attach nonmetal compatibility evidence (flammability/offgassing/tox) for this "
            "configuration and environment."
        )
    if family == "processes":
        return (
            "Attach qualified process specification and verification records (WPS/procedure, "
            "acceptance/NDE evidence)."
        )
    if family == "nde":
        return "Attach NDE plan citation and inspection acceptance evidence for this hardware."
    if family == "special_materials":
        return (
            "Attach special-materials analysis/test evidence (residual stress, contamination, "
            "HEE/SCC, ESD, packaging) tied to the requirement."
        )
    if family == "general_controls":
        return (
            "Attach approved M&P control plan citation and implementation evidence for this "
            "program item."
        )
    return (
        "Provide an authoritative test or analysis citation for this requirement, or route "
        "to closure path."
    )


def build_citation_helper_codex(
    mpr_section: str,
    related_modes: list[str],
    status: str,
    maptis_code: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build section-aware citation helper metadata for HITL.

    This is used by API and question-generation so UI can present one-click guidance.
    """
    mode_tokens = sorted(set(related_modes or []))
    family = _section_family(mpr_section)
    if set(mode_tokens).intersection({"flam", "offgas", "tvs", "tox", "o2_prohibited", "o2_restricted"}):
        family = "flammability_offgassing_compatibility"
    elif set(mode_tokens).intersection({"hee", "scc", "corr", "fs"}):
        family = "metals"
    maptis_ref = f"MAPTIS:{maptis_code}" if maptis_code else "MAPTIS:UNKNOWN"

    suggestions = [
        {
            "suggestion_id": "TEST_REPORT",
            "label": "Test Report Citation",
            "source_type": "test_report",
            "description": "Attach a test report covering actual use conditions.",
            "template": (
                f"Test report [ID], section [X], demonstrates compliance for {mpr_section}; "
                f"material reference {maptis_ref}."
            ),
        },
        {
            "suggestion_id": "ANALYSIS_REPORT",
            "label": "Analysis Citation",
            "source_type": "analysis_report",
            "description": "Attach signed engineering analysis tied to requirement text.",
            "template": (
                f"Analysis [ID], section [X], evaluates requirement {mpr_section} for material "
                f"{maptis_ref} in mission environment."
            ),
        },
        {
            "suggestion_id": "STANDARD_REFERENCE",
            "label": "Standard/Spec Citation",
            "source_type": "standard",
            "description": "Attach governing standard/spec clause plus implementation evidence.",
            "template": (
                f"NASA-STD-6016C {mpr_section} and program spec [ID] implemented by process "
                f"record [ID] for {maptis_ref}."
            ),
        },
    ]

    if family in {"processes", "nde"}:
        suggestions.append(
            {
                "suggestion_id": "PROCESS_RECORD",
                "label": "Process Record",
                "source_type": "analysis_report",
                "description": "Attach process qualification and acceptance records.",
                "template": (
                    f"Procedure [ID], qualification [ID], acceptance record [ID] satisfy "
                    f"{mpr_section} for {maptis_ref}."
                ),
            }
        )

    if status == STATUS_UNKNOWN:
        quick_actions = [
            "ADD_TEST_CITATION",
            "ADD_ANALYSIS_CITATION",
            "ADD_STANDARD_CITATION",
            "ROUTE_TO_CLOSURE",
        ]
    elif status == STATUS_CONSTRAINED:
        quick_actions = [
            "ACCEPT_WITH_CONSTRAINT",
            "ADD_ANALYSIS_CITATION",
            "FLAG_FOR_EDIT",
        ]
    elif status == STATUS_NONCOMPLIANT:
        quick_actions = [
            "ROUTE_TO_CLOSURE",
            "NEEDS_TEST",
            "FLAG_FOR_EDIT",
        ]
    else:
        quick_actions = ["ACCEPT", "FLAG_FOR_EDIT"]

    return {
        "section_family": family,
        "related_modes": mode_tokens,
        "recommended_action": _unknown_action_by_section(mpr_section, mode_tokens),
        "quick_actions": quick_actions,
        "suggestions": suggestions,
    }


class ComplianceEvaluationEngineCodex:
    """
    Full-index compliance evaluation engine.

    Produces:
    - Determinations for every applicable MPR in the session matrix.
    - Nonconformance signals for deterministic failures.
    - Deficiency signals only when required evidence is genuinely missing.
    """

    def _eval_flam(
        self,
        resolution: MaterialResolutionResult,
        env_o2: float,
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        rating = (resolution.flam_rating or "").strip().upper() or "U"
        required = "A"

        if rating == "A":
            return (
                STATUS_COMPLIANT,
                f"FLAM rating {rating} meets requirement at {env_o2:.1f}% O2.",
                rating,
                required,
                "low",
                0.98,
            )
        if rating == "B":
            if env_o2 <= max(23.5, float(resolution.test_o2_pct or 0.0)):
                return (
                    STATUS_CONSTRAINED,
                    (
                        f"FLAM rating {rating} accepted with constraint: use O2 "
                        f"{env_o2:.1f}% must not exceed test envelope "
                        f"{float(resolution.test_o2_pct or 0.0):.1f}%."
                    ),
                    rating,
                    required,
                    "medium",
                    0.8,
                )
            return (
                STATUS_NONCOMPLIANT,
                (
                    f"FLAM rating {rating} does not cover use O2 {env_o2:.1f}% "
                    f"(tested {float(resolution.test_o2_pct or 0.0):.1f}%)."
                ),
                rating,
                required,
                "high",
                0.9,
            )
        if rating in {"C", "D", "X"}:
            sev = "critical" if rating in {"D", "X"} else "high"
            return (
                STATUS_NONCOMPLIANT,
                f"FLAM rating {rating} fails requirement in elevated O2 service.",
                rating,
                required,
                sev,
                0.95,
            )
        return (
            STATUS_UNKNOWN,
            f"FLAM rating unavailable or unknown ({rating}).",
            rating,
            required,
            "medium",
            0.4,
        )

    def _eval_tvs(
        self,
        resolution: MaterialResolutionResult,
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        rating = (resolution.tvs_rating or "").strip().upper() or "U"
        required = "A"
        if rating == "A":
            return (
                STATUS_COMPLIANT,
                f"TVS rating {rating} meets requirement.",
                rating,
                required,
                "low",
                0.95,
            )
        if rating == "B":
            return (
                STATUS_CONSTRAINED,
                "TVS rating B acceptable only with documented configuration controls.",
                rating,
                required,
                "medium",
                0.8,
            )
        if rating in {"C", "D", "X"}:
            return (
                STATUS_NONCOMPLIANT,
                f"TVS rating {rating} fails requirement.",
                rating,
                required,
                "high",
                0.9,
            )
        return (
            STATUS_UNKNOWN,
            f"TVS rating unavailable or unknown ({rating}).",
            rating,
            required,
            "medium",
            0.4,
        )

    def _eval_tox(
        self,
        resolution: MaterialResolutionResult,
        habitable: bool,
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        rating = (resolution.tox_rating or "").strip().upper() or "U"
        required = "A"
        if rating == "A":
            return (
                STATUS_COMPLIANT,
                f"TOX rating {rating} meets requirement.",
                rating,
                required,
                "low",
                0.95,
            )
        if rating == "B":
            if habitable:
                return (
                    STATUS_NONCOMPLIANT,
                    "TOX rating B is not acceptable in habitable volume without closure.",
                    rating,
                    required,
                    "high",
                    0.9,
                )
            return (
                STATUS_CONSTRAINED,
                "TOX rating B acceptable only for non-habitable use with controls.",
                rating,
                required,
                "medium",
                0.8,
            )
        if rating in {"C", "D", "X"}:
            return (
                STATUS_NONCOMPLIANT,
                f"TOX rating {rating} fails requirement.",
                rating,
                required,
                "high",
                0.92,
            )
        return (
            STATUS_UNKNOWN,
            f"TOX rating unavailable or unknown ({rating}).",
            rating,
            required,
            "medium",
            0.4,
        )

    def _eval_scc(
        self,
        resolution: MaterialResolutionResult,
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        """Evaluate stress corrosion cracking using MSFC-STD-3029A SCC rating."""
        rating = (getattr(resolution, "scc_rating", None) or "").strip().upper() or "U"

        if rating == "1":
            return (
                STATUS_COMPLIANT,
                "SCC rating 1 (highly resistant) meets requirement.",
                rating,
                "1",
                "low",
                0.95,
            )
        if rating == "2":
            return (
                STATUS_CONSTRAINED,
                "SCC rating 2 (moderate). Acceptable with documented stress controls and temper verification.",
                rating,
                "1",
                "medium",
                0.8,
            )
        if rating == "3":
            return (
                STATUS_NONCOMPLIANT,
                "SCC rating 3 (susceptible). Requires closure path or material substitution.",
                rating,
                "1",
                "high",
                0.9,
            )
        return (
            STATUS_UNKNOWN,
            f"SCC rating unavailable or unknown ({rating}). Requires MSFC-STD-3029A evaluation.",
            rating,
            "1",
            "medium",
            0.4,
        )

    def _eval_corr(
        self,
        resolution: MaterialResolutionResult,
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        """Evaluate corrosion resistance rating."""
        rating = (getattr(resolution, "corr_rating", None) or "").strip().upper() or "U"

        if rating == "A":
            return (
                STATUS_COMPLIANT,
                "Corrosion rating A (resistant) meets requirement.",
                rating,
                "A",
                "low",
                0.95,
            )
        if rating == "B":
            return (
                STATUS_CONSTRAINED,
                "Corrosion rating B. Acceptable with documented corrosion protection plan.",
                rating,
                "A",
                "medium",
                0.8,
            )
        if rating in {"C", "D", "X"}:
            return (
                STATUS_NONCOMPLIANT,
                f"Corrosion rating {rating}. Requires corrosion protection closure or material change.",
                rating,
                "A",
                "high",
                0.9,
            )
        return (
            STATUS_UNKNOWN,
            f"Corrosion rating unavailable or unknown ({rating}). Requires corrosion assessment.",
            rating,
            "A",
            "medium",
            0.4,
        )

    def _eval_hee(
        self,
        resolution: MaterialResolutionResult,
        material: MaterialEntry,
        environment: Any,
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        """Evaluate hydrogen environment embrittlement using the H2 compatibility engine."""
        # Gate: only evaluate if environment has hydrogen exposure
        if not getattr(environment, "hydrogen_service", False):
            return (
                STATUS_UNKNOWN,
                "Environment does not have hydrogen exposure (hydrogen_service=False); HEE check skipped.",
                None,
                None,
                "low",
                0.5,
            )

        try:
            from mira.h2 import evaluate_h2_compatibility, H2CompatibilityRequest
        except ImportError:
            LOGGER.warning("mira.h2 not available for HEE evaluation")
            return (
                STATUS_UNKNOWN,
                "H2 compatibility engine not available (import failed).",
                None,
                None,
                "medium",
                0.0,
            )

        try:
            # Normalize material name to lowercase with underscores
            material_key = (material.name or "").strip().lower().replace(" ", "_")
            if not material_key:
                return (
                    STATUS_UNKNOWN,
                    "Material name is empty; cannot evaluate HEE.",
                    None,
                    None,
                    "medium",
                    0.0,
                )

            # Extract environment parameters
            pressure_psia = float(getattr(environment, "pressure_psia", 0.0) or 0.0)

            # Temperature: use min temp (worst case) from temp_range_c, convert C→K
            temp_range = getattr(environment, "temp_range_c", None)
            if temp_range and len(temp_range) >= 1:
                min_temp_c = float(temp_range[0])
            else:
                min_temp_c = 25.0  # default to room temp if not specified
            temperature_k = min_temp_c + 273.15

            # Phase: LH2 if temp < -253°C, else GH2
            phase = "lh2" if min_temp_c < -253.0 else "gh2"

            request = H2CompatibilityRequest(
                material_key=material_key,
                pressure_psia=pressure_psia,
                temperature_k=temperature_k,
                phase=phase,
            )
            response = evaluate_h2_compatibility(request)

            # Map classification to compliance status
            classification = str(response.classification.value).lower()
            rationale = response.rationale or "No rationale provided."

            if classification == "ok":
                return (
                    STATUS_COMPLIANT,
                    f"HEE: {rationale}",
                    None,
                    "H2-compatible",
                    "low",
                    0.9,
                )
            if classification == "caution":
                return (
                    STATUS_CONSTRAINED,
                    f"HEE: {rationale}",
                    "caution",
                    "H2-compatible",
                    "medium",
                    0.75,
                )
            if classification == "prohibited":
                return (
                    STATUS_NONCOMPLIANT,
                    f"HEE: {rationale}",
                    "prohibited",
                    "H2-compatible",
                    "critical",
                    0.9,
                )
            # unknown or any other value
            return (
                STATUS_UNKNOWN,
                f"HEE: {rationale}",
                classification,
                "H2-compatible",
                "medium",
                0.4,
            )

        except Exception as exc:
            LOGGER.error("HEE evaluation failed for %s: %s", material.name, exc)
            return (
                STATUS_UNKNOWN,
                f"HEE evaluation error: {exc}",
                None,
                None,
                "medium",
                0.0,
            )

    def _eval_prohibition(
        self,
        material: MaterialEntry,
        environment: Any,
        prohibition: dict,
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        """
        Evaluate material-family-level prohibition MPRs.

        These are binary checks that don't need MAPTIS ratings — they evaluate
        material name/keywords against hard prohibitions from 6016C.
        """
        material_text = " ".join([
            material.name or "",
            material.application or "",
            material.spec or "",
            material.function or "",
        ]).lower()

        ptype = prohibition.get("type", "")
        keywords = [k.lower() for k in prohibition.get("material_keywords", [])]
        exclude = [k.lower() for k in prohibition.get("exclude_keywords", [])]
        rationale = prohibition.get("rationale", "Prohibited by NASA-STD-6016C")

        # Check if any keyword matches
        keyword_match = any(kw in material_text for kw in keywords)
        if not keyword_match:
            return (
                STATUS_COMPLIANT,
                "Material does not match prohibition keywords.",
                None,
                None,
                "low",
                0.9,
            )

        # Check exclusions
        if exclude and any(ex in material_text for ex in exclude):
            return (
                STATUS_COMPLIANT,
                "Material matches prohibition keywords but is excluded by exception.",
                None,
                None,
                "low",
                0.85,
            )

        # Check environment condition for material_environment type
        if ptype == "material_environment":
            env_cond = prohibition.get("environment_condition", "")
            env_triggered = False
            if env_cond == "oxygen_service":
                env_triggered = float(environment.o2_pct) > 23.5
            elif env_cond == "habitable_or_vacuum":
                env_triggered = bool(environment.habitable) or bool(environment.vacuum_exposure)
            elif env_cond == "external_environment":
                env_triggered = bool(environment.vacuum_exposure) or bool(getattr(environment, "lunar_dust", False))
            elif env_cond == "habitable":
                env_triggered = bool(environment.habitable)

            if not env_triggered:
                return (
                    STATUS_COMPLIANT,
                    "Material matches prohibition keywords but environment condition not met.",
                    None,
                    None,
                    "low",
                    0.85,
                )

        # Check temperature limit for material_temperature type
        if ptype == "material_temperature":
            max_temp = prohibition.get("max_temp_c")
            if max_temp is not None:
                env_max_temp = float(environment.temp_range_c[1])
                if env_max_temp <= max_temp:
                    return (
                        STATUS_COMPLIANT,
                        f"Environment max temp {env_max_temp:.0f}°C within limit {max_temp:.0f}°C.",
                        None,
                        None,
                        "low",
                        0.9,
                    )

        # Prohibition triggered
        return (
            STATUS_NONCOMPLIANT,
            f"PROHIBITED: {rationale}",
            "prohibited",
            "not prohibited",
            "critical",
            0.98,
        )

    def _evaluate_mode(
        self,
        mode: str,
        material: MaterialEntry,
        environment: Any,
        resolution: Optional[MaterialResolutionResult],
    ) -> tuple[str, str, Optional[str], Optional[str], str, float]:
        if not resolution:
            return (
                STATUS_UNKNOWN,
                "MAPTIS resolution not available.",
                None,
                None,
                "high",
                0.0,
            )

        if mode in {"flam", "o2_prohibited", "o2_restricted"}:
            return self._eval_flam(resolution, float(environment.o2_pct))
        if mode in {"offgas", "tvs"}:
            return self._eval_tvs(resolution)
        if mode == "tox":
            return self._eval_tox(resolution, bool(environment.habitable))
        if mode == "hee":
            return self._eval_hee(resolution, material, environment)
        if mode == "scc":
            return self._eval_scc(resolution)
        if mode == "corr":
            return self._eval_corr(resolution)

        # Full-index fallback: keep requirement visible and route to human review.
        return (
            STATUS_UNKNOWN,
            (
                f"No deterministic rating feed for mode '{mode}' from current "
                "MAPTIS payload; requires analysis/test citation."
            ),
            None,
            None,
            "medium",
            0.35,
        )

    @staticmethod
    def _status_worst(statuses: list[str]) -> str:
        return max(statuses, key=lambda s: STATUS_RANK.get(s, -1)) if statuses else STATUS_UNKNOWN

    @staticmethod
    def _basis_from_status(status: str) -> str:
        if status in {STATUS_COMPLIANT, STATUS_CONSTRAINED, STATUS_NONCOMPLIANT}:
            return "test"
        return "analysis"

    @staticmethod
    def _review_priority(status: str, confidence: float) -> int:
        if status == STATUS_NONCOMPLIANT:
            return 100
        if status == STATUS_UNKNOWN:
            return 90
        if status == STATUS_CONSTRAINED:
            return 70
        if confidence < 0.85:
            return 60
        return 10

    def run(
        self,
        session: PlanGeneratorSession,
    ) -> tuple[list[DeficiencySignal], list[NonconformanceSignal], list[dict[str, Any]]]:
        """
        Evaluate all applicable MPRs in the session matrix.
        """
        now_iso = datetime.now().isoformat()
        deficiencies: dict[tuple[str, str, str], DeficiencySignal] = {}
        nonconformances: dict[str, NonconformanceSignal] = {}
        determinations: list[dict[str, Any]] = []

        if not session.applicability_matrix:
            return [], [], []

        for usage_key, mpr_map in session.applicability_matrix.items():
            material_id, environment_id = usage_key.split(":", 1)
            material = session.get_material(material_id)
            environment = session.get_environment(environment_id)
            if not material or not environment:
                continue
            resolution = session.get_resolution(material_id)

            for mpr_id, mpr_decision in mpr_map.items():
                applicability_status = mpr_decision.get("status", STATUS_UNKNOWN)
                determination_id = _hash_id(
                    "det",
                    f"{material.id}:{environment.environment_id}:{mpr_id}",
                )

                base_citation = mpr_decision.get(
                    "citation",
                    f"NASA-STD-6016C w/CHANGE 2 §{mpr_decision.get('mpr_section', '')}",
                )
                citations = [base_citation]
                evidence_refs = [_standard_evidence(str(mpr_decision.get("mpr_section", "")))]

                if resolution:
                    citations.append(f"MAPTIS:{resolution.maptis_code}")
                    evidence_refs.append(_maptis_evidence(resolution))

                related_modes = [
                    str(m).lower() for m in mpr_decision.get("related_failure_modes", [])
                ]

                if applicability_status != "applicable":
                    determinations.append(
                        {
                            "determination_id": determination_id,
                            "generated_at": now_iso,
                            "material_id": material.id,
                            "material_name": material.name,
                            "environment_id": environment.environment_id,
                            "environment_name": environment.name,
                            "mpr_id": mpr_id,
                            "mpr_number": mpr_decision.get("mpr_number"),
                            "mpr_title": mpr_decision.get("mpr_title"),
                            "mpr_section": mpr_decision.get("mpr_section"),
                            "applicability_status": applicability_status,
                            "applicability_rationale": mpr_decision.get("rationale", ""),
                            "status": "not_applicable",
                            "basis": "not_applicable",
                            "confidence": mpr_decision.get("confidence", 1.0),
                            "rationale": "Requirement not applicable for this usage context.",
                            "failing_value": None,
                            "required_value": None,
                            "related_failure_modes": related_modes,
                            "citations": citations,
                            "evidence_refs": [e.model_dump() for e in evidence_refs],
                            "needs_review": False,
                            "review_reason": "",
                            "review_priority": 0,
                        }
                    )
                    continue

                if not resolution:
                    key = (material.id, environment.environment_id, "missing_maptis_resolution")
                    if key not in deficiencies:
                        deficiencies[key] = DeficiencySignal(
                            deficiency_id=_hash_id("def", ":".join(key)),
                            deficiency_type="missing_maptis_resolution",
                            missing_field="maptis_resolution",
                            missing_for=f"compliance determination for {material.name}",
                            material_id=material.id,
                            environment_id=environment.environment_id,
                            blocked_decision_ids=[determination_id],
                            conservative_default_available=False,
                            source="compliance_eval_codex",
                        )

                # Check prohibition before mode evaluation
                prohibition = mpr_decision.get("prohibition")
                if prohibition:
                    prohibition_result = self._eval_prohibition(
                        material=material,
                        environment=environment,
                        prohibition=prohibition,
                    )
                    if prohibition_result[0] == STATUS_NONCOMPLIANT:
                        # Prohibition triggered — skip mode evaluation, this is a hard fail
                        mode_results = [prohibition_result]
                        related_modes = related_modes or ["missing_input"]
                        # Jump directly to determination assembly below
                        statuses = [prohibition_result[0]]
                        final_status = STATUS_NONCOMPLIANT
                        confidence = prohibition_result[5]
                        rationale_parts = [prohibition_result[1]]
                        failing_values = [prohibition_result[2]] if prohibition_result[2] else []
                        required_values = [prohibition_result[3]] if prohibition_result[3] else []
                        worst_severity = prohibition_result[4]

                        needs_review = True
                        review_reason = "Material is PROHIBITED by NASA-STD-6016C for this application/environment."
                        human_action = "Remove this material or obtain a formal MUA with engineering justification."
                        human_meaning = "This material violates a hard prohibition in the standard."
                        citation_helper = build_citation_helper_codex(
                            mpr_section=str(mpr_decision.get("mpr_section", "")),
                            related_modes=related_modes,
                            status=final_status,
                            maptis_code=(resolution.maptis_code if resolution else None),
                        )

                        determinations.append(
                            {
                                "determination_id": determination_id,
                                "generated_at": now_iso,
                                "material_id": material.id,
                                "material_name": material.name,
                                "environment_id": environment.environment_id,
                                "environment_name": environment.name,
                                "mpr_id": mpr_id,
                                "mpr_number": mpr_decision.get("mpr_number"),
                                "mpr_title": mpr_decision.get("mpr_title"),
                                "mpr_section": mpr_decision.get("mpr_section"),
                                "applicability_status": applicability_status,
                                "applicability_rationale": mpr_decision.get("rationale", ""),
                                "status": final_status,
                                "basis": "analysis",
                                "confidence": round(confidence, 3),
                                "rationale": " | ".join(rationale_parts),
                                "failing_value": ", ".join(failing_values) if failing_values else None,
                                "required_value": ", ".join(sorted(set(required_values))) if required_values else None,
                                "related_failure_modes": related_modes,
                                "citations": citations,
                                "evidence_refs": [e.model_dump() for e in evidence_refs],
                                "needs_review": needs_review,
                                "review_reason": review_reason,
                                "review_priority": 100,
                                "human_action": human_action,
                                "human_meaning": human_meaning,
                                "quick_actions": citation_helper.get("quick_actions", []),
                                "citation_helper": citation_helper,
                                "prohibition_triggered": True,
                            }
                        )

                        primary_mode = next((m for m in PRIMARY_MODE_ORDER if m in related_modes), related_modes[0] if related_modes else "missing_input")
                        nc_id = _hash_id("nc", determination_id)
                        nonconformances[nc_id] = NonconformanceSignal(
                            nonconformance_id=nc_id,
                            gap_type=_to_failure_mode(primary_mode),
                            failing_requirement=f"{mpr_id} {mpr_decision.get('mpr_title', '')}".strip(),
                            failing_value="prohibited",
                            required_value="not prohibited",
                            material_id=material.id,
                            environment_id=environment.environment_id,
                            affected_mprs=[mpr_id],
                            severity=GapSeverity.CRITICAL,
                            confidence=max(0.0, min(1.0, confidence)),
                            evidence_refs=evidence_refs,
                            source_adapter="compliance_eval_codex",
                        )
                        continue

                if not related_modes:
                    related_modes = ["unknown"]

                mode_results = [
                    self._evaluate_mode(
                        mode=mode,
                        material=material,
                        environment=environment,
                        resolution=resolution,
                    )
                    for mode in related_modes
                ]

                statuses = [r[0] for r in mode_results]
                final_status = self._status_worst(statuses)
                confidence = min((float(r[5]) for r in mode_results), default=0.5)
                rationale_parts = [r[1] for r in mode_results]
                failing_values = [r[2] for r in mode_results if r[2]]
                required_values = [r[3] for r in mode_results if r[3]]
                severities = [r[4] for r in mode_results]
                worst_severity = (
                    "critical"
                    if "critical" in severities
                    else "high" if "high" in severities else "medium"
                )

                needs_review = final_status in {STATUS_NONCOMPLIANT, STATUS_UNKNOWN, STATUS_CONSTRAINED}
                review_reason = (
                    "Noncompliant determination requires closure path."
                    if final_status == STATUS_NONCOMPLIANT
                    else "Engine cannot determine this requirement from available MAPTIS/test data; human citation or closure decision is required."
                    if final_status == STATUS_UNKNOWN
                    else "Constraint-based acceptance requires reviewer confirmation."
                    if final_status == STATUS_CONSTRAINED
                    else ""
                )
                human_action = (
                    "Select a closure path (or accept open with owner/due date) and provide rationale."
                    if final_status == STATUS_NONCOMPLIANT
                    else _unknown_action_by_section(
                        str(mpr_decision.get("mpr_section", "")),
                        related_modes,
                    )
                    if final_status == STATUS_UNKNOWN
                    else "Confirm the constraint is valid for this mission use case and keep evidence citation."
                    if final_status == STATUS_CONSTRAINED
                    else ""
                )
                human_meaning = (
                    "Requirement currently fails with available evidence."
                    if final_status == STATUS_NONCOMPLIANT
                    else "Requirement is unresolved with current evidence."
                    if final_status == STATUS_UNKNOWN
                    else "Requirement is conditionally acceptable, pending reviewer confirmation."
                    if final_status == STATUS_CONSTRAINED
                    else "Requirement is automatically satisfied."
                )
                citation_helper = build_citation_helper_codex(
                    mpr_section=str(mpr_decision.get("mpr_section", "")),
                    related_modes=related_modes,
                    status=final_status,
                    maptis_code=(resolution.maptis_code if resolution else None),
                )

                determinations.append(
                    {
                        "determination_id": determination_id,
                        "generated_at": now_iso,
                        "material_id": material.id,
                        "material_name": material.name,
                        "environment_id": environment.environment_id,
                        "environment_name": environment.name,
                        "mpr_id": mpr_id,
                        "mpr_number": mpr_decision.get("mpr_number"),
                        "mpr_title": mpr_decision.get("mpr_title"),
                        "mpr_section": mpr_decision.get("mpr_section"),
                        "applicability_status": applicability_status,
                        "applicability_rationale": mpr_decision.get("rationale", ""),
                        "status": final_status,
                        "basis": self._basis_from_status(final_status),
                        "confidence": round(confidence, 3),
                        "rationale": " | ".join(rationale_parts),
                        "failing_value": ", ".join(failing_values) if failing_values else None,
                        "required_value": ", ".join(sorted(set(required_values))) if required_values else None,
                        "related_failure_modes": related_modes,
                        "citations": citations,
                        "evidence_refs": [e.model_dump() for e in evidence_refs],
                        "needs_review": needs_review,
                        "review_reason": review_reason,
                        "review_priority": self._review_priority(final_status, confidence),
                        "human_action": human_action,
                        "human_meaning": human_meaning,
                        "quick_actions": citation_helper.get("quick_actions", []),
                        "citation_helper": citation_helper,
                    }
                )

                if final_status == STATUS_NONCOMPLIANT:
                    primary_mode = next((m for m in PRIMARY_MODE_ORDER if m in related_modes), related_modes[0])
                    nc_id = _hash_id("nc", determination_id)
                    nonconformances[nc_id] = NonconformanceSignal(
                        nonconformance_id=nc_id,
                        gap_type=_to_failure_mode(primary_mode),
                        failing_requirement=f"{mpr_id} {mpr_decision.get('mpr_title', '')}".strip(),
                        failing_value=", ".join(failing_values) if failing_values else None,
                        required_value=", ".join(sorted(set(required_values))) if required_values else None,
                        material_id=material.id,
                        environment_id=environment.environment_id,
                        affected_mprs=[mpr_id],
                        severity=_to_gap_severity(worst_severity),
                        confidence=max(0.0, min(1.0, confidence)),
                        evidence_refs=evidence_refs,
                        source_adapter="compliance_eval_codex",
                    )

        LOGGER.info(
            "Codex compliance complete: %d determinations, %d deficiencies, %d nonconformances",
            len(determinations),
            len(deficiencies),
            len(nonconformances),
        )
        return list(deficiencies.values()), list(nonconformances.values()), determinations
