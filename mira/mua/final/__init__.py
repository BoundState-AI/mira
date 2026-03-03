"""
MUA Final - Unified Material Usage Agreement System

Best of v6/v7/v8:
  - v7 evidence engine (Steps 1-3: Define, Investigate, Review)
  - v8 LLM renderer (Claude as semantic layer over structured PG data)
  - v8 section-level workflow (accept/edit/override per section)
  - v7 fact checker (deterministic claim verification)
  - v7 safety rules (hedged language, HITL floor, divergence detection)

Architecture:
  PostgreSQL (structured data) -> Claude (semantic layer) -> Engineer (judgment)

BoundState AI 2026
"""

from .renderer import MUADocumentRenderer
from .precedent_retriever import PrecedentRetriever
from .draft_builder import MUADraftBuilder
from .workflow import MUADraftWorkflow, MUADraftSection, SectionStatus, ReviewAction
from .models import MUASessionData, MUAGap, MUAPrecedent, MUARenderedDocument

__all__ = [
    "MUADocumentRenderer",
    "MUADraftBuilder",
    "MUADraftWorkflow",
    "MUADraftSection",
    "SectionStatus",
    "ReviewAction",
    "PrecedentRetriever",
    "MUASessionData",
    "MUAGap",
    "MUAPrecedent",
    "MUARenderedDocument",
]
