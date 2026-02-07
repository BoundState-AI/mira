#!/usr/bin/env python3
"""
Module: Compliance Conductor
Purpose: Orchestrates NASA-STD-6016C compliance analysis

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

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - Compliance Conductor

The Conductor orchestrates compliance analysis by:
1. Resolving materials to canonical IDs
2. Routing materials to appropriate twins (O2, H2)
3. Mapping signals from adapters to MPR determinations
4. Triggering MUA generation when needed

KEY RESPONSIBILITY: Maps GapSignals to MPRDeterminations.
This is the ONLY place where signals are connected to requirements.

Fran Fix #1: Adapters emit signals only, conductor maps to MPRs.
Fran Fix #3: CAUTION action uses policy flags.
Fran Fix #8: Uses MPRIndex.get_mprs_for_signal(), no [0] selection.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from datetime import datetime
from typing import Any, Optional
import uuid

from mira.compliance.adapters.h2_adapter import H2Adapter
from mira.compliance.adapters.mua_adapter import MUAAdapter
from mira.compliance.adapters.o2_adapter import O2Adapter
from mira.compliance.models.adapter_outputs import (
    H2AdapterOutput,
    MUAAdapterOutput,
    O2AdapterOutput,
)
from mira.compliance.models.determination import MPRDetermination
from mira.compliance.models.enums import (
    ApplicabilityStatus,
    ComplianceBasis,
    ComplianceStatus,
    GapSeverity,
    RequiredAction,
)
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal, GapSummary
from mira.compliance.models.manifest import RunManifest
from mira.compliance.models.mpr import MPRIndex, MPRRecord
from mira.compliance.models.policy import (
    ConductorPolicy,
    EnvironmentDefinition,
    EnvironmentPolicy,
    PolicyRoutingDecision,
)
from mira.compliance.models.resolution import MaterialResolutionResult
from mira.compliance.models.result import ComplianceAnalysisResult


class ParsedPlan:
    """Parsed compliance plan input."""

    def __init__(
        self,
        plan_id: str,
        version: str,
        materials: list[dict],
        environments: list[EnvironmentDefinition],
    ):
        self.plan_id = plan_id
        self.version = version
        self.materials = materials
        self.environments = environments


class MaterialResolver:
    """Material resolver interface."""

    def resolve(
        self,
        maptis_code: Optional[int] = None,
        material_name: Optional[str] = None,
        material_spec: Optional[str] = None,
    ) -> MaterialResolutionResult:
        """Resolve material to canonical identifiers."""
        # Case 1: MAPTIS code provided - high confidence
        if maptis_code:
            return MaterialResolutionResult(
                input_maptis_code=maptis_code,
                input_material_name=material_name,
                input_material_spec=material_spec,
                resolved=True,
                resolution_method="maptis_code_direct",
                resolution_confidence=1.0,
                canonical_maptis_code=maptis_code,
                canonical_material_id=f"MAPTIS:{maptis_code}",
                canonical_name=material_name or f"Material {maptis_code}",
                canonical_spec=material_spec,
                material_family="unknown",
                evidence_ref=EvidenceRef(
                    source_type="maptis",
                    source_id=f"MAPTIS:{maptis_code}",
                    confidence=1.0,
                    confidence_basis="Direct MAPTIS lookup",
                    retrieved_at=datetime.now(),
                    retrieval_method="maptis_direct",
                ),
            )

        # Case 2: Material name provided - lower confidence, needs verification
        if material_name:
            # Infer material family from name patterns
            name_upper = material_name.upper()
            family = "unknown"
            if any(x in name_upper for x in ["SS", "316", "304", "321", "STAINLESS"]):
                family = "austenitic_stainless"
            elif any(x in name_upper for x in ["INCONEL", "718", "625", "HASTELLOY"]):
                family = "nickel_superalloy"
            elif any(x in name_upper for x in ["TI-", "TI6", "TITANIUM"]):
                family = "titanium_alloy"
            elif any(x in name_upper for x in ["AL", "ALUMINUM", "2024", "6061", "7075"]):
                family = "aluminum_alloy"
            elif any(x in name_upper for x in ["MONEL", "K-500"]):
                family = "nickel_copper"

            return MaterialResolutionResult(
                input_material_name=material_name,
                input_material_spec=material_spec,
                resolved=True,
                resolution_method="name_pattern_match",
                resolution_confidence=0.6,  # Lower confidence - needs MAPTIS lookup
                canonical_material_id=f"NAME:{material_name}",
                canonical_name=material_name,
                canonical_spec=material_spec,
                material_family=family,
                ambiguous=True,  # Flag that this needs verification
                evidence_ref=EvidenceRef(
                    source_type="engineering_judgment",  # Name inference is engineering judgment
                    source_id=f"NAME:{material_name}",
                    confidence=0.6,
                    confidence_basis="Name pattern match - requires MAPTIS verification",
                    retrieved_at=datetime.now(),
                    retrieval_method="name_inference",
                ),
            )

        # Case 3: No useful input
        return MaterialResolutionResult(
            input_material_name=material_name,
            input_material_spec=material_spec,
            resolved=False,
            resolution_method="failed",
            resolution_confidence=0.0,
        )


class ComplianceConductor:
    """
    Orchestrates compliance analysis.

    KEY RESPONSIBILITY: Maps GapSignals to MPRDeterminations.
    This is the ONLY place where signals are connected to requirements.

    Fran Fix #1: Adapters emit signals only, conductor maps to MPRs.
    Fran Fix #8: Uses MPRIndex.get_mprs_for_signal(), no [0] selection.
    """

    def __init__(
        self,
        mpr_index: MPRIndex,
        environment_policy: EnvironmentPolicy,
        conductor_policy: ConductorPolicy,
        o2_adapter: Optional[O2Adapter] = None,
        h2_adapter: Optional[H2Adapter] = None,
        mua_adapter: Optional[MUAAdapter] = None,
        resolver: Optional[MaterialResolver] = None,
    ):
        """
        Initialize conductor.

        Args:
            mpr_index: Index of all MPRs from NASA-STD-6016C
            environment_policy: Policy for environment-based routing
            conductor_policy: Policy flags for conductor behavior
            o2_adapter: O2 twin adapter
            h2_adapter: H2 twin adapter
            mua_adapter: MUA generator adapter
            resolver: Material resolver
        """
        self.mpr_index = mpr_index
        self.environment_policy = environment_policy
        self.conductor_policy = conductor_policy
        self.o2_adapter = o2_adapter or O2Adapter()
        self.h2_adapter = h2_adapter or H2Adapter()
        self.mua_adapter = mua_adapter or MUAAdapter()
        self.resolver = resolver or MaterialResolver()

    def run(self, parsed_plan: ParsedPlan) -> ComplianceAnalysisResult:
        """
        Execute compliance analysis.

        Args:
            parsed_plan: Parsed compliance plan

        Returns:
            Complete compliance analysis result
        """
        run_start = datetime.now()
        manifest = self._init_manifest(parsed_plan)

        # Collect all adapter outputs
        all_o2_outputs: list[O2AdapterOutput] = []
        all_h2_outputs: list[H2AdapterOutput] = []
        all_mua_outputs: list[MUAAdapterOutput] = []

        # Step 1: Resolve materials
        manifest.log_decision("phase_start", {"phase": "material_resolution"})
        for material in parsed_plan.materials:
            resolution = self.resolver.resolve(
                maptis_code=material.get("maptis_code"),
                material_name=material.get("name"),
                material_spec=material.get("spec"),
            )
            resolution.should_flag_h2_risk()  # Fran Fix #5
            manifest.material_resolutions.append(resolution)

            if resolution.h2_token_match_risk:
                manifest.materials_with_h2_token_risk += 1

            if resolution.ambiguous:
                manifest.materials_with_ambiguous_resolution += 1

        manifest.total_materials_evaluated = len(manifest.material_resolutions)
        manifest.log_decision("phase_complete", {
            "phase": "material_resolution",
            "resolved": sum(1 for r in manifest.material_resolutions if r.resolved),
            "unresolved": sum(1 for r in manifest.material_resolutions if not r.resolved),
        })

        # Step 2: Route and call adapters
        # NOTE: We do NOT skip unresolved materials - adapters handle them
        # and generate MISSING_DATA gap signals appropriately
        manifest.log_decision("phase_start", {"phase": "adapter_evaluation"})
        for resolution in manifest.material_resolutions:
            for environment in parsed_plan.environments:
                routing = self._make_routing_decision(resolution, environment)
                manifest.routing_decisions.append(routing)

                if routing.route_to_o2:
                    output = self.o2_adapter.evaluate(resolution, environment)
                    all_o2_outputs.append(output)
                    manifest.o2_adapter_outputs.append(output)

                if routing.route_to_h2:
                    output = self.h2_adapter.evaluate(resolution, environment)
                    all_h2_outputs.append(output)
                    manifest.h2_adapter_outputs.append(output)

        manifest.log_decision("phase_complete", {
            "phase": "adapter_evaluation",
            "o2_evaluations": len(all_o2_outputs),
            "h2_evaluations": len(all_h2_outputs),
        })

        # Step 3: MAP SIGNALS TO MPRs (THIS IS THE KEY STEP)
        manifest.log_decision("phase_start", {"phase": "signal_to_mpr_mapping"})
        env_context = self._build_env_context(parsed_plan)
        mpr_determinations = self._map_signals_to_mprs(
            o2_outputs=all_o2_outputs,
            h2_outputs=all_h2_outputs,
            env_context=env_context,
        )
        manifest.log_decision("phase_complete", {
            "phase": "signal_to_mpr_mapping",
            "determinations": len(mpr_determinations),
        })

        # Step 4: Determine which materials need MUAs
        manifest.log_decision("phase_start", {"phase": "mua_determination"})
        gap_signals_requiring_mua = self._filter_signals_requiring_mua(
            o2_outputs=all_o2_outputs,
            h2_outputs=all_h2_outputs,
        )

        # Step 5: Generate MUAs
        for signal_group in self._group_signals_by_material(
            gap_signals_requiring_mua, manifest.material_resolutions, parsed_plan.environments
        ):
            mua_output = self.mua_adapter.generate(
                signals=signal_group["signals"],
                material=signal_group["material"],
                environment=signal_group["environment"],
            )
            all_mua_outputs.append(mua_output)
            manifest.mua_adapter_outputs.append(mua_output)
            manifest.materials_requiring_mua += 1

        manifest.mua_llm_invocations.extend(self.mua_adapter.get_llm_invocations())
        self.mua_adapter.clear_llm_invocations()

        manifest.log_decision("phase_complete", {
            "phase": "mua_determination",
            "muas_generated": len(all_mua_outputs),
        })

        # Update manifest summary
        self._update_manifest_summary(manifest, mpr_determinations)

        # Build gap summaries
        gap_summaries = self._build_gap_summaries(
            o2_outputs=all_o2_outputs,
            h2_outputs=all_h2_outputs,
        )

        # Collect all constraints
        all_constraints = []
        for det in mpr_determinations:
            all_constraints.extend(det.operational_constraints)

        # Calculate run duration
        manifest.run_duration_ms = int((datetime.now() - run_start).total_seconds() * 1000)

        result = ComplianceAnalysisResult(
            plan_id=parsed_plan.plan_id,
            plan_version=parsed_plan.version,
            analysis_timestamp=run_start,
            standard_version=self.mpr_index.standard_version,
            mpr_index_version=self.mpr_index.standard_version,
            environment_policy=self.environment_policy,
            manifest=manifest,
            mpr_determinations=mpr_determinations,
            mua_outputs=all_mua_outputs,
            gap_summaries=gap_summaries,
            all_constraints=all_constraints,
        )

        result.compute_summary()
        return result

    def _init_manifest(self, parsed_plan: ParsedPlan) -> RunManifest:
        """Initialize run manifest."""
        return RunManifest(
            run_id=str(uuid.uuid4())[:12],
            run_timestamp=datetime.now(),
            inputs=[
                {
                    "type": "plan",
                    "plan_id": parsed_plan.plan_id,
                    "version": parsed_plan.version,
                }
            ],
            environment_policy_version=self.environment_policy.version,
            mpr_index_version=self.mpr_index.standard_version,
            conductor_policy_version=self.conductor_policy.version,
            o2_twin_version=self.o2_adapter.version,
            h2_twin_version=self.h2_adapter.version,
            mua_generator_version=self.mua_adapter.version,
        )

    def _make_routing_decision(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> PolicyRoutingDecision:
        """Make routing decision for material/environment pair."""
        route_to_o2 = self.environment_policy.requires_o2_twin(environment)
        route_to_h2 = self.environment_policy.requires_h2_twin(environment)

        return PolicyRoutingDecision(
            material_id=material.canonical_material_id or "",
            environment_id=environment.environment_id,
            route_to_o2=route_to_o2,
            route_to_o2_reason="O2 environment detected" if route_to_o2 else "Not O2 environment",
            route_to_h2=route_to_h2,
            route_to_h2_reason="H2 environment detected" if route_to_h2 else "Not H2 environment",
            policy_version=self.environment_policy.version,
        )

    def _build_env_context(self, parsed_plan: ParsedPlan) -> dict:
        """Build environment context for MPR applicability."""
        context = {}
        for env in parsed_plan.environments:
            # Merge environment attributes into context
            context["is_oxygen_enriched"] = context.get("is_oxygen_enriched", False) or env.is_oxygen_enriched
            context["oxygen_pct"] = max(context.get("oxygen_pct", 21.0), env.oxygen_pct)
            context["is_hydrogen_service"] = context.get("is_hydrogen_service", False) or env.is_hydrogen_service
            context["is_habitable"] = context.get("is_habitable", False) or env.is_habitable
            context["is_cryogenic"] = context.get("is_cryogenic", False) or env.is_cryogenic
            context["pressure_is_high"] = context.get("pressure_is_high", False) or env.pressure_is_high
        return context

    def _map_signals_to_mprs(
        self,
        o2_outputs: list[O2AdapterOutput],
        h2_outputs: list[H2AdapterOutput],
        env_context: dict,
    ) -> list[MPRDetermination]:
        """
        Map adapter signals to MPR determinations.

        Fran Fix #1: This is the ONLY place that maps signals to MPRs.
        Fran Fix #8: Uses MPRIndex.get_mprs_for_signal(), no [0] selection.
        """
        # Initialize determinations for all applicable MPRs
        applicable_mprs = self.mpr_index.get_applicable(env_context)
        determinations: dict[int, MPRDetermination] = {}

        for mpr in applicable_mprs:
            determinations[mpr.mpr_number] = MPRDetermination(
                mpr_number=mpr.mpr_number,
                mpr_section=mpr.section,
                mpr_title=mpr.title,
                mpr_source_evidence=mpr.source_evidence,
                applicability_status=ApplicabilityStatus.APPLICABLE,
                applicability_rationale="Environment triggers present",
                compliant=ComplianceStatus.COMPLIANT,  # Default, may be downgraded
                compliance_basis=ComplianceBasis.NOT_APPLICABLE,
                gap_signals=[],
                operational_constraints=[],
            )

        # Collect all signals from adapters
        all_signals: list[GapSignal] = []
        for output in o2_outputs:
            all_signals.extend(output.gap_signals)
        for output in h2_outputs:
            all_signals.extend(output.gap_signals)

        # Map each signal to ALL matching MPRs (no [0] selection)
        for signal in all_signals:
            matching_mprs = self.mpr_index.get_mprs_for_signal(signal, env_context)

            for mpr in matching_mprs:
                if mpr.mpr_number not in determinations:
                    continue

                det = determinations[mpr.mpr_number]

                # Attach signal
                det.gap_signals.append(signal)

                # Downgrade compliance status based on signal severity
                new_status = self._signal_to_compliance_status(signal, det.compliant)
                if self._is_worse_status(new_status, det.compliant):
                    det.compliant = new_status
                    det.compliance_basis = signal.suggested_basis
                    det.compliance_rationale = signal.summary

                # Determine required action (Fran Fix #3)
                det.required_action = self._determine_required_action(
                    status=det.compliant,
                    signal=signal,
                    env_context=env_context,
                    has_constraints=len(det.operational_constraints) > 0,
                )

                # Mark if MUA required
                if det.required_action == RequiredAction.GENERATE_MUA:
                    det.mua_required = True

        # Attach constraints from H2 outputs
        for output in h2_outputs:
            for constraint in output.operational_constraints:
                # Find relevant MPRs (HEE-related)
                from mira.compliance.models.enums import FailureMode
                hee_mprs = self.mpr_index.get_by_failure_mode(FailureMode.HEE)
                for mpr in hee_mprs:
                    if mpr.mpr_number in determinations:
                        determinations[mpr.mpr_number].operational_constraints.append(constraint)

        # Set compliance_basis from adapter outputs even for OK results (no gaps)
        # This ensures we record that an evaluation was performed
        self._set_basis_from_adapter_outputs(
            determinations=determinations,
            o2_outputs=o2_outputs,
            h2_outputs=h2_outputs,
        )

        return list(determinations.values())

    def _set_basis_from_adapter_outputs(
        self,
        determinations: dict[int, MPRDetermination],
        o2_outputs: list[O2AdapterOutput],
        h2_outputs: list[H2AdapterOutput],
    ) -> None:
        """
        Set compliance_basis from adapter outputs even when there are no gaps.

        This ensures that MPRs show the evaluation method used, not just
        'not_applicable' when the material is OK.
        """
        from mira.compliance.models.enums import FailureMode

        # Map O2 adapter outputs to O2-related MPRs
        o2_failure_modes = [FailureMode.FLAM, FailureMode.O2_PROHIBITED]
        o2_mpr_numbers = set()
        for fm in o2_failure_modes:
            for mpr in self.mpr_index.get_by_failure_mode(fm):
                o2_mpr_numbers.add(mpr.mpr_number)

        # Map H2 adapter outputs to H2-related MPRs
        h2_failure_modes = [FailureMode.HEE]
        h2_mpr_numbers = set()
        for fm in h2_failure_modes:
            for mpr in self.mpr_index.get_by_failure_mode(fm):
                h2_mpr_numbers.add(mpr.mpr_number)

        # Set basis from O2 outputs for O2-related MPRs with no gaps
        if o2_outputs:
            # Use the suggested_basis from the first O2 output that has one
            o2_basis = None
            for output in o2_outputs:
                if output.suggested_basis and output.suggested_basis != ComplianceBasis.NOT_APPLICABLE:
                    o2_basis = output.suggested_basis
                    break

            if o2_basis:
                for mpr_num in o2_mpr_numbers:
                    if mpr_num in determinations:
                        det = determinations[mpr_num]
                        # Only update if no gaps (still at default NOT_APPLICABLE)
                        if det.compliance_basis == ComplianceBasis.NOT_APPLICABLE and len(det.gap_signals) == 0:
                            det.compliance_basis = o2_basis
                            det.compliance_rationale = "O2 Knowledge Twin evaluation - material compatible"

        # Set basis from H2 outputs for H2-related MPRs with no gaps
        if h2_outputs:
            # Use the suggested_basis from the first H2 output that has one
            h2_basis = None
            for output in h2_outputs:
                if output.suggested_basis and output.suggested_basis != ComplianceBasis.NOT_APPLICABLE:
                    h2_basis = output.suggested_basis
                    break

            if h2_basis:
                for mpr_num in h2_mpr_numbers:
                    if mpr_num in determinations:
                        det = determinations[mpr_num]
                        # Only update if no gaps (still at default NOT_APPLICABLE)
                        if det.compliance_basis == ComplianceBasis.NOT_APPLICABLE and len(det.gap_signals) == 0:
                            det.compliance_basis = h2_basis
                            det.compliance_rationale = "H2 Knowledge Twin evaluation - material compatible"

    def _signal_to_compliance_status(
        self,
        signal: GapSignal,
        current_status: ComplianceStatus,
    ) -> ComplianceStatus:
        """Map signal severity to compliance status."""
        if signal.severity == GapSeverity.CRITICAL:
            return ComplianceStatus.NONCOMPLIANT
        elif signal.severity == GapSeverity.HIGH:
            return ComplianceStatus.NONCOMPLIANT
        elif signal.severity == GapSeverity.MEDIUM:
            return ComplianceStatus.COMPLIANT_WITH_CONSTRAINTS
        else:
            return current_status

    def _is_worse_status(
        self,
        new_status: ComplianceStatus,
        current_status: ComplianceStatus,
    ) -> bool:
        """Check if new status is worse than current."""
        order = [
            ComplianceStatus.COMPLIANT,
            ComplianceStatus.COMPLIANT_WITH_CONSTRAINTS,
            ComplianceStatus.UNKNOWN,
            ComplianceStatus.NONCOMPLIANT,
        ]
        return order.index(new_status) > order.index(current_status)

    def _determine_required_action(
        self,
        status: ComplianceStatus,
        signal: GapSignal,
        env_context: dict,
        has_constraints: bool,
    ) -> RequiredAction:
        """
        Determine required action based on status and context.

        Fran Fix #3: CAUTION action depends on policy flags.
        """
        if status == ComplianceStatus.COMPLIANT:
            return RequiredAction.NONE

        elif status == ComplianceStatus.NONCOMPLIANT:
            if signal.severity == GapSeverity.CRITICAL:
                return RequiredAction.SUBSTITUTE_MATERIAL
            else:
                return RequiredAction.GENERATE_MUA

        elif status == ComplianceStatus.COMPLIANT_WITH_CONSTRAINTS:
            # Use policy to determine action (Fran Fix #3)
            return self.conductor_policy.get_caution_action(
                is_habitable=env_context.get("is_habitable", False),
                o2_pct=env_context.get("oxygen_pct", 21.0),
                has_constraints=has_constraints,
            )

        else:  # UNKNOWN
            return RequiredAction.PROVIDE_DATA

    def _filter_signals_requiring_mua(
        self,
        o2_outputs: list[O2AdapterOutput],
        h2_outputs: list[H2AdapterOutput],
    ) -> list[GapSignal]:
        """Filter signals that require MUA generation."""
        signals = []

        for output in o2_outputs:
            for signal in output.gap_signals:
                if signal.requires_mua():
                    signals.append(signal)

        for output in h2_outputs:
            for signal in output.gap_signals:
                if signal.requires_mua():
                    signals.append(signal)

        return signals

    def _group_signals_by_material(
        self,
        signals: list[GapSignal],
        resolutions: list[MaterialResolutionResult],
        environments: list[EnvironmentDefinition],
    ) -> list[dict]:
        """Group signals by material for MUA generation."""
        groups = {}

        for signal in signals:
            key = (signal.material_id, signal.environment_id)
            if key not in groups:
                # Find matching resolution and environment
                resolution = next(
                    (r for r in resolutions if r.canonical_material_id == signal.material_id),
                    None
                )
                environment = next(
                    (e for e in environments if e.environment_id == signal.environment_id),
                    None
                )
                if resolution and environment:
                    groups[key] = {
                        "material": resolution,
                        "environment": environment,
                        "signals": [],
                    }
            if key in groups:
                groups[key]["signals"].append(signal)

        return list(groups.values())

    def _build_gap_summaries(
        self,
        o2_outputs: list[O2AdapterOutput],
        h2_outputs: list[H2AdapterOutput],
    ) -> list[GapSummary]:
        """Build gap summaries by material."""
        summaries_by_key: dict[tuple, list[GapSignal]] = {}

        for output in o2_outputs:
            key = (output.material_id, output.environment_id)
            if key not in summaries_by_key:
                summaries_by_key[key] = []
            summaries_by_key[key].extend(output.gap_signals)

        for output in h2_outputs:
            key = (output.material_id, output.environment_id)
            if key not in summaries_by_key:
                summaries_by_key[key] = []
            summaries_by_key[key].extend(output.gap_signals)

        return [
            GapSummary.from_gaps(gaps, material_id, env_id)
            for (material_id, env_id), gaps in summaries_by_key.items()
        ]

    def _update_manifest_summary(
        self,
        manifest: RunManifest,
        determinations: list[MPRDetermination],
    ) -> None:
        """Update manifest with summary statistics."""
        manifest.total_mprs_evaluated = len(determinations)
        manifest.applicable_mprs = sum(1 for d in determinations if d.is_applicable())
        manifest.not_applicable_by_condition_mprs = sum(
            1 for d in determinations
            if d.applicability_status == ApplicabilityStatus.NOT_APPLICABLE_BY_CONDITION
        )
        manifest.tailored_mprs = sum(
            1 for d in determinations
            if d.applicability_status == ApplicabilityStatus.TAILORED_OUT
        )
        manifest.compliant_mprs = sum(1 for d in determinations if d.is_compliant())
        manifest.compliant_with_constraints_mprs = sum(
            1 for d in determinations if d.is_compliant_with_constraints()
        )
        manifest.noncompliant_mprs = sum(1 for d in determinations if d.is_noncompliant())
        manifest.unknown_mprs = sum(
            1 for d in determinations
            if d.is_applicable() and d.compliant == ComplianceStatus.UNKNOWN
        )

        # Count gaps
        all_gaps = []
        for d in determinations:
            all_gaps.extend(d.gap_signals)
        manifest.total_gap_signals = len(all_gaps)
        manifest.critical_gaps = sum(1 for g in all_gaps if g.is_critical())
        manifest.high_gaps = sum(1 for g in all_gaps if g.severity == GapSeverity.HIGH)
