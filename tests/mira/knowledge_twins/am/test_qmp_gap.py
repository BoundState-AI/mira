"""
Tests: QMP/MPS documentation-gap engine + synthetic demo program (PR-3).
The assessed-mode tests verify the tool FINDS all four Rev 5 §11 seeded
failures in the synthetic GRCop-42 registry.

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import pytest

from mira.knowledge_twins.am.am_models import (
    AMPartClass,
    ControlledArtifact,
    EvidenceRecord,
)
from mira.knowledge_twins.am.content_store import AMContentStore, default_store_dir
from mira.knowledge_twins.am.engines.applicability import evaluate_applicability
from mira.knowledge_twins.am.engines.qmp_gap import (
    AuthorityLabel,
    GapSeverity,
    _evidence_depth,
    derive_required_artifacts,
    evaluate_doc_gap,
)
from mira.knowledge_twins.am.synthetic_demo import (
    SYNTHETIC_MARKER,
    demo_access_context,
    demo_conflicts,
    demo_program_context,
    demo_request,
)

_REAL_STORE = default_store_dir()
_NEEDS_STORE = pytest.mark.skipif(
    not (_REAL_STORE / "manifest.json").is_file(),
    reason="real AM content store not populated on this machine",
)


def _class_a_applicability():
    store = AMContentStore(_REAL_STORE)
    return evaluate_applicability(store, demo_access_context(), AMPartClass.CLASS_A)


# ------------------------------------------------------------ checklist mode


@_NEEDS_STORE
def test_required_doc_set_is_derived_from_frozen_text() -> None:
    applicability = _class_a_applicability()
    required = derive_required_artifacts(applicability)
    types = {r.artifact_type for r in required}
    # Class A required set must include the core 6030 plans/records, each
    # cited by at least one applicable requirement.
    for expected in ("AMCP", "QMP", "MPS", "PPP", "EFCP", "EIDP", "NDE"):
        assert expected in types, f"{expected} missing from derived doc set"
    for entry in required:
        assert entry.required_by, f"{entry.artifact_type} has no citing requirement"


@_NEEDS_STORE
def test_checklist_mode_without_program(

) -> None:
    applicability = _class_a_applicability()
    result = evaluate_doc_gap(applicability, None)
    assert result.authority is AuthorityLabel.CHECKLIST
    assert result.required and not result.gaps
    assert any("never fabricates an allowable" in n or "fabricates" in n for n in result.notes)


# ------------------------------------------------------------- assessed mode


@_NEEDS_STORE
def test_assessed_mode_finds_all_four_seeded_failures() -> None:
    """The §11 demo moment: superseded QMP, missing witness report (EIDP),
    stale NDE reference, plus the conflict carried separately."""
    applicability = _class_a_applicability()
    store = AMContentStore(_REAL_STORE)
    versions = {
        sid: store.load_pack(sid, demo_access_context()).version
        for sid in ("NASA-STD-6030", "NASA-STD-6033")
    }
    result = evaluate_doc_gap(applicability, demo_program_context(), versions)

    assert result.authority is AuthorityLabel.NON_AUTHORITATIVE
    by_severity = {g.severity for g in result.gaps}

    # 1. Superseded QMP rev A.
    superseded = [g for g in result.gaps if g.severity is GapSeverity.SUPERSEDED]
    assert any("BSI-QMP-A-017 Rev B" in g.detail for g in superseded)

    # 2. Missing EIDP (home of the witness testing report, [AMR-106]).
    missing = [g for g in result.gaps if g.severity is GapSeverity.MISSING]
    assert any(g.artifact_type == "EIDP" for g in missing)
    eidp_gap = next(g for g in missing if g.artifact_type == "EIDP")
    assert "REQ:NASA-STD-6030:AMR-106" in eidp_gap.governing_requirements

    # 3. Stale NDE procedure reference vs frozen 6033 baseline.
    stale = [g for g in result.gaps if g.severity is GapSeverity.STALE_REFERENCE]
    assert any("BSI-NDE-CT-009" in g.detail for g in stale)

    # 4. PPP still in review -> state gap.
    assert GapSeverity.STATE in by_severity

    # Satisfied artifacts carry explicit evidence depth, never inflated.
    mps = next(s for s in result.satisfied if s.artifact_type == "MPS")
    assert mps.evidence_depth == 2
    amcp = next(s for s in result.satisfied if s.artifact_type == "AMCP")
    assert amcp.evidence_depth == 1


def test_seeded_conflict_is_unresolved_and_high_impact() -> None:
    conflicts = demo_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0].resolved is False
    assert conflicts[0].high_impact is True
    assert "REQ:NASA-STD-6030:AMR-102" in conflicts[0].requirement_ids


def test_synthetic_data_is_marked_synthetic_everywhere() -> None:
    """ITAR honesty: notional values, explicit synthetic markers."""
    request = demo_request()
    assert SYNTHETIC_MARKER in request.part_description
    assert all(
        a.artifact_id is None or a.artifact_id.startswith("BSI-")
        for a in demo_program_context().artifact_registry
    )
    assert SYNTHETIC_MARKER in demo_conflicts()[0].description


# ----------------------------------------------------------- evidence depth


def test_evidence_depth_never_inflates() -> None:
    artifact = ControlledArtifact(
        artifact_type="MPS", artifact_id="X-1", state="approved"
    )
    # No records: existence only, linkage confirmable (id present).
    assert _evidence_depth(artifact, []) == (1, True)
    # Linked to a build but no coupon/serial chain: L2 even if the record
    # claims depth 3.
    linked = EvidenceRecord(
        record_id="r1", artifact_ref="X-1", evidence_depth=3, build_id="B-1"
    )
    assert _evidence_depth(artifact, [linked]) == (2, True)
    # Full lot -> build -> coupon trace at declared depth 3: L3.
    full = EvidenceRecord(
        record_id="r2",
        artifact_ref="X-1",
        evidence_depth=3,
        powder_lot_id="L-1",
        build_id="B-1",
        coupon_ids=["C-1"],
    )
    assert _evidence_depth(artifact, [full]) == (3, True)
    # No artifact_id: depth cannot be confirmed -- L1 and flagged as such,
    # never silently matched against empty-string refs.
    anon = ControlledArtifact(artifact_type="MPS", state="approved")
    assert _evidence_depth(anon, [full]) == (1, False)


def test_stale_reference_uses_exact_version_token() -> None:
    """Regression for the startswith/endswith bug: version '1.0.0' must not
    clear a ref citing '2.1.0.0', and separator-less prefixes must not fire."""
    from mira.knowledge_twins.am.engines.qmp_gap import _artifact_gaps
    from mira.knowledge_twins.am.engines.qmp_gap import RequiredArtifact

    required = RequiredArtifact(artifact_type="NDE", required_by=["REQ:X:R1"])
    versions = {"NASA-STD-6033": "1.0.0"}

    def gaps_for(ref: str):
        artifact = ControlledArtifact(
            artifact_type="NDE",
            artifact_id="N-1",
            state="approved",
            referenced_standard_version=ref,
        )
        return [
            g
            for g in _artifact_gaps(required, artifact, versions)
            if g.severity is GapSeverity.STALE_REFERENCE
        ]

    # Suffix collision: '2.1.0.0' endswith '1.0.0' -- must STILL be stale.
    assert gaps_for("NASA-STD-6033:2.1.0.0")
    # Exact match: current, no gap.
    assert not gaps_for("NASA-STD-6033:1.0.0")
    # Different standard family sharing a prefix-free form: no separator
    # match, no gap (not our baseline to judge).
    assert not gaps_for("NASA-STD-6033-COMPANION:0.1")
