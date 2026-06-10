"""
Module: AM Knowledge Twin -- typed cross-walk graph contracts (Rev 5 §4.2)
Purpose: Node/edge models for the conflict-aware requirement crosswalk.
         Cross-standard mapping is frequently judgment-dependent; these types
         make false equivalence unrepresentable rather than discouraged.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032 (Data Validation), SWE-033, NASA-STD-8739.8B
Safety Critical: True

Enforcement invariants (Rev 5 §4.2):
- Edge source/target kinds are validated structurally: verified_by ->
  TestMethodNode, documented_in -> ArtifactTypeNode, satisfied_by ->
  EvidenceNode. An edge violating the pair table fails validation.
- NO edge may originate from or target a PlaceholderStandardNode -- the
  graph validator raises; placeholders stay inert (Golden Test 16).
- Mappings that are not 1:1 carry mapping_status and surface "SME judgment
  required" downstream instead of collapsing to one answer.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EdgeType(str, Enum):
    MAPS_TO = "maps_to"
    RELATED_TO = "related_to"
    PARTIALLY_COVERS = "partially_covers"
    CONFLICTS_WITH = "conflicts_with"
    VERIFIED_BY = "verified_by"
    DOCUMENTED_IN = "documented_in"
    SATISFIED_BY = "satisfied_by"


class MappingStatus(str, Enum):
    EXACT = "exact"
    MULTIPLE = "multiple"
    CONFLICT = "conflict"
    MANUAL_REVIEW = "manual_review"


class ApprovalStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    SME_APPROVED = "sme_approved"
    DISPUTED = "disputed"


class RequirementNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_kind: Literal["requirement"] = "requirement"
    node_id: str  # REQ:<standard>:<tag>
    standard_id: str
    section: str = ""
    page: Optional[int] = None


class TestMethodNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_kind: Literal["test_method"] = "test_method"
    node_id: str  # METHOD:<standard>:<id>
    description: str = ""


class ArtifactTypeNode(BaseModel):
    """A controlled-artifact type named by the standard (AMCP, QMP, PPP...)."""

    model_config = ConfigDict(extra="forbid")

    node_kind: Literal["artifact_type"] = "artifact_type"
    node_id: str  # ARTIFACT:<type>
    artifact_type: str


class EvidenceNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_kind: Literal["evidence"] = "evidence"
    node_id: str  # EVIDENCE:<record_id>


class PlaceholderStandardNode(BaseModel):
    """Demo-track inert node: name only, provably edge-free (Rev 5 §4.1)."""

    model_config = ConfigDict(extra="forbid")

    node_kind: Literal["placeholder_standard"] = "placeholder_standard"
    node_id: str  # PLACEHOLDER:<standard_id>
    standard_id: str
    loaded: Literal[False] = False
    note: str = "not licensed / not loaded"


CrosswalkNode = Union[
    RequirementNode,
    TestMethodNode,
    ArtifactTypeNode,
    EvidenceNode,
    PlaceholderStandardNode,
]

# Rev 5 §4.2: allowed (edge_type -> target node_kind) pairs, validated in CI
# and at graph build time. maps_to/related_to/partially_covers/conflicts_with
# connect requirements to requirements.
_EDGE_TARGET_KINDS: dict[EdgeType, str] = {
    EdgeType.MAPS_TO: "requirement",
    EdgeType.RELATED_TO: "requirement",
    EdgeType.PARTIALLY_COVERS: "requirement",
    EdgeType.CONFLICTS_WITH: "requirement",
    EdgeType.VERIFIED_BY: "test_method",
    EdgeType.DOCUMENTED_IN: "artifact_type",
    EdgeType.SATISFIED_BY: "evidence",
}
_EDGE_SOURCE_KIND = "requirement"  # every edge type originates at a requirement


class CrosswalkEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src: str
    dst: str
    edge_type: EdgeType
    mapping_status: MappingStatus = MappingStatus.MANUAL_REVIEW
    mapping_logic: Optional[str] = None  # subset|superset|equivalent|equivalent_if|disjoint
    conditions: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None
    owner: Optional[str] = None
    approval_status: ApprovalStatus = ApprovalStatus.UNREVIEWED

    @model_validator(mode="after")
    def _conditional_mappings_never_auto_approve(self) -> "CrosswalkEdge":
        # Rev 5 §4.2: conditional mappings are never auto-approved.
        if self.conditions and self.approval_status is ApprovalStatus.SME_APPROVED:
            if not self.rationale:
                raise ValueError(
                    "Conditional mapping cannot be sme_approved without a "
                    "recorded rationale (Rev 5 §4.2)."
                )
        return self


class CrosswalkGraph(BaseModel):
    """Validated crosswalk graph. Construction enforces the §4.2 rules."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[CrosswalkNode] = Field(default_factory=list)
    edges: list[CrosswalkEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_edge_rules(self) -> "CrosswalkGraph":
        by_id: dict[str, str] = {}
        for node in self.nodes:
            if node.node_id in by_id:
                raise ValueError(f"Duplicate crosswalk node id {node.node_id!r}.")
            by_id[node.node_id] = node.node_kind

        seen_edges: set[tuple[str, str, str]] = set()
        for edge in self.edges:
            key = (edge.src, edge.dst, edge.edge_type.value)
            if key in seen_edges:
                raise ValueError(
                    f"Duplicate edge {edge.edge_type.value} from {edge.src!r} "
                    f"to {edge.dst!r}."
                )
            seen_edges.add(key)
            for endpoint in (edge.src, edge.dst):
                kind = by_id.get(endpoint)
                if kind is None:
                    raise ValueError(
                        f"Edge {edge.edge_type.value} references unknown node "
                        f"{endpoint!r}."
                    )
                if kind == "placeholder_standard":
                    raise ValueError(
                        f"Edge {edge.edge_type.value} touches placeholder node "
                        f"{endpoint!r}: placeholders are inert by construction "
                        "(Rev 5 §4.1; Golden Test 16)."
                    )
            if by_id[edge.src] != _EDGE_SOURCE_KIND:
                raise ValueError(
                    f"Edge {edge.edge_type.value} must originate at a "
                    f"requirement node, not {by_id[edge.src]!r}."
                )
            expected = _EDGE_TARGET_KINDS[edge.edge_type]
            if by_id[edge.dst] != expected:
                raise ValueError(
                    f"Edge {edge.edge_type.value} must target a {expected} "
                    f"node, not {by_id[edge.dst]!r} ({edge.dst!r})."
                )
        return self

    def edges_from(self, node_id: str) -> list[CrosswalkEdge]:
        return [e for e in self.edges if e.src == node_id]

    def manual_review_edges(self) -> list[CrosswalkEdge]:
        return [
            e
            for e in self.edges
            if e.mapping_status in (MappingStatus.MANUAL_REVIEW, MappingStatus.CONFLICT)
            or (e.conditions and e.approval_status is not ApprovalStatus.SME_APPROVED)
        ]
