#!/usr/bin/env python3
"""
Module: Compliance Router
Purpose: NASA-STD-6016C Compliance Analysis API endpoints

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright (c) 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mira.compliance.conductor import (
    ComplianceConductor,
    ParsedPlan,
)
from mira.compliance.models.enums import (
    EnvironmentType,
    MUACategory,
)
from mira.compliance.models.mpr import MPRIndex, create_mpr_index_from_yaml
from mira.compliance.models.policy import (
    ConductorPolicy,
    EnvironmentDefinition,
    EnvironmentPolicy,
)


router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class ComplianceAnalysisRequest(BaseModel):
    """Request model for compliance analysis."""

    material_key: str = Field(
        ...,
        description="Material identifier (name, spec, or MAPTIS code)",
    )
    maptis_code: Optional[int] = Field(
        None,
        description="MAPTIS code if known",
    )
    pressure_psia: float = Field(
        14.7,
        description="Operating pressure in PSIA",
    )
    temperature_f: float = Field(
        70.0,
        description="Operating temperature in Fahrenheit",
    )
    o2_percent: Optional[float] = Field(
        21.0,
        description="Oxygen concentration (percent)",
    )
    is_hydrogen_service: bool = Field(
        False,
        description="Whether this is hydrogen service",
    )
    is_habitable: bool = Field(
        False,
        description="Whether environment is crew-occupied",
    )
    hydrogen_phase: Optional[str] = Field(
        None,
        description="GH2 or LH2 for hydrogen service",
    )

    model_config = {"extra": "forbid"}


class GapSignalResponse(BaseModel):
    """Gap signal in response."""
    gap_id: str
    gap_type: str
    trigger: str
    severity: str
    description: str
    evidence_count: int = 0


class OperationalConstraintResponse(BaseModel):
    """Operational constraint in response."""
    constraint_id: str
    parameter: str
    limit_type: str
    limit_value: str
    description: str


class MPRDeterminationResponse(BaseModel):
    """MPR determination in response."""
    mpr_number: int
    mpr_section: str
    mpr_title: str
    applicability_status: str
    compliance_status: str
    compliance_basis: str
    required_action: str
    gap_count: int = 0
    constraint_count: int = 0


class ComplianceSummaryResponse(BaseModel):
    """High-level summary in response."""
    overall_status: str
    status_rationale: str
    total_materials: int
    materials_compliant: int
    materials_noncompliant: int
    materials_requiring_mua: int
    total_mprs_applicable: int
    mprs_compliant: int
    mprs_compliant_with_constraints: int
    mprs_noncompliant: int
    total_gaps: int
    critical_gaps: int


class ComplianceAnalysisResponse(BaseModel):
    """Response model for compliance analysis."""

    request_id: str
    material_key: str
    environment_description: str
    timestamp: datetime

    summary: ComplianceSummaryResponse
    determinations: list[MPRDeterminationResponse]
    gaps: list[GapSignalResponse]
    constraints: list[OperationalConstraintResponse]

    run_duration_ms: int = 0
    warnings: list[str] = []
    errors: list[str] = []

    model_config = {"extra": "forbid"}


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/ping")
async def ping() -> dict[str, str]:
    """Health check for compliance endpoint."""
    return {"status": "ok", "domain": "compliance"}


@router.post("/analyze", response_model=ComplianceAnalysisResponse)
async def analyze_compliance(
    request: ComplianceAnalysisRequest,
) -> ComplianceAnalysisResponse:
    """
    Analyze material compliance with NASA-STD-6016C.

    Orchestrates the compliance conductor to:
    1. Resolve material to canonical identifiers
    2. Evaluate against O2 and/or H2 twins
    3. Map gap signals to MPR determinations
    4. Generate MUA requirements if needed

    Returns comprehensive compliance analysis result.
    """
    try:
        # Build environment definition
        environment = _build_environment(request)

        # Build material entry
        materials = [
            {
                "name": request.material_key,
                "maptis_code": request.maptis_code,
                "spec": None,
            }
        ]

        # Create parsed plan
        plan = ParsedPlan(
            plan_id=f"api-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            version="1.0",
            materials=materials,
            environments=[environment],
        )

        # Initialize conductor
        mpr_index = _get_mpr_index()
        env_policy = EnvironmentPolicy()
        conductor_policy = ConductorPolicy()

        conductor = ComplianceConductor(
            mpr_index=mpr_index,
            environment_policy=env_policy,
            conductor_policy=conductor_policy,
        )

        # Run analysis
        result = conductor.run(plan)

        # Convert to response
        return _build_response(request, environment, result)

    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Compliance analysis error: {str(exc)}",
        ) from exc


@router.get("/mprs")
async def list_mprs() -> dict[str, Any]:
    """
    List all MPRs from NASA-STD-6016C.

    Returns the MPR index with sections, titles, and applicability info.
    """
    try:
        mpr_index = _get_mpr_index()
        mprs = []
        for mpr_num, mpr in mpr_index.records.items():
            mprs.append({
                "mpr_number": mpr.mpr_number,
                "mpr_id": mpr.mpr_id,
                "section": mpr.section,
                "title": mpr.title,
                "applicability_triggers": mpr.applicability_triggers,
                "failure_modes": [fm.value for fm in mpr.related_failure_modes],
            })
        return {
            "standard_version": mpr_index.standard_version,
            "total_mprs": len(mprs),
            "mprs": mprs,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error loading MPRs: {str(exc)}",
        ) from exc


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _build_environment(request: ComplianceAnalysisRequest) -> EnvironmentDefinition:
    """Build environment definition from request."""
    # Determine environment type
    if request.is_hydrogen_service:
        env_type = EnvironmentType.HYDROGEN
    elif request.o2_percent and request.o2_percent > 23.5:
        env_type = EnvironmentType.OXYGEN
    elif request.is_habitable:
        env_type = EnvironmentType.HABITABLE
    else:
        env_type = EnvironmentType.OTHER

    # Build description
    parts = []
    if request.is_hydrogen_service:
        phase = request.hydrogen_phase or "GH2"
        parts.append(f"{phase} service")
    if request.o2_percent and request.o2_percent > 23.5:
        parts.append(f"{request.o2_percent}% O2")
    parts.append(f"{request.pressure_psia} psia")
    parts.append(f"{request.temperature_f}°F")
    if request.is_habitable:
        parts.append("habitable")
    description = ", ".join(parts)

    return EnvironmentDefinition(
        environment_id=f"ENV_{env_type.value.upper()}_{datetime.now().strftime('%H%M%S')}",
        environment_type=env_type,
        description=description,
        is_oxygen_enriched=request.o2_percent is not None and request.o2_percent > 23.5,
        oxygen_pct=request.o2_percent or 21.0,
        is_hydrogen_service=request.is_hydrogen_service,
        hydrogen_phase=request.hydrogen_phase,
        pressure_psia=request.pressure_psia,
        pressure_is_high=request.pressure_psia > 300,
        is_habitable=request.is_habitable,
        temperature_min_f=request.temperature_f,
        temperature_max_f=request.temperature_f,
        is_cryogenic=request.temperature_f < -238,  # Below -150°C
    )


def _get_mpr_index() -> MPRIndex:
    """Get or create MPR index."""
    from pathlib import Path

    # Try to load from YAML
    yaml_path = Path(__file__).parent.parent.parent / "compliance" / "data" / "mprs_6016c.yaml"
    if yaml_path.exists():
        return create_mpr_index_from_yaml(str(yaml_path))

    # Return empty index if not found
    return MPRIndex(
        standard_version="C",
        parse_date=datetime.now(),
        source_document_hash="no_yaml_loaded",
        records={},
    )


def _build_response(
    request: ComplianceAnalysisRequest,
    environment: EnvironmentDefinition,
    result,
) -> ComplianceAnalysisResponse:
    """Build API response from analysis result."""
    # Build summary
    summary = ComplianceSummaryResponse(
        overall_status=result.summary.overall_status if result.summary else "unknown",
        status_rationale=result.summary.status_rationale if result.summary else "",
        total_materials=result.manifest.total_materials_evaluated,
        materials_compliant=result.summary.materials_compliant if result.summary else 0,
        materials_noncompliant=result.summary.materials_noncompliant if result.summary else 0,
        materials_requiring_mua=result.manifest.materials_requiring_mua,
        total_mprs_applicable=result.summary.total_mprs_applicable if result.summary else 0,
        mprs_compliant=result.summary.mprs_compliant if result.summary else 0,
        mprs_compliant_with_constraints=result.summary.mprs_compliant_with_constraints if result.summary else 0,
        mprs_noncompliant=result.summary.mprs_noncompliant if result.summary else 0,
        total_gaps=result.summary.total_gaps if result.summary else 0,
        critical_gaps=result.summary.critical_gaps if result.summary else 0,
    )

    # Build determinations
    determinations = []
    for det in result.mpr_determinations:
        determinations.append(MPRDeterminationResponse(
            mpr_number=det.mpr_number,
            mpr_section=det.mpr_section,
            mpr_title=det.mpr_title,
            applicability_status=det.applicability_status.value,
            compliance_status=det.compliant.value,
            compliance_basis=det.compliance_basis.value if det.compliance_basis else "not_applicable",
            required_action=det.required_action.value if det.required_action else "none",
            gap_count=len(det.gap_signals),
            constraint_count=len(det.operational_constraints),
        ))

    # Build gaps
    gaps = []
    for det in result.mpr_determinations:
        for gap in det.gap_signals:
            gaps.append(GapSignalResponse(
                gap_id=gap.gap_id,
                gap_type=gap.gap_type.value,
                trigger=gap.trigger.value,
                severity=gap.severity.value,
                description=gap.summary or "",
                evidence_count=len(gap.evidence_refs),
            ))

    # Build constraints
    constraints = []
    for constraint in result.all_constraints:
        constraints.append(OperationalConstraintResponse(
            constraint_id=constraint.constraint_id,
            parameter=constraint.parameter,
            limit_type=constraint.limit_type,
            limit_value=constraint.limit_value,
            description=constraint.description,
        ))

    return ComplianceAnalysisResponse(
        request_id=result.manifest.run_id,
        material_key=request.material_key,
        environment_description=environment.description,
        timestamp=result.analysis_timestamp,
        summary=summary,
        determinations=determinations,
        gaps=gaps,
        constraints=constraints,
        run_duration_ms=result.manifest.run_duration_ms,
        warnings=result.manifest.warnings,
        errors=result.manifest.errors,
    )


__safety_critical__ = True  # NASA SWE-032 compliance
