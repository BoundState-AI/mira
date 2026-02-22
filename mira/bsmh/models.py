#!/usr/bin/env python3
"""
Shared models for the temporary BSMH query path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class BSMHStructuredQuery(BaseModel):
    """Structured query produced by the bouncer."""

    material: Optional[str] = None
    materials: List[str] = Field(default_factory=list)
    environment: Optional[str] = None
    pressure_psi: Optional[float] = None
    temperature_f: Optional[float] = None
    o2_pct: Optional[float] = None
    intent: str = "general"
    original_query: str

    model_config = {"extra": "forbid"}


class BouncerResult(BaseModel):
    """Outcome from the bouncer layer."""

    status: Literal["accepted", "rejected"]
    rejection_reason: Optional[str] = None
    structured_query: Optional[BSMHStructuredQuery] = None
    source: Literal["local_llm", "heuristic", "haiku"] = "heuristic"

    model_config = {"extra": "forbid"}


class RuleEvidenceItem(BaseModel):
    """Single deterministic evidence check."""

    property: str
    value: str
    requirement: str
    passed: bool
    source: Optional[str] = None

    model_config = {"extra": "forbid"}


class MaterialRuleResult(BaseModel):
    """Deterministic verdict for one material."""

    material_name: str
    material_key: Optional[Any] = None
    oxygen_rating: Optional[str] = None
    hydrogen_signal_present: Optional[bool] = None
    verdict: Literal["COMPATIBLE", "INCOMPATIBLE", "CONDITIONAL", "INSUFFICIENT_DATA"]
    score: float = Field(..., ge=0.0, le=1.0)
    evidence_strength: Literal["strong", "moderate", "limited", "insufficient"] = "limited"
    linkage_gap: bool = Field(
        False,
        description="True when MUA heritage is substantial but MAPTIS test linkage is sparse, "
        "indicating a database coverage gap rather than untested material.",
    )
    warnings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    evidence_chain: List[RuleEvidenceItem] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class RuleDecisionPacket(BaseModel):
    """Output from deterministic MIRA-rules stage."""

    verdict: Literal["COMPATIBLE", "INCOMPATIBLE", "CONDITIONAL", "INSUFFICIENT_DATA"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    materials: List[MaterialRuleResult] = Field(default_factory=list)
    aggregation_scope: Literal["primary_only", "all_materials"] = "primary_only"
    primary_material_count: int = 0
    associated_material_count: int = 0
    bok_context_used: bool = False
    bok_evidence_count: int = 0
    bok_sources: List[str] = Field(default_factory=list)
    requested_materials: List[str] = Field(default_factory=list)
    missing_requested_materials: List[str] = Field(default_factory=list)
    determination_material_keys: List[Any] = Field(default_factory=list)
    determination_material_names: List[str] = Field(default_factory=list)
    rules_applied: List[str] = Field(default_factory=list)
    standards_category: Optional[str] = None
    evidence_gaps: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# =============================================================================
# Fracture Control Authority Pack Models
# =============================================================================


# Valid enum values for fracture context fields.
# Used for validation: unknown strings log a warning and coerce to None
# rather than silently passing through to the predicate evaluator.
_VALID_CONSEQUENCE = {"catastrophic", "critical", "non_critical"}
_VALID_INSPECTABILITY = {"inspectable", "limited_access", "non_inspectable"}
_VALID_GEOMETRY = {
    "pressure_vessel", "fitting", "line", "structural",
    "fastener", "mechanism", "other",
}
_VALID_MATERIAL_CONDITION = {
    "wrought", "cast", "forged", "welded",
    "am_printed", "powder_metallurgy",
}
_VALID_CENTER_CODE = {
    "MSFC", "JSC", "KSC", "GRC", "GSFC", "JPL", "ARC", "LaRC", "SSC",
}


class FractureContextInput(BaseModel):
    """Structured context for fracture control classification.

    Minimum required fields for rule engine execution.
    Missing fields route to CLARIFY, never assumed.

    IMPORTANT: The model_validator coerces empty strings to None.
    This prevents Sonnet returning "" instead of null from bypassing
    the NULL guard in the predicate evaluator (fracture_engine.py).
    """

    material: Optional[str] = None
    part_name: Optional[str] = None
    pressure_boundary: Optional[bool] = None
    consequence_of_failure: Optional[str] = Field(
        None, description="catastrophic | critical | non_critical"
    )
    inspectability: Optional[str] = Field(
        None, description="inspectable | limited_access | non_inspectable"
    )
    geometry_type: Optional[str] = Field(
        None, description="pressure_vessel | fitting | line | structural | fastener | mechanism | other"
    )
    material_condition: Optional[str] = Field(
        None, description="wrought | cast | forged | welded | am_printed | powder_metallurgy"
    )
    center_code: Optional[str] = Field(
        None, description="MSFC | JSC | KSC | GRC | GSFC | JPL | ARC | LaRC | SSC"
    )
    design_life_cycles: Optional[int] = Field(None, ge=0)
    operating_pressure_psi: Optional[float] = Field(None, ge=0)
    operating_pressure_unit: Optional[str] = Field(
        None, description="Unit as stated: psi, psia, kPa, etc."
    )
    operating_temperature_f: Optional[float] = None
    operating_temperature_unit: Optional[str] = Field(
        None, description="Unit as stated: F, C, K, etc."
    )
    proof_factor: Optional[float] = Field(None, ge=1.0)

    model_config = {"extra": "ignore"}  # tolerate extra keys from Sonnet

    from pydantic import model_validator

    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_strings_and_validate_enums(cls, values: Any) -> Any:
        """Normalize Sonnet output before field validation.

        1. Coerce empty strings to None (VSClaude finding: "" bypasses NULL guard).
        2. Validate enum-like fields; unknown values → None + warning log.
        """
        import logging as _logging

        _log = _logging.getLogger(__name__)
        if not isinstance(values, dict):
            return values

        # --- Step 1: empty string → None ---
        for key, val in list(values.items()):
            if isinstance(val, str) and val.strip() == "":
                values[key] = None

        # --- Step 2: enum validation (warn + coerce, don't crash) ---
        _enum_checks = {
            "consequence_of_failure": _VALID_CONSEQUENCE,
            "inspectability": _VALID_INSPECTABILITY,
            "geometry_type": _VALID_GEOMETRY,
            "material_condition": _VALID_MATERIAL_CONDITION,
        }
        for field_name, valid_set in _enum_checks.items():
            val = values.get(field_name)
            if val is not None and isinstance(val, str):
                normalized = val.strip().lower()
                if normalized not in valid_set:
                    _log.warning(
                        "[FC] Invalid %s value %r from Sonnet; coercing to None",
                        field_name, val,
                    )
                    values[field_name] = None
                else:
                    values[field_name] = normalized

        # center_code is case-sensitive (MSFC, not msfc)
        cc = values.get("center_code")
        if cc is not None and isinstance(cc, str):
            cc_upper = cc.strip().upper()
            if cc_upper not in _VALID_CENTER_CODE:
                _log.warning(
                    "[FC] Invalid center_code %r from Sonnet; coercing to None", cc,
                )
                values["center_code"] = None
            else:
                values["center_code"] = cc_upper

        return values

    def get_missing_required(self) -> List[str]:
        """Return names of fields required for classification but not provided."""
        required = ["pressure_boundary", "consequence_of_failure", "inspectability", "geometry_type"]
        return [f for f in required if getattr(self, f) is None]


class FractureClassificationResult(BaseModel):
    """Output of fracture control part classification."""

    part_class: str = Field(..., description="Part classification per 5019A")
    fcr_set: List[str] = Field(default_factory=list, description="Applicable FCR numbers")
    nde_required: bool = Field(False)
    nde_methods: List[str] = Field(default_factory=list)
    nde_exceptions_applied: List[str] = Field(default_factory=list)
    rule_matched: Optional[str] = Field(None, description="Rule code that determined classification")
    rules_evaluated: int = Field(0)
    center_overrides_applied: List[str] = Field(default_factory=list)
    classification_confidence: float = Field(1.0, ge=0.0, le=1.0)
    clarify_fields: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class FractureCitation(BaseModel):
    """Single citation to source document."""

    standard: str
    revision: str
    section: str
    page: Optional[int] = None
    clause_text: Optional[str] = None

    model_config = {"extra": "forbid"}


class FractureDecisionPacket(BaseModel):
    """Complete fracture control assessment output.

    Parallel to RuleDecisionPacket for materials compatibility.
    """

    verdict: Literal["CLASSIFIED", "NEEDS_CLARIFICATION", "INSUFFICIENT_DATA", "ERROR"]
    classification: Optional[FractureClassificationResult] = None
    context_provided: FractureContextInput
    citations: List[FractureCitation] = Field(default_factory=list)
    documentation_required: List[str] = Field(default_factory=list)
    derived_values: Dict[str, Any] = Field(default_factory=dict, description="KIc/Fty ratio etc. computed at eval time")
    warnings: List[str] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)
    rules_applied: List[str] = Field(default_factory=list)
    provenance_hash: Optional[str] = None
    trace_id: Optional[int] = None

    model_config = {"extra": "forbid"}


class BSMHQueryRequest(BaseModel):
    """Request model for the temporary BSMH endpoint."""

    query: str = Field(..., min_length=1, description="Natural language M&P query")
    material_key: Optional[str] = Field(None, description="Target material identifier")
    temperature_c: Optional[float] = Field(None, description="Temperature in Celsius")
    pressure_kpa: Optional[float] = Field(None, ge=0, description="Pressure in kPa")
    o2_pct: Optional[float] = Field(None, ge=0, le=100, description="O2 concentration %")
    fluid_medium: Optional[str] = Field(None, description="Fluid medium (LOX, GOX, LH2, etc.)")
    duration_hr: Optional[float] = Field(None, ge=0, description="Exposure duration hours")
    cycles: Optional[int] = Field(None, ge=0, description="Thermal/pressure cycles")
    answer_mode: Literal["sonnet"] = Field(
        "sonnet",
        description="Answer formatter mode. BSMH production path is Sonnet-only.",
    )

    model_config = {"extra": "forbid"}


class BSMHQueryResponse(BaseModel):
    """Response model for temporary BSMH endpoint."""

    status: Literal["ok", "rejected", "error"]
    pipeline: str = "B-S-M-S"
    answer: str
    answer_sonnet: Optional[str] = None
    answer_mode: Literal["sonnet"] = "sonnet"
    sonnet_calls_used: int = 0
    bouncer: BouncerResult
    rules: Optional[RuleDecisionPacket] = None
    fracture_result: Optional[FractureDecisionPacket] = None
    materials: List[Dict[str, Any]] = Field(default_factory=list)
    sonnet_metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_v4_answer: Optional[str] = None
    v4_lineage_id: Optional[str] = None
    v4_gate_action: Optional[str] = None
    v4_confidence_score: Optional[float] = None
    error: Optional[str] = None

    model_config = {"extra": "forbid"}
