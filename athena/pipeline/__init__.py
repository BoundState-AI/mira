#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Pipeline Stages Package.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from athena.pipeline.ingest import IngestPipeline, IngestPipelineV2, IngestState, save_ingest_state
from athena.pipeline.boundary import (
    BoundaryDetector,
    SeparatorDetector,
    HybridBoundaryDetector,
)
from athena.pipeline.triage import TriageStage, TextOnlyTriageStage
from athena.pipeline.extract import ExtractionStage, TextOnlyExtractionStage
from athena.pipeline.reconcile import ConservativeReconciler, ReconciliationConfig
from athena.pipeline.index import IndexingStage
from athena.pipeline.orchestrator import PipelineOrchestrator
# V2 stages
from athena.pipeline.discovery import DiscoveryStage
from athena.pipeline.ocr_stage import OCRStage

__all__ = [
    # V1 stages
    "IngestPipeline",
    "BoundaryDetector",
    "TriageStage",
    "ExtractionStage",
    "ConservativeReconciler",
    "ReconciliationConfig",
    "IndexingStage",
    "PipelineOrchestrator",
    # V2 stages
    "IngestPipelineV2",
    "IngestState",
    "save_ingest_state",
    "SeparatorDetector",
    "HybridBoundaryDetector",
    "DiscoveryStage",
    "OCRStage",
    "TextOnlyTriageStage",
    "TextOnlyExtractionStage",
]
