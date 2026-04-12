"""Deterministic Phase 1 OCA engine with shared persisted case snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from mira.core.session_store import load_model, save_model

from .maptis_stub import get_material_for_o2, get_o2_family_rule

from .models import (
    AssessmentSnapshot,
    BlockedState,
    BlockedStateCode,
    ComponentInfo,
    ComponentInput,
    CreateOcaCaseRequest,
    CreateOcaCaseResponse,
    CredibleStatus,
    DecisionAction,
    EvidenceApplicabilityClass,
    EvidenceApplicabilityScore,
    EvidenceCard,
    FinalDisposition,
    HazardControlEntry,
    IgnitionContextInput,
    KindlingChainResult,
    MaterialInstance,
    MechanismAssessment,
    MechanismTrace,
    MUASeed,
    NormalizedInput,
    OcaDecisionPacket,
    OcaDecisionResponse,
    OcaEvidenceResponse,
    OcaExportArtifact,
    OcaExportResponse,
    OcaLineageResponse,
    OcaMechanismsResponse,
    OcaPrecheckResponse,
    OcaRequirementsResponse,
    OcaRevision,
    OcaTier,
    OxygenServiceContext,
    OxidizerType,
    PrecheckWarning,
    ReactionEffect,
    RequirementStatus,
    ResolvedMaterial,
    RuleTraceEvent,
    ServicePhase,
    TriggeredRequirement,
)
from .reference_pack import (
    get_authority_manifest as _get_authority_manifest,
    get_hazard_control_library,
    get_ignition_mechanisms,
    get_material_reference,
    get_requirement_binding,
    get_test_mapping,
)


IDENTITY_THRESHOLD = 0.75
DIRECT_EVIDENCE_THRESHOLD = 0.75
PARTIAL_EVIDENCE_THRESHOLD = 0.50
WEAK_EVIDENCE_THRESHOLD = 0.25


_OCA_CASES_MODULE = "oca_cases"


def get_authority_manifest():
    return _get_authority_manifest()

async def _load_snapshot(case_id: str) -> AssessmentSnapshot:
    snapshot = await load_model(_OCA_CASES_MODULE, case_id, AssessmentSnapshot)
    if snapshot is None:
        raise KeyError(case_id)
    return snapshot


async def _save_snapshot(snapshot: AssessmentSnapshot) -> None:
    await save_model(_OCA_CASES_MODULE, snapshot.case_id, snapshot)


async def create_case(request: CreateOcaCaseRequest) -> CreateOcaCaseResponse:
    case_id = f"oca-{uuid4().hex[:12]}"
    snapshot = _build_snapshot(case_id, request, 1)
    await _save_snapshot(snapshot)
    return CreateOcaCaseResponse(
        case_id=snapshot.case_id,
        revision=snapshot.revision,
        normalized_input=snapshot.normalized_input,
        blocked_states=snapshot.blocked_states,
        precheck_warnings=snapshot.precheck_warnings,
    )


async def get_case_precheck(case_id: str) -> OcaPrecheckResponse:
    snapshot = await _load_snapshot(case_id)
    return OcaPrecheckResponse(
        case_id=case_id,
        revision=snapshot.revision,
        blocked_states=snapshot.blocked_states,
        triggered_requirements=snapshot.requirements,
        precheck_warnings=snapshot.precheck_warnings,
    )


async def get_case_evidence(case_id: str) -> OcaEvidenceResponse:
    snapshot = await _load_snapshot(case_id)
    gaps = sorted({gap for card in snapshot.evidence for gap in card.gaps})
    return OcaEvidenceResponse(
        case_id=case_id,
        revision=snapshot.revision,
        evidence=snapshot.evidence,
        gaps=gaps,
    )


async def get_case_mechanisms(case_id: str) -> OcaMechanismsResponse:
    snapshot = await _load_snapshot(case_id)
    return OcaMechanismsResponse(case_id=case_id, revision=snapshot.revision, mechanisms=snapshot.mechanisms)


async def get_case_decision(case_id: str) -> OcaDecisionResponse:
    snapshot = await _load_snapshot(case_id)
    return OcaDecisionResponse(case_id=case_id, revision=snapshot.revision, decision=snapshot.decision)


async def get_case_requirements(case_id: str) -> OcaRequirementsResponse:
    snapshot = await _load_snapshot(case_id)
    return OcaRequirementsResponse(case_id=case_id, revision=snapshot.revision, requirements=snapshot.requirements)


async def get_case_lineage(case_id: str) -> OcaLineageResponse:
    snapshot = await _load_snapshot(case_id)
    return OcaLineageResponse(
        case_id=case_id,
        revision=snapshot.revision,
        revisions=snapshot.revisions,
        decision_lineage=snapshot.decision_lineage,
    )


async def export_case_artifacts(case_id: str) -> OcaExportResponse:
    snapshot = await _load_snapshot(case_id)
    material_names = ", ".join(item.canonical_name for item in snapshot.normalized_input.materials)
    service = snapshot.normalized_input.service_context
    requirements = ", ".join(req.requirement_id for req in snapshot.requirements if req.triggered) or "none"
    artifacts = [
        OcaExportArtifact(
            artifact_type="oca_packet",
            filename=f"{case_id}_oca_packet.txt",
            content_type="text/plain",
            generated_text=(
                f"OCA Decision Memo\nCase: {case_id}\nMaterials: {material_names}\n"
                f"Disposition: {snapshot.decision.final_disposition.value}\n"
                f"Triggered requirements: {requirements}\n"
                f"Summary: {snapshot.decision.summary_rationale}\n"
            ),
        ),
        OcaExportArtifact(
            artifact_type="evidence_packet",
            filename=f"{case_id}_evidence_packet.txt",
            content_type="text/plain",
            generated_text="\n".join(
                f"{item.source_id} | {item.applicability.applicability_class.value} | {item.summary}"
                for item in snapshot.evidence
            ),
        ),
        OcaExportArtifact(
            artifact_type="mua_seed",
            filename=f"{case_id}_mua_seed.txt",
            content_type="text/plain",
            generated_text=(
                f"Material(s): {material_names}\n"
                f"O2 fraction: {service.o2_fraction}\n"
                f"Pressure max psia: {service.total_pressure_max_psia}\n"
                f"Disposition trigger: {snapshot.decision.final_disposition.value}\n"
            ),
        ),
        OcaExportArtifact(
            artifact_type="reviewer_summary",
            filename=f"{case_id}_reviewer_summary.txt",
            content_type="text/plain",
            generated_text="\n".join([snapshot.decision.summary_rationale, *snapshot.decision.unresolved_gaps]),
        ),
    ]
    return OcaExportResponse(case_id=case_id, revision=snapshot.revision, artifacts=artifacts)


def _build_snapshot(case_id: str, request: CreateOcaCaseRequest, revision: int) -> AssessmentSnapshot:
    resolved_materials = [_resolve_material(material) for material in request.materials]
    service_context = _normalize_service_context(request.service_context)
    normalized = NormalizedInput(
        service_context=service_context,
        materials=resolved_materials,
        components=request.components,
        ignition_context=request.ignition_context,
    )
    blocked_states, blocked_trace = _build_blocked_states(normalized)
    requirements, requirement_trace = _build_requirements(normalized, blocked_states)
    precheck_warnings = _build_precheck_warnings(normalized, requirements)
    evidence, evidence_trace = _build_evidence(normalized)
    mechanisms, mechanism_trace = _build_mechanisms(normalized, evidence)
    decision, decision_trace = _build_decision(
        case_id=case_id,
        normalized=normalized,
        blocked_states=blocked_states,
        requirements=requirements,
        evidence=evidence,
        mechanisms=mechanisms,
    )
    created_at = datetime.utcnow()
    return AssessmentSnapshot(
        case_id=case_id,
        revision=revision,
        created_at=created_at,
        normalized_input=normalized,
        blocked_states=blocked_states,
        precheck_warnings=precheck_warnings,
        requirements=requirements,
        evidence=evidence,
        mechanisms=mechanisms,
        decision=decision,
        decision_lineage=[*blocked_trace, *requirement_trace, *evidence_trace, *mechanism_trace, *decision_trace],
        revisions=[OcaRevision(revision=revision, created_at=created_at, note="Initial intake confirmation")],
    )


def _normalize_service_context(context):
    normalized = context.model_copy(deep=True)
    if (
        normalized.oxygen_partial_pressure_psia is None
        and normalized.o2_fraction is not None
        and normalized.total_pressure_max_psia is not None
    ):
        normalized.oxygen_partial_pressure_psia = round(
            normalized.o2_fraction * normalized.total_pressure_max_psia,
            2,
        )
    return normalized


def _resolve_material(material) -> ResolvedMaterial:
    record = get_material_for_o2(material.material_name)
    confidence = record.confidence
    if record.data_source == "heuristic_fallback" and record.family.value != "unknown":
        confidence = max(confidence, 0.8)
    return ResolvedMaterial(
        material_name=material.material_name,
        canonical_name=record.designation or material.material_name,
        family=record.family.value,
        spec=material.spec,
        grade=material.grade,
        temper=material.temper,
        product_form=material.product_form,
        coating=material.coating,
        surface_condition=material.surface_condition,
        role_in_component=material.role_in_component,
        identity_confidence=round(confidence, 2),
        synonym_list=[material.material_name] if record.designation != material.material_name else [],
        rating_flam=record.rating_flam,
        auto_ignition_temp_c=record.auto_ignition_temp_c,
        o2_test_count=record.o2_test_count,
        max_tested_pressure_psia=record.max_tested_pressure_psi,
        data_source=record.data_source,
        provenance_tier=record.provenance_tier,
    )


def _build_blocked_states(normalized: NormalizedInput) -> tuple[list[BlockedState], list[RuleTraceEvent]]:
    blocked: list[BlockedState] = []
    trace: list[RuleTraceEvent] = []
    unresolved_materials = [
        material.material_name
        for material in normalized.materials
        if material.identity_confidence < IDENTITY_THRESHOLD or material.family == "unknown"
    ]
    if unresolved_materials:
        blocked.append(
            BlockedState(
                code=BlockedStateCode.MATERIAL_IDENTITY_UNRESOLVED,
                detail=f"Low-confidence identity resolution for: {', '.join(unresolved_materials)}.",
                resolution_hint="Confirm canonical material name, spec, grade, and temper before final disposition.",
                severity="amber",
            )
        )
        trace.append(
            RuleTraceEvent(
                stage="blocked_state",
                rule_id="material_identity",
                tier=OcaTier.TIER_C,
                outcome="active",
                detail="Material identity confidence fell below threshold.",
            )
        )

    service = normalized.service_context
    missing_service = []
    if service.o2_fraction is None:
        missing_service.append("O2 fraction")
    if service.total_pressure_max_psia is None:
        missing_service.append("pressure")
    if service.phase is None:
        missing_service.append("phase")
    if service.temp_min_c is None and service.temp_max_c is None:
        missing_service.append("temperature")
    if missing_service:
        blocked.append(
            BlockedState(
                code=BlockedStateCode.SERVICE_ENVELOPE_INCOMPLETE,
                detail=f"Missing critical service context: {', '.join(missing_service)}.",
                resolution_hint="Populate worst-case oxygen fraction, pressure, phase, and temperature before mechanism assessment.",
                severity="red",
            )
        )
        trace.append(
            RuleTraceEvent(
                stage="blocked_state",
                rule_id="service_envelope",
                tier=OcaTier.TIER_B,
                outcome="active",
                detail="Worst-case operating conditions were incomplete.",
            )
        )

    design_unknown = not normalized.components or any(
        not component.component_class or not component.geometry_class or not component.design_function
        for component in normalized.components
    )
    if design_unknown:
        blocked.append(
            BlockedState(
                code=BlockedStateCode.DESIGN_FUNCTION_UNKNOWN,
                detail="Component class, geometry, or design function is incomplete for mechanism evaluation.",
                resolution_hint="Provide component class, geometry class, and design function for each assessed part.",
                severity="amber",
            )
        )
        trace.append(
            RuleTraceEvent(
                stage="blocked_state",
                rule_id="design_function",
                tier=OcaTier.TIER_B,
                outcome="active",
                detail="Component configuration was not fully defined.",
            )
        )

    return blocked, trace


def _build_precheck_warnings(
    normalized: NormalizedInput,
    requirements: list[TriggeredRequirement],
) -> list[PrecheckWarning]:
    warnings: list[PrecheckWarning] = []
    if normalized.service_context.cleanliness_verified is None:
        warnings.append(
            PrecheckWarning(
                code="cleanliness_unknown",
                message="Cleanliness state not confirmed. Particle-impact assessment will remain conservative.",
            )
        )
    if normalized.service_context.velocity_m_s is None:
        warnings.append(
            PrecheckWarning(
                code="velocity_missing",
                message="Velocity not provided. Particle impact and flow-friction checks may be indeterminate.",
            )
        )
    if any(
        requirement.requirement_id == "MPR_53" and requirement.status == RequirementStatus.ACTION_REQUIRED
        for requirement in requirements
    ):
        warnings.append(
            PrecheckWarning(
                code="acceptance_test_branch",
                message="Acceptance-test branch is active. Confirm MPR 53 exemption fields before closure.",
            )
        )
    return warnings


def _build_requirements(
    normalized: NormalizedInput,
    blocked_states: list[BlockedState],
) -> tuple[list[TriggeredRequirement], list[RuleTraceEvent]]:
    bindings = {item["requirement_id"]: item for item in get_requirement_binding()}
    trace: list[RuleTraceEvent] = []
    blocked_codes = {item.code for item in blocked_states}
    service = normalized.service_context
    pressure_max = service.total_pressure_max_psia or 0.0
    o2_partial = service.oxygen_partial_pressure_psia or 0.0
    materials = normalized.materials
    flammable = any(_material_requires_full_oca(material, normalized.components) for material in materials)
    titanium_present = any(material.family == "titanium" for material in materials)
    non_exempt_component = any(not _is_mpr53_exempt(component) for component in normalized.components) if normalized.components else True

    requirement_results: list[TriggeredRequirement] = []
    for requirement_id in ("MPR_51", "MPR_52", "MPR_53", "MPR_67"):
        binding = bindings[requirement_id]
        triggered = False
        status = RequirementStatus.NOT_TRIGGERED
        reasoning = "Not triggered by current service context."
        evidence_links: list[str] = []

        if requirement_id == "MPR_51":
            triggered = service.oxidizer_type in {
                OxidizerType.LOX,
                OxidizerType.GOX,
                OxidizerType.ENRICHED_AIR,
                OxidizerType.COMPRESSED_AIR,
            }
            if triggered:
                status = (
                    RequirementStatus.SATISFIED
                    if BlockedStateCode.SERVICE_ENVELOPE_INCOMPLETE not in blocked_codes
                    else RequirementStatus.ACTION_REQUIRED
                )
                reasoning = (
                    "Oxygen-service context requires formal oxygen compatibility evaluation."
                    if status == RequirementStatus.SATISFIED
                    else "Oxygen-service context is in scope, but worst-case service envelope is incomplete."
                )
                evidence_links = [binding["citation"]]
        elif requirement_id == "MPR_52":
            triggered = flammable
            if triggered:
                status = RequirementStatus.ACTION_REQUIRED
                reasoning = "At least one material/configuration is flammable or unknown, so an OCA and MUA branch are required."
                evidence_links = [binding["citation"]]
        elif requirement_id == "MPR_53":
            triggered = (
                service.oxidizer_type in {OxidizerType.GOX, OxidizerType.ENRICHED_AIR}
                and pressure_max > 265.0
                and non_exempt_component
            )
            if triggered:
                status = RequirementStatus.ACTION_REQUIRED
                reasoning = "GOX/enriched-air hardware exceeds 265 psia and no MPR 53 exemption fully covers the component set."
                evidence_links = [binding["citation"]]
        elif requirement_id == "MPR_67":
            triggered = titanium_present and (
                service.oxidizer_type in {OxidizerType.LOX, OxidizerType.GOX}
                or o2_partial > 5.0
            )
            if triggered:
                status = RequirementStatus.PROHIBITED
                reasoning = "Titanium alloy usage is prohibited in this oxygen-service envelope by governing requirement."
                evidence_links = [binding["citation"]]

        requirement_results.append(
            TriggeredRequirement(
                requirement_id=requirement_id,
                title=binding["title"],
                citation=binding["citation"],
                tier=OcaTier(binding["tier"]),
                triggered=triggered,
                status=status,
                reasoning=reasoning,
                evidence_links=evidence_links,
                downstream_actions=binding.get("downstream_workflow_actions", []),
            )
        )
        trace.append(
            RuleTraceEvent(
                stage="requirements",
                rule_id=requirement_id,
                tier=OcaTier(binding["tier"]),
                outcome=status.value,
                detail=reasoning,
            )
        )

    return requirement_results, trace


def _material_requires_full_oca(material: ResolvedMaterial, components: list[ComponentInput]) -> bool:
    geometry_sensitive = any(
        (component.geometry_class or "").lower() in {"thin-wall", "thin_wall", "mesh", "porous", "sintered", "seal"}
        for component in components
    )
    if material.family in {"titanium", "magnesium", "polymer_organic", "composite", "unknown"}:
        return True
    if material.rating_flam and material.rating_flam.upper() in {"C", "D", "X", "U"}:
        return True
    if geometry_sensitive and material.family in {"aluminum", "austenitic_steel"}:
        return True
    return material.rating_flam is None and material.o2_test_count == 0


def _is_mpr53_exempt(component: ComponentInput) -> bool:
    return any(
        (
            component.is_rigid_metallic_tubing,
            component.is_metallic_flex_hose,
            component.is_all_metal_seal,
            component.is_metallic_pressure_vessel,
        )
    )


def _build_evidence(normalized: NormalizedInput) -> tuple[list[EvidenceCard], list[RuleTraceEvent]]:
    trace: list[RuleTraceEvent] = []
    evidence_cards: list[EvidenceCard] = []
    material_reference = {item["family"]: item for item in get_material_reference()}
    test_mapping = get_test_mapping()
    geometry_values = {(component.geometry_class or "").lower() for component in normalized.components}

    for index, material in enumerate(normalized.materials, start=1):
        family_rule = get_o2_family_rule(get_material_for_o2(material.canonical_name).family)
        applicability = _score_evidence(
            exact_material_match=material.identity_confidence >= 0.85,
            spec_match=bool(material.spec),
            form_match=bool(material.product_form),
            geometry_match=bool(geometry_values),
            pressure_match=_pressure_match(normalized.service_context.total_pressure_max_psia, material.max_tested_pressure_psia),
            o2_fraction_match=normalized.service_context.o2_fraction is not None,
            phase_match=normalized.service_context.phase is not None,
            temperature_match=normalized.service_context.temp_min_c is not None or normalized.service_context.temp_max_c is not None,
            coating_match=not material.coating,
            method_relevance=True,
            identity_confidence=material.identity_confidence,
        )
        family_gaps = []
        if not applicability.pressure_match:
            family_gaps.append("Pressure-specific qualification was not confirmed for this evidence item.")
        if not applicability.geometry_match:
            family_gaps.append("Configuration geometry was not specific enough to score direct applicability.")
        evidence_cards.append(
            EvidenceCard(
                evidence_id=f"evidence-family-{index}",
                material_name=material.canonical_name,
                source_id=family_rule["bok_ref"],
                title="Family-level oxygen compatibility rule",
                citation=family_rule["bok_ref"],
                tier=OcaTier.TIER_C,
                summary=family_rule["reason"],
                test_method="family_classification",
                specimen_description=material.canonical_name,
                test_conditions="Rule-based family screening",
                result=family_rule["classification"],
                applicability=applicability,
                gaps=family_gaps,
            )
        )
        trace.append(
            RuleTraceEvent(
                stage="evidence",
                rule_id=f"family_rule_{index}",
                tier=OcaTier.TIER_C,
                outcome=applicability.applicability_class.value,
                detail=f"Family evidence scored for {material.canonical_name}.",
            )
        )

        reference = material_reference.get(material.family, {})
        test_method = _map_test_method(material.family, normalized)
        test_result = material.rating_flam or reference.get("compatibility_class", "unknown")
        map_applicability = _score_evidence(
            exact_material_match=material.identity_confidence >= 0.90,
            spec_match=bool(material.spec),
            form_match=bool(material.product_form),
            geometry_match=bool(geometry_values),
            pressure_match=_pressure_match(normalized.service_context.total_pressure_max_psia, material.max_tested_pressure_psia),
            o2_fraction_match=normalized.service_context.o2_fraction is not None,
            phase_match=normalized.service_context.phase is not None,
            temperature_match=normalized.service_context.temp_min_c is not None or normalized.service_context.temp_max_c is not None,
            coating_match=True,
            method_relevance=bool(test_method),
            identity_confidence=material.identity_confidence,
        )
        evidence_cards.append(
            EvidenceCard(
                evidence_id=f"evidence-maptis-{index}",
                material_name=material.canonical_name,
                source_id="MAPTIS / NASA-STD-6001B",
                title="Test-data alignment",
                citation=f"{test_method} / {test_mapping.get(test_method, {}).get('citation', 'NASA-STD-6001B')}",
                tier=OcaTier.TIER_C,
                summary=(
                    f"Resolved identity confidence {material.identity_confidence:.2f}; "
                    f"flammability rating {test_result}; O2 test count {material.o2_test_count}."
                ),
                test_method=test_method,
                specimen_description=material.canonical_name,
                test_conditions=(
                    f"Service envelope {normalized.service_context.phase or 'unknown'} "
                    f"at {normalized.service_context.total_pressure_max_psia or 'unknown'} psia."
                ),
                result=str(test_result),
                applicability=map_applicability,
                gaps=_build_evidence_gaps(material, map_applicability),
            )
        )
        trace.append(
            RuleTraceEvent(
                stage="evidence",
                rule_id=f"test_mapping_{index}",
                tier=OcaTier.TIER_C,
                outcome=map_applicability.applicability_class.value,
                detail=f"Test-evidence applicability scored for {material.canonical_name}.",
            )
        )

    return evidence_cards, trace


def _build_evidence_gaps(
    material: ResolvedMaterial,
    applicability: EvidenceApplicabilityScore,
) -> list[str]:
    gaps: list[str] = []
    if material.o2_test_count == 0:
        gaps.append("No direct MAPTIS oxygen test record was linked to this material.")
    if not applicability.pressure_match:
        gaps.append("Pressure match is weak or absent.")
    if not applicability.exact_material_match:
        gaps.append("Material identity is not locked strongly enough for direct applicability.")
    return gaps


def _pressure_match(service_pressure: Optional[float], tested_pressure: Optional[float]) -> bool:
    if service_pressure is None or tested_pressure is None or tested_pressure <= 0:
        return False
    lower = tested_pressure * 0.8
    upper = tested_pressure * 1.2
    return lower <= service_pressure <= upper


def _score_evidence(
    *,
    exact_material_match: bool,
    spec_match: bool,
    form_match: bool,
    geometry_match: bool,
    pressure_match: bool,
    o2_fraction_match: bool,
    phase_match: bool,
    temperature_match: bool,
    coating_match: bool,
    method_relevance: bool,
    identity_confidence: float,
) -> EvidenceApplicabilityScore:
    weights = {
        "exact_material_match": 0.22,
        "spec_match": 0.08,
        "form_match": 0.07,
        "geometry_match": 0.14,
        "pressure_match": 0.14,
        "o2_fraction_match": 0.10,
        "phase_match": 0.08,
        "temperature_match": 0.07,
        "coating_match": 0.04,
        "method_relevance": 0.06,
    }
    raw_score = (
        weights["exact_material_match"] * float(exact_material_match)
        + weights["spec_match"] * float(spec_match)
        + weights["form_match"] * float(form_match)
        + weights["geometry_match"] * float(geometry_match)
        + weights["pressure_match"] * float(pressure_match)
        + weights["o2_fraction_match"] * float(o2_fraction_match)
        + weights["phase_match"] * float(phase_match)
        + weights["temperature_match"] * float(temperature_match)
        + weights["coating_match"] * float(coating_match)
        + weights["method_relevance"] * float(method_relevance)
    )
    aggregate_score = round(raw_score * identity_confidence, 3)
    if aggregate_score >= DIRECT_EVIDENCE_THRESHOLD:
        applicability_class = EvidenceApplicabilityClass.DIRECT
    elif aggregate_score >= PARTIAL_EVIDENCE_THRESHOLD:
        applicability_class = EvidenceApplicabilityClass.PARTIAL
    elif aggregate_score >= WEAK_EVIDENCE_THRESHOLD:
        applicability_class = EvidenceApplicabilityClass.WEAK_ANALOG
    else:
        applicability_class = EvidenceApplicabilityClass.NOT_APPLICABLE
    return EvidenceApplicabilityScore(
        exact_material_match=exact_material_match,
        spec_match=spec_match,
        form_match=form_match,
        geometry_match=geometry_match,
        pressure_match=pressure_match,
        o2_fraction_match=o2_fraction_match,
        phase_match=phase_match,
        temperature_match=temperature_match,
        coating_match=coating_match,
        method_relevance=method_relevance,
        aggregate_score=aggregate_score,
        applicability_class=applicability_class,
    )


def _is_material_flammable(normalized: NormalizedInput) -> bool:
    """Return True if any assessed material is flammable per TM Table 2.

    Flammable = rating C, D, X, U, unknown, or None (no data).
    Nonflammable = rating A or B only.
    """
    for mat in normalized.materials:
        rating = (mat.rating_flam or "").upper()
        if rating not in ("A", "B"):
            return True
    return False


def _rate_mechanism_table2(
    all_elements: list[str],
    observed: list[str],
    missing: list[str],
    false_count: int,
    material_flammable: bool,
) -> tuple[int, CredibleStatus]:
    """Apply TM-2007-213740 Table 2 rating logic (0-4 scale).

    0 = Not Possible: not all elements present AND material nonflammable
    1 = Remotely Possible: (all present + nonflammable) OR (not all present + flammable)
    2 = Possible: all present and active + flammable
    3 = Probable: all present + some strongly active + flammable
    4 = Highly Probable: all present + all strongly active + flammable

    "Strongly active" is approximated as: for mechanisms with >=3 elements,
    the element is in the observed list AND the signal was positively confirmed
    (not just defaulted).  For mechanisms with <=2 elements all observed
    elements are treated as strongly active.
    """
    total = len(all_elements)
    all_present = (false_count == 0 and len(missing) == 0)
    some_present = len(observed) > 0

    if not all_present and not material_flammable:
        # 0 — Not Possible
        return 0, CredibleStatus.NOT_CREDIBLE

    if all_present and not material_flammable:
        # 1 — Remotely Possible (all elements but material won't burn)
        return 1, CredibleStatus.INDETERMINATE

    if not all_present and material_flammable:
        # 1 — Remotely Possible (flammable but missing elements)
        if some_present:
            return 1, CredibleStatus.INDETERMINATE
        # Nothing observed and some explicitly false — still 1 if there are
        # missing (unknown) elements since we can't rule it out
        if missing:
            return 1, CredibleStatus.INDETERMINATE
        # All explicitly false but flammable — 0 (impossible mechanism)
        return 0, CredibleStatus.NOT_CREDIBLE

    # All present AND flammable — rating is 2, 3, or 4
    # Use proportion of strongly-active elements to differentiate
    strongly_active_count = len(observed)  # all observed are confirmed active
    if total <= 1:
        # Single-element mechanism: if present+flammable => Probable
        return 3, CredibleStatus.CREDIBLE

    ratio = strongly_active_count / total if total > 0 else 0
    if ratio >= 1.0:
        # 4 — Highly Probable: all elements strongly active
        return 4, CredibleStatus.CREDIBLE
    elif ratio >= 0.5:
        # 3 — Probable: some strongly active
        return 3, CredibleStatus.CREDIBLE
    else:
        # 2 — Possible: all present, few strongly active
        return 2, CredibleStatus.CREDIBLE


def _build_mechanisms(
    normalized: NormalizedInput,
    evidence_cards: list[EvidenceCard],
) -> tuple[list[MechanismAssessment], list[RuleTraceEvent]]:
    mechanisms: list[MechanismAssessment] = []
    trace: list[RuleTraceEvent] = []
    evidence_ids = [item.evidence_id for item in evidence_cards]
    material_flammable = _is_material_flammable(normalized)
    for definition in get_ignition_mechanisms():
        observed: list[str] = []
        missing: list[str] = []
        false_count = 0
        all_labels = [element["label"] for element in definition["required_elements"]]
        for element in definition["required_elements"]:
            value = _evaluate_signal(element["key"], normalized)
            if value is True:
                observed.append(element["label"])
            elif value is None:
                missing.append(element["label"])
            else:
                false_count += 1
        rating, credible = _rate_mechanism_table2(
            all_elements=all_labels,
            observed=observed,
            missing=missing,
            false_count=false_count,
            material_flammable=material_flammable,
        )
        gaps = ["Additional context needed for full rating."] if credible == CredibleStatus.INDETERMINATE else []
        trace_obj = MechanismTrace(
            mechanism_name=definition["mechanism_name"],
            source_ref=definition["source_ref"],
            required_elements=[element["label"] for element in definition["required_elements"]],
            observed_elements=observed,
            missing_elements=missing,
            rating_formula_version=definition["rating_formula_version"],
            rating_result=rating,
        )
        mechanisms.append(
            MechanismAssessment(
                mechanism_name=definition["mechanism_name"],
                credible_status=credible,
                rating=rating,
                source_ref=definition["source_ref"],
                required_elements=trace_obj.required_elements,
                observed_elements=observed,
                missing_elements=missing,
                linked_evidence_ids=evidence_ids,
                gaps_identified=gaps,
                mechanism_trace=trace_obj,
            )
        )
        trace.append(
            RuleTraceEvent(
                stage="mechanisms",
                rule_id=definition["mechanism_name"].lower().replace(" ", "_"),
                tier=OcaTier.TIER_B,
                outcome=credible.value,
                detail=f"Observed={len(observed)} missing={len(missing)} false={false_count}.",
            )
        )
    return mechanisms, trace


def _check_adiabatic_concern(normalized: NormalizedInput) -> Optional[bool]:
    """Compute adiabatic compression final temperature and compare to AIT.

    Tf = Ti * (Pf / Pi) ^ ((n-1)/n)  where n = 1.4 for O2.

    Pi = ambient (14.696 psia), Ti = ambient temperature (default 293 K).
    Pf = total_pressure_max_psia from service context.

    Returns True if Tf exceeds any nonmetal AIT (rapid pressurization concern),
    or if pressure > 265 psia and no AIT data is available (conservative).
    Returns False if Tf is safely below all AITs.
    Returns None if pressure data is missing.
    """
    service = normalized.service_context
    if service.total_pressure_max_psia is None:
        return None

    pf = service.total_pressure_max_psia
    pi = 14.696  # ambient pressure psia
    if pf <= pi:
        return False

    # Inlet temperature: use provided min temp or default 20 C (293 K)
    ti_c = service.temp_min_c if service.temp_min_c is not None else 20.0
    ti_k = ti_c + 273.15

    gamma = 1.4  # ratio of specific heats for O2
    tf_k = ti_k * (pf / pi) ** ((gamma - 1.0) / gamma)
    tf_c = tf_k - 273.15

    # Find minimum AIT among all nonmetal materials
    nonmetal_aits: list[float] = []
    for mat in normalized.materials:
        if mat.auto_ignition_temp_c is not None:
            nonmetal_aits.append(mat.auto_ignition_temp_c)

    if nonmetal_aits:
        min_ait = min(nonmetal_aits)
        return tf_c > min_ait

    # No AIT data available — fall back to conservative pressure threshold
    return pf > 265.0


def _evaluate_signal(key: str, normalized: NormalizedInput) -> Optional[bool]:
    service = normalized.service_context
    components = normalized.components
    materials = normalized.materials
    ignition = normalized.ignition_context
    contains_nonmetal = any((component.seal_type or "").lower() not in {"", "metal", "all_metal"} for component in components)
    contains_reactive_metal = any(material.family in {"aluminum", "titanium", "magnesium"} for material in materials)
    dynamic_contact = any(component.dynamic_contact_flag for component in components)
    geometry_values = {(component.geometry_class or "").lower() for component in components}
    phase_gas = service.phase == ServicePhase.GAS if service.phase is not None else None

    signal_map = {
        "entrainable_particles": (
            ignition.entrainable_particles_present
            if ignition.entrainable_particles_present is not None
            else (False if service.cleanliness_verified else None if service.cleanliness_verified is None else True)
        ),
        "velocity_above_30_m_s": None if service.velocity_m_s is None else service.velocity_m_s > 30.0,
        "impact_geometry_present": None if not components else bool(geometry_values & {"mesh", "porous", "sintered", "filter"}),
        "fast_pressurization": None if ignition.rapid_pressurization_time_ms is None else ignition.rapid_pressurization_time_ms <= 1000.0,
        "nonmetal_near_dead_end": None if ignition.dead_end_configuration is None else ignition.dead_end_configuration and contains_nonmetal,
        "pressure_ratio_concern": _check_adiabatic_concern(normalized),
        "nonmetal_in_flow": ignition.nonmetal_exposed_to_flow if ignition.nonmetal_exposed_to_flow is not None else contains_nonmetal,
        "vibration_or_erosion": ignition.vibration_or_erosion_present,
        "acoustic_cavity": ignition.acoustic_cavity_present,
        "closed_end_exposure": ignition.dead_end_configuration,
        "mechanical_impact_risk": ignition.mechanical_impact_risk,
        "reactive_or_nonmetal_target": contains_nonmetal or contains_reactive_metal,
        "metal_to_metal_contact": dynamic_contact,
        "rapid_motion_or_load": dynamic_contact,
        "fresh_reactive_surface": contains_reactive_metal and dynamic_contact,
        "dry_gas": ignition.dry_gas_environment if ignition.dry_gas_environment is not None else phase_gas,
        "isolated_surface": ignition.isolated_surface_present,
        "power_source": ignition.electrical_power_present,
        "arc_exposure": ignition.electrical_power_present and contains_nonmetal if ignition.electrical_power_present is not None else None,
        "reactive_pair_present": ignition.reactive_chemical_pair_present,
        "porous_or_fine_geometry": ignition.porous_media_present if ignition.porous_media_present is not None else bool(geometry_values & {"porous", "sintered", "mesh"}),
        "poor_heat_dissipation": bool(geometry_values & {"porous", "sintered", "thin-wall", "thin_wall"}) if components else None,
        "external_heat_or_flame": ignition.open_flame_or_hot_work_present,
        # Partial mappings for the TM "Other" category mechanisms. These use
        # existing case inputs where a defensible screening proxy already exists.
        "open_flame_possible": ignition.open_flame_or_hot_work_present,
        "welding_or_cutting": ignition.open_flame_or_hot_work_present,
        "residual_oxygen": None if service.o2_fraction is None else service.o2_fraction > 0.23,
        "fragment_impact_credible": ignition.mechanical_impact_risk,
    }
    return signal_map.get(key)


def _worst_flammability_reaction_effect(materials: list[ResolvedMaterial]) -> str:
    """Return worst-case reaction effect letter from resolved materials."""
    effect = "A"
    for mat in materials:
        rating = (mat.rating_flam or "U").upper()
        if rating in ("D", "X"):
            return "D"
        if rating == "C" and effect in ("A", "B"):
            effect = "C"
        elif rating in ("U", "UNKNOWN") and effect == "A":
            effect = "B"
    return effect


def _build_decision(
    *,
    case_id: str,
    normalized: NormalizedInput,
    blocked_states: list[BlockedState],
    requirements: list[TriggeredRequirement],
    evidence: list[EvidenceCard],
    mechanisms: list[MechanismAssessment],
) -> tuple[OcaDecisionPacket, list[RuleTraceEvent]]:
    trace: list[RuleTraceEvent] = []
    blocked = bool(blocked_states)
    direct_evidence = any(item.applicability.applicability_class == EvidenceApplicabilityClass.DIRECT for item in evidence)
    partial_evidence = any(item.applicability.applicability_class == EvidenceApplicabilityClass.PARTIAL for item in evidence)
    indeterminate_mechanisms = [item for item in mechanisms if item.credible_status == CredibleStatus.INDETERMINATE]
    high_risk_mechanisms = [item for item in mechanisms if item.credible_status == CredibleStatus.CREDIBLE and item.rating >= 3]
    prohibited_req = next((item for item in requirements if item.status == RequirementStatus.PROHIBITED), None)
    mpr53_req = next((item for item in requirements if item.requirement_id == "MPR_53"), None)
    mpr52_req = next((item for item in requirements if item.requirement_id == "MPR_52"), None)

    unresolved_gaps = [state.detail for state in blocked_states]
    unresolved_gaps.extend(gap for card in evidence for gap in card.gaps if gap not in unresolved_gaps)
    for mechanism in indeterminate_mechanisms:
        unresolved_gaps.append(f"{mechanism.mechanism_name}: additional context needed.")

    actions: list[DecisionAction] = []
    if prohibited_req is not None:
        disposition = FinalDisposition.PROHIBITED
        governing_prohibition = prohibited_req.citation
        summary = "A Tier A governing prohibition was triggered. The configuration is not acceptable as entered."
        actions.append(
            DecisionAction(
                action_id="replace_prohibited_material",
                label="Replace prohibited material",
                rationale="Titanium use in this oxygen-service envelope violates MPR 67.",
            )
        )
    elif blocked:
        disposition = FinalDisposition.INSUFFICIENT_EVIDENCE
        governing_prohibition = None
        summary = "Assessment is partial because required service or configuration context is incomplete."
        actions.extend(
            DecisionAction(
                action_id=f"resolve_{state.code.value.lower()}",
                label=f"Resolve {state.code.value.replace('_', ' ').title()}",
                rationale=state.resolution_hint,
            )
            for state in blocked_states
        )
    elif mpr53_req and mpr53_req.status == RequirementStatus.ACTION_REQUIRED:
        disposition = FinalDisposition.REQUIRES_ACCEPTANCE_TEST
        governing_prohibition = None
        summary = "The hardware exceeds the MPR 53 acceptance-test threshold and is not exempt."
        actions.append(
            DecisionAction(
                action_id="route_acceptance_test",
                label="Open MPR 53 acceptance test branch",
                rationale="Minimum 10 cycles from ambient to MDP within 100 ms are required before closure.",
            )
        )
    elif mpr52_req and mpr52_req.status == RequirementStatus.ACTION_REQUIRED:
        disposition = FinalDisposition.REQUIRES_MUA if (direct_evidence or partial_evidence) else FinalDisposition.REQUIRES_SUPPLEMENTAL_TESTING
        governing_prohibition = None
        summary = "Flammable or unknown material behavior requires formal OCA rationale and MUA routing."
        actions.append(
            DecisionAction(
                action_id="generate_mua_seed",
                label="Generate MUA seed",
                rationale="MPR 52 routes the case to MUA once the OCA rationale is documented.",
            )
        )
    elif not direct_evidence and not partial_evidence:
        disposition = FinalDisposition.REQUIRES_SUPPLEMENTAL_TESTING
        governing_prohibition = None
        summary = "No directly applicable evidence was found for the assessed service envelope."
        actions.append(
            DecisionAction(
                action_id="request_supplemental_testing",
                label="Request supplemental testing",
                rationale="Evidence applicability remained weak or not applicable across the assessed envelope.",
            )
        )
    elif high_risk_mechanisms or indeterminate_mechanisms:
        disposition = FinalDisposition.COMPATIBLE_WITH_CONTROLS
        governing_prohibition = None
        summary = "The configuration may be supportable, but mechanism control actions are still needed before signoff."
        for control in get_hazard_control_library()[:3]:
            actions.append(
                DecisionAction(
                    action_id=control["control_id"],
                    label=control["title"],
                    rationale=control["evidence_basis"],
                )
            )
    else:
        disposition = FinalDisposition.COMPATIBLE_AS_CONFIGURED
        governing_prohibition = None
        summary = "Tier A trigger checks passed and available evidence/mechanism review support the entered configuration."

    mean_identity = sum(item.identity_confidence for item in normalized.materials) / len(normalized.materials)
    overall_confidence = "high" if direct_evidence and mean_identity >= 0.9 and not indeterminate_mechanisms else "medium"
    if blocked or not direct_evidence:
        overall_confidence = "low"

    # Compute kindling chain and history_of_use per TM section 4.6
    active_mechanisms = [item for item in mechanisms if item.credible_status != CredibleStatus.NOT_CREDIBLE]
    worst_flam = _worst_flammability_reaction_effect(normalized.materials)
    kindling_chain_present = bool(active_mechanisms) and worst_flam != "A"
    # Per TM section 4.6:
    #   (+) = successful history in similar or more severe conditions
    #   (-) = negative history (incident/failure)
    #   (?) = unknown
    # We derive from evidence: if direct evidence exists with good rating => (+),
    # if prohibited => (-), otherwise (?)
    if prohibited_req is not None:
        history_of_use = "(-)"
    elif direct_evidence and not high_risk_mechanisms:
        history_of_use = "(+)"
    else:
        history_of_use = "(?)"

    # Compute provenance warning from material data tiers
    provenance_tiers = [mat.provenance_tier for mat in normalized.materials]
    tier_priority = {"governing_standard": 0, "published_literature": 1, "estimated": 2, "not_available": 3}
    worst_prov = max(provenance_tiers, key=lambda t: tier_priority.get(t, 3)) if provenance_tiers else "not_available"
    provenance_warning = None
    if worst_prov == "estimated":
        provenance_warning = (
            "This assessment used estimated values derived from published literature, "
            "not facility-specific test data. Material flammability ratings and ignition "
            "thresholds may not reflect specimen-level results. Connect your MAPTIS instance "
            "for test-report-grade data."
        )
    elif worst_prov == "published_literature":
        provenance_warning = (
            "This assessment used published literature values (ASTM Manual 36, manufacturer "
            "data sheets), not specimen-specific MAPTIS test reports. For formal OCA submittals, "
            "integrate with MAPTIS for specimen-level flammability and ignition data."
        )
    elif worst_prov == "not_available":
        provenance_warning = (
            "Key material properties (test counts, pressure limits, ignition temperatures) are "
            "not available in the current reference pack. This screening is based on family-level "
            "classification only. Connect your MAPTIS instance for complete material records."
        )

    packet = OcaDecisionPacket(
        case_id=case_id,
        final_disposition=disposition,
        triggered_requirements=requirements,
        blocked_states=blocked_states,
        unresolved_gaps=unresolved_gaps,
        kindling_chain_present=kindling_chain_present,
        reaction_effect=worst_flam,
        history_of_use=history_of_use,
        acceptance_test_required=bool(mpr53_req and mpr53_req.status == RequirementStatus.ACTION_REQUIRED),
        reviewer_required=blocked
        or disposition
        in {
            FinalDisposition.PROHIBITED,
            FinalDisposition.REQUIRES_ACCEPTANCE_TEST,
            FinalDisposition.REQUIRES_MUA,
            FinalDisposition.REQUIRES_SUPPLEMENTAL_TESTING,
        }
        or bool(indeterminate_mechanisms),
        overall_confidence=overall_confidence,
        authority_level=OcaTier.TIER_A,
        governing_prohibition=governing_prohibition,
        summary_rationale=summary,
        actions=actions,
        provenance_warning=provenance_warning,
        mua_seed={
            "materials": [item.canonical_name for item in normalized.materials],
            "service_conditions": normalized.service_context.model_dump(),
            "mechanism_summary": [
                {
                    "mechanism_name": item.mechanism_name,
                    "credible_status": item.credible_status.value,
                    "rating": item.rating,
                }
                for item in mechanisms
                if item.credible_status != CredibleStatus.NOT_CREDIBLE
            ],
            "assumptions_needing_signoff": unresolved_gaps,
        },
    )
    trace.append(
        RuleTraceEvent(
            stage="decision",
            rule_id="final_disposition",
            tier=OcaTier.TIER_A,
            outcome=packet.final_disposition.value,
            detail=packet.summary_rationale,
        )
    )
    return packet, trace


def _map_test_method(material_family: str, normalized: NormalizedInput) -> str:
    if material_family in {"titanium", "magnesium", "aluminum"}:
        return "Test 17"
    if normalized.service_context.phase == ServicePhase.GAS:
        return "ASTM G74"
    return "Test 1"


class OCAEngine:
    """Legacy compatibility facade for Phase 2 system-builder imports."""


_LEGACY_ENGINE = OCAEngine()


def get_oca_engine() -> OCAEngine:
    return _LEGACY_ENGINE


def adiabatic_compression_temperature(
    initial_temp_c: Optional[float],
    pressure_ratio: float,
) -> Optional[float]:
    if initial_temp_c is None or pressure_ratio <= 0:
        return None
    gamma = 1.4
    temp_k = initial_temp_c + 273.15
    compressed_k = temp_k * (pressure_ratio ** ((gamma - 1.0) / gamma))
    return round(compressed_k - 273.15, 2)


def _legacy_family(material: MaterialInstance) -> str:
    if material.family:
        return material.family
    if material.is_titanium:
        return "titanium"
    if material.is_nonmetal:
        return "polymer_organic"
    return "unknown"


def _material_instance_to_resolved(material: MaterialInstance) -> ResolvedMaterial:
    canonical_name = material.canonical_name or material.material_name
    return ResolvedMaterial(
        material_name=material.material_name,
        canonical_name=canonical_name,
        family=_legacy_family(material),
        spec=material.spec,
        grade=material.grade,
        temper=material.temper,
        product_form=material.product_form,
        coating=material.coating,
        surface_condition=material.surface_condition,
        role_in_component=material.role_in_component,
        identity_confidence=material.identity_confidence,
        synonym_list=[],
        rating_flam=material.flammability_rating.value,
        o2_test_count=material.o2_test_count,
        max_tested_pressure_psia=material.max_tested_pressure_psia,
        data_source=material.data_source,
    )


def _build_legacy_normalized_input(
    context: OxygenServiceContext,
    component: ComponentInfo,
    materials: list[MaterialInstance],
    ignition_context: Optional[IgnitionContextInput] = None,
) -> NormalizedInput:
    return NormalizedInput(
        service_context=context,
        materials=[_material_instance_to_resolved(item) for item in materials],
        components=[component],
        ignition_context=ignition_context or IgnitionContextInput(),
    )


def assess_ignition_mechanisms(
    context: OxygenServiceContext,
    component: ComponentInfo,
    materials: list[MaterialInstance],
) -> list[MechanismAssessment]:
    normalized = _build_legacy_normalized_input(context, component, materials)
    mechanisms, _ = _build_mechanisms(normalized, [])
    for mechanism in mechanisms:
        if not mechanism.reviewer_comments and mechanism.gaps_identified:
            mechanism.reviewer_comments = list(mechanism.gaps_identified)
    return mechanisms


def evaluate_requirement_triggers(
    context: OxygenServiceContext,
    component: ComponentInfo,
    materials: list[MaterialInstance],
) -> list[TriggeredRequirement]:
    normalized = _build_legacy_normalized_input(context, component, materials)
    requirements, _ = _build_requirements(normalized, [])
    return requirements


def retrieve_evidence(
    materials: list[MaterialInstance],
    context: OxygenServiceContext,
) -> tuple[list[EvidenceCard], list[str]]:
    normalized = _build_legacy_normalized_input(
        context,
        ComponentInfo(design_function="assessment"),
        materials,
    )
    evidence, _ = _build_evidence(normalized)
    gaps = sorted({gap for card in evidence for gap in card.gaps})
    return evidence, gaps


def _worst_reaction_effect(materials: list[MaterialInstance]) -> ReactionEffect:
    effect = ReactionEffect.A
    for material in materials:
        rating = material.flammability_rating.value
        if rating in {"D", "X"}:
            return ReactionEffect.D
        if rating == "C":
            effect = ReactionEffect.C
        elif rating in {"U", "unknown"} and effect == ReactionEffect.A:
            effect = ReactionEffect.B
    return effect


def evaluate_kindling_chain(
    materials: list[MaterialInstance],
    component: ComponentInfo,
    mechanisms: list[MechanismAssessment],
) -> KindlingChainResult:
    del component
    active_mechanisms = [item for item in mechanisms if item.credible_status != CredibleStatus.NOT_CREDIBLE]
    effect = _worst_reaction_effect(materials)
    return KindlingChainResult(
        kindling_chain_present=bool(active_mechanisms) and effect != ReactionEffect.A,
        reaction_effect=effect,
        history_of_use="screening_only",
        propagation_notes=[],
    )


def _hazard_control_recommendation(ignition_hazard: str) -> str:
    recommendation_map = {
        "particle_impact": "Reduce particle source strength with filtration, cleanliness, or lower velocity.",
        "rapid_pressurization": "Slow valve opening and eliminate trapped dead-end volumes.",
        "flow_friction": "Reduce flow velocity and remove exposed nonmetal surfaces from the stream.",
        "resonance": "Break up acoustic cavities or move downstream hardware away from sonic sources.",
        "mechanical_impact": "Reduce motion, chatter, or impact loading at contact interfaces.",
        "galling_friction": "Use dissimilar gall-resistant materials or lubricious surface treatments.",
        "fresh_metal_exposure": "Limit metal-on-metal damage and avoid reactive freshly exposed surfaces.",
        "static_discharge": "Control charge accumulation and confirm grounding/bonding where applicable.",
        "electrical_arc": "Isolate energized hardware from oxygen-wetted regions or remove ignition sources.",
        "chemical_reaction": "Remove incompatible material pairings or isolate the reactive interface.",
        "thermal_runaway": "Reduce surface-area-to-volume ratio or add thermal margin and heat sinking.",
        "kindling_chain": "Break the propagation path with nonflammable materials or isolation barriers.",
    }
    return recommendation_map.get(
        ignition_hazard,
        "Apply configuration-specific controls and document closure evidence.",
    )


def generate_hazard_controls(
    component: ComponentInfo,
    mechanisms: list[MechanismAssessment],
    kindling: KindlingChainResult,
) -> list[HazardControlEntry]:
    component_ref = component.component_id or component.component_class or "component"
    controls: list[HazardControlEntry] = []
    seen_hazards: set[str] = set()

    for mechanism in mechanisms:
        if mechanism.credible_status == CredibleStatus.NOT_CREDIBLE:
            continue
        hazard = mechanism.mechanism_name.value
        if hazard in seen_hazards:
            continue
        seen_hazards.add(hazard)
        controls.append(
            HazardControlEntry(
                component_ref=component_ref,
                ignition_hazard=hazard,
                probability_rating=max(mechanism.rating, 1),
                recommendation=_hazard_control_recommendation(hazard),
                confidence=mechanism.credible_status.value.lower(),
            )
        )

    if kindling.kindling_chain_present and "kindling_chain" not in seen_hazards:
        controls.append(
            HazardControlEntry(
                component_ref=component_ref,
                ignition_hazard="kindling_chain",
                probability_rating=4 if kindling.reaction_effect == ReactionEffect.D else 3,
                recommendation=_hazard_control_recommendation("kindling_chain"),
                confidence="medium",
            )
        )

    return controls


def determine_disposition(
    requirements: list[TriggeredRequirement],
    mechanisms: list[MechanismAssessment],
    kindling: KindlingChainResult,
    hazard_controls: list[HazardControlEntry],
    gaps: list[str],
    blocked_states: list[BlockedState],
) -> FinalDisposition:
    del gaps
    if any(item.status == RequirementStatus.PROHIBITED for item in requirements):
        return FinalDisposition.PROHIBITED
    if blocked_states:
        return FinalDisposition.INSUFFICIENT_EVIDENCE
    if any(
        item.requirement_id == "MPR_53" and item.status == RequirementStatus.ACTION_REQUIRED
        for item in requirements
    ):
        return FinalDisposition.REQUIRES_ACCEPTANCE_TEST
    if any(
        item.requirement_id == "MPR_52" and item.status == RequirementStatus.ACTION_REQUIRED
        for item in requirements
    ):
        return FinalDisposition.REQUIRES_MUA
    if any(item.credible_status == CredibleStatus.INDETERMINATE for item in mechanisms):
        return FinalDisposition.COMPATIBLE_WITH_CONTROLS
    if any(
        item.credible_status == CredibleStatus.CREDIBLE and item.rating >= 3
        for item in mechanisms
    ):
        return FinalDisposition.COMPATIBLE_WITH_CONTROLS
    if kindling.kindling_chain_present or hazard_controls:
        return FinalDisposition.COMPATIBLE_WITH_CONTROLS
    return FinalDisposition.COMPATIBLE_AS_CONFIGURED


def generate_mua_seed(
    context: OxygenServiceContext,
    materials: list[MaterialInstance],
    mechanisms: list[MechanismAssessment],
    gaps: list[str],
    disposition: FinalDisposition,
) -> Optional[MUASeed]:
    if disposition not in {
        FinalDisposition.REQUIRES_MUA,
        FinalDisposition.REQUIRES_SUPPLEMENTAL_TESTING,
        FinalDisposition.INSUFFICIENT_EVIDENCE,
    }:
        return None

    return MUASeed(
        material_names=[item.canonical_name or item.material_name for item in materials],
        service_conditions=context.model_dump(),
        mechanism_summary=[
            {
                "mechanism_name": item.mechanism_name.value,
                "credible_status": item.credible_status.value,
                "rating": item.rating,
            }
            for item in mechanisms
            if item.credible_status != CredibleStatus.NOT_CREDIBLE
        ],
        evidence_gaps=list(gaps),
        recommended_disposition=disposition,
        notes=["Generated by the Phase 1 compatibility shim for the Phase 2 system builder."],
    )
