#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Data Models Package.

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

from athena.models.enums import (
    DeploymentMode,
    DocumentStatus,
    RoutingDecision,
    EntityType,
    EntityLinkStatus,
    QualityIssue,
    BoundarySignal,
    # V2 enums
    OCRSource,
    VisionTrigger,
)
from athena.models.evidence import (
    BoundingBox,
    Evidence,
    ExtractedValue,
    EvidencePolicy,
)
from athena.models.document import (
    FieldSpec,
    EntityBag,
    DocumentSection,
    Annotation,
    ProcessingEvent,
    TriageResult,
    ExtractedTable,
    ExtractionResult,
    Document,
)
from athena.models.entity import (
    EntityMention,
    EntityRelation,
    EntityLink,
    Entity,
)
from athena.models.security import (
    Role,
    Permission,
    ROLE_PERMISSIONS,
    AuditEvent,
)
from athena.models.cost import (
    CostEvent,
    BatchBudget,
)
from athena.models.review import (
    BoundaryCandidate,
    BoundaryReviewItem,
    EntityReviewItem,
)
# V2 models
from athena.models.separator import (
    SeparatorResult,
    FolderSegment,
)
from athena.models.ocr import (
    ALTOWord,
    ALTOPage,
    OCRResult,
    BatchOCRResult,
)
from athena.models.discovery import (
    CorpusProfile,
    DiscoveryResult,
    DiscoveryAggregator,
    BatchDiscoveryState,
)

__all__ = [
    # Enums
    "DeploymentMode",
    "DocumentStatus",
    "RoutingDecision",
    "EntityType",
    "EntityLinkStatus",
    "QualityIssue",
    "BoundarySignal",
    # Evidence
    "BoundingBox",
    "Evidence",
    "ExtractedValue",
    "EvidencePolicy",
    # Document
    "FieldSpec",
    "EntityBag",
    "DocumentSection",
    "Annotation",
    "ProcessingEvent",
    "TriageResult",
    "ExtractedTable",
    "ExtractionResult",
    "Document",
    # Entity
    "EntityMention",
    "EntityRelation",
    "EntityLink",
    "Entity",
    # Security
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "AuditEvent",
    # Cost
    "CostEvent",
    "BatchBudget",
    # Review
    "BoundaryCandidate",
    "BoundaryReviewItem",
    "EntityReviewItem",
    # V2 Enums
    "OCRSource",
    "VisionTrigger",
    # V2 Separator
    "SeparatorResult",
    "FolderSegment",
    # V2 OCR
    "ALTOWord",
    "ALTOPage",
    "OCRResult",
    "BatchOCRResult",
    # V2 Discovery
    "CorpusProfile",
    "DiscoveryResult",
    "DiscoveryAggregator",
    "BatchDiscoveryState",
]
