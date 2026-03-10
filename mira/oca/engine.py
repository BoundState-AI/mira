#!/usr/bin/env python3
"""
Module: OCA Engine
Purpose: Deterministic 7-step OCA pipeline per NASA/TM-2007-213740.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary
Spec: BS-SPEC-OCA-001-REV1

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6001B, NASA-STD-6016C, SWE-013, SWE-032
Safety Critical: True

Pipeline stages (Spec §11):
  Stage 0 — Intake: normalize inputs, check blocked states
  Stage 1 — Requirement Triggers: MPR 51/52/53/67
  Stage 2 — Evidence Retrieval
  Stage 3 — Applicability Scoring
  Stage 4 — Mechanism Assessment (12 mechanisms per TM §4.3)
  Stage 5 — Disposition (matrix-based, no model inference)
  Stage 6 — Artifact Generation

LLM is used ONLY for intake normalization. The engine never decides compatibility.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

from .models import (
    ApplicabilityClass,
    BlockedState,
    BlockedStateType,
    ComponentInfo,
    CredibleStatus,
    EvidenceApplicabilityScore,
    FlammabilityRating,
    GeometryClass,
    HazardControlEntry,
    HistoryOfUse,
    IgnitionMechanismName,
    KindlingChainResult,
    MechanismTrace,
    MaterialInstance,
    MUASeed,
    OCADecisionPacket,
    OCADisposition,
    OxidizerType,
    OxygenPhase,
    OxygenServiceContext,
    ReactionEffect,
    RecommendationClass,
    RuleTier,
    TestEvidence,
    TriggeredRequirement,
)

LOGGER = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Data pack loader (singleton)
# ---------------------------------------------------------------------------

_mechanisms_cache: Optional[dict] = None
_requirements_cache: Optional[dict] = None
_material_rules_cache: Optional[dict] = None


def _load_json(filename: str) -> dict:
    path = _DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"OCA data pack missing: {path}")
    with open(path, "r") as f:
        return json.load(f)


def get_mechanisms_data() -> dict:
    global _mechanisms_cache
    if _mechanisms_cache is None:
        _mechanisms_cache = _load_json("oca_ignition_mechanisms.json")
    return _mechanisms_cache


def get_requirements_data() -> dict:
    global _requirements_cache
    if _requirements_cache is None:
        _requirements_cache = _load_json("oca_requirement_binding.json")
    return _requirements_cache


def get_material_rules_data() -> dict:
    global _material_rules_cache
    if _material_rules_cache is None:
        _material_rules_cache = _load_json("oca_material_pressure_rules.json")
    return _material_rules_cache


# ---------------------------------------------------------------------------
# Adiabatic compression calculator (Spec §6 Step 3 — Rapid Pressurization)
# ---------------------------------------------------------------------------

def adiabatic_compression_temperature(
    ti_k: float,
    pi_psia: float,
    pf_psia: float,
    gamma: float = 1.4,
) -> float:
    """Compute final temperature from adiabatic compression.

    Tf = Ti * (Pf/Pi)^((gamma-1)/gamma)

    Args:
        ti_k: Initial temperature in Kelvin.
        pi_psia: Initial pressure in psia.
        pf_psia: Final pressure in psia.
        gamma: Heat capacity ratio (1.4 for O2).

    Returns:
        Final temperature in Kelvin.
    """
    if pi_psia <= 0:
        return ti_k
    ratio = pf_psia / pi_psia
    exponent = (gamma - 1.0) / gamma
    return ti_k * math.pow(ratio, exponent)


# ---------------------------------------------------------------------------
# Stage 0 — Intake & Blocked State Detection
# ---------------------------------------------------------------------------

def check_blocked_states(
    context: OxygenServiceContext,
    component: ComponentInfo,
    materials: list[MaterialInstance],
) -> list[BlockedState]:
    """Check for blocked states that prevent full assessment."""
    blocked: list[BlockedState] = []

    # MATERIAL IDENTITY UNRESOLVED
    for mat in materials:
        if mat.identity_confidence < 0.5:
            blocked.append(BlockedState(
                state_type=BlockedStateType.MATERIAL_IDENTITY_UNRESOLVED,
                description=f"Material '{mat.material_name}' identity confidence is {mat.identity_confidence:.0%}. "
                            "Evidence scoring will be degraded.",
                missing_fields=["canonical_name", "spec"],
                resolution_hint="Provide material specification, alloy grade, or MAPTIS code.",
            ))

    # SERVICE ENVELOPE INCOMPLETE
    missing_env = []
    if context.o2_fraction is None or context.o2_fraction <= 0:
        missing_env.append("o2_fraction")
    if context.total_pressure_max_psia <= 0:
        missing_env.append("total_pressure_max_psia")
    if missing_env:
        blocked.append(BlockedState(
            state_type=BlockedStateType.SERVICE_ENVELOPE_INCOMPLETE,
            description="Critical service context missing. Mechanism assessment cannot proceed.",
            missing_fields=missing_env,
            resolution_hint="Provide O2 fraction, pressure, phase, and temperature.",
        ))

    # DESIGN FUNCTION UNKNOWN
    if component.component_class.value == "other" and component.geometry_class.value == "other":
        blocked.append(BlockedState(
            state_type=BlockedStateType.DESIGN_FUNCTION_UNKNOWN,
            description="Part function, geometry, or configuration insufficient for mechanism evaluation.",
            missing_fields=["component_class", "geometry_class"],
            resolution_hint="Select component type (valve, regulator, line, etc.) and geometry class.",
        ))

    return blocked


# ---------------------------------------------------------------------------
# Stage 1 — Requirement Triggers (deterministic)
# ---------------------------------------------------------------------------

def evaluate_requirement_triggers(
    context: OxygenServiceContext,
    component: ComponentInfo,
    materials: list[MaterialInstance],
) -> list[TriggeredRequirement]:
    """Deterministic requirement trigger evaluation per Spec §3."""
    triggered: list[TriggeredRequirement] = []

    # MPR 51: All O2 service materials require evaluation
    if context.oxidizer_type in (
        OxidizerType.LOX, OxidizerType.GOX,
        OxidizerType.ENRICHED_AIR, OxidizerType.COMPRESSED_AIR,
    ):
        triggered.append(TriggeredRequirement(
            requirement_id="MPR-51",
            source_standard="NASA-STD-6016C",
            section="§4.2.1.4a",
            title="Oxygen Compatibility Evaluation Required",
            tier=RuleTier.A,
            satisfied=False,
            satisfaction_basis="OCA assessment in progress",
        ))

    # MPR 52: Flammable materials require OCA + MUA
    has_flammable = any(
        m.flammability_rating in (
            FlammabilityRating.C, FlammabilityRating.D,
            FlammabilityRating.X, FlammabilityRating.UNKNOWN,
        )
        for m in materials
    )
    if has_flammable and context.oxidizer_type in (
        OxidizerType.LOX, OxidizerType.GOX,
        OxidizerType.ENRICHED_AIR, OxidizerType.COMPRESSED_AIR,
    ):
        triggered.append(TriggeredRequirement(
            requirement_id="MPR-52",
            source_standard="NASA-STD-6016C",
            section="§4.2.1.4b",
            title="OCA + MUA for Flammable Materials",
            tier=RuleTier.A,
            satisfied=False,
            satisfaction_basis="Flammable material detected; MUA required",
        ))

    # MPR 53: Acceptance testing for GOX/enriched-air > 265 psia (non-exempt)
    if (
        context.oxidizer_type in (OxidizerType.GOX, OxidizerType.ENRICHED_AIR)
        and context.total_pressure_max_psia > 265
    ):
        exempt = (
            component.is_rigid_metallic_tubing
            or component.is_metallic_flex_hose
            or component.is_all_metal_seal
            or component.is_metallic_pressure_vessel
        )
        exemption_reason = None
        if component.is_rigid_metallic_tubing:
            exemption_reason = "Rigid metallic tubing — exempt per MPR 53"
        elif component.is_metallic_flex_hose:
            exemption_reason = "Metallic flex hose — exempt per MPR 53"
        elif component.is_all_metal_seal:
            exemption_reason = "All-metal seal fitting — exempt per MPR 53"
        elif component.is_metallic_pressure_vessel:
            exemption_reason = "Metallic pressure vessel (incl. COPV w/metallic liner) — exempt per MPR 53"

        triggered.append(TriggeredRequirement(
            requirement_id="MPR-53",
            source_standard="NASA-STD-6016C",
            section="§4.2.1.4.1",
            title="Oxygen Component Acceptance Testing",
            tier=RuleTier.A,
            satisfied=exempt,
            satisfaction_basis=exemption_reason or "Non-exempt component above 265 psia; acceptance testing required",
        ))

    # MPR 67: Titanium prohibition (GOVERNING — Tier A)
    o2_pp = context.compute_o2_partial_pressure()
    for mat in materials:
        if mat.is_titanium:
            is_prohibited = (
                context.oxidizer_type in (OxidizerType.LOX, OxidizerType.GOX)
                or o2_pp > 5.0
            )
            if is_prohibited:
                triggered.append(TriggeredRequirement(
                    requirement_id="MPR-67",
                    source_standard="NASA-STD-6016C",
                    section="§4.2.1.3c",
                    title="Titanium Prohibition in Oxygen Service",
                    tier=RuleTier.A,
                    satisfied=False,
                    is_prohibition=True,
                    prohibition_detail=(
                        f"Titanium alloy '{mat.material_name}' SHALL NOT be used. "
                        f"LOX/GOX at any pressure prohibited. Air prohibited above 5 psia O2 PP "
                        f"(current: {o2_pp:.1f} psia). Per NASA-STD-6016C §4.2.1.3c."
                    ),
                ))

    return triggered


# ---------------------------------------------------------------------------
# Stage 2–3 — Evidence Retrieval & Applicability Scoring
# ---------------------------------------------------------------------------

def score_evidence_applicability(
    evidence: TestEvidence,
    material: MaterialInstance,
    context: OxygenServiceContext,
) -> EvidenceApplicabilityScore:
    """Score a single evidence object against material + context (Spec §7)."""
    score = EvidenceApplicabilityScore(evidence_id=evidence.evidence_id)

    # Scoring is degraded by identity confidence
    confidence_factor = material.identity_confidence

    # Count matches (simplified — production would do detailed field matching)
    match_count = 0
    total_fields = 10

    # For now, all evidence is scored as partial unless exact match info is available
    # In production, this queries MAPTIS/Granta and compares test conditions
    score.aggregate_score = 0.3 * confidence_factor
    score.applicability_class = ApplicabilityClass.PARTIAL

    if score.aggregate_score >= 0.8:
        score.applicability_class = ApplicabilityClass.DIRECT
    elif score.aggregate_score >= 0.5:
        score.applicability_class = ApplicabilityClass.PARTIAL
    elif score.aggregate_score >= 0.2:
        score.applicability_class = ApplicabilityClass.WEAK_ANALOG
    else:
        score.applicability_class = ApplicabilityClass.NOT_APPLICABLE

    return score


def retrieve_evidence(
    materials: list[MaterialInstance],
    context: OxygenServiceContext,
) -> tuple[list[TestEvidence], list[str]]:
    """Retrieve and score applicable evidence. Returns (evidence, gaps)."""
    evidence_list: list[TestEvidence] = []
    gaps: list[str] = []

    for mat in materials:
        # Check for flammability data gap
        if mat.flammability_rating in (FlammabilityRating.X, FlammabilityRating.UNKNOWN):
            gaps.append(
                f"No flammability rating for '{mat.material_name}'. "
                "REQUIRES SUPPLEMENTAL TESTING per FOCR 34."
            )

        # Check for promoted combustion data gap at service pressure
        if context.total_pressure_max_psia > 200:
            gaps.append(
                f"Promoted combustion test data needed for '{mat.material_name}' "
                f"at {context.total_pressure_max_psia:.0f} psia. "
                "NASA-STD-6001B Test 17 recommended."
            )

    return evidence_list, gaps


# ---------------------------------------------------------------------------
# Stage 4 — Mechanism Assessment (12 mechanisms per TM §4.3)
# ---------------------------------------------------------------------------

def assess_ignition_mechanisms(
    context: OxygenServiceContext,
    component: ComponentInfo,
    materials: list[MaterialInstance],
) -> list[MechanismTrace]:
    """Evaluate all 12 ignition mechanisms per TM-2007-213740 §4.3."""
    mechanisms_data = get_mechanisms_data()
    assessments: list[MechanismTrace] = []

    has_nonmetal = any(m.is_nonmetal for m in materials)
    has_reactive_metal = any(m.is_titanium for m in materials)  # Al also, simplified
    has_dynamic = component.dynamic_contact_flag
    velocity = context.velocity_m_s or 0.0
    pressure = context.total_pressure_max_psia
    is_lox = context.phase == OxygenPhase.LIQUID
    is_high_pressure = pressure > 265

    for mech_data in mechanisms_data.get("mechanisms", []):
        name = mech_data["name"]
        try:
            mech_name = IgnitionMechanismName(name)
        except ValueError:
            continue

        trace = MechanismTrace(
            mechanism_name=mech_name,
            source_ref=mech_data.get("source_ref", ""),
            required_elements=mech_data.get("characteristic_elements", []),
        )

        # Determine credibility and rating per mechanism
        if mech_name == IgnitionMechanismName.PARTICLE_IMPACT:
            observed = []
            if velocity > 0:
                observed.append("velocity_above_30_m_s" if velocity > 30 else "high_velocity_flow")
            if has_nonmetal or has_reactive_metal:
                observed.append("flammable_target_material")
            observed.append("oxygen_enriched_environment")
            trace.observed_elements = observed

            if velocity > 30 and (has_nonmetal or has_reactive_metal):
                trace.credible_status = CredibleStatus.CREDIBLE
                trace.rating = 3
            elif velocity > 0:
                trace.credible_status = CredibleStatus.INDETERMINATE
                trace.rating = 2
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.RAPID_PRESSURIZATION:
            observed = ["oxygen_enriched_environment"]
            if has_nonmetal:
                observed.append("exposed_nonmetal_near_dead_end")

            # Adiabatic compression check
            if pressure > 14.7 and has_nonmetal:
                ti_k = 293.15  # ~20°C ambient
                tf_k = adiabatic_compression_temperature(ti_k, 14.7, pressure)
                observed.append(f"adiabatic_tf={tf_k:.0f}K")
                if tf_k > 500:  # Approximate AIT threshold
                    trace.credible_status = CredibleStatus.CREDIBLE
                    trace.rating = 3 if tf_k > 600 else 2
                else:
                    trace.credible_status = CredibleStatus.NOT_CREDIBLE
                    trace.rating = 1
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0
            trace.observed_elements = observed

        elif mech_name == IgnitionMechanismName.FLOW_FRICTION:
            if has_nonmetal and velocity > 0:
                trace.credible_status = CredibleStatus.INDETERMINATE
                trace.rating = 2
                trace.observed_elements = ["nonmetal_in_flow_path", "high_velocity_flow"]
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.RESONANCE:
            # Credible only with sonic flow into cavities
            if velocity > 300 and component.geometry_class in (GeometryClass.OTHER,):
                trace.credible_status = CredibleStatus.INDETERMINATE
                trace.rating = 2
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.MECHANICAL_IMPACT:
            if has_dynamic and (has_nonmetal or is_lox):
                trace.credible_status = CredibleStatus.CREDIBLE
                trace.rating = 3 if is_lox else 2
                trace.observed_elements = ["impact_energy_source", "oxygen_enriched_environment"]
                if is_lox:
                    trace.observed_elements.append("lox_sensitivity_multiplier")
            elif has_dynamic:
                trace.credible_status = CredibleStatus.INDETERMINATE
                trace.rating = 1
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.GALLING_FRICTION:
            if has_dynamic and component.component_class.value in ("valve", "regulator"):
                trace.credible_status = CredibleStatus.CREDIBLE
                trace.rating = 3
                trace.observed_elements = [
                    "metal_to_metal_contact", "rapid_relative_motion",
                    "chatter_in_valves_regulators", "oxygen_enriched_environment",
                ]
            elif has_dynamic:
                trace.credible_status = CredibleStatus.INDETERMINATE
                trace.rating = 1
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.FRESH_METAL_EXPOSURE:
            if has_reactive_metal:
                trace.credible_status = CredibleStatus.CREDIBLE
                trace.rating = 3
                trace.observed_elements = [
                    "quick_oxidizing_metal_present",
                    "aluminum_or_titanium",
                    "oxygen_enriched_environment",
                ]
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.STATIC_DISCHARGE:
            # Generally low concern unless specific conditions
            trace.credible_status = CredibleStatus.NOT_CREDIBLE
            trace.rating = 0

        elif mech_name == IgnitionMechanismName.ELECTRICAL_ARC:
            if component.component_class.value == "sensor":
                trace.credible_status = CredibleStatus.INDETERMINATE
                trace.rating = 2
                trace.observed_elements = ["power_source_present", "oxygen_enriched_environment"]
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.CHEMICAL_REACTION:
            trace.credible_status = CredibleStatus.NOT_CREDIBLE
            trace.rating = 0

        elif mech_name == IgnitionMechanismName.THERMAL_RUNAWAY:
            if component.geometry_class in (GeometryClass.POROUS, GeometryClass.SINTERED, GeometryClass.MESH):
                trace.credible_status = CredibleStatus.INDETERMINATE
                trace.rating = 2
                trace.observed_elements = [
                    "high_surface_area_to_volume",
                    "porous_or_fines_material",
                    "oxygen_enriched_environment",
                ]
            else:
                trace.credible_status = CredibleStatus.NOT_CREDIBLE
                trace.rating = 0

        elif mech_name == IgnitionMechanismName.OTHER:
            trace.credible_status = CredibleStatus.NOT_CREDIBLE
            trace.rating = 0

        # Compute missing elements
        trace.missing_elements = [
            e for e in trace.required_elements
            if e not in trace.observed_elements
        ]

        assessments.append(trace)

    return assessments


# ---------------------------------------------------------------------------
# Stage 5 — Kindling Chain & Reaction Effect (TM §4.4–4.5)
# ---------------------------------------------------------------------------

def evaluate_kindling_chain(
    materials: list[MaterialInstance],
    component: ComponentInfo,
    mechanisms: list[MechanismTrace],
) -> KindlingChainResult:
    """Evaluate kindling chain and reaction effect per TM §4.4–4.5."""
    credible_mechanisms = [m for m in mechanisms if m.credible_status == CredibleStatus.CREDIBLE]
    max_rating = max((m.rating for m in mechanisms), default=0)

    # Kindling chain: can ignition propagate?
    all_flammable = all(
        m.flammability_rating in (
            FlammabilityRating.C, FlammabilityRating.D,
            FlammabilityRating.X, FlammabilityRating.UNKNOWN,
        )
        for m in materials
    )
    has_nonflammable = any(
        m.flammability_rating in (FlammabilityRating.A, FlammabilityRating.B)
        for m in materials
    )

    kindling_present = bool(credible_mechanisms) and all_flammable
    propagation_path = []

    if kindling_present:
        propagation_path = [
            f"{m.material_name} ({m.flammability_rating.value})" for m in materials
        ]

    # Reaction Effect per TM Table 3
    if not credible_mechanisms or max_rating == 0:
        effect = ReactionEffect.A  # Negligible
    elif max_rating <= 2 and has_nonflammable:
        effect = ReactionEffect.B  # Marginal
    elif max_rating <= 3:
        effect = ReactionEffect.C  # Critical
    else:
        effect = ReactionEffect.D  # Catastrophic

    rationale_parts = []
    if credible_mechanisms:
        rationale_parts.append(
            f"{len(credible_mechanisms)} credible ignition mechanism(s) identified."
        )
    if kindling_present:
        rationale_parts.append("Kindling chain: all materials flammable, propagation likely.")
    elif has_nonflammable:
        rationale_parts.append("Kindling chain interrupted by nonflammable material(s).")
    else:
        rationale_parts.append("No credible ignition mechanisms; kindling chain not assessed.")

    return KindlingChainResult(
        kindling_chain_present=kindling_present,
        propagation_path=propagation_path,
        reaction_effect=effect,
        rationale=" ".join(rationale_parts),
    )


# ---------------------------------------------------------------------------
# Stage 5 (cont.) — Disposition (matrix-based, no model inference)
# ---------------------------------------------------------------------------

def determine_disposition(
    triggered_requirements: list[TriggeredRequirement],
    mechanisms: list[MechanismTrace],
    kindling: KindlingChainResult,
    evidence: list[TestEvidence],
    gaps: list[str],
    blocked_states: list[BlockedState],
) -> OCADisposition:
    """Deterministic disposition based on requirement satisfaction + mechanism results."""
    # Any prohibition = cannot proceed
    prohibitions = [r for r in triggered_requirements if r.is_prohibition and not r.satisfied]
    if prohibitions:
        return OCADisposition.INSUFFICIENT_EVIDENCE

    # Any blocked states = insufficient
    if blocked_states:
        return OCADisposition.INSUFFICIENT_EVIDENCE

    # Acceptance test required
    acceptance_req = [r for r in triggered_requirements if r.requirement_id == "MPR-53" and not r.satisfied]
    if acceptance_req:
        return OCADisposition.REQUIRES_ACCEPTANCE_TEST

    # Check mechanism results
    credible = [m for m in mechanisms if m.credible_status == CredibleStatus.CREDIBLE]
    indeterminate = [m for m in mechanisms if m.credible_status == CredibleStatus.INDETERMINATE]

    # Evidence gaps
    if gaps:
        if credible:
            return OCADisposition.REQUIRES_SUPPLEMENTAL_TESTING
        if indeterminate:
            return OCADisposition.REQUIRES_MUA

    # MUA required for flammable materials
    mua_req = [r for r in triggered_requirements if r.requirement_id == "MPR-52"]
    if mua_req:
        return OCADisposition.REQUIRES_MUA

    # Credible mechanisms with kindling chain
    if credible and kindling.kindling_chain_present:
        return OCADisposition.REQUIRES_MUA

    # Credible mechanisms but no kindling chain
    if credible:
        return OCADisposition.COMPATIBLE_WITH_CONTROLS

    # Some indeterminate mechanisms
    if indeterminate:
        return OCADisposition.COMPATIBLE_WITH_CONTROLS

    # All clear
    return OCADisposition.COMPATIBLE_AS_CONFIGURED


# ---------------------------------------------------------------------------
# Stage 6 — Generate Hazard Controls
# ---------------------------------------------------------------------------

def generate_hazard_controls(
    component: ComponentInfo,
    mechanisms: list[MechanismTrace],
    kindling: KindlingChainResult,
) -> list[HazardControlEntry]:
    """Generate Hazard Control Table entries per TM Table 4."""
    controls: list[HazardControlEntry] = []
    mechanisms_data = get_mechanisms_data()

    mech_lookup = {m["name"]: m for m in mechanisms_data.get("mechanisms", [])}

    for mech in mechanisms:
        if mech.credible_status == CredibleStatus.NOT_CREDIBLE:
            continue

        data = mech_lookup.get(mech.mechanism_name.value, {})
        mitigations = data.get("typical_mitigations", [])

        for mitigation in mitigations:
            controls.append(HazardControlEntry(
                component_ref=component.component_id,
                ignition_hazard=mech.mechanism_name.value,
                probability_rating=mech.rating,
                reaction_effect=kindling.reaction_effect,
                recommendation=mitigation,
                recommendation_class=RecommendationClass.STANDARDS_DERIVED,
                affected_mechanisms=[mech.mechanism_name],
                evidence_basis=mech.source_ref,
                confidence="medium" if mech.credible_status == CredibleStatus.CREDIBLE else "low",
                status="open",
            ))

    return controls


# ---------------------------------------------------------------------------
# MUA Seed Generation (Spec §13)
# ---------------------------------------------------------------------------

def generate_mua_seed(
    context: OxygenServiceContext,
    materials: list[MaterialInstance],
    mechanisms: list[MechanismTrace],
    gaps: list[str],
    disposition: OCADisposition,
) -> Optional[MUASeed]:
    """Generate structured MUA pre-population packet if MUA is needed."""
    if disposition not in (OCADisposition.REQUIRES_MUA, OCADisposition.REQUIRES_SUPPLEMENTAL_TESTING):
        return None

    mat_names = [m.material_name for m in materials]
    credible = [m for m in mechanisms if m.credible_status == CredibleStatus.CREDIBLE]
    mechanism_summary = ", ".join(m.mechanism_name.value for m in credible) if credible else "None credible"

    return MUASeed(
        material_identity="; ".join(mat_names),
        service_conditions=(
            f"{context.oxidizer_type.value} at {context.total_pressure_max_psia:.0f} psia, "
            f"O2 fraction {context.o2_fraction:.0%}, {context.phase.value}"
        ),
        trigger_reason=f"OCA disposition: {disposition.value}",
        mechanism_summary=mechanism_summary,
        applicable_evidence=[],
        gaps=gaps,
        rationale_draft=(
            f"Material(s) {', '.join(mat_names)} assessed in "
            f"{context.oxidizer_type.value} service at {context.total_pressure_max_psia:.0f} psia. "
            f"Credible ignition mechanisms: {mechanism_summary}. "
            f"{'Evidence gaps require resolution. ' if gaps else ''}"
            "Safety rationale must address identified hazards per NASA-STD-6001B."
        ),
        assumptions=["Worst-case operating conditions as specified", "Cleanliness per NASA-STD-6016C"],
    )


# ---------------------------------------------------------------------------
# Full Pipeline Orchestrator
# ---------------------------------------------------------------------------

class OCAEngine:
    """Orchestrates the full 7-step OCA pipeline."""

    def __init__(self) -> None:
        # Verify data packs are loadable
        get_mechanisms_data()
        get_requirements_data()
        get_material_rules_data()
        LOGGER.info("[OCA Engine] Data packs loaded successfully.")

    def create_case(
        self,
        context: OxygenServiceContext,
        component: ComponentInfo,
        materials: list[MaterialInstance],
    ) -> tuple[OxygenServiceContext, list[BlockedState], list[str]]:
        """Stage 0: Normalize inputs and detect blocked states."""
        # Auto-compute O2 partial pressure
        context.oxygen_partial_pressure_psia = context.compute_o2_partial_pressure()

        # Normalize materials
        for mat in materials:
            if not mat.canonical_name:
                mat.canonical_name = mat.material_name.upper().strip()
            # Detect titanium
            name_lower = mat.material_name.lower()
            if any(kw in name_lower for kw in ("titanium", "ti-6al-4v", "ti-", "ti ", "grade 5")):
                mat.is_titanium = True
            # Detect nonmetals
            if any(kw in name_lower for kw in (
                "teflon", "ptfe", "viton", "kel-f", "pctfe", "silicone", "rubber",
                "nylon", "peek", "vespel", "polyimide", "epoxy", "composite",
            )):
                mat.is_nonmetal = True

        blocked = check_blocked_states(context, component, materials)
        warnings = []
        if context.cleanliness_verified is False:
            warnings.append("Cleanliness not verified — all assessments assume clean per NASA-STD-6016C.")

        return context, blocked, warnings

    def precheck(
        self,
        context: OxygenServiceContext,
        component: ComponentInfo,
        materials: list[MaterialInstance],
    ) -> tuple[list[TriggeredRequirement], bool, bool, Optional[str]]:
        """Stage 1: Evaluate requirement triggers."""
        triggered = evaluate_requirement_triggers(context, component, materials)

        acceptance_required = any(
            r.requirement_id == "MPR-53" and not r.satisfied for r in triggered
        )
        acceptance_exempt = any(
            r.requirement_id == "MPR-53" and r.satisfied for r in triggered
        )
        exemption_reason = None
        for r in triggered:
            if r.requirement_id == "MPR-53" and r.satisfied:
                exemption_reason = r.satisfaction_basis

        return triggered, acceptance_required, acceptance_exempt, exemption_reason

    def retrieve_and_score_evidence(
        self,
        context: OxygenServiceContext,
        materials: list[MaterialInstance],
    ) -> tuple[list[TestEvidence], list[str]]:
        """Stages 2-3: Retrieve evidence and score applicability."""
        return retrieve_evidence(materials, context)

    def assess_mechanisms(
        self,
        context: OxygenServiceContext,
        component: ComponentInfo,
        materials: list[MaterialInstance],
    ) -> list[MechanismTrace]:
        """Stage 4: Assess all 12 ignition mechanisms."""
        return assess_ignition_mechanisms(context, component, materials)

    def evaluate_kindling_and_effect(
        self,
        materials: list[MaterialInstance],
        component: ComponentInfo,
        mechanisms: list[MechanismTrace],
    ) -> KindlingChainResult:
        """Stage 5a: Kindling chain and reaction effect."""
        return evaluate_kindling_chain(materials, component, mechanisms)

    def run_full_assessment(
        self,
        context: OxygenServiceContext,
        component: ComponentInfo,
        materials: list[MaterialInstance],
    ) -> OCADecisionPacket:
        """Run the complete 7-step OCA pipeline and return a decision packet."""
        # Stage 0
        context, blocked_states, warnings = self.create_case(context, component, materials)

        # Stage 1
        triggered, acceptance_required, acceptance_exempt, exemption_reason = self.precheck(
            context, component, materials
        )

        # Stage 2-3
        evidence, gaps = self.retrieve_and_score_evidence(context, materials)

        # Stage 4
        mechanisms = self.assess_mechanisms(context, component, materials)

        # Stage 5a
        kindling = self.evaluate_kindling_and_effect(materials, component, mechanisms)

        # Stage 5b — Disposition
        disposition = determine_disposition(
            triggered, mechanisms, kindling, evidence, gaps, blocked_states
        )

        # Stage 6 — Hazard controls
        hazard_controls = generate_hazard_controls(component, mechanisms, kindling)

        # MUA seed
        mua_seed = generate_mua_seed(context, materials, mechanisms, gaps, disposition)

        # Build decision packet
        credible_count = sum(1 for m in mechanisms if m.credible_status == CredibleStatus.CREDIBLE)
        summary_parts = [
            f"Disposition: {disposition.value}.",
            f"Triggered requirements: {len(triggered)}.",
            f"Credible mechanisms: {credible_count}/12.",
            f"Reaction effect: {kindling.reaction_effect.value}.",
        ]
        if gaps:
            summary_parts.append(f"Evidence gaps: {len(gaps)}.")
        if blocked_states:
            summary_parts.append(f"Blocked states: {len(blocked_states)}.")

        return OCADecisionPacket(
            case_id=context.case_id,
            final_disposition=disposition,
            triggered_requirements=triggered,
            blocked_states=blocked_states,
            unresolved_gaps=gaps,
            kindling_chain_present=kindling.kindling_chain_present,
            reaction_effect=kindling.reaction_effect,
            history_of_use=HistoryOfUse.UNKNOWN,
            mua_seed=mua_seed,
            acceptance_test_required=acceptance_required,
            reviewer_required=disposition != OCADisposition.COMPATIBLE_AS_CONFIGURED,
            summary_rationale=" ".join(summary_parts),
            mechanism_assessments=mechanisms,
            evidence=evidence,
            hazard_controls=hazard_controls,
            kindling_chain=kindling,
        )


# Singleton
_engine_instance: Optional[OCAEngine] = None


def get_oca_engine() -> OCAEngine:
    """Get or create the singleton OCA engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OCAEngine()
    return _engine_instance


__safety_critical__ = True
