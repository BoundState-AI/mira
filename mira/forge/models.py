#!/usr/bin/env python3
"""
Pydantic models for FORGE compiler requests, background jobs, and responses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ForgeCompileRequest(BaseModel):
    """Request to compile a database into FORGE artifacts."""

    database_url: str = Field(..., min_length=1, description="SQLAlchemy database URL")
    app_name: str = Field(
        "FORGE Generated App",
        min_length=1,
        max_length=120,
        description="Human-readable application name for generated artifacts.",
    )
    sample_rows_per_table: int = Field(
        50,
        ge=5,
        le=500,
        description="Sampling budget per table for profiling and inference.",
    )
    persist_artifacts: bool = Field(
        False,
        description="When true, serializes generated artifacts to output_dir.",
    )
    output_dir: Optional[str] = Field(
        None,
        description="Optional directory for emitted JSON artifacts.",
    )
    generate_bundle: bool = Field(
        True,
        description="When true, emit a generated application bundle on disk.",
    )
    require_llm_refinement: bool = Field(
        False,
        description="When true, Sonnet refinement is requested. Currently unimplemented — a warning is emitted.",
    )
    max_generated_questions: int = Field(
        240,
        ge=1,
        le=2000,
        description="Hard cap on the curated question surface shipped to the generated app.",
    )
    max_questions_per_table: int = Field(
        6,
        ge=1,
        le=50,
        description="Maximum number of curated questions kept for any single table.",
    )

    model_config = {"extra": "forbid"}


class ForgeCompilationSummary(BaseModel):
    """High-level compile summary."""

    app_name: str
    database_url_redacted: str
    dialect: str
    schemas: List[str] = Field(default_factory=list)
    table_count: int = 0
    column_count: int = 0
    relationship_count: int = 0
    latent_relationship_count: int = 0
    generated_question_count: int = 0

    model_config = {"extra": "forbid"}


class ForgeGeneratedBundle(BaseModel):
    """Generated application bundle metadata."""

    root_dir: str
    artifacts_dir: str
    app_dir: str
    backend_dir: str
    frontend_dir: str
    authority_pack_dir: str
    bsms_pipeline_dir: str
    lineage_dir: str
    files: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ForgeCompileResponse(BaseModel):
    """Successful deterministic FORGE compile response."""

    status: Literal["ok"]
    summary: ForgeCompilationSummary
    schema_manifest: Dict[str, Any] = Field(default_factory=dict)
    semantic_map: Dict[str, Any] = Field(default_factory=dict)
    relationship_graph: Dict[str, Any] = Field(default_factory=dict)
    latent_relationships: Dict[str, Any] = Field(default_factory=dict)
    data_quality_report: Dict[str, Any] = Field(default_factory=dict)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    question_map: Dict[str, Any] = Field(default_factory=dict)
    scaffold_plan: Dict[str, Any] = Field(default_factory=dict)
    bsms_pipeline: Dict[str, Any] = Field(default_factory=dict)
    authority_pack: Dict[str, Any] = Field(default_factory=dict)
    lineage_schema: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    output_dir: Optional[str] = None
    generated_bundle: Optional[ForgeGeneratedBundle] = None

    model_config = {"extra": "forbid"}


class ForgeCompileAcceptedResponse(BaseModel):
    """Accepted FORGE compile job response."""

    status: Literal["accepted"]
    job_id: str
    status_url: str
    poll_after_ms: int = 1500

    model_config = {"extra": "forbid"}


class ForgeCompileJobEvent(BaseModel):
    """Single compile job progress event."""

    timestamp: str
    status: Literal["queued", "running", "completed", "failed"]
    stage: str
    message: str
    progress: float = Field(ge=0.0, le=100.0)

    model_config = {"extra": "forbid"}


class ForgeCompileJobResponse(BaseModel):
    """FORGE compile job status, progress, and final result."""

    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    stage: str
    message: str
    progress: float = Field(ge=0.0, le=100.0)
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[ForgeCompileResponse] = None
    events: List[ForgeCompileJobEvent] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
