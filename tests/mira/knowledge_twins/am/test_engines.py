"""
Tests: AM engines 6.1-6.3 (PR-2) -- applicability scoping, crosswalk graph
rules, classification validator. Real-corpus tests pin against the frozen
6030/6033 packs and skip on machines without the local store.

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import pytest

from mira.knowledge_twins.am.am_models import (
    AccessContext,
    AMPartClass,
    AMProcess,
    ClassificationInput,
    ConsequenceTier,
    DataClassification,
    HazardFlag,
    MaterialType,
)
from mira.knowledge_twins.am.classification_model import (
    AM_RISK_CRITERIA,
    METALLIC_STRUCTURAL_DEMAND,
    SecondaryInputs,
)
from mira.knowledge_twins.am.content_store import AMContentStore, default_store_dir
from mira.knowledge_twins.am.crosswalk_models import (
    ArtifactTypeNode,
    CrosswalkEdge,
    CrosswalkGraph,
    EdgeType,
    PlaceholderStandardNode,
    RequirementNode,
)
from mira.knowledge_twins.am.engines import (
    build_crosswalk,
    evaluate_applicability,
    evaluate_classification,
)
from mira.knowledge_twins.am.engines.applicability import (
    CoverageLevel,
    derive_class_scope,
)

_REAL_STORE = default_store_dir()
_NEEDS_STORE = pytest.mark.skipif(
    not (_REAL_STORE / "manifest.json").is_file(),
    reason="real AM content store not populated on this machine",
)


def _access() -> AccessContext:
    return AccessContext(
        tenant_id="boundstate-demo",
        program_ids=["demo"],
        permitted_source_classes=["public"],
        deployment_boundary="demo-public-box",
        max_data_classification=DataClassification.PUBLIC,
    )


# ------------------------------------------------------------ class scoping


def test_derive_class_scope_phrasings() -> None:
    assert derive_class_scope(
        "For Class A and B parts, an MPS shall be developed."
    ) == [AMPartClass.CLASS_A, AMPartClass.CLASS_B]
    assert derive_class_scope("For Class C parts, a CoC shall be required.") == [
        AMPartClass.CLASS_C
    ]
    assert derive_class_scope("Class A parts shall not: be fasteners.") == [
        AMPartClass.CLASS_A
    ]
    assert derive_class_scope(
        "All AM parts in Classes A1 through B2 shall be subject to testing."
    ) == [AMPartClass.CLASS_A, AMPartClass.CLASS_B]
    # No stated scope -> applies to all classes.
    assert derive_class_scope("The CEO shall maintain a QMS.") == []
    # "All Class X" phrasings (AMR-17/19/32) — caught by adversarial review.
    assert derive_class_scope(
        "All Class A parts shall receive quantitative NDE with full coverage."
    ) == [AMPartClass.CLASS_A]
    assert derive_class_scope(
        "All Class B parts shall receive NDE for process control."
    ) == [AMPartClass.CLASS_B]
    assert derive_class_scope(
        "All Class A and B AM parts shall be proof tested."
    ) == [AMPartClass.CLASS_A, AMPartClass.CLASS_B]
    # Comma list with subclasses and an interposed word (AMR-45 phrasing).
    assert derive_class_scope(
        "MPs used for metallic Class A, B1, and B2 part production shall "
        "include HIP."
    ) == [AMPartClass.CLASS_A, AMPartClass.CLASS_B]


# ------------------------------------------------------ crosswalk graph rules


def test_edges_to_placeholders_are_rejected() -> None:
    """Golden Test 16: any edge touching a placeholder fails validation."""
    nodes = [
        RequirementNode(node_id="REQ:X:R1", standard_id="X"),
        PlaceholderStandardNode(node_id="PLACEHOLDER:AMS", standard_id="AMS"),
    ]
    edge = CrosswalkEdge(
        src="REQ:X:R1", dst="PLACEHOLDER:AMS", edge_type=EdgeType.RELATED_TO
    )
    with pytest.raises(ValueError, match="inert"):
        CrosswalkGraph(nodes=nodes, edges=[edge])


def test_edge_target_kind_rules_enforced() -> None:
    nodes = [
        RequirementNode(node_id="REQ:X:R1", standard_id="X"),
        ArtifactTypeNode(node_id="ARTIFACT:QMP", artifact_type="QMP"),
    ]
    # documented_in must target an artifact node: OK.
    CrosswalkGraph(
        nodes=nodes,
        edges=[
            CrosswalkEdge(
                src="REQ:X:R1", dst="ARTIFACT:QMP", edge_type=EdgeType.DOCUMENTED_IN
            )
        ],
    )
    # verified_by targeting an artifact node: rejected.
    with pytest.raises(ValueError, match="verified_by"):
        CrosswalkGraph(
            nodes=nodes,
            edges=[
                CrosswalkEdge(
                    src="REQ:X:R1", dst="ARTIFACT:QMP", edge_type=EdgeType.VERIFIED_BY
                )
            ],
        )


# ------------------------------------------------- classification validator


def test_unsupported_framework_declines_with_factors() -> None:
    """GC-6: no loaded validator -> CANNOT_VALIDATE, factors surfaced."""
    result = evaluate_classification(
        ClassificationInput(
            classification_framework="CUSTOMER-SCHEME-X",
            intended_class=AMPartClass.CLASS_B,
            consequence_of_failure=ConsequenceTier.CRITICAL,
            hazard_context=[HazardFlag.PRESSURE_VESSEL],
            safety_critical_confirmed=True,
        )
    )
    assert result.verdict == "CANNOT_VALIDATE"
    assert result.framework_supported is False
    assert "consequence_of_failure=critical" in result.surfaced_factors
    assert "hazard:pressure_vessel" in result.surfaced_factors
    assert result.expected_class is None


def test_gc4_declared_class_mismatch_cites_amr6() -> None:
    """GC-4: declared C, consequence implies A -> mismatch with citation."""
    result = evaluate_classification(
        ClassificationInput(
            classification_framework="NASA-STD-6030",
            intended_class=AMPartClass.CLASS_C,
            consequence_of_failure=ConsequenceTier.CATASTROPHIC,
            class_c_criteria_confirmed=True,
            safety_critical_confirmed=True,
        )
    )
    assert result.verdict == "MISMATCH"
    assert result.expected_class is AMPartClass.CLASS_A
    assert any("AMR-6" in c for c in result.citations)


def test_secondary_subclass_attaches_on_match() -> None:
    inputs = SecondaryInputs(
        demand_criteria_met={c.criterion_id: True for c in METALLIC_STRUCTURAL_DEMAND},
        risk_answers={c.criterion_id: True for c in AM_RISK_CRITERIA},
    )
    result = evaluate_classification(
        ClassificationInput(
            classification_framework="NASA-STD-6030",
            intended_class=AMPartClass.CLASS_A,
            consequence_of_failure=ConsequenceTier.CATASTROPHIC,
            safety_critical_confirmed=True,
        ),
        material_type=MaterialType.METALLIC,
        am_process=AMProcess.L_PBF,
        secondary_inputs=inputs,
    )
    assert result.verdict == "MATCHES"
    assert result.subclass == 4


def test_secondary_missing_inputs_are_named_not_assumed() -> None:
    result = evaluate_classification(
        ClassificationInput(
            classification_framework="NASA-STD-6030",
            intended_class=AMPartClass.CLASS_A,
            consequence_of_failure=ConsequenceTier.CATASTROPHIC,
            safety_critical_confirmed=True,
        ),
        material_type=MaterialType.METALLIC,
        am_process=None,
        secondary_inputs=SecondaryInputs(),
    )
    assert result.subclass is None
    assert "am_process" in result.missing_inputs


# ------------------------------------------------------- real-corpus engines


@_NEEDS_STORE
def test_applicability_scopes_by_class_on_real_corpus() -> None:
    store = AMContentStore(_REAL_STORE)
    result = evaluate_applicability(store, _access(), AMPartClass.CLASS_C)

    assert result.coverage.level is CoverageLevel.FULL
    assert result.coverage.families_missing == []
    assert len(result.coverage.placeholder_families) == 7
    assert "placeholders" in result.coverage.statement

    ids = {r.requirement_id for r in result.applicable}
    # [AMR-62] "For Class C parts..." applies to a Class C part.
    assert "REQ:NASA-STD-6030:AMR-62" in ids
    # [AMR-61] "For Class A and B parts, an MPS shall be developed" must not.
    excluded = set(result.excluded_by_class)
    assert "REQ:NASA-STD-6030:AMR-61" in excluded
    # "All Class A/B parts" NDE + proof-test requirements must not hit a
    # Class C part (AMR-17/19/32; regression for the scope-parser bug).
    assert "REQ:NASA-STD-6030:AMR-17" in excluded
    assert "REQ:NASA-STD-6030:AMR-19" in excluded
    assert "REQ:NASA-STD-6030:AMR-32" in excluded
    # 6033 requirements are in the applicable set (both packs consulted).
    assert any(r.standard_id == "NASA-STD-6033" for r in result.applicable)


@_NEEDS_STORE
def test_applicability_exempt_leaves_only_classification_reqs() -> None:
    store = AMContentStore(_REAL_STORE)
    result = evaluate_applicability(store, _access(), AMPartClass.EXEMPT)
    tags = sorted(r.source_tag for r in result.applicable)
    assert tags == ["AMR 11", "AMR 5"]


@_NEEDS_STORE
def test_crosswalk_builds_validated_graph_on_real_corpus() -> None:
    store = AMContentStore(_REAL_STORE)
    result = build_crosswalk(store, _access())

    assert result.requirement_count == 115 + 33
    assert result.placeholder_count == 7
    # [AMR-2] requires the consolidated AMCP -> documented_in ARTIFACT:AMCP.
    amcp_edges = [
        e
        for e in result.graph.edges
        if e.src == "REQ:NASA-STD-6030:AMR-2"
        and e.dst == "ARTIFACT:AMCP"
        and e.edge_type is EdgeType.DOCUMENTED_IN
    ]
    assert len(amcp_edges) == 1
    # Explicit section cross-references produce related_to edges.
    assert result.reference_edge_count > 0
    # The §4.2 validator guarantees no placeholder edges; assert anyway.
    placeholder_ids = {
        n.node_id for n in result.graph.nodes if n.node_kind == "placeholder_standard"
    }
    for edge in result.graph.edges:
        assert edge.src not in placeholder_ids
        assert edge.dst not in placeholder_ids


@_NEEDS_STORE
def test_no_access_means_no_engine_output() -> None:
    store = AMContentStore(_REAL_STORE)
    with pytest.raises(PermissionError):
        evaluate_applicability(store, None, AMPartClass.CLASS_A)
    with pytest.raises(PermissionError):
        build_crosswalk(store, None)
