"""
Module: AM Knowledge Twin -- crosswalk engine (Rev 5 §6.2)
Purpose: Build the typed, conflict-aware requirement crosswalk from frozen
         pack text. Demo Track: 6030/6033 nodes + inert placeholders only.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True

Edge derivation (text-derived, deterministic -- no asserted equivalences):
- documented_in: a requirement that names a controlled artifact type
  (AMCP, QMP, MPS, PPP, EFCP, QPP, PCRD, EIDP, MUA, CoC) gets an edge to
  that ArtifactTypeNode. The artifact vocabulary is NASA-STD-6030's own
  (§4-§8 plan/record names), matched on word boundaries.
- related_to: an explicit intra-standard cross-reference in the text
  ("see section 5.4", "per section 4.11") gets an edge to every requirement
  whose section matches that reference. Explicit reference = exact status.
- Cross-standard maps_to edges are NOT generated: asserted equivalence
  requires SME approval (Rev 5 §4.2) and the demo corpus has no licensed
  counterpart standards to map. Placeholders appear as nodes with zero
  edges, enforced by the graph validator.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict

from mira.knowledge_twins.am.am_models import AccessContext
from mira.knowledge_twins.am.content_store import AMContentStore
from mira.knowledge_twins.am.crosswalk_models import (
    ApprovalStatus,
    ArtifactTypeNode,
    CrosswalkEdge,
    CrosswalkGraph,
    CrosswalkNode,
    EdgeType,
    MappingStatus,
    PlaceholderStandardNode,
    RequirementNode,
)

# NASA-STD-6030/6033 controlled-artifact vocabulary (the standards' own
# plan/record acronyms; see 6030 §4-§8 and 6033 EFCP). "NDE" covers the
# NDE procedure artifact type (Rev 5 §5.3) named throughout 6030 §4.8.
CONTROLLED_ARTIFACT_TYPES: tuple[str, ...] = (
    "AMCP",
    "QMP",
    "MPS",
    "PPP",
    "EFCP",
    "QPP",
    "PCRD",
    "EIDP",
    "MUA",
    "CoC",
    "NDE",
)

_SECTION_REF = re.compile(
    r"\bsections?\s+(\d+(?:\.\d+)+)(?:\s+(?:and|through)\s+(\d+(?:\.\d+)+))?",
    re.IGNORECASE,
)


class CrosswalkResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: CrosswalkGraph
    requirement_count: int
    artifact_edge_count: int
    reference_edge_count: int
    manual_review_count: int
    placeholder_count: int


def _artifact_pattern(acronym: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(acronym)}\b")


# Public: shared with the qmp_gap engine, which derives the required
# document set from the same vocabulary (single source of truth).
ARTIFACT_PATTERNS: dict[str, re.Pattern[str]] = {
    a: _artifact_pattern(a) for a in CONTROLLED_ARTIFACT_TYPES
}


def build_crosswalk(
    store: AMContentStore,
    access: Optional[AccessContext],
    standard_ids: Optional[list[str]] = None,
) -> CrosswalkResult:
    """Engine 6.2: build the validated crosswalk graph from frozen packs."""
    available = store.available_standards(access)
    targets = [s for s in (standard_ids or available) if s in available]

    nodes: list[CrosswalkNode] = []
    edges: list[CrosswalkEdge] = []

    requirement_nodes: dict[str, RequirementNode] = {}
    by_section: dict[str, list[str]] = {}
    artifact_nodes: dict[str, ArtifactTypeNode] = {}

    packs = [store.load_pack(s, access) for s in targets]
    for pack in packs:
        for req in pack.requirements:
            node = RequirementNode(
                node_id=req.requirement_id,
                standard_id=pack.standard_id,
                section=req.section,
                page=req.page,
            )
            requirement_nodes[node.node_id] = node
            if req.section:
                by_section.setdefault(f"{pack.standard_id}:{req.section}", []).append(
                    node.node_id
                )

    artifact_edge_count = 0
    reference_edge_count = 0
    for pack in packs:
        for req in pack.requirements:
            # documented_in edges from the artifact vocabulary.
            for acronym, pattern in ARTIFACT_PATTERNS.items():
                if pattern.search(req.shall_text):
                    artifact_id = f"ARTIFACT:{acronym}"
                    if artifact_id not in artifact_nodes:
                        artifact_nodes[artifact_id] = ArtifactTypeNode(
                            node_id=artifact_id, artifact_type=acronym
                        )
                    edges.append(
                        CrosswalkEdge(
                            src=req.requirement_id,
                            dst=artifact_id,
                            edge_type=EdgeType.DOCUMENTED_IN,
                            mapping_status=MappingStatus.EXACT,
                            rationale=(
                                f"{req.requirement_id} names controlled artifact "
                                f"type {acronym} in its frozen text."
                            ),
                            approval_status=ApprovalStatus.UNREVIEWED,
                        )
                    )
                    artifact_edge_count += 1

            # related_to edges from explicit intra-standard section refs.
            # Dedupe: a requirement may cite the same section more than once;
            # the graph validator rejects duplicate (src, dst, type) edges.
            emitted_refs: set[str] = set()
            for match in _SECTION_REF.finditer(req.shall_text):
                for ref in filter(None, match.groups()):
                    key = f"{pack.standard_id}:{ref}"
                    for target_id in by_section.get(key, []):
                        if target_id == req.requirement_id or target_id in emitted_refs:
                            continue
                        emitted_refs.add(target_id)
                        edges.append(
                            CrosswalkEdge(
                                src=req.requirement_id,
                                dst=target_id,
                                edge_type=EdgeType.RELATED_TO,
                                mapping_status=MappingStatus.EXACT,
                                rationale=(
                                    f"Explicit cross-reference to section {ref} "
                                    "in the frozen requirement text."
                                ),
                                approval_status=ApprovalStatus.UNREVIEWED,
                            )
                        )
                        reference_edge_count += 1

    placeholder_nodes = [
        PlaceholderStandardNode(
            node_id=f"PLACEHOLDER:{p.standard_id}",
            standard_id=p.standard_id,
            note=p.note,
        )
        for p in store.get_placeholders(access)
    ]

    nodes.extend(requirement_nodes.values())
    nodes.extend(artifact_nodes.values())
    nodes.extend(placeholder_nodes)

    graph = CrosswalkGraph(nodes=nodes, edges=edges)  # validator enforces §4.2
    return CrosswalkResult(
        graph=graph,
        requirement_count=len(requirement_nodes),
        artifact_edge_count=artifact_edge_count,
        reference_edge_count=reference_edge_count,
        manual_review_count=len(graph.manual_review_edges()),
        placeholder_count=len(placeholder_nodes),
    )
