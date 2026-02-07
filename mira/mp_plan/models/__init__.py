#!/usr/bin/env python3
"""
Module: M&P Plan Generator Models
Purpose: Model exports for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from .aggregation import (
    GroupingAssumption,
    MinorQuantityAggregation,
    MinorQuantityGroup,
)
from .artifacts import ArtifactType, GeneratedArtifact
from .blocking import BlockingQuestion, BlockingQuestionType, UserDecision
from .closure import (
    AcceptedOpenGap,
    ClosureDecision,
    ClosureOption,
    InvalidationTrigger,
    OperationalConstraint,
)
from .context import ComputationContext, RunManifest
from .draft import DraftTextBox
from .environment import EnvironmentDefinition, MaterialEnvironmentUsage
from .gaps import DeficiencySignal, NonconformanceSignal, split_gap_signals
from .graph import DecisionEdge, DecisionGraph, DecisionNode
from .materials import (
    COTSItem,
    HardwareContext,
    MaterialEntry,
    MaterialResolutionResult,
    OrgChart,
)
from .session import PlanGeneratorSession

__all__ = [
    # Session
    "PlanGeneratorSession",
    # Environment
    "EnvironmentDefinition",
    "MaterialEnvironmentUsage",
    # Materials
    "MaterialEntry",
    "MaterialResolutionResult",
    "COTSItem",
    "HardwareContext",
    "OrgChart",
    # Gaps (V2 split)
    "DeficiencySignal",
    "NonconformanceSignal",
    "split_gap_signals",
    # Closure
    "ClosureDecision",
    "ClosureOption",
    "AcceptedOpenGap",
    "InvalidationTrigger",
    "OperationalConstraint",
    # Graph
    "DecisionGraph",
    "DecisionNode",
    "DecisionEdge",
    # Aggregation
    "MinorQuantityAggregation",
    "MinorQuantityGroup",
    "GroupingAssumption",
    # Context
    "ComputationContext",
    "RunManifest",
    # Draft
    "DraftTextBox",
    # Blocking
    "BlockingQuestion",
    "BlockingQuestionType",
    "UserDecision",
    # Artifacts
    "GeneratedArtifact",
    "ArtifactType",
]

__version__ = "2.0.0"
__safety_critical__ = False
