#!/usr/bin/env python3
"""
MIRA V3 Pipeline Package

Usage:
    from mira.pipeline import create_pipeline

    pipeline = create_pipeline()
    ctx = pipeline.run("Is aluminum 6061 compatible with GOX at 200 psi?")
    response = ctx.to_response()

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from .context import (
    EnvironmentClass,
    MaterialConstraints,
    QueryContext,
    QueryIntent,
    StageResult,
    Verdict,
)
from .pipeline import QueryPipeline
from .router import RouteStage
from .stage import PipelineStage
from .stages import (
    BoundaryCheckStage,
    ClassifyStage,
    DecideStage,
    EvidenceEvalStage,
    GenerateStage,
    MaterialsSearchStage,
    MUARetrievalStage,
    ParseStage,
    SemanticSearchStage,
    TestRetrievalStage,
)


def create_pipeline(
    db_url: str | None = None,
    llm_provider: str = "ollama",
    enable_semantic: bool = True,
) -> QueryPipeline:
    """
    Factory: Build the complete MIRA V3 query pipeline.

    Stage order:
        1. Parse            → constraints
        2. Classify          → intent scores
        3. Route             → pipeline_name
        4. BoundaryCheck     → short-circuit if PROHIBITED (compatibility only)
        5. MUARetrieval      → mua_precedents (compatibility only)
        6. TestRetrieval     → test_results (compatibility only)
        7. SemanticSearch    → semantic_evidence (compatibility + general)
        8. EvidenceEval      → has_sufficient_evidence (compatibility only)
        9. Decide            → decisions (compatibility only)
        10. Generate         → llm_answer (compatibility only)
        11. MaterialsSearch  → materials_found (materials_search only)

    Each stage's should_skip() gates on ctx.pipeline_name so only
    relevant stages run for each query type.
    """
    stages = [
        ParseStage(),
        ClassifyStage(),
        RouteStage(),
        BoundaryCheckStage(),
        MUARetrievalStage(db_url=db_url),
        TestRetrievalStage(db_url=db_url),
    ]

    if enable_semantic:
        stages.append(SemanticSearchStage(db_url=db_url))

    stages.extend([
        EvidenceEvalStage(),
        DecideStage(),
        GenerateStage(llm_provider=llm_provider),
        MaterialsSearchStage(db_url=db_url),
    ])

    return QueryPipeline(stages)


__all__ = [
    # Factory
    "create_pipeline",
    # Core
    "QueryPipeline",
    "PipelineStage",
    "QueryContext",
    # Enums
    "EnvironmentClass",
    "QueryIntent",
    "Verdict",
    # Models
    "MaterialConstraints",
    "StageResult",
    # Stages
    "ParseStage",
    "ClassifyStage",
    "RouteStage",
    "BoundaryCheckStage",
    "MUARetrievalStage",
    "TestRetrievalStage",
    "SemanticSearchStage",
    "EvidenceEvalStage",
    "DecideStage",
    "GenerateStage",
    "MaterialsSearchStage",
]
