# ATHENA Complete Engineering Specification

**Version:** 3.0 (Consolidated for Implementation)  
**Date:** December 2024  
**Status:** Ready for Claude Code  
**Classification:** BoundState Proprietary

---

# Table of Contents

1. [Overview](#1-overview)
2. [Deployment & Cost Model](#2-deployment--cost-model)
3. [Security & Data Sovereignty](#3-security--data-sovereignty)
4. [Evidence Model](#4-evidence-model)
5. [Complete Data Models](#5-complete-data-models)
6. [Pipeline Stages](#6-pipeline-stages)
7. [Boundary Detection](#7-boundary-detection)
8. [Conservative Reconciliation](#8-conservative-reconciliation)
9. [Cost Controls](#9-cost-controls)
10. [API Specification](#10-api-specification)
11. [Configuration](#11-configuration)
12. [Project Structure](#12-project-structure)
13. [Implementation Guidance](#13-implementation-guidance)

---

# 1. Overview

## 1.1 What Is ATHENA

ATHENA = "Adaptive Triage & Hierarchical Extraction for Noisy Archives"

A document intelligence pipeline that turns decades of scanned paper chaos into searchable, connected knowledge. Handles the "order from chaos" problem: mixed document types, degraded scans, unknown schemas, with full evidence traceability.

**First Customer:** Red River Army Depot - legacy file cabinets being digitized.

## 1.2 Design Principles

1. **Vision-first:** All extraction uses vision models on rendered page images, NOT OCR libraries
2. **Evidence-backed:** Every extracted value links to page, bounding box, and image snippet
3. **Deployment-flexible:** Pluggable LLM providers (cloud, GovCloud, on-prem)
4. **Conservative reconciliation:** Entity merges are proposed, not automatic. High-impact types require human approval
5. **Cost-controlled:** Per-batch budgets, content-hash caching, adaptive routing
6. **Auditable:** Full processing logs, API call records, cost attribution

## 1.3 High-Level Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   INGEST    │───▶│   TRIAGE    │───▶│  EXTRACT    │───▶│  RECONCILE  │
│             │    │  (Haiku)    │    │  (Sonnet)   │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         STATE STORE (PostgreSQL)                     │
└─────────────────────────────────────────────────────────────────────┘
      │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  File Store │    │   Qdrant    │    │  NetworkX   │    │  JSON/API   │
│    (S3)     │    │  (Vectors)  │    │   (Graph)   │    │  (Export)   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

---

# 2. Deployment & Cost Model

## 2.1 Deployment Target

- **Primary:** AWS Bedrock GovCloud (us-gov-west-1)
- **Models:** Claude Haiku 4.5, Claude Sonnet 4.5
- **Why:** Government customer, CUI-adjacent data, FedRAMP required

## 2.2 Bedrock Pricing (Verified)

```python
BEDROCK_PRICING = {
    # Model: (input_per_1k_tokens, output_per_1k_tokens)
    
    # Haiku 4.5
    "us.anthropic.claude-3-5-haiku-20241022-v1:0": (0.001, 0.005),
    "us-gov.anthropic.claude-3-5-haiku-20241022-v1:0": (0.001, 0.005),
    
    # Sonnet 4.5
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": (0.003, 0.015),
    "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0": (0.003, 0.015),
}
```

## 2.3 Per-Page Cost Breakdown

Typical page: ~10k input tokens (image), ~500 output tokens

| Model | Input Cost | Output Cost | **Per Page** |
|-------|------------|-------------|--------------|
| Haiku 4.5 | 10k × $0.001/1k = $0.010 | 0.5k × $0.005/1k = $0.0025 | **$0.0125** |
| Sonnet 4.5 | 10k × $0.003/1k = $0.030 | 0.5k × $0.015/1k = $0.0075 | **$0.0375** |
| Batch Haiku | — | — | **$0.00625** |
| Batch Sonnet | — | — | **$0.01875** |

## 2.4 Blended Cost Estimate

Typical routing distribution:
- 100% triage (Haiku): $0.0125
- 30% extract_full (Sonnet): 0.3 × $0.0375 = $0.01125
- 50% extract_light (Haiku): 0.5 × $0.0125 = $0.00625
- 20% skip/manual: $0
- Reconciliation (amortized): ~$0.005

**Blended Total: ~$0.035/page**

| Volume | Cost | At $0.50/page |
|--------|------|---------------|
| 1,000 pages | $35 | $500 revenue |
| 10,000 pages | $350 | $5,000 revenue |
| 100,000 pages | $3,500 | $50,000 revenue |

**Gross Margin: 93%**

---

# 3. Security & Data Sovereignty

## 3.1 Deployment Modes

```python
class DeploymentMode(str, Enum):
    CLOUD = "cloud"          # Commercial Anthropic API
    GOVCLOUD = "govcloud"    # AWS Bedrock GovCloud
    ON_PREM = "on_prem"      # Local model server
```

| Mode | LLM Provider | Use Case |
|------|--------------|----------|
| CLOUD | Anthropic API | Commercial, non-sensitive |
| GOVCLOUD | AWS Bedrock (us-gov-west-1) | CUI, FedRAMP, DoD |
| ON_PREM | Local (vLLM + Llama Vision) | Air-gapped, ITAR |

## 3.2 LLM Provider Interface

```python
from typing import Protocol

class LLMResponse(BaseModel):
    content: str
    tokens_in: int
    tokens_out: int
    model: str
    latency_ms: int
    cost_usd: float

class LLMProvider(Protocol):
    """Abstract interface for LLM providers."""
    
    async def complete_vision(
        self,
        images: list[str],           # Base64 PNGs
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096
    ) -> LLMResponse: ...
```

## 3.3 Bedrock Provider Implementation

```python
import anthropic
from datetime import datetime

class BedrockProvider:
    """AWS Bedrock for GovCloud."""
    
    def __init__(self, region: str = "us-gov-west-1"):
        self.client = anthropic.AnthropicBedrock(aws_region=region)
        self.models = {
            "triage": "us-gov.anthropic.claude-3-5-haiku-20241022-v1:0",
            "extract": "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
        }
    
    async def complete_vision(
        self,
        images: list[str],
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        model_key: str = "extract"
    ) -> LLMResponse:
        start = datetime.utcnow()
        
        content = []
        for img in images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img}
            })
        content.append({"type": "text", "text": user_prompt})
        
        response = self.client.messages.create(
            model=self.models[model_key],
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": content}]
        )
        
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        cost = self._calculate_cost(
            self.models[model_key],
            response.usage.input_tokens,
            response.usage.output_tokens
        )
        
        return LLMResponse(
            content=response.content[0].text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=self.models[model_key],
            latency_ms=latency_ms,
            cost_usd=cost
        )
    
    def _calculate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        pricing = BEDROCK_PRICING.get(model, (0.003, 0.015))
        cost = (tokens_in * pricing[0] + tokens_out * pricing[1]) / 1000
        return round(cost, 6)
```

## 3.4 Access Control

```python
class Role(str, Enum):
    ADMIN = "admin"          # Full access
    OPERATOR = "operator"    # Process batches, view results
    REVIEWER = "reviewer"    # Review extractions, approve entities
    VIEWER = "viewer"        # Read-only
    AUDITOR = "auditor"      # Audit logs only

class Permission(str, Enum):
    BATCH_CREATE = "batch:create"
    BATCH_PROCESS = "batch:process"
    DOCUMENT_VIEW = "document:view"
    DOCUMENT_EXPORT = "document:export"
    ENTITY_APPROVE = "entity:approve"
    ENTITY_REJECT = "entity:reject"
    CONFIG_MODIFY = "config:modify"
    AUDIT_VIEW = "audit:view"

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.OPERATOR: {
        Permission.BATCH_CREATE, Permission.BATCH_PROCESS,
        Permission.DOCUMENT_VIEW, Permission.DOCUMENT_EXPORT
    },
    Role.REVIEWER: {
        Permission.DOCUMENT_VIEW, Permission.ENTITY_APPROVE, 
        Permission.ENTITY_REJECT
    },
    Role.VIEWER: {Permission.DOCUMENT_VIEW},
    Role.AUDITOR: {Permission.AUDIT_VIEW}
}
```

## 3.5 Audit Logging

```python
class AuditEvent(BaseModel):
    """Immutable audit log entry."""
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tenant_id: str
    user_id: str
    action: str                      # e.g., "document.extract"
    resource_type: str               # e.g., "document"
    resource_id: str
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str
    user_agent: str
    outcome: str                     # "success" | "failure" | "denied"

# Audit logs are:
# - Written to append-only table (no UPDATE/DELETE)
# - Retained per compliance requirements (7 years default)
```

---

# 4. Evidence Model

**CRITICAL:** Every extracted value MUST have evidence. "Confidence: 0.85" is meaningless without "show me on the page."

## 4.1 Evidence Structure

```python
class BoundingBox(BaseModel):
    """Normalized coordinates (0.0-1.0) within page."""
    x_min: float = Field(..., ge=0.0, le=1.0)
    y_min: float = Field(..., ge=0.0, le=1.0)
    x_max: float = Field(..., ge=0.0, le=1.0)
    y_max: float = Field(..., ge=0.0, le=1.0)
    
    @property
    def width(self) -> float:
        return self.x_max - self.x_min
    
    @property
    def height(self) -> float:
        return self.y_max - self.y_min


class Evidence(BaseModel):
    """Links extracted value to source location. REQUIRED for all extractions."""
    page: int                                    # 1-indexed
    bbox: BoundingBox
    snippet_hash: str                            # SHA256 of cropped region
    snippet_path: str | None = None              # Path in file store
    raw_text: str | None = None                  # Vision text from region
    confidence: float = Field(..., ge=0.0, le=1.0)
    additional_regions: list["Evidence"] = Field(default_factory=list)


class ExtractedValue(BaseModel):
    """Single extracted field with mandatory evidence."""
    value: Any
    value_type: str                              # "string"|"number"|"date"|"list"|"null"
    evidence: Evidence                           # REQUIRED - cannot be None
    confidence: float = Field(..., ge=0.0, le=1.0)
    extraction_method: str = "vision"            # "vision"|"manual"
    validated: bool = False
    validated_by: str | None = None
    validated_at: datetime | None = None
```

## 4.2 Evidence Requirements

```python
class EvidencePolicy(BaseModel):
    """Evidence requirements - clarifies mandatory vs targets."""
    
    # HARD REQUIREMENT: Every ExtractedValue MUST have Evidence
    # Enforced by Pydantic - cannot create without evidence
    extracted_values_require_evidence: bool = True  # Always True
    
    # SOFT TARGET: % of schema fields with bbox evidence
    # Some fields legitimately missing from document
    target_evidence_coverage: float = 0.95
    
    # TARGET: % with high-quality evidence (bbox + snippet)
    target_high_quality_evidence: float = 0.90
```

## 4.3 Extraction Prompt (Evidence Required)

```python
EXTRACTION_SYSTEM_PROMPT = """You are a document extraction system.
Extract structured data from scanned document images.

CRITICAL: For EVERY extracted value, include location evidence:
{
    "fields": {
        "field_name": {
            "value": "extracted value",
            "confidence": 0.95,
            "evidence": {
                "page": 1,
                "bbox": {"x_min": 0.12, "y_min": 0.34, "x_max": 0.45, "y_max": 0.38},
                "raw_text": "the text as seen on page"
            }
        }
    }
}

Bounding boxes use normalized coordinates (0.0-1.0):
- x_min, x_max: horizontal (0=left, 1=right)
- y_min, y_max: vertical (0=top, 1=bottom)

If value spans multiple regions, include additional_regions array.
"""
```

---

# 5. Complete Data Models

**CRITICAL:** Use `Field(default_factory=list)` for ALL list/dict defaults. Never use `= []` or `= {}`.

## 5.1 Enumerations

```python
from enum import Enum

class DeploymentMode(str, Enum):
    CLOUD = "cloud"
    GOVCLOUD = "govcloud"
    ON_PREM = "on_prem"

class DocumentStatus(str, Enum):
    PENDING = "pending"
    TRIAGED = "triaged"
    EXTRACTED = "extracted"
    RECONCILED = "reconciled"
    INDEXED = "indexed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"
    RESCAN_REQUESTED = "rescan_requested"

class RoutingDecision(str, Enum):
    EXTRACT_FULL = "extract_full"       # Sonnet, full schema
    EXTRACT_LIGHT = "extract_light"     # Haiku, basic schema
    MANUAL_REVIEW = "manual_review"
    RESCAN = "rescan"
    SKIP = "skip"

class EntityType(str, Enum):
    PERSON = "person"
    EQUIPMENT = "equipment"
    LOCATION = "location"
    ORGANIZATION = "organization"
    DATE = "date"
    REFERENCE = "reference"             # Serial#, part#, doc#
    EVENT = "event"
    MATERIAL = "material"
    PROCEDURE = "procedure"

class EntityLinkStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"

class QualityIssue(str, Enum):
    FADED = "faded"
    SKEWED = "skewed"
    HANDWRITTEN = "handwritten"
    TORN = "torn"
    BLURRY = "blurry"
    STAINED = "stained"
    LOW_CONTRAST = "low_contrast"
    MIXED_ORIENTATION = "mixed_orientation"

class BoundarySignal(str, Enum):
    BLANK_OR_SEPARATOR_LIKELY = "blank_or_separator_likely"
    PAGE_NUMBERING_RESET = "page_numbering_reset"
    LETTERHEAD_CHANGE = "letterhead_change"
    DATE_DISCONTINUITY = "date_discontinuity"
    FORM_NUMBER_CHANGE = "form_number_change"
    ORIENTATION_CHANGE = "orientation_change"
    CLASSIFICATION_CHANGE = "classification_change"
    BARCODE_DIVIDER = "barcode_divider"
```

## 5.2 Supporting Models

```python
from pydantic import BaseModel, Field
from typing import Any
from datetime import datetime
from uuid import UUID, uuid4

class FieldSpec(BaseModel):
    """Schema field specification."""
    field: str
    type: str                        # "string"|"number"|"date"|"list"|"boolean"
    description: str
    required: bool = False
    validation_pattern: str | None = None


class EntityBag(BaseModel):
    """Container for preliminary entity extraction."""
    equipment: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)


class DocumentSection(BaseModel):
    """Hierarchical document section."""
    heading: str | None = None
    content: str
    page: int
    evidence: Evidence
    subsections: list["DocumentSection"] = Field(default_factory=list)


class Annotation(BaseModel):
    """Non-text annotation."""
    annotation_type: str             # "handwritten"|"stamp"|"signature"|"highlight"
    content: str | None = None
    page: int
    evidence: Evidence
    confidence: float = Field(..., ge=0.0, le=1.0)


class ProcessingEvent(BaseModel):
    """Single event in processing log."""
    event_id: UUID = Field(default_factory=uuid4)
    stage: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str                      # "started"|"completed"|"failed"|"skipped"
    duration_ms: int | None = None
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    cost_usd: float = 0.0
```

## 5.3 Entity Models

```python
class EntityMention(BaseModel):
    """Single mention of entity in document."""
    mention_id: UUID = Field(default_factory=uuid4)
    text: str
    normalized_text: str
    document_id: UUID
    page: int
    evidence: Evidence
    entity_type: EntityType
    confidence: float = Field(..., ge=0.0, le=1.0)
    context: str | None = None


class EntityRelation(BaseModel):
    """Relationship between entities."""
    relation_id: UUID = Field(default_factory=uuid4)
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str               # "works_on", "located_at", "part_of"
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_documents: list[UUID] = Field(default_factory=list)
    status: EntityLinkStatus = EntityLinkStatus.PROPOSED


class EntityLink(BaseModel):
    """Proposed/approved link between mentions (same entity)."""
    link_id: UUID = Field(default_factory=uuid4)
    mention_ids: list[UUID] = Field(default_factory=list)
    canonical_entity_id: UUID | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_type: str               # "exact_match"|"fuzzy_match"|"cooccurrence"
    evidence_details: dict[str, Any] = Field(default_factory=dict)
    status: EntityLinkStatus = EntityLinkStatus.PROPOSED
    proposed_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None


class Entity(BaseModel):
    """Resolved canonical entity."""
    entity_id: UUID = Field(default_factory=uuid4)
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    mentions: list[EntityMention] = Field(default_factory=list)
    mention_count: int = 0
    first_seen: datetime
    last_seen: datetime
    relationships: list[EntityRelation] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(..., ge=0.0, le=1.0)
    validation_status: str = "unvalidated"
    validated_by: str | None = None
```

## 5.4 Triage Result

```python
class TriageResult(BaseModel):
    """Complete triage output."""
    document_type: str
    document_subtype: str | None = None
    date_detected: str | None = None
    language: str = "en"
    entities: EntityBag = Field(default_factory=EntityBag)
    quality_score: float = Field(..., ge=0.0, le=1.0)
    quality_issues: list[QualityIssue] = Field(default_factory=list)
    suggested_schema: list[FieldSpec] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    routing: RoutingDecision
    routing_reason: str
    recommended_dpi: int = 200
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    pages_analyzed: list[int] = Field(default_factory=list)
```

## 5.5 Extraction Result

```python
class ExtractedTable(BaseModel):
    """Table with per-cell evidence."""
    table_id: str
    title: str | None = None
    page: int
    evidence: Evidence
    headers: list[str] = Field(default_factory=list)
    rows: list[list[ExtractedValue]] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Complete extraction output with evidence."""
    schema_used: list[FieldSpec] = Field(default_factory=list)
    schema_extended: bool = False
    fields: dict[str, ExtractedValue] = Field(default_factory=dict)
    tables: list[ExtractedTable] = Field(default_factory=list)
    sections: list[DocumentSection] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    evidence_coverage: float
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    pages_processed: list[int] = Field(default_factory=list)
    dpi_used: int
```

## 5.6 Document

```python
class Document(BaseModel):
    """Core document entity."""
    document_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    batch_id: str
    source_file: str
    source_path: str
    source_hash: str                 # SHA256 of original
    source_dpi: int | None = None
    page_range: tuple[int, int]      # (start, end) 1-indexed
    page_count: int
    status: DocumentStatus = DocumentStatus.PENDING
    quality_score: float | None = None
    routing: RoutingDecision | None = None
    triage_result: TriageResult | None = None
    extraction_result: ExtractionResult | None = None
    cluster_id: str | None = None
    linked_entities: list[UUID] = Field(default_factory=list)
    related_documents: list[UUID] = Field(default_factory=list)
    embedding: list[float] | None = None
    embedding_model: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    pipeline_version: str
    processing_log: list[ProcessingEvent] = Field(default_factory=list)
    total_cost_usd: float = 0.0
```

## 5.7 Review Models

**CRITICAL:** Use file pointers, NOT base64 blobs.

```python
class BoundaryCandidate(BaseModel):
    """Candidate document boundary."""
    after_page: int
    signals: list[BoundarySignal] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: Evidence | None = None


class BoundaryReviewItem(BaseModel):
    """Boundary review queue item - file pointers only."""
    review_id: UUID = Field(default_factory=uuid4)
    batch_id: str
    source_file: str
    candidate: BoundaryCandidate
    page_image_paths: list[str] = Field(default_factory=list)  # S3 paths
    page_image_urls: list[str] | None = None  # Signed URLs (on request)
    page_numbers: list[int] = Field(default_factory=list)
    status: str = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None


class EntityReviewItem(BaseModel):
    """Entity review queue item - file pointers only."""
    review_id: UUID = Field(default_factory=uuid4)
    link: EntityLink
    mentions: list[EntityMention] = Field(default_factory=list)
    evidence_snippet_paths: list[str] = Field(default_factory=list)
    evidence_snippet_urls: list[str] | None = None
    entity_type: EntityType
    suggested_canonical: str
    priority: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

---

# 6. Pipeline Stages

## 6.1 Stage 0: Ingestion

```python
import fitz
import hashlib
from pathlib import Path

class IngestPipeline:
    """Accept PDFs, validate, queue for processing."""
    
    def __init__(self, config: AthenaConfig, storage: FileStore, db: PostgresClient):
        self.config = config
        self.storage = storage
        self.db = db
        self.boundary_detector = BoundaryDetector(config)
    
    async def ingest_file(
        self, 
        file_path: Path, 
        batch_id: str,
        tenant_id: str
    ) -> list[Document]:
        """Ingest PDF and create Document records."""
        # Validate
        if not file_path.suffix.lower() in ['.pdf', '.tiff', '.tif']:
            raise ValueError(f"Unsupported format: {file_path.suffix}")
        
        file_bytes = file_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        
        # Upload to storage
        storage_path = f"batches/{batch_id}/source/{file_path.name}"
        await self.storage.upload(storage_path, file_bytes)
        
        # Extract metadata
        doc = fitz.open(file_path)
        metadata = self._extract_metadata(doc)
        
        # Detect boundaries
        boundaries = await self.boundary_detector.detect_boundaries(
            doc, file_path.name, batch_id
        )
        
        # Create Document records
        documents = []
        for start, end in boundaries:
            document = Document(
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_file=file_path.name,
                source_path=storage_path,
                source_hash=file_hash,
                source_dpi=metadata.get("source_dpi"),
                page_range=(start, end),
                page_count=end - start + 1,
                pipeline_version=self.config.pipeline_version
            )
            await self.db.insert_document(document)
            documents.append(document)
        
        return documents
    
    def _extract_metadata(self, doc: fitz.Document) -> dict:
        """Extract DPI and metadata from PDF."""
        metadata = {"page_count": len(doc), "pages": []}
        
        for page in doc:
            page_meta = {"page_num": page.number + 1}
            images = page.get_images()
            if images:
                xref = images[0][0]
                try:
                    img_info = doc.extract_image(xref)
                    img_width = img_info.get("width", 0)
                    page_width_pt = page.rect.width
                    if page_width_pt > 0:
                        page_meta["dpi"] = int(img_width / (page_width_pt / 72))
                except:
                    pass
            metadata["pages"].append(page_meta)
        
        dpis = [p.get("dpi") for p in metadata["pages"] if p.get("dpi")]
        metadata["source_dpi"] = min(dpis) if dpis else None
        
        return metadata
```

## 6.2 Stage 1: Triage

```python
TRIAGE_SYSTEM_PROMPT = """You are a document classification system.
Analyze scanned document images and output structured JSON.

OUTPUT FORMAT (strict JSON, no markdown):
{
    "document_type": "report|form|memo|correspondence|manual|drawing|invoice|personnel|other",
    "document_subtype": "more specific if identifiable, else null",
    "date_detected": "ISO date or range if visible, else null",
    "language": "en|es|other ISO code",
    "entities": {
        "equipment": ["list of equipment/asset IDs"],
        "people": ["list of person names"],
        "locations": ["list of locations"],
        "organizations": ["list of orgs"],
        "references": ["doc numbers, serial numbers, part numbers"]
    },
    "quality_score": 0.0-1.0,
    "quality_issues": ["faded", "skewed", "handwritten", "torn", "blurry", etc.],
    "suggested_schema": [
        {"field": "field_name", "type": "string|number|date|list", "description": "what to extract"}
    ],
    "confidence": 0.0-1.0,
    "routing": "extract_full|extract_light|manual_review|rescan|skip",
    "routing_reason": "brief explanation"
}

ROUTING RULES:
- extract_full: Clear, complex content (tables, forms, technical)
- extract_light: Clear, simple content (memos, basic correspondence)
- manual_review: Uncertain classification
- rescan: quality_score < 0.5
- skip: Blank, duplicates
"""

class TriageStage:
    def __init__(self, config: AthenaConfig, llm: LLMProvider, cost_tracker: CostTracker):
        self.config = config
        self.llm = llm
        self.cost_tracker = cost_tracker
    
    async def triage_document(self, doc: Document, pdf: fitz.Document) -> TriageResult:
        """Triage document for routing."""
        # Get first N pages as images
        start = doc.page_range[0] - 1
        end = min(start + self.config.pages_per_triage, doc.page_range[1])
        images = pages_to_images(pdf, start, end, dpi=200)
        
        # Build request
        content_parts = []
        for i, img in enumerate(images):
            content_parts.append(f"[Page {start + i + 1}]")
        
        response = await self.llm.complete_vision(
            images=images,
            system_prompt=TRIAGE_SYSTEM_PROMPT,
            user_prompt="Classify this document. " + " ".join(content_parts),
            max_tokens=1500,
            model_key="triage"
        )
        
        # Parse response
        result = self._parse_response(response)
        
        # Calculate adaptive DPI
        result.recommended_dpi = DPIStrategy.calculate(
            result.routing,
            result.quality_issues,
            doc.source_dpi
        )
        
        # Record cost
        await self.cost_tracker.record(
            batch_id=doc.batch_id,
            document_id=doc.document_id,
            stage="triage",
            cost=response.cost_usd,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            model=response.model
        )
        
        return result
    
    def _parse_response(self, response: LLMResponse) -> TriageResult:
        """Parse triage JSON from model."""
        text = response.content
        # Strip markdown fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        data = json.loads(text.strip())
        
        # Safe parse enums
        quality_issues = safe_parse_enum_list(QualityIssue, data.get("quality_issues", []))
        routing = safe_parse_enum(RoutingDecision, data.get("routing"), RoutingDecision.MANUAL_REVIEW)
        
        return TriageResult(
            document_type=data.get("document_type", "other"),
            document_subtype=data.get("document_subtype"),
            date_detected=data.get("date_detected"),
            language=data.get("language", "en"),
            entities=EntityBag(**data.get("entities", {})),
            quality_score=parse_confidence(data.get("quality_score", 0.5)),
            quality_issues=quality_issues,
            suggested_schema=[FieldSpec(**f) for f in data.get("suggested_schema", [])],
            confidence=parse_confidence(data.get("confidence", 0.5)),
            routing=routing,
            routing_reason=data.get("routing_reason", ""),
            model_used=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            pages_analyzed=list(range(1, len(data.get("suggested_schema", [])) + 1))
        )
```

## 6.3 Stage 2: Extraction

```python
EXTRACTION_SYSTEM_PROMPT = """You are a document extraction system.
Extract structured data from scanned document images.

CONTEXT:
- Document type: {document_type}
- Suggested schema: {schema}

CRITICAL: Every extracted value MUST include bounding box evidence.

OUTPUT FORMAT (strict JSON):
{{
    "schema_used": [
        {{"field": "name", "type": "string|number|date|list", "description": "..."}}
    ],
    "fields": {{
        "field_name": {{
            "value": "extracted value",
            "confidence": 0.0-1.0,
            "evidence": {{
                "page": 1,
                "bbox": {{"x_min": 0.0, "y_min": 0.0, "x_max": 1.0, "y_max": 1.0}},
                "raw_text": "text as seen"
            }}
        }}
    }},
    "tables": [
        {{
            "table_id": "T1",
            "title": "table title if visible",
            "page": 1,
            "bbox": {{"x_min": 0.0, "y_min": 0.0, "x_max": 1.0, "y_max": 1.0}},
            "headers": ["col1", "col2"],
            "rows": [
                [{{"value": "cell", "confidence": 0.9, "bbox": {{...}}}}, ...]
            ]
        }}
    ],
    "annotations": [
        {{
            "type": "handwritten|stamp|signature",
            "content": "text if readable",
            "page": 1,
            "bbox": {{...}},
            "confidence": 0.0-1.0
        }}
    ],
    "overall_confidence": 0.0-1.0
}}

Bounding boxes: normalized 0.0-1.0 (x_min=left, x_max=right, y_min=top, y_max=bottom)
"""

class ExtractionStage:
    def __init__(self, config: AthenaConfig, llm: LLMProvider, cost_tracker: CostTracker):
        self.config = config
        self.llm = llm
        self.cost_tracker = cost_tracker
    
    async def extract_document(self, doc: Document, pdf: fitz.Document) -> ExtractionResult:
        """Full extraction with evidence."""
        # Select model based on routing
        model_key = "extract" if doc.routing == RoutingDecision.EXTRACT_FULL else "triage"
        dpi = doc.triage_result.recommended_dpi if doc.triage_result else 200
        
        # Process in chunks
        all_results = []
        start = doc.page_range[0] - 1
        end = doc.page_range[1]
        
        for chunk_start in range(start, end, self.config.pages_per_extraction):
            chunk_end = min(chunk_start + self.config.pages_per_extraction, end)
            
            images = pages_to_images(pdf, chunk_start, chunk_end, dpi=dpi)
            
            prompt = EXTRACTION_SYSTEM_PROMPT.format(
                document_type=doc.triage_result.document_type if doc.triage_result else "unknown",
                schema=json.dumps([f.model_dump() for f in (doc.triage_result.suggested_schema if doc.triage_result else [])])
            )
            
            response = await self.llm.complete_vision(
                images=images,
                system_prompt=prompt,
                user_prompt=f"Extract all data from pages {chunk_start+1}-{chunk_end}.",
                max_tokens=4096,
                model_key=model_key
            )
            
            chunk_result = self._parse_extraction(response, chunk_start + 1)
            all_results.append(chunk_result)
            
            # Record cost
            await self.cost_tracker.record(
                batch_id=doc.batch_id,
                document_id=doc.document_id,
                stage="extraction",
                cost=response.cost_usd,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                model=response.model
            )
        
        # Merge chunks
        return self._merge_results(all_results, dpi)
    
    def _parse_extraction(self, response: LLMResponse, page_offset: int) -> dict:
        """Parse extraction JSON."""
        text = response.content
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    
    def _merge_results(self, results: list[dict], dpi: int) -> ExtractionResult:
        """Merge chunk results."""
        merged_fields = {}
        merged_tables = []
        merged_annotations = []
        merged_schema = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        
        for r in results:
            # Merge fields (later pages can update)
            for field_name, field_data in r.get("fields", {}).items():
                # Convert to ExtractedValue
                evidence = Evidence(
                    page=field_data["evidence"]["page"],
                    bbox=BoundingBox(**field_data["evidence"]["bbox"]),
                    snippet_hash="",  # Computed later
                    raw_text=field_data["evidence"].get("raw_text")
                )
                merged_fields[field_name] = ExtractedValue(
                    value=field_data["value"],
                    value_type=type(field_data["value"]).__name__,
                    evidence=evidence,
                    confidence=parse_confidence(field_data.get("confidence", 0.5))
                )
            
            merged_tables.extend(r.get("tables", []))
            merged_annotations.extend(r.get("annotations", []))
            if r.get("schema_used"):
                merged_schema = r["schema_used"]
        
        # Calculate evidence coverage
        fields_with_bbox = sum(1 for f in merged_fields.values() if f.evidence.bbox)
        coverage = fields_with_bbox / len(merged_fields) if merged_fields else 1.0
        
        return ExtractionResult(
            schema_used=[FieldSpec(**s) for s in merged_schema],
            fields=merged_fields,
            tables=[],  # Convert tables similarly
            annotations=[],  # Convert annotations similarly
            overall_confidence=sum(f.confidence for f in merged_fields.values()) / len(merged_fields) if merged_fields else 0.0,
            field_confidences={k: v.confidence for k, v in merged_fields.items()},
            evidence_coverage=coverage,
            model_used="",
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            latency_ms=0,
            cost_usd=total_cost,
            pages_processed=[],
            dpi_used=dpi
        )
```

---

# 7. Boundary Detection

**CRITICAL:** Must be image-based. `get_text()` returns empty on scanned PDFs.

## 7.1 Blank Page Detection (Adaptive)

```python
import numpy as np

class BlankPageDetector:
    """Adaptive blank detection calibrated per batch."""
    
    def __init__(self):
        self.calibrated = False
        self.variance_threshold: float = 1000
        self.whitespace_threshold: float = 0.95
    
    def calibrate(self, sample_pages: list[fitz.Page], sample_size: int = 20):
        """Calibrate thresholds from batch sample."""
        variances = []
        for page in sample_pages[:sample_size]:
            gray = self._to_grayscale(page)
            variances.append(np.var(gray))
        
        if variances:
            self.variance_threshold = np.percentile(variances, 10) * 1.5
            self.calibrated = True
    
    def is_likely_blank(self, page: fitz.Page) -> tuple[bool, float]:
        """Returns (is_blank, confidence)."""
        gray = self._to_grayscale(page)
        variance = np.var(gray)
        whitespace_ratio = np.sum(gray > 245) / gray.size
        
        is_blank = (variance < self.variance_threshold and 
                    whitespace_ratio > self.whitespace_threshold)
        
        if is_blank:
            confidence = min(1.0, (self.variance_threshold - variance) / self.variance_threshold)
        else:
            confidence = 0.0
        
        return (is_blank, confidence)
    
    def _to_grayscale(self, page: fitz.Page) -> np.ndarray:
        mat = fitz.Matrix(72/72, 72/72)
        pix = page.get_pixmap(matrix=mat)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        return np.mean(img[:, :, :3], axis=2) if pix.n >= 3 else img[:, :, 0].astype(float)
```

## 7.2 Page Number Detection (Vision-Based)

```python
async def detect_page_number_in_footer(
    page: fitz.Page,
    llm: LLMProvider
) -> tuple[bool, int | None]:
    """
    Use VISION to detect page number.
    get_text() does NOT work on scanned images.
    """
    rect = page.rect
    footer_rect = fitz.Rect(
        rect.x0,
        rect.y1 - (rect.height * 0.12),
        rect.x1,
        rect.y1
    )
    
    mat = fitz.Matrix(200 / 72, 200 / 72)
    pix = page.get_pixmap(matrix=mat, clip=footer_rect)
    footer_b64 = base64.b64encode(pix.tobytes("png")).decode()
    
    response = await llm.complete_vision(
        images=[footer_b64],
        system_prompt="Extract page numbers. Output JSON only.",
        user_prompt='{"has_page_number": bool, "page_number": int|null}',
        max_tokens=50
    )
    
    try:
        result = json.loads(response.content)
        return (result.get("has_page_number", False), result.get("page_number"))
    except:
        return (False, None)
```

## 7.3 Confidence Calculation (Probabilistic)

```python
SIGNAL_WEIGHTS = {
    BoundarySignal.BLANK_OR_SEPARATOR_LIKELY: 0.4,  # Weak alone
    BoundarySignal.BARCODE_DIVIDER: 0.9,
    BoundarySignal.PAGE_NUMBERING_RESET: 0.7,
    BoundarySignal.LETTERHEAD_CHANGE: 0.6,
    BoundarySignal.DATE_DISCONTINUITY: 0.5,
    BoundarySignal.FORM_NUMBER_CHANGE: 0.6,
    BoundarySignal.ORIENTATION_CHANGE: 0.4,
    BoundarySignal.CLASSIFICATION_CHANGE: 0.5,
}

def combine_signal_confidences(signals: list[BoundarySignal]) -> float:
    """
    Probabilistic combination: 1 - Π(1 - w_i)
    Naturally bounded [0, 1].
    """
    if not signals:
        return 0.0
    
    weights = [SIGNAL_WEIGHTS.get(s, 0.3) for s in signals]
    prob_all_wrong = 1.0
    for w in weights:
        prob_all_wrong *= (1.0 - w)
    
    return 1.0 - prob_all_wrong
```

## 7.4 Boundary Decision (Requires Corroboration)

```python
def should_create_boundary(signals: list[BoundarySignal], confidence: float) -> bool:
    """
    Determine if signals warrant split.
    Blank alone is NOT enough.
    """
    # Single blank = weak, need more
    if signals == [BoundarySignal.BLANK_OR_SEPARATOR_LIKELY]:
        return False
    
    # Barcode divider = strong
    if BoundarySignal.BARCODE_DIVIDER in signals:
        return confidence >= 0.7
    
    # Blank + page reset = strong
    if (BoundarySignal.BLANK_OR_SEPARATOR_LIKELY in signals and 
        BoundarySignal.PAGE_NUMBERING_RESET in signals):
        return confidence >= 0.6
    
    # Multiple non-blank signals
    non_blank = [s for s in signals if s != BoundarySignal.BLANK_OR_SEPARATOR_LIKELY]
    if len(non_blank) >= 2:
        return confidence >= 0.65
    
    return confidence >= 0.8
```

## 7.5 Full Boundary Detector

```python
BOUNDARY_CONFIRMATION_PROMPT = """Analyze consecutive pages for document boundary.

Is there a document boundary between these pages (page 2 starts NEW document)?

OUTPUT (strict JSON):
{
    "is_boundary": true/false,
    "confidence": 0.0-1.0,
    "additional_signals": ["letterhead_change", "date_discontinuity", etc.],
    "reasoning": "brief explanation"
}

Look for:
- Different letterhead/logo
- Page numbering resets to 1
- Large date gap
- Different form number
- Orientation change
"""

class BoundaryDetector:
    def __init__(self, config: AthenaConfig, llm: LLMProvider, storage: FileStore):
        self.config = config
        self.llm = llm
        self.storage = storage
        self.blank_detector = BlankPageDetector()
    
    async def detect_boundaries(
        self, 
        doc: fitz.Document,
        source_file: str,
        batch_id: str
    ) -> list[tuple[int, int]]:
        """Detect document boundaries."""
        # Calibrate blank detector
        self.blank_detector.calibrate(list(doc))
        
        # Heuristic detection
        candidates = await self._heuristic_detection(doc)
        
        # Vision confirmation
        confirmed = await self._confirm_with_vision(doc, candidates)
        
        # Resolve to ranges
        return self._resolve_boundaries(confirmed, len(doc))
    
    async def _heuristic_detection(self, doc: fitz.Document) -> list[BoundaryCandidate]:
        candidates = []
        
        for i in range(len(doc) - 1):
            signals = []
            
            # Blank check
            is_blank, conf = self.blank_detector.is_likely_blank(doc[i])
            if is_blank:
                signals.append(BoundarySignal.BLANK_OR_SEPARATOR_LIKELY)
            
            # Page reset (next page)
            has_num, num = await detect_page_number_in_footer(doc[i+1], self.llm)
            if has_num and num == 1:
                signals.append(BoundarySignal.PAGE_NUMBERING_RESET)
            
            # Orientation change
            if self._orientation_changed(doc[i], doc[i+1]):
                signals.append(BoundarySignal.ORIENTATION_CHANGE)
            
            if signals:
                candidates.append(BoundaryCandidate(
                    after_page=i + 1,
                    signals=signals,
                    confidence=combine_signal_confidences(signals)
                ))
        
        return candidates
    
    async def _confirm_with_vision(
        self, 
        doc: fitz.Document,
        candidates: list[BoundaryCandidate]
    ) -> list[BoundaryCandidate]:
        confirmed = []
        
        for candidate in candidates:
            before_idx = candidate.after_page - 1
            after_idx = candidate.after_page
            
            if after_idx >= len(doc):
                continue
            
            images = pages_to_images(doc, before_idx, after_idx + 1, dpi=150)
            
            response = await self.llm.complete_vision(
                images=images,
                system_prompt=BOUNDARY_CONFIRMATION_PROMPT,
                user_prompt=f"Signals: {[s.value for s in candidate.signals]}",
                max_tokens=500,
                model_key="triage"
            )
            
            try:
                result = json.loads(response.content)
            except:
                candidate.confidence *= 0.5
                confirmed.append(candidate)
                continue
            
            # HONOR is_boundary response
            if not result.get("is_boundary", True):
                continue  # Drop candidate
            
            # Update confidence
            candidate.confidence = parse_confidence(result.get("confidence", candidate.confidence))
            
            # Add additional signals
            for sig in result.get("additional_signals", []):
                parsed = safe_parse_enum(BoundarySignal, sig)
                if parsed and parsed not in candidate.signals:
                    candidate.signals.append(parsed)
            
            confirmed.append(candidate)
        
        return confirmed
    
    def _resolve_boundaries(
        self, 
        candidates: list[BoundaryCandidate],
        total_pages: int
    ) -> list[tuple[int, int]]:
        """Convert candidates to (start, end) ranges."""
        ranges = []
        start = 1
        
        for cand in sorted(candidates, key=lambda c: c.after_page):
            if should_create_boundary(cand.signals, cand.confidence):
                ranges.append((start, cand.after_page))
                start = cand.after_page + 1
        
        if start <= total_pages:
            ranges.append((start, total_pages))
        
        return ranges
    
    def _orientation_changed(self, page1: fitz.Page, page2: fitz.Page) -> bool:
        r1, r2 = page1.rect, page2.rect
        p1_portrait = r1.height > r1.width
        p2_portrait = r2.height > r2.width
        return p1_portrait != p2_portrait
```

---

# 8. Conservative Reconciliation

**SAFETY CRITICAL:** Bad merges pollute knowledge base. Equipment ID confusion can misroute maintenance history.

## 8.1 Entity Type Rules

| Entity Type | Match Method | Auto-Approve? | Notes |
|-------------|--------------|---------------|-------|
| EQUIPMENT | Exact ID | **NEVER** | Always human review |
| REFERENCE | Exact | **NEVER** | Part#, serial#, doc# |
| MATERIAL | Validated ID | **NEVER** | Use material DB lookup |
| PERSON | Fuzzy (>0.90) | If >0.95 | Handle name variants |
| ORGANIZATION | Fuzzy (>0.85) | If >0.95 | Abbreviations |
| LOCATION | Fuzzy + geocode | If >0.95 | Normalize addresses |

## 8.2 Reconciliation Implementation

```python
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
from collections import defaultdict

class ReconciliationConfig(BaseModel):
    embedding_model: str = "all-MiniLM-L12-v2"
    
    match_thresholds: dict[EntityType, float] = {
        EntityType.EQUIPMENT: 1.0,      # Exact only
        EntityType.REFERENCE: 1.0,
        EntityType.MATERIAL: 1.0,
        EntityType.PERSON: 0.90,
        EntityType.ORGANIZATION: 0.85,
        EntityType.LOCATION: 0.85,
        EntityType.DATE: 1.0,
        EntityType.EVENT: 0.80,
        EntityType.PROCEDURE: 0.85,
    }
    
    auto_approve_thresholds: dict[EntityType, float | None] = {
        EntityType.EQUIPMENT: None,     # NEVER
        EntityType.REFERENCE: None,
        EntityType.MATERIAL: None,
        EntityType.PERSON: 0.95,
        EntityType.ORGANIZATION: 0.95,
        EntityType.LOCATION: 0.95,
        EntityType.DATE: 0.99,
        EntityType.EVENT: 0.90,
        EntityType.PROCEDURE: 0.90,
    }


class ConservativeReconciler:
    def __init__(self, config: ReconciliationConfig):
        self.config = config
        self.embed_model = SentenceTransformer(config.embedding_model)
    
    async def reconcile_entities(
        self, 
        mentions: list[EntityMention]
    ) -> list[EntityLink]:
        """Propose entity links - NO automatic merging."""
        proposed = []
        
        # Group by type
        by_type: dict[EntityType, list[EntityMention]] = defaultdict(list)
        for m in mentions:
            by_type[m.entity_type].append(m)
        
        for entity_type, type_mentions in by_type.items():
            threshold = self.config.match_thresholds[entity_type]
            auto_threshold = self.config.auto_approve_thresholds.get(entity_type)
            
            matches = self._find_matches(type_mentions, threshold)
            
            for group, confidence, evidence_type in matches:
                if auto_threshold and confidence >= auto_threshold:
                    status = EntityLinkStatus.AUTO_APPROVED
                else:
                    status = EntityLinkStatus.PROPOSED
                
                link = EntityLink(
                    mention_ids=[m.mention_id for m in group],
                    confidence=confidence,
                    evidence_type=evidence_type,
                    evidence_details={
                        "entity_type": entity_type.value,
                        "texts": [m.text for m in group]
                    },
                    status=status
                )
                proposed.append(link)
        
        return proposed
    
    def _find_matches(
        self,
        mentions: list[EntityMention],
        threshold: float
    ) -> list[tuple[list[EntityMention], float, str]]:
        matches = []
        
        if threshold >= 1.0:
            # Exact matching
            by_norm = defaultdict(list)
            for m in mentions:
                by_norm[m.normalized_text.lower()].append(m)
            
            for group in by_norm.values():
                if len(group) > 1:
                    matches.append((group, 1.0, "exact_match"))
        else:
            # Embedding similarity
            texts = [m.normalized_text for m in mentions]
            embeddings = self.embed_model.encode(texts)
            sims = cosine_similarity(embeddings)
            
            groups = self._cluster_by_similarity(mentions, sims, threshold)
            for group in groups:
                if len(group) > 1:
                    indices = [mentions.index(m) for m in group]
                    group_sims = sims[np.ix_(indices, indices)]
                    min_sim = group_sims[group_sims < 0.999].min() if len(indices) > 1 else 1.0
                    matches.append((group, float(min_sim), "fuzzy_match"))
        
        return matches
    
    def _cluster_by_similarity(
        self,
        mentions: list[EntityMention],
        sims: np.ndarray,
        threshold: float
    ) -> list[list[EntityMention]]:
        """Union-find clustering."""
        n = len(mentions)
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        for i in range(n):
            for j in range(i + 1, n):
                if sims[i, j] >= threshold:
                    union(i, j)
        
        groups = defaultdict(list)
        for i, m in enumerate(mentions):
            groups[find(i)].append(m)
        
        return list(groups.values())
```

---

# 9. Cost Controls

## 9.1 Cost Tracker

```python
class CostTracker:
    PRICING = BEDROCK_PRICING  # From earlier
    
    def calculate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        pricing = self.PRICING.get(model, (0.003, 0.015))
        return round((tokens_in * pricing[0] + tokens_out * pricing[1]) / 1000, 6)
    
    async def record(
        self,
        batch_id: str,
        document_id: UUID,
        stage: str,
        cost: float,
        tokens_in: int,
        tokens_out: int,
        model: str
    ):
        event = CostEvent(
            batch_id=batch_id,
            document_id=document_id,
            stage=stage,
            cost_usd=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model
        )
        await self.db.insert_cost_event(event)
        await self.db.increment_batch_cost(batch_id, cost)


class CostEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    batch_id: str
    document_id: UUID
    stage: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    model: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

## 9.2 Budget Enforcement

```python
class BatchBudget(BaseModel):
    budget_usd: float
    warn_threshold_pct: float = 0.80
    stop_threshold_pct: float = 0.95
    per_document_cap_usd: float = 5.0
    on_budget_exceeded: str = "pause"  # "pause"|"fail"|"notify_continue"


class BudgetEnforcer:
    async def check_budget(self, batch_id: str, estimated_cost: float) -> tuple[bool, str]:
        batch = await self.db.get_batch(batch_id)
        spend_pct = batch.total_cost_usd / batch.budget.budget_usd
        
        if spend_pct >= batch.budget.stop_threshold_pct:
            if batch.budget.on_budget_exceeded == "pause":
                await self._pause_batch(batch_id)
                return (False, "batch_paused")
            elif batch.budget.on_budget_exceeded == "fail":
                return (False, "budget_exceeded")
        
        if spend_pct >= batch.budget.warn_threshold_pct:
            await self._send_warning(batch_id, spend_pct)
        
        return (True, "ok")
```

## 9.3 Content-Hash Caching

```python
class ExtractionCache:
    def __init__(self, redis: Redis, ttl_days: int = 30):
        self.redis = redis
        self.ttl = ttl_days * 86400
    
    def _hash_pages(self, images: list[str]) -> str:
        combined = "".join(sorted(images))
        return hashlib.sha256(combined.encode()).hexdigest()[:32]
    
    async def get_triage(self, images: list[str]) -> TriageResult | None:
        key = f"triage:{self._hash_pages(images)}"
        data = await self.redis.get(key)
        return TriageResult.model_validate_json(data) if data else None
    
    async def set_triage(self, images: list[str], result: TriageResult):
        key = f"triage:{self._hash_pages(images)}"
        await self.redis.setex(key, self.ttl, result.model_dump_json())
```

---

# 10. API Specification

## 10.1 REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /batches | Create batch, upload files |
| GET | /batches/{id} | Get batch status |
| POST | /batches/{id}/process | Start processing |
| GET | /documents/{id} | Get document details |
| GET | /search | Semantic search |
| GET | /entities | List/search entities |
| GET | /entities/{id}/graph | Entity relationships |
| GET | /review/boundaries | Pending boundary reviews |
| POST | /review/boundaries/{id} | Submit decision |
| GET | /review/entities | Pending entity reviews |
| POST | /review/entities/{id} | Submit decision |
| GET | /export/{batch_id} | Export as JSON/CSV |

## 10.2 Search API Example

```python
# GET /search?q=maintenance+1992&type=report&limit=20

{
    "query": "maintenance 1992",
    "total": 47,
    "results": [
        {
            "document_id": "uuid",
            "score": 0.89,
            "source_file": "RRAD_20241217_042.pdf",
            "document_type": "maintenance_report",
            "date_detected": "1992-03-15",
            "preview": "Maintenance performed on Unit 4421...",
            "entities": {
                "equipment": ["Unit 4421"],
                "people": ["J. Smith"]
            }
        }
    ]
}
```

---

# 11. Configuration

## 11.1 Full Config Model

```python
class AthenaConfig(BaseModel):
    # Deployment
    deployment_mode: DeploymentMode = DeploymentMode.GOVCLOUD
    pipeline_version: str = "3.0.0"
    
    # AWS/Bedrock
    aws_region: str = "us-gov-west-1"
    
    # Storage
    postgres_url: str
    redis_url: str
    s3_bucket: str
    qdrant_url: str
    qdrant_collection: str = "athena_docs"
    
    # Models
    embedding_model: str = "all-MiniLM-L12-v2"
    
    # Processing
    max_concurrent_jobs: int = 10
    pages_per_triage: int = 3
    pages_per_extraction: int = 3
    default_dpi: int = 200
    max_dpi: int = 400
    
    # Thresholds
    quality_threshold: float = 0.5
    confidence_threshold: float = 0.7
    boundary_threshold: float = 0.7
    
    # Cost
    default_budget_usd: float = 1000.0
    per_document_cap_usd: float = 5.0
    cache_ttl_days: int = 30
    
    # Security
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    # Audit
    audit_log_enabled: bool = True
    audit_log_retention_days: int = 2555
    
    @classmethod
    def from_env(cls) -> "AthenaConfig":
        return cls(
            deployment_mode=DeploymentMode(os.environ.get("DEPLOYMENT_MODE", "govcloud")),
            postgres_url=os.environ["POSTGRES_URL"],
            redis_url=os.environ["REDIS_URL"],
            s3_bucket=os.environ["S3_BUCKET"],
            qdrant_url=os.environ["QDRANT_URL"],
            jwt_secret=os.environ["JWT_SECRET"],
        )
```

## 11.2 Environment Variables

```bash
DEPLOYMENT_MODE=govcloud
AWS_REGION=us-gov-west-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
POSTGRES_URL=postgresql://user:pass@host:5432/athena
REDIS_URL=redis://host:6379
S3_BUCKET=athena-documents
QDRANT_URL=http://host:6333
JWT_SECRET=...
```

---

# 12. Project Structure

```
athena/
├── __init__.py
├── config.py
├── models/
│   ├── __init__.py
│   ├── enums.py
│   ├── evidence.py
│   ├── document.py
│   ├── entity.py
│   ├── security.py
│   ├── cost.py
│   └── review.py
├── providers/
│   ├── __init__.py
│   ├── base.py
│   └── bedrock.py
├── pipeline/
│   ├── __init__.py
│   ├── ingest.py
│   ├── boundary.py
│   ├── triage.py
│   ├── extract.py
│   ├── reconcile.py
│   ├── index.py
│   └── orchestrator.py
├── prompts/
│   ├── __init__.py
│   ├── triage.py
│   ├── extract.py
│   └── boundary.py
├── api/
│   ├── __init__.py
│   ├── main.py
│   ├── deps.py
│   ├── auth.py
│   └── routes/
│       ├── batches.py
│       ├── documents.py
│       ├── search.py
│       ├── entities.py
│       └── review.py
├── services/
│   ├── __init__.py
│   ├── cost.py
│   ├── cache.py
│   ├── audit.py
│   └── storage.py
├── utils/
│   ├── __init__.py
│   ├── pdf.py
│   ├── retry.py
│   ├── parsing.py
│   └── blank_detection.py
├── worker.py
└── db/
    ├── __init__.py
    ├── postgres.py
    └── migrations/
```

---

# 13. Implementation Guidance

## 13.1 Dependencies

```
# requirements.txt
anthropic>=0.39.0
pydantic>=2.0
fastapi>=0.109.0
uvicorn>=0.27.0
httpx>=0.26.0
PyMuPDF>=1.23.0
Pillow>=10.0.0
sentence-transformers>=2.2.0
numpy>=1.24.0
scikit-learn>=1.3.0
hdbscan>=0.8.33
networkx>=3.2
asyncpg>=0.29.0
redis>=5.0.0
qdrant-client>=1.7.0
boto3>=1.34.0
python-multipart>=0.0.6
python-jose[cryptography]>=3.3.0
structlog>=24.1.0
pytest>=7.4.0
pytest-asyncio>=0.23.0

# DO NOT USE:
# - langchain, llama-index
# - pytesseract, easyocr (vision only)
# - openai
```

## 13.2 Helper Functions

```python
# utils/parsing.py

from typing import Any, Type
from enum import Enum

def parse_confidence(value: Any) -> float:
    """Safely parse confidence, always returns [0, 1]."""
    if value is None:
        return 0.5
    
    if isinstance(value, (int, float)):
        conf = float(value)
        if conf > 1.0:
            conf = conf / 100.0
    elif isinstance(value, str):
        try:
            conf = float(value.strip().rstrip('%'))
            if conf > 1.0:
                conf = conf / 100.0
        except ValueError:
            return 0.5
    else:
        return 0.5
    
    return min(1.0, max(0.0, conf))


def safe_parse_enum(enum_class: Type[Enum], value: str, default=None):
    """Parse enum without crashing on unknown."""
    try:
        return enum_class(value)
    except (ValueError, KeyError):
        return default


def safe_parse_enum_list(enum_class: Type[Enum], values: list[str]) -> list:
    """Parse list of enums, skip unknowns."""
    return [p for v in values if (p := safe_parse_enum(enum_class, v))]
```

```python
# utils/pdf.py

import fitz
import base64

def pages_to_images(
    doc: fitz.Document,
    page_start: int,
    page_end: int,
    dpi: int = 200
) -> list[str]:
    """Convert pages to base64 PNGs."""
    images = []
    for i in range(page_start, min(page_end, len(doc))):
        page = doc[i]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    return images
```

```python
# utils/retry.py

import asyncio
from anthropic import RateLimitError, APIConnectionError

async def with_retry(func, *args, max_retries=3, base_delay=1.0, **kwargs):
    """Retry with exponential backoff."""
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except (RateLimitError, APIConnectionError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
    
    raise last_error
```

## 13.3 Implementation Order

1. **models/** - All Pydantic models (use `Field(default_factory=list)`)
2. **config.py** - Full configuration
3. **utils/** - pdf.py, retry.py, parsing.py, blank_detection.py
4. **providers/bedrock.py** - Primary LLM provider
5. **services/storage.py** - S3 with signed URLs
6. **pipeline/boundary.py** - Full boundary detection
7. **pipeline/triage.py** - With adaptive DPI
8. **pipeline/extract.py** - Mandatory evidence
9. **pipeline/reconcile.py** - Conservative rules
10. **pipeline/index.py** - Qdrant with embedding profile
11. **services/cost.py** - Tracking and budgets
12. **api/** - FastAPI routes
13. **worker.py** - Background processor

## 13.4 Key Invariants

1. **Evidence is mandatory** - Cannot create ExtractedValue without Evidence
2. **Confidence is [0, 1]** - Use parse_confidence() and probabilistic combination
3. **Collections are profile-keyed** - Include embedding model in collection name
4. **Review items use file pointers** - Never base64 in database
5. **Blank page alone ≠ boundary** - Require corroboration
6. **Cost tracked per-call** - Log every LLM invocation
7. **No mutable defaults** - Always `Field(default_factory=list)`
8. **Page number detection uses vision** - get_text() is empty on scans

## 13.5 Acceptance Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Extraction precision | ≥0.95 | Golden set |
| Extraction recall | ≥0.90 | Golden set |
| Evidence coverage | ≥0.95 | % fields with bbox |
| False merge rate | <0.01 | Manual review |
| Cost p50 | <$0.04 | Batch reports |
| Cost p99 | <$0.15 | Batch reports |
| Boundary accuracy | ≥0.90 | Manual review |

---

**END OF SPECIFICATION**

Questions? Ask before assuming. This spec went through 3 review cycles.
