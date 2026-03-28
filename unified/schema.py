from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from unified._compat import ensure_external_paths

ensure_external_paths()

try:
    from gptl.schema import DocFeatures, IntentCategory
except Exception:  # pragma: no cover - fallback for import-poor environments
    DocFeatures = Any

    class IntentCategory(str, Enum):
        MATERIAL_LOOKUP = "material_lookup"
        COMPATIBILITY_CHECK = "compatibility_check"
        FAILURE_PREDICTION = "failure_prediction"
        SUBSTITUTION_ANALYSIS = "substitution_analysis"
        COMPLIANCE_CHECK = "compliance_check"
        LIABILITY_ASSESSMENT = "liability_assessment"
        PROPERTY_COMPARISON = "property_comparison"
        PROCESS_GUIDANCE = "process_guidance"
        GENERAL_QUERY = "general_query"


AUTHORITY_BOUNDARY_TEXT = (
    "Precedent retrieval may support draft rationale generation. The system SHALL NOT "
    "infer new engineering allowables, approve alternative design-value methods, or "
    "convert precedent into acceptance authority. All outputs are draft artifacts "
    "pending responsible NASA M&P review, Program/Project approval, or any approval "
    "path defined by the governing Materials and Processes Selection, Control, and "
    "Implementation Plan and NASA-STD-6016C."
)


class AuthorityClass(str, Enum):
    PRIMARY_TEST_DATA = "primary_test_data"
    SPECIFICATION_REQUIREMENT = "specification_requirement"
    HANDBOOK_VALUE = "handbook_value"
    HERITAGE_PRECEDENT = "heritage_precedent"
    ENGINEERING_JUDGMENT = "engineering_judgment"
    VENDOR_DATASHEET = "vendor_datasheet"
    DERIVED_CALCULATION = "derived_calculation"
    UNKNOWN = "unknown"


class HashedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content_hash: str = ""

    def compute_hash(self) -> str:
        data = self.model_dump(exclude={"content_hash", "is_superseded"}, mode="json")
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def populate_content_hash(self) -> "HashedRecord":
        if not self.content_hash:
            self.content_hash = self.compute_hash()
        return self


class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_doc_id: str
    source_chunk_id: str | None = None
    page: int | None = None
    location: str | None = None
    extraction_method: str
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    extraction_model: str | None = None
    normalization_log: str | None = None
    original_unit: str | None = None
    authority_class: AuthorityClass = AuthorityClass.UNKNOWN
    human_reviewed: bool = False
    human_reviewer: str | None = None
    review_timestamp: datetime | None = None
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class ICDocument(HashedRecord):
    doc_id: str
    doc_hash: str
    source_path: str
    source_type: Literal["pdf", "docx", "image", "db_record", "api"]
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    features: DocFeatures | dict[str, Any] | None = None
    is_superseded: bool = False


class ICChunk(HashedRecord):
    chunk_id: str
    doc_id: str
    page: int | None = None
    location: str | None = None
    content_text: str
    content_type: Literal["text", "table", "figure_caption", "header", "metadata"]
    extraction_method: Literal["athena_vision", "athena_ocr", "athena_text", "manual", "db_query"]
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    extraction_model: str | None = None
    is_superseded: bool = False


class ICEntity(HashedRecord):
    entity_id: str
    chunk_id: str
    entity_type: Literal[
        "material",
        "standard",
        "hazard",
        "system",
        "process",
        "person",
        "organization",
        "date",
        "measurement",
        "part_number",
        "test_method",
        "environment",
        "specification",
    ]
    value: str
    normalized_value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    is_superseded: bool = False


class ICAssertion(HashedRecord):
    assertion_id: str
    chunk_id: str
    subject: str
    predicate: str
    object_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: ProvenanceRecord
    is_superseded: bool = False


class ICMeasurement(HashedRecord):
    measurement_id: str
    chunk_id: str
    assertion_id: str | None = None
    property_name: str
    value: float
    unit: str
    normalized_value: float | None = None
    normalized_unit: str | None = None
    test_conditions: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceRecord
    is_superseded: bool = False


class ICProvenanceEdge(HashedRecord):
    edge_id: str
    source_id: str
    source_type: Literal["document", "chunk", "entity", "assertion", "measurement"]
    target_id: str
    target_type: Literal["document", "chunk", "entity", "assertion", "measurement"]
    relationship: Literal[
        "extracted_from",
        "cites",
        "supersedes",
        "contradicts",
        "supports",
        "derived_from",
        "normalized_from",
        "reviewed_by",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_superseded: bool = False


class QuerySource(str, Enum):
    DB = "db"
    DOCS = "docs"
    HYBRID = "hybrid"


class QueryRoute(str, Enum):
    DB_ONLY = "db_only"
    DOC_ONLY = "doc_only"
    CROSS_SOURCE = "cross_source"


class EvidenceSourceType(str, Enum):
    DB = "db"
    DOC = "doc"
    SYNTHESIS = "synthesis"
    CANONICAL = "canonical"


class ICEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    evidence_id: str
    source_type: EvidenceSourceType
    source_label: str
    source_id: str
    doc_id: str | None = None
    chunk_id: str | None = None
    content: str
    snippet: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    authority_class: AuthorityClass = AuthorityClass.UNKNOWN
    provenance: ProvenanceRecord | None = None
    claim_key: str | None = None
    claim_value: str | float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ICConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    conflict_id: str
    subject: str
    description: str
    policy: str
    evidence_ids: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class MergedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    items: list[ICEvidenceItem] = Field(default_factory=list)
    conflicts: list[ICConflict] = Field(default_factory=list)
    source_counts: dict[str, int] = Field(default_factory=dict)
    human_review_required: bool = False


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query: str
    source: QuerySource = QuerySource.HYBRID
    intent: str | IntentCategory | None = None
    limit: int = Field(default=10, ge=1, le=100)
    include_superseded: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query: str
    route: QueryRoute
    answer: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    citations: list[ICEvidenceItem] = Field(default_factory=list)
    conflicts: list[ICConflict] = Field(default_factory=list)
    authority_boundary: str = AUTHORITY_BOUNDARY_TEXT
    insufficient_evidence: bool = False
    audit: dict[str, Any] = Field(default_factory=dict)


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: QuerySource
    db_url: str | None = None
    materialize: bool = False
    materialized_db_url: str | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    module_name: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompileResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: QuerySource
    compiled_at: datetime = Field(default_factory=datetime.utcnow)
    canonical_record_count: int = 0
    materialized_db_url: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"

