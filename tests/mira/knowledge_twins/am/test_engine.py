"""
Tests: AM package synthesis engine + adapter E2E (PR-5).
GC-1 (full synthetic package), GC-4 (mismatch), gate enforcement (GC-18),
verdict capping on UNVERIFIED packs, and reproducibility of the snapshot.

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import asyncio

import pytest

from mira.knowledge_twins.am.am_models import AMPartClass
from mira.knowledge_twins.am.content_store import default_store_dir
from mira.knowledge_twins.am.engine import evaluate_am_package
from mira.knowledge_twins.am.synthetic_demo import demo_request

_REAL_STORE = default_store_dir()
_NEEDS_STORE = pytest.mark.skipif(
    not (_REAL_STORE / "manifest.json").is_file(),
    reason="real AM content store not populated on this machine",
)


# ------------------------------------------------------------------- gates


def test_unconfirmed_safety_critical_blocks_before_retrieval() -> None:
    request = demo_request().model_copy(update={"safety_critical_confirmed": False})
    package = evaluate_am_package(request)
    assert package.overall_verdict == "BLOCKED"
    assert package.verdict_basis == ["gate:safety_critical_confirmed"]
    assert package.applicability.applicable_requirements == []


def test_unknown_data_classification_is_quarantined() -> None:
    request = demo_request().model_copy(update={"data_classification": None})
    package = evaluate_am_package(request)
    assert package.overall_verdict == "BLOCKED"
    assert package.verdict_basis == ["gate:data_classification_unknown"]


def test_missing_access_context_blocks() -> None:
    request = demo_request().model_copy(update={"access": None})
    package = evaluate_am_package(request)
    assert package.overall_verdict == "BLOCKED"
    assert package.verdict_basis == ["gate:access_context_missing"]


# --------------------------------------------------------------- GC-1 / GC-4


@_NEEDS_STORE
def test_gc1_full_synthetic_package() -> None:
    package = evaluate_am_package(demo_request())

    # Verdict: capped, never PASS on UNVERIFIED packs + seeded gaps.
    assert package.overall_verdict == "CONDITIONAL_PASS_WITH_GAPS"
    assert any("UNVERIFIED" in b for b in package.verdict_basis)
    assert any("documentation gap" in b for b in package.verdict_basis)
    assert any("conflict" in b for b in package.verdict_basis)

    # Labels at the top of the output (Rev 5 §6.7).
    assert package.mode == "assessed"
    assert package.authority == "NON_AUTHORITATIVE"
    assert package.coverage == "FULL"
    assert "Not a qualification" in package.banner

    # Classification: Class A confirmed with citations.
    assert package.classification.verdict == "MATCHES"

    # Seeded failures all present in the gap analysis.
    assert any("BSI-QMP-A-017 Rev B" in g for g in package.gap_analysis.qmp_gaps)
    flat_docs = "\n".join(package.gap_analysis.document_gaps)
    assert "EIDP" in flat_docs
    assert "BSI-NDE-CT-009" in flat_docs
    assert len(package.conflicts) == 1 and not package.conflicts[0].resolved

    # Baseline matrix from test-activity requirements + enrichment notice.
    assert package.test_matrix.items
    assert package.test_matrix.enrichment_notice  # no DesignPartInput supplied
    assert all(i.test_id.startswith("REQ:NASA-STD-") for i in package.test_matrix.items)

    # Deterministic confidence rubric with shipped breakdown.
    assert 0.0 < package.confidence < 1.0
    assert set(package.confidence_breakdown) == {
        "input_completeness",
        "corpus_coverage",
        "rule_pack_verification",
        "evidence_depth",
        "registry_authority",
    }
    # UNVERIFIED packs show up as zero verification credit -- honest.
    assert package.confidence_breakdown["rule_pack_verification"] == 0.0

    # Snapshot pins the request and both packs by hash.
    snapshot = package.evaluation_snapshot
    assert len(snapshot["request_sha256"]) == 64
    assert {p["standard_id"] for p in snapshot["rule_packs"]} == {
        "NASA-STD-6030",
        "NASA-STD-6033",
    }


@_NEEDS_STORE
def test_gc4_mismatch_blocks_package() -> None:
    request = demo_request()
    request = request.model_copy(
        update={
            "classification": request.classification.model_copy(
                update={
                    "intended_class": AMPartClass.CLASS_C,
                    "class_c_criteria_confirmed": True,
                    "hazard_context": [],
                }
            )
        }
    )
    package = evaluate_am_package(request)
    assert package.overall_verdict == "BLOCKED"
    assert package.classification.verdict == "MISMATCH"
    assert package.classification.expected_class is AMPartClass.CLASS_A


@_NEEDS_STORE
def test_same_request_same_answer() -> None:
    """Rev 5 §7: identical request vs the same frozen baseline -> identical
    verdict, counts, confidence, and request hash."""
    first = evaluate_am_package(demo_request())
    second = evaluate_am_package(demo_request())
    assert first.overall_verdict == second.overall_verdict
    assert first.confidence == second.confidence
    # content_basis_sha256 is the replay-equivalence key; evaluated_at is a
    # recording timestamp excluded from equivalence by design.
    assert (
        first.evaluation_snapshot["content_basis_sha256"]
        == second.evaluation_snapshot["content_basis_sha256"]
    )
    snap_a = {k: v for k, v in first.evaluation_snapshot.items() if k != "evaluated_at"}
    snap_b = {k: v for k, v in second.evaluation_snapshot.items() if k != "evaluated_at"}
    assert snap_a == snap_b
    assert first.gap_analysis == second.gap_analysis
    assert len(first.applicability.applicable_requirements) == len(
        second.applicability.applicable_requirements
    )


# ------------------------------------------------------------- adapter E2E


@_NEEDS_STORE
def test_adapter_end_to_end_checklist_mode(monkeypatch_off=None) -> None:
    from mira.chat.adapters.am_adapter import AMAdapter
    from mira.chat.models import Status

    parsed_input = {
        "part_description": "Synthetic L-PBF combustion liner (demo)",
        "material_designation": "GRCop-42",
        "intended_class": "Class A",
        "consequence_of_failure": "catastrophic",
        "hazard_context": ["fracture_critical", "pressure_vessel"],
        "am_process": "L-PBF",
        "material_type": "metallic",
        "safety_critical_confirmed": True,
    }
    envelope = asyncio.run(AMAdapter().execute(parsed_input, session_context={}))
    assert envelope.status is Status.CONDITIONAL_PASS
    assert envelope.domain_payload["engine_verdict"] == "CONDITIONAL_PASS_WITH_GAPS"
    assert "NASA-STD-6030" in envelope.authority_basis
    assert envelope.domain_payload["am_package"]["banner"].startswith("Audit-prep")
