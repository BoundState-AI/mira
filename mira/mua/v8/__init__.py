"""
MUA V8 - LLM-Rendered Material Usage Agreements

80/20 automated MUA generation:
  - 80% AI: header, classification, test data, gaps, precedent retrieval,
    draft rationale, mitigations, verification, references
  - 20% Engineer: application description, rationale review/edit,
    gap dispositions, final approval

Uses a frontier model as a semantic layer over structured MUA session data
and Postgres-backed precedent corpus (bok.mua_precedents) to produce
professional NASA-quality MUA documents.

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
