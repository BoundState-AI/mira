"""
Module: AM Knowledge Twin -- synthetic GRCop-42 demo program (Rev 5 §11)
Purpose: The seeded Demo Track scenario: a NOTIONAL GRCop-42 L-PBF
         combustion-chamber liner program whose registry models realistic
         messiness -- the demo's value is watching the tool FIND the seeded
         problems, not a green board.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True

ITAR HONESTY (Rev 5 §0.5): every value below is obviously notional
("BSI-*" identifiers, round numbers, SYNTHETIC markers). No real Ursa
Major, NASA program, or customer build parameters appear here, ever.
Populating this module with real controlled technical data is the exact
thing gate G2 exists to prevent.

Seeded failures (Rev 5 §11, all four required):
1. Superseded process spec  -- QMP rev A superseded by rev B, registry
   still points at rev A.
2. Missing witness report   -- no EIDP in the registry; [AMR-106] names
   the witness testing report as required EIDP content.
3. Stale NDE reference      -- NDE procedure citing an older revision of
   its governing standard than the frozen baseline.
4. Unresolved conflict      -- synthetic internal witness-sampling spec
   conflicts with [AMR-102]; no approved precedence rule.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from mira.knowledge_twins.am.am_models import (
    AccessContext,
    AMPartClass,
    AMProcess,
    AMRequest,
    ClassificationInput,
    ConsequenceTier,
    DataClassification,
    FeedstockInput,
    HazardFlag,
    MaterialType,
    ControlledArtifact,
    EvidenceRecord,
    ProcessQualStatus,
    ProgramContext,
)
from mira.knowledge_twins.am.crosswalk_models import ConflictSet

SYNTHETIC_MARKER = "SYNTHETIC DEMO DATA — notional values, no real program data"


def demo_access_context() -> AccessContext:
    """Demo boundary: public sources only, clean US-person box."""
    return AccessContext(
        tenant_id="boundstate-demo",
        program_ids=["BSI-DEMO-LINER"],
        permitted_source_classes=["public", "boundstate_owned"],
        deployment_boundary="demo-public-box",
        max_data_classification=DataClassification.PUBLIC,
    )


def demo_program_context() -> ProgramContext:
    """The seeded synthetic registry (manual entry -> NON_AUTHORITATIVE)."""
    registry = [
        ControlledArtifact(
            artifact_type="AMCP",
            artifact_id="BSI-AMCP-001",
            state="approved",
            version="Rev A",
            approval_authority="BSI M&P (synthetic)",
            governing_clauses=["REQ:NASA-STD-6030:AMR-2"],
        ),
        # Seeded failure 1: superseded QMP, registry still cites Rev A.
        ControlledArtifact(
            artifact_type="QMP",
            artifact_id="BSI-QMP-A-017 Rev A",
            state="approved",
            version="Rev A",
            superseded_by="BSI-QMP-A-017 Rev B",
            governing_clauses=["REQ:NASA-STD-6030:AMR-60"],
        ),
        ControlledArtifact(
            artifact_type="MPS",
            artifact_id="BSI-MPS-GRCOP42-001",
            state="approved",
            version="Rev A",
            governing_clauses=["REQ:NASA-STD-6030:AMR-61"],
        ),
        ControlledArtifact(
            artifact_type="PPP",
            artifact_id="BSI-PPP-LINER-001",
            state="in_review",
            version="Draft 3",
            governing_clauses=["REQ:NASA-STD-6030:AMR-97"],
        ),
        ControlledArtifact(
            artifact_type="EFCP",
            artifact_id="BSI-EFCP-001",
            state="approved",
            version="Rev A",
            governing_clauses=["REQ:NASA-STD-6030:AMR-14"],
        ),
        # Seeded failure 3: NDE procedure citing an older 6033 revision than
        # the frozen baseline version.
        ControlledArtifact(
            artifact_type="NDE",
            artifact_id="BSI-NDE-CT-009",
            state="approved",
            version="Rev C",
            referenced_standard_version="NASA-STD-6033:0.9-draft",
            governing_clauses=["REQ:NASA-STD-6030:AMR-17"],
        ),
        # Seeded failure 2 is an ABSENCE: no EIDP artifact in the registry,
        # so the witness testing report required by [AMR-106] has no home.
    ]
    evidence = [
        # MPS satisfied at L2: linked to a build, but no coupon/serial trace.
        EvidenceRecord(
            record_id="BSI-EV-001",
            artifact_ref="BSI-MPS-GRCOP42-001",
            evidence_depth=2,
            build_id="BSI-BUILD-0042",
            machine_id="BSI-LPBF-03",
        ),
        # AMCP exists with no linkage records: L1 only.
    ]
    return ProgramContext(
        program_id="BSI-DEMO-LINER",
        artifact_registry=registry,
        evidence_records=evidence,
        applicable_standards=["NASA-STD-6030", "NASA-STD-6033"],
        registry_source=None,  # manual entry => NON_AUTHORITATIVE (Rev 5 §5.2)
        recorded_conflicts=[c.model_dump(mode="json") for c in demo_conflicts()],
    )


def demo_conflicts() -> list[ConflictSet]:
    """Seeded failure 4: unresolved high-impact requirement conflict."""
    return [
        ConflictSet(
            conflict_id="BSI-CONFLICT-001",
            requirement_ids=[
                "REQ:NASA-STD-6030:AMR-102",
                "REQ:BSI-INTERNAL-WT-SPEC:3.2 (synthetic)",
            ],
            description=(
                "Synthetic internal witness-sampling spec BSI-WT-3.2 requires "
                "2 tensile witness coupons per build plate; [AMR-102] PPP "
                "witness description derives from NASA-STD-6030 §4.11 "
                "requirements that the seeded program documented differently. "
                "No approved PrecedenceRule resolves which governs. "
                f"({SYNTHETIC_MARKER})"
            ),
            resolved=False,
            high_impact=True,
        )
    ]


def demo_request() -> AMRequest:
    """GC-1: the notional Class A GRCop-42 L-PBF liner request."""
    return AMRequest(
        part_description=(
            "Regeneratively cooled combustion-chamber liner, L-PBF "
            f"({SYNTHETIC_MARKER})"
        ),
        material_designation="GRCop-42",
        classification=ClassificationInput(
            classification_framework="NASA-STD-6030",
            intended_class=AMPartClass.CLASS_A,
            consequence_of_failure=ConsequenceTier.CATASTROPHIC,
            hazard_context=[
                HazardFlag.FRACTURE_CRITICAL,
                HazardFlag.PRESSURE_VESSEL,
            ],
            fluid_service="LOX/RP-1 (notional duty cycle)",
            mission_critical=True,
            safety_critical_confirmed=True,
        ),
        am_process=AMProcess.L_PBF,
        material_type=MaterialType.METALLIC,
        feedstock=FeedstockInput(
            powder_spec="BSI-PWDR-GRCOP42-SPEC (synthetic)",
            lot_id="BSI-LOT-2026-001",
            reuse_count=2,
            reuse_history_available=True,
        ),
        process_qual=ProcessQualStatus(
            machine_id="BSI-LPBF-03",
            process_spec="BSI-PS-LPBF-001 (synthetic)",
            machine_qualified=True,
            # Deliberately cites the SUPERSEDED QMP revision (seeded failure
            # 1). The doc-gap engine flags the registry artifact; the
            # request-vs-registry cross-check that would also flag this
            # field is PR-5 synthesis work and is not yet evaluated.
            qmp_reference="BSI-QMP-A-017 Rev A",
        ),
        access=demo_access_context(),
        data_classification=DataClassification.PUBLIC,
        safety_critical_confirmed=True,
        program=demo_program_context(),
    )
