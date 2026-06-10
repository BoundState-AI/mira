"""
Module: AM Knowledge Twin -- package synthesis engine (Rev 5 §6.7, §7, PR-5)
Purpose: Orchestrate the engines into one AMQualificationPackage with
         top-of-output authority/mode/coverage/evidence-depth labels, a
         capped verdict, a deterministic confidence rubric, and an
         evaluation snapshot. The synthesizer refuses certifying phrasing.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True

Verdict policy (deterministic; every cap cites its rule):
- Unconfirmed safety-critical inputs, unknown data classification, or a
  missing AccessContext -> BLOCKED (Rev 5 §5.1, §4.5; GC-18). Never proceed.
- Unsupported classification framework or unvalidatable class ->
  CANNOT_VALIDATE (Rev 5 §6.3; GC-5/GC-6).
- Declared-class MISMATCH -> BLOCKED with the mismatch rationale (GC-4):
  a qualification package against a wrong class is not conditionally
  passable.
- Corpus coverage INSUFFICIENT -> REQUIRES_ADDITIONAL_EVIDENCE (GC-17).
- Corpus coverage PARTIAL also -> REQUIRES_ADDITIONAL_EVIDENCE: a missing
  required family is missing evidence, not a conditional pass (GC-17).
- Any doc gap, unresolved HIGH-IMPACT conflict, or UNVERIFIED rule pack
  caps at CONDITIONAL_PASS_WITH_GAPS -- a PASS can never be produced from
  unverified packs (Rev 5 §4.3) or past an unresolved high-impact conflict
  (Rev 5 §4.2). Low-impact unresolved conflicts are surfaced, not capping.
- PASS only when: coverage FULL, no gaps, no unresolved high-impact
  conflicts, all packs VERIFIED.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError

from mira.knowledge_twins.am.am_models import AMRequest
from mira.knowledge_twins.am.classification_model import SecondaryInputs
from mira.knowledge_twins.am.content_store import AMContentStore
from mira.knowledge_twins.am.crosswalk_models import ConflictSet
from mira.knowledge_twins.am.engines.applicability import (
    ApplicabilityResult,
    CoverageLevel,
    evaluate_applicability,
)
from mira.knowledge_twins.am.engines.classification import (
    ClassificationResult,
    evaluate_classification,
)
from mira.knowledge_twins.am.engines.crosswalk import build_crosswalk
from mira.knowledge_twins.am.engines.qmp_gap import (
    AuthorityLabel,
    DocGapResult,
    evaluate_doc_gap,
)
from mira.knowledge_twins.am.rule_pack_models import VerificationStatus

LOGGER = logging.getLogger(__name__)

# Test-activity vocabulary for the baseline matrix: a requirement enters the
# matrix iff its frozen text names one of these verification activities.
_TEST_ACTIVITY = re.compile(
    r"\b(witness test|witness specimen|proof test|qualification test|"
    r"acceptance test|NDE|nondestructive|tensile)\b",
    re.IGNORECASE,
)

_NON_CERTIFYING_BANNER = (
    "Audit-prep / gap report for engineer review. Not a qualification, "
    "certification, or acceptance record; M&P, FCB, MRB, and NADCAP/customer "
    "sign-off authorities are not replaced (Rev 5 §10)."
)


class EvidenceDepthLabel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ApplicabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage_statement: str
    applicable_requirements: list[str]
    excluded_by_class: list[str]
    notes: list[str] = Field(default_factory=list)


class GapAnalysis(BaseModel):
    """Gap lists rendered as engineer-readable strings, each citing its
    governing requirements."""

    model_config = ConfigDict(extra="forbid")

    qmp_gaps: list[str] = Field(default_factory=list)
    mps_gaps: list[str] = Field(default_factory=list)
    document_gaps: list[str] = Field(default_factory=list)


class TestMatrixItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_id: str  # the governing requirement id
    description: str
    # The depth at which the resulting record must link into the digital
    # thread to close this line: L2 = linked to this build/lot (Rev 5 §5.3
    # linkage definition). This is the tool's bookkeeping expectation, not a
    # standard-derived value.
    evidence_depth: EvidenceDepthLabel = EvidenceDepthLabel.L2


class TestMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TestMatrixItem] = Field(default_factory=list)
    enrichment_notice: Optional[str] = None


class AMQualificationPackage(BaseModel):
    """The synthesized package (Rev 5 §1). Labels render at the top."""

    model_config = ConfigDict(extra="forbid")

    overall_verdict: str
    verdict_basis: list[str]
    mode: str
    authority: str
    coverage: str
    evidence_depth: str
    banner: str = _NON_CERTIFYING_BANNER
    classification: ClassificationResult
    applicability: ApplicabilitySummary
    gap_analysis: GapAnalysis
    conflicts: list[ConflictSet] = Field(default_factory=list)
    test_matrix: TestMatrix
    confidence: float
    confidence_breakdown: dict[str, float]
    notes: list[str] = Field(default_factory=list)
    evaluation_snapshot: dict = Field(default_factory=dict)


def _request_hash(request: AMRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot(request: AMRequest, pack_entries: list[dict]) -> dict:
    """Evaluation snapshot (Rev 5 §7).

    ``content_basis_sha256`` is the replay-equivalence key: identical request
    + identical frozen baseline => identical value. ``evaluated_at`` is a
    recording timestamp EXCLUDED from replay equivalence by design --
    compare content_basis_sha256, not the whole dict.
    """
    request_sha = _request_hash(request)
    basis = json.dumps(
        {
            "request_sha256": request_sha,
            "rule_packs": sorted(
                (p["rule_pack_id"], p["version"], p["source_document_hash"])
                for p in pack_entries
            ),
            "engine_version": __version__,
        },
        sort_keys=True,
    )
    return {
        "request_sha256": request_sha,
        "rule_packs": pack_entries,
        "engine_version": __version__,
        "content_basis_sha256": hashlib.sha256(basis.encode("utf-8")).hexdigest(),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def _confidence(
    request: AMRequest,
    coverage: CoverageLevel,
    doc: DocGapResult,
    packs_verified_fraction: float,
) -> tuple[float, dict[str, float]]:
    """Deterministic rubric (Rev 5 §7): equal-weight mean of named
    components, each in [0, 1], reproducible for identical inputs. The
    breakdown ships with the number so it explains itself."""
    inputs_present = [
        request.am_process is not None,
        request.material_type is not None,
        request.feedstock is not None,
        request.process_qual is not None,
        request.design is not None,
        request.program is not None,
    ]
    coverage_score = {
        CoverageLevel.FULL: 1.0,
        CoverageLevel.PARTIAL: 0.5,
        CoverageLevel.INSUFFICIENT: 0.0,
    }[coverage]
    if doc.satisfied:
        evidence_score = sum(s.evidence_depth for s in doc.satisfied) / (
            3 * len(doc.satisfied)
        )
    else:
        evidence_score = 0.0
    authority_score = {
        AuthorityLabel.CHECKLIST: 0.5,
        AuthorityLabel.NON_AUTHORITATIVE: 0.5,
        AuthorityLabel.SYSTEM_SOURCED: 1.0,
    }[doc.authority]
    breakdown = {
        "input_completeness": sum(inputs_present) / len(inputs_present),
        "corpus_coverage": coverage_score,
        "rule_pack_verification": packs_verified_fraction,
        "evidence_depth": evidence_score,
        "registry_authority": authority_score,
    }
    return round(sum(breakdown.values()) / len(breakdown), 3), breakdown


def _blocked(request: AMRequest, reason: str, basis: str) -> AMQualificationPackage:
    return AMQualificationPackage(
        overall_verdict="BLOCKED",
        verdict_basis=[basis],
        mode="not evaluated",
        authority="none",
        coverage="not consulted",
        evidence_depth="not evaluated",
        classification=ClassificationResult(
            verdict="CANNOT_VALIDATE",
            framework=request.classification.classification_framework,
            framework_supported=False,
            declared_class=request.classification.intended_class,
            expected_class=None,
            reason=reason,
        ),
        applicability=ApplicabilitySummary(
            coverage_statement="Not consulted: evaluation blocked before retrieval.",
            applicable_requirements=[],
            excluded_by_class=[],
        ),
        gap_analysis=GapAnalysis(),
        test_matrix=TestMatrix(),
        confidence=0.0,
        confidence_breakdown={},
        notes=[reason],
        evaluation_snapshot=_snapshot(request, []),
    )


def evaluate_am_package(
    request: AMRequest,
    store: Optional[AMContentStore] = None,
    secondary_inputs: Optional[SecondaryInputs] = None,
) -> AMQualificationPackage:
    """Rev 5 §6.7: full package synthesis with capped verdict."""
    # --- gates (Rev 5 §5.1, §4.5) -- never proceed past a failed gate ----
    if not request.safety_critical_confirmed:
        return _blocked(
            request,
            "Safety-critical inputs (consequence/hazard/class) are not "
            "engineer-confirmed; evaluation requires explicit confirmation "
            "(Rev 5 §5.1, GC-18).",
            "gate:safety_critical_confirmed",
        )
    if request.data_classification is None:
        return _blocked(
            request,
            "data_classification is undeclared (UNKNOWN). Unknown or mixed "
            "classification is quarantined, never processed (Rev 5 §4.5).",
            "gate:data_classification_unknown",
        )
    if request.access is None:
        return _blocked(
            request,
            "No AccessContext supplied; retrieval is deny-by-default "
            "(Rev 5 §4.5, §8).",
            "gate:access_context_missing",
        )

    content = store or AMContentStore()

    # --- engines ---------------------------------------------------------
    classification = evaluate_classification(
        request.classification,
        material_type=request.material_type,
        am_process=request.am_process,
        secondary_inputs=secondary_inputs,
    )
    applicability = evaluate_applicability(
        content, request.access, request.classification.intended_class
    )
    crosswalk = build_crosswalk(content, request.access)

    pack_versions: dict[str, str] = {}
    pack_entries: list[dict] = []
    verified = 0
    for standard_id in applicability.coverage.families_present:
        pack = content.load_pack(standard_id, request.access)
        pack_versions[standard_id] = pack.version
        pack_entries.append(
            {
                "rule_pack_id": pack.rule_pack_id,
                "standard_id": pack.standard_id,
                "version": pack.version,
                "source_document_hash": pack.source_document_hash,
                "verification_status": pack.verification_status.value,
            }
        )
        if pack.verification_status is VerificationStatus.VERIFIED:
            verified += 1
    packs_verified_fraction = verified / len(pack_entries) if pack_entries else 0.0

    doc = evaluate_doc_gap(applicability, request.program, pack_versions)

    conflicts: list[ConflictSet] = []
    if request.program:
        for raw in request.program.recorded_conflicts:
            try:
                conflicts.append(ConflictSet.model_validate(raw))
            except ValidationError as exc:
                LOGGER.error("[AM engine] Invalid recorded conflict: %s", exc)
                raise

    # --- gap rendering ----------------------------------------------------
    def _render(gaps, types: set[str]) -> list[str]:
        return [
            f"[{g.severity.value}] {g.artifact_type}: {g.detail} "
            f"(governs: {', '.join(g.governing_requirements[:3])}"
            + ("..." if len(g.governing_requirements) > 3 else "")
            + (f" | action: {g.closing_action}" if g.closing_action else "")
            + ")"
            for g in doc.gaps
            if g.artifact_type in types
        ]

    all_types = {g.artifact_type for g in doc.gaps}
    qmp_types = {"QMP", "QPP"} & all_types
    mps_types = {"MPS", "PCRD"} & all_types
    other_types = all_types - qmp_types - mps_types
    gap_analysis = GapAnalysis(
        qmp_gaps=_render(doc.gaps, qmp_types),
        mps_gaps=_render(doc.gaps, mps_types),
        document_gaps=_render(doc.gaps, other_types),
    )
    total_gaps = len(doc.gaps)

    # --- baseline test matrix (test-activity requirements) ----------------
    items = [
        TestMatrixItem(
            test_id=req.requirement_id,
            description=(req.shall_text[:240] + ("..." if len(req.shall_text) > 240 else "")),
        )
        for req in applicability.applicable
        if _TEST_ACTIVITY.search(req.shall_text)
    ]
    test_matrix = TestMatrix(
        items=items,
        enrichment_notice=(
            None
            if request.design is not None
            else (
                "Baseline standards matrix only: program-specific test "
                "planning requires DesignPartInput (geometry_class, "
                "build_orientation, post_process_route, service_conditions, "
                "load_case, acceptance_criteria) -- Rev 5 §6.5, GC-11."
            )
        ),
    )

    # --- verdict (policy in module docstring; every cap cited) ------------
    basis: list[str] = []
    unresolved_conflicts = [c for c in conflicts if not c.resolved]
    if classification.verdict == "CANNOT_VALIDATE":
        verdict = "CANNOT_VALIDATE"
        basis.append("classification: " + classification.reason)
    elif classification.verdict == "MISMATCH":
        verdict = "BLOCKED"
        basis.append(
            "Declared class mismatch: a qualification package cannot proceed "
            "against the wrong class ([AMR-5]/[AMR-6]). " + classification.reason
        )
    elif applicability.coverage.level is not CoverageLevel.FULL:
        # GC-17: ANY missing required family caps the verdict -- PARTIAL is
        # not conditionally passable, it is missing-evidence territory.
        verdict = "REQUIRES_ADDITIONAL_EVIDENCE"
        basis.append(
            f"Corpus coverage {applicability.coverage.level.value}: required "
            "standard families missing (GC-17). "
            + applicability.coverage.statement
        )
    else:
        caps: list[str] = []
        if total_gaps:
            caps.append(f"{total_gaps} documentation gap(s) open")
        # Rev 5 §4.2 verdict-blocking rule: HIGH-IMPACT unresolved conflicts
        # cap the verdict. Low-impact unresolved conflicts are surfaced in
        # the package but do not cap.
        high_impact_unresolved = [c for c in unresolved_conflicts if c.high_impact]
        if high_impact_unresolved:
            caps.append(
                f"{len(high_impact_unresolved)} unresolved high-impact "
                "requirement conflict(s) (caps below PASS, Rev 5 §4.2)"
            )
        if packs_verified_fraction < 1.0:
            caps.append(
                "rule packs UNVERIFIED: output is provisional and capped "
                "below PASS until human verification (Rev 5 §4.3)"
            )
        if caps:
            verdict = "CONDITIONAL_PASS_WITH_GAPS"
            basis.extend(caps)
        else:
            verdict = "PASS"
            basis.append(
                "Coverage FULL, no documentation gaps, no unresolved "
                "conflicts, all rule packs VERIFIED."
            )

    confidence, breakdown = _confidence(
        request, applicability.coverage.level, doc, packs_verified_fraction
    )

    depths = sorted({s.evidence_depth for s in doc.satisfied})
    evidence_depth_label = (
        f"L{depths[0]}-L{depths[-1]} (per artifact; see documentation set)"
        if depths
        else "no satisfied artifacts to state a depth for"
    )

    return AMQualificationPackage(
        overall_verdict=verdict,
        verdict_basis=basis,
        mode="assessed" if request.program else "checklist",
        authority=doc.authority.value,
        coverage=applicability.coverage.level.value,
        evidence_depth=evidence_depth_label,
        classification=classification,
        applicability=ApplicabilitySummary(
            coverage_statement=applicability.coverage.statement,
            applicable_requirements=[
                r.requirement_id for r in applicability.applicable
            ],
            excluded_by_class=applicability.excluded_by_class,
            notes=applicability.notes,
        ),
        gap_analysis=gap_analysis,
        conflicts=conflicts,
        test_matrix=test_matrix,
        confidence=confidence,
        confidence_breakdown=breakdown,
        notes=doc.notes
        + [
            f"Crosswalk: {crosswalk.requirement_count} requirement nodes, "
            f"{crosswalk.artifact_edge_count} artifact edges, "
            f"{crosswalk.reference_edge_count} cross-reference edges, "
            f"{crosswalk.placeholder_count} inert controlled-standard "
            "placeholders (no content, no edges)."
        ],
        evaluation_snapshot=_snapshot(request, pack_entries),
    )


class AMKnowledgeTwinEngine:
    """Class facade expected by the chat adapter (PR-E wiring)."""

    def __init__(self, store: Optional[AMContentStore] = None) -> None:
        self._store = store

    def evaluate_am_package(
        self,
        request: AMRequest,
        secondary_inputs: Optional[SecondaryInputs] = None,
    ) -> AMQualificationPackage:
        return evaluate_am_package(
            request, store=self._store, secondary_inputs=secondary_inputs
        )
