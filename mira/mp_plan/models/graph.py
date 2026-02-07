#!/usr/bin/env python3
"""
Module: Decision Graph Models
Purpose: Dependency tracking for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #5, #12: Dependency graph for recompute

Fran: "This is what makes recompute correct and explainable."

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

__version__ = "2.0.0"
__safety_critical__ = False


class DecisionNode(BaseModel):
    """
    Node in the decision graph.

    Represents a computed value or decision that depends on other values.
    """

    node_id: str
    """Unique node identifier (format: '{node_type}:{object_id}')."""

    node_type: str
    """Type of node: 'material', 'environment', 'mpr', 'gap', 'closure', 'determination'."""

    object_id: str
    """ID of the actual object this node represents."""

    object_type: str
    """Python type name of the object."""

    # Dependencies
    depends_on: list[str] = Field(default_factory=list)
    """Node IDs this node depends on."""

    derived_from_fields: list[str] = Field(default_factory=list)
    """Field names that affect this node (e.g., 'material.MAT001.mass_g')."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class DecisionEdge(BaseModel):
    """
    Edge in the decision graph.

    Represents a dependency relationship between nodes.
    """

    from_node: str
    """Source node ID."""

    to_node: str
    """Target node ID."""

    edge_type: str
    """Type of edge: 'depends_on', 'triggers', 'satisfies', 'invalidates'."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class DecisionGraph(BaseModel):
    """
    Explicit dependency graph for selective recompute.

    Fran: "This is what makes recompute correct and explainable."

    The graph tracks which computations depend on which inputs,
    enabling efficient recomputation when only some inputs change.

    Compliance: SWE-013 (dependency tracking).
    """

    nodes: dict[str, DecisionNode] = Field(default_factory=dict)
    """All nodes in the graph, keyed by node_id."""

    edges: list[DecisionEdge] = Field(default_factory=list)
    """All edges in the graph."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    def get_invalidated_by(self, changed_field: str) -> list[str]:
        """
        Get all nodes invalidated by a field change.

        Args:
            changed_field: Field path that changed (e.g., 'material.MAT001.mass_g').

        Returns:
            List of node IDs that need recomputation.
        """
        affected = []
        for node_id, node in self.nodes.items():
            if changed_field in node.derived_from_fields:
                affected.append(node_id)
                # Cascade to dependents
                affected.extend(self._get_dependents(node_id))
        return list(set(affected))

    def _get_dependents(self, node_id: str) -> list[str]:
        """
        Get all nodes that depend on this node (recursive).

        Args:
            node_id: Node to find dependents for.

        Returns:
            List of dependent node IDs.
        """
        dependents = []
        for edge in self.edges:
            if edge.from_node == node_id and edge.edge_type == "depends_on":
                dependents.append(edge.to_node)
                dependents.extend(self._get_dependents(edge.to_node))
        return dependents

    def add_node(
        self,
        node_type: str,
        object_id: str,
        object_type: str,
        depends_on: Optional[list[str]] = None,
        derived_from_fields: Optional[list[str]] = None,
    ) -> str:
        """
        Add a node to the graph.

        Args:
            node_type: Type of node.
            object_id: ID of the object this node represents.
            object_type: Python type name.
            depends_on: List of node IDs this depends on.
            derived_from_fields: List of field paths that affect this node.

        Returns:
            The node_id of the added node.
        """
        node_id = f"{node_type}:{object_id}"
        self.nodes[node_id] = DecisionNode(
            node_id=node_id,
            node_type=node_type,
            object_id=object_id,
            object_type=object_type,
            depends_on=depends_on or [],
            derived_from_fields=derived_from_fields or [],
        )
        return node_id

    def add_edge(self, from_node: str, to_node: str, edge_type: str) -> None:
        """
        Add an edge to the graph.

        Args:
            from_node: Source node ID.
            to_node: Target node ID.
            edge_type: Type of relationship.
        """
        self.edges.append(
            DecisionEdge(
                from_node=from_node,
                to_node=to_node,
                edge_type=edge_type,
            )
        )

    def get_node(self, node_id: str) -> Optional[DecisionNode]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_nodes_by_type(self, node_type: str) -> list[DecisionNode]:
        """Get all nodes of a specific type."""
        return [n for n in self.nodes.values() if n.node_type == node_type]

    def clear(self) -> None:
        """Clear all nodes and edges."""
        self.nodes.clear()
        self.edges.clear()
