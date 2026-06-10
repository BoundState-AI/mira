"""
Module: AM Knowledge Twin -- QMP/MPS & documentation-set gap engine (Rev 5 §6.4)
Purpose: Derive the required controlled-document set for a part class from
         the frozen requirement text, then (assessed mode) check a program's
         artifact registry for existence, state, currency-by-supersession,
         referenced-standard staleness, and evidence depth.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True

Honesty invariants:
- The required artifact set is DERIVED: an artifact type is required for a
  class iff an applicable (class-scoped-in) frozen requirement names it.
  No hand-maintained per-class checklist exists to drift from the source.
- Assessed-mode claims are stated at their evidence depth (L1/L2/L3) and
  never inflated; manual registries are labeled NON_AUTHORITATIVE.
- Property-level MPS allowables are NOT fabricated: MPS status is reported
  at requirement level against the registry; the property-by-property
  matrix requires §6.11 table ingestion and is named as not yet ingested.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from mira.knowledge_twins.am.am_models import (
    ControlledArtifact,
    EvidenceRecord,
    ProgramContext,
)
from mira.knowledge_twins.am.engines.applicability import ApplicabilityResult
from mira.knowledge_twins.am.engines.crosswalk import (
    ARTIFACT_PATTERNS,
    CONTROLLED_ARTIFACT_TYPES,
)


class AuthorityLabel(str, Enum):
    """Rev 5 §5.2 output authority levels. SYSTEM_VERIFIED requires
    freshness/hash/sync checks that are Product Track; not emitted here."""

    CHECKLIST = "CHECKLIST"
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE"
    SYSTEM_SOURCED = "SYSTEM_SOURCED"


class GapSeverity(str, Enum):
    MISSING = "missing"
    STATE = "state"
    SUPERSEDED = "superseded"
    STALE_REFERENCE = "stale_reference"
    EVIDENCE_DEPTH = "evidence_depth"


class RequiredArtifact(BaseModel):
    """An artifact type required for the class, with citing requirements."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    required_by: list[str]  # requirement_ids whose frozen text names it


class DocGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    severity: GapSeverity
    detail: str
    governing_requirements: list[str] = Field(default_factory=list)
    closing_action: str = ""


class SatisfiedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    artifact_id: Optional[str]
    evidence_depth: int = Field(ge=1, le=3)  # Rev 5 §5.3; never inflated
    detail: str


class DocGapResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority: AuthorityLabel
    required: list[RequiredArtifact]
    satisfied: list[SatisfiedArtifact] = Field(default_factory=list)
    gaps: list[DocGap] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def derive_required_artifacts(
    applicability: ApplicabilityResult,
) -> list[RequiredArtifact]:
    """Required doc set = artifact types named by applicable requirements."""
    citing: dict[str, list[str]] = {}
    for req in applicability.applicable:
        for acronym in CONTROLLED_ARTIFACT_TYPES:
            if ARTIFACT_PATTERNS[acronym].search(req.shall_text):
                citing.setdefault(acronym, []).append(req.requirement_id)
    return [
        RequiredArtifact(artifact_type=a, required_by=sorted(set(reqs)))
        for a, reqs in sorted(citing.items())
    ]


def _artifact_gaps(
    required: RequiredArtifact,
    artifact: ControlledArtifact,
    pack_versions: dict[str, str],
) -> list[DocGap]:
    gaps: list[DocGap] = []
    if artifact.superseded_by:
        gaps.append(
            DocGap(
                artifact_type=required.artifact_type,
                severity=GapSeverity.SUPERSEDED,
                detail=(
                    f"{artifact.artifact_id or required.artifact_type} is "
                    f"superseded by {artifact.superseded_by}; the registry "
                    "still references the superseded revision (currency by "
                    "supersession, not expiry)."
                ),
                governing_requirements=required.required_by,
                closing_action=(
                    f"Re-baseline against {artifact.superseded_by} and update "
                    "the registry reference."
                ),
            )
        )
    elif artifact.state != "approved":
        gaps.append(
            DocGap(
                artifact_type=required.artifact_type,
                severity=GapSeverity.STATE if artifact.state != "missing" else GapSeverity.MISSING,
                detail=(
                    f"{required.artifact_type} is in state "
                    f"{artifact.state!r}; an approved revision is required."
                ),
                governing_requirements=required.required_by,
                closing_action=f"Complete approval workflow for {required.artifact_type}.",
            )
        )
    ref = artifact.referenced_standard_version
    # A superseded artifact's single closing action (re-baseline) subsumes
    # any stale reference it carries; do not double-report one root cause.
    if ref and not artifact.superseded_by:
        # Stale if it cites a standard we have frozen at a different version.
        # Exact-token comparison: "<standard_id>:<version>" -- bare prefix/
        # suffix matching misfires on substring IDs and versions.
        for standard_id, version in pack_versions.items():
            prefix = f"{standard_id}:"
            if not ref.startswith(prefix):
                continue
            cited_version = ref[len(prefix):]
            if cited_version != version:
                gaps.append(
                    DocGap(
                        artifact_type=required.artifact_type,
                        severity=GapSeverity.STALE_REFERENCE,
                        detail=(
                            f"{artifact.artifact_id or required.artifact_type} "
                            f"references {ref}, but the frozen baseline for "
                            f"{standard_id} is version {version}."
                        ),
                        governing_requirements=required.required_by,
                        closing_action=(
                            f"Review against {standard_id} {version} and "
                            "update the procedure reference."
                        ),
                    )
                )
    return gaps


def _evidence_depth(
    artifact: ControlledArtifact, records: list[EvidenceRecord]
) -> tuple[int, bool]:
    """L1 = exists; L2 = linked to build/lot/machine; L3 = full trace
    (lot AND build AND coupon/part serials resolvable). Rev 5 §5.3.

    Returns (depth, linkage_confirmable). An artifact with no artifact_id
    cannot be matched to evidence records at all: depth is L1 and
    linkage_confirmable is False, so the output can say WHY rather than
    silently under-reporting traceability that may exist.
    """
    if artifact.artifact_id is None:
        return 1, False
    linked = [r for r in records if r.artifact_ref == artifact.artifact_id]
    if not linked:
        return 1, True
    depth = 1
    for record in linked:
        has_link = any((record.powder_lot_id, record.build_id, record.machine_id))
        full_trace = (
            record.powder_lot_id
            and record.build_id
            and (record.coupon_ids or record.part_serials)
        )
        if full_trace:
            depth = max(depth, min(record.evidence_depth, 3))
        elif has_link:
            depth = max(depth, min(record.evidence_depth, 2))
    return depth, True


def evaluate_doc_gap(
    applicability: ApplicabilityResult,
    program: Optional[ProgramContext],
    pack_versions: Optional[dict[str, str]] = None,
) -> DocGapResult:
    """Engine 6.4 (documentation set): checklist or assessed mode.

    ``pack_versions`` maps standard_id -> frozen pack version for staleness
    checks (taken from the loaded FrozenRulePacks, not hardcoded).
    """
    required = derive_required_artifacts(applicability)
    notes = [
        "Property-level MPS allowables matrix not evaluated: NASA-STD-6030 "
        "§6.11 tables are not yet ingested as structured rules; MPS status "
        "is reported at requirement level only. The tool never fabricates "
        "an allowable (Rev 5 §3)."
    ]

    if program is None or not program.artifact_registry:
        return DocGapResult(
            authority=AuthorityLabel.CHECKLIST,
            required=required,
            notes=notes
            + [
                "Checklist mode: no program registry supplied; listing the "
                "required controlled-document set for the declared class."
            ],
        )

    authority = (
        AuthorityLabel.SYSTEM_SOURCED
        if program.registry_source
        else AuthorityLabel.NON_AUTHORITATIVE
    )
    if authority is AuthorityLabel.NON_AUTHORITATIVE:
        notes.append(
            "Registry was manually entered (no system of record): output is "
            "NON_AUTHORITATIVE engineer-review input, not audit evidence "
            "(Rev 5 §5.2)."
        )

    by_type: dict[str, list[ControlledArtifact]] = {}
    for artifact in program.artifact_registry:
        by_type.setdefault(artifact.artifact_type, []).append(artifact)

    satisfied: list[SatisfiedArtifact] = []
    gaps: list[DocGap] = []
    versions = pack_versions or {}

    for req_artifact in required:
        artifacts = by_type.get(req_artifact.artifact_type, [])
        if not artifacts:
            gaps.append(
                DocGap(
                    artifact_type=req_artifact.artifact_type,
                    severity=GapSeverity.MISSING,
                    detail=(
                        f"No {req_artifact.artifact_type} in the program "
                        "registry, but it is named by "
                        f"{len(req_artifact.required_by)} applicable "
                        "requirement(s)."
                    ),
                    governing_requirements=req_artifact.required_by,
                    closing_action=(
                        f"Create and approve the {req_artifact.artifact_type} "
                        "or register the existing document."
                    ),
                )
            )
            continue
        for artifact in artifacts:
            artifact_gaps = _artifact_gaps(req_artifact, artifact, versions)
            gaps.extend(artifact_gaps)
            blocking = {GapSeverity.MISSING, GapSeverity.STATE, GapSeverity.SUPERSEDED}
            if not any(g.severity in blocking for g in artifact_gaps):
                depth, confirmable = _evidence_depth(
                    artifact, program.evidence_records
                )
                if not confirmable:
                    suffix = (
                        " (no artifact_id registered: evidence linkage cannot "
                        "be confirmed; depth above L1 may exist but is not "
                        "claimable)."
                    )
                elif depth < 3:
                    suffix = (
                        f" (higher-depth gap: no L{depth + 1} linkage in "
                        "evidence records)."
                    )
                else:
                    suffix = " (full lot->build->coupon/serial trace)."
                satisfied.append(
                    SatisfiedArtifact(
                        artifact_type=req_artifact.artifact_type,
                        artifact_id=artifact.artifact_id,
                        evidence_depth=depth,
                        detail=f"Approved and current; satisfied at L{depth}{suffix}",
                    )
                )

    return DocGapResult(
        authority=authority,
        required=required,
        satisfied=satisfied,
        gaps=gaps,
        notes=notes,
    )
