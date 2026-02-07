#!/usr/bin/env python3
"""
Module: M&P Plan Generator
Purpose: NASA M&P Plan generation with V2 architecture

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

This module implements the M&P Plan Generator V2 specification with
all 13 Fran corrections:

1. MPR count from index (not hardcoded)
2. Multi-environment support
3. Structured evidence references
4. Minor quantity aggregation by zone
5. Explicit dependency tracking
6. Policy pack configuration
7. Split gap types (Deficiency vs Nonconformance)
8. Accepted open gaps
9. Logic-free templates
10. Complete cache keys
11. LLM output isolation
12. Decision graph
13. Review packet generation

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from .models import (
    # Session
    PlanGeneratorSession,
    # Environment
    EnvironmentDefinition,
    MaterialEnvironmentUsage,
    # Materials
    MaterialEntry,
    MaterialResolutionResult,
    COTSItem,
    HardwareContext,
    OrgChart,
    # Gaps
    DeficiencySignal,
    NonconformanceSignal,
    split_gap_signals,
    # Closure
    ClosureDecision,
    ClosureOption,
    AcceptedOpenGap,
    OperationalConstraint,
    # Graph
    DecisionGraph,
    DecisionNode,
    DecisionEdge,
    # Aggregation
    MinorQuantityAggregation,
    MinorQuantityGroup,
    # Context
    ComputationContext,
    RunManifest,
    # Draft
    DraftTextBox,
    # Blocking
    BlockingQuestion,
    BlockingQuestionType,
    UserDecision,
    # Artifacts
    GeneratedArtifact,
    ArtifactType,
)

from .compute_loop import (
    run_compute_loop,
    generate_blocking_questions,
    build_decision_graph,
    apply_user_decision,
)

from .session_manager import (
    SessionManager,
    get_session_manager,
)

from .policy import (
    PolicyPack,
    RoutingThreshold,
    ClosurePathRule,
    create_default_policy_pack,
    load_policy_pack,
)

from .generation import (
    # Section builder
    SectionContent,
    SectionBuilder,
    build_all_sections,
    # Template renderer
    TemplateRenderer,
    render_section,
    # DOCX generator
    MPPlanDocxGenerator,
    generate_mp_plan_docx,
    # Excel generator
    MIULExcelGenerator,
    generate_miul_xlsx,
    # Review packet
    ReviewPacket,
    ReviewPacketGenerator,
    generate_review_packet,
)

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
    # Gaps
    "DeficiencySignal",
    "NonconformanceSignal",
    "split_gap_signals",
    # Closure
    "ClosureDecision",
    "ClosureOption",
    "AcceptedOpenGap",
    "OperationalConstraint",
    # Graph
    "DecisionGraph",
    "DecisionNode",
    "DecisionEdge",
    # Aggregation
    "MinorQuantityAggregation",
    "MinorQuantityGroup",
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
    # Compute loop
    "run_compute_loop",
    "generate_blocking_questions",
    "build_decision_graph",
    "apply_user_decision",
    # Session manager
    "SessionManager",
    "get_session_manager",
    # Policy
    "PolicyPack",
    "RoutingThreshold",
    "ClosurePathRule",
    "create_default_policy_pack",
    "load_policy_pack",
    # Generation
    "SectionContent",
    "SectionBuilder",
    "build_all_sections",
    "TemplateRenderer",
    "render_section",
    "MPPlanDocxGenerator",
    "generate_mp_plan_docx",
    "MIULExcelGenerator",
    "generate_miul_xlsx",
    "ReviewPacket",
    "ReviewPacketGenerator",
    "generate_review_packet",
]

__version__ = "2.0.0"
__safety_critical__ = False
