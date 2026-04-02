#!/usr/bin/env python3
"""
Module: Generated Artifact Models
Purpose: Output tracking for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import base64
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

__version__ = "2.0.0"
__safety_critical__ = False


class ArtifactType(str, Enum):
    """Output artifact types."""

    MP_PLAN = "mp_plan"
    """M&P Plan document."""

    MP_PLAN_DOCX = "mp_plan_docx"
    """M&P Plan document (DOCX)."""

    MIUL = "miul"
    """MIUL spreadsheet."""

    MIUL_XLSX = "miul_xlsx"
    """MIUL spreadsheet (Excel)."""

    APPLICABILITY_MATRIX_XLSX = "applicability_matrix_xlsx"
    """MPR applicability matrix (Excel)."""

    MUA_DOCX = "mua_docx"
    """Material Usage Agreement (DOCX)."""

    GAP_REPORT_JSON = "gap_report_json"
    """Gap analysis report (JSON)."""

    RUN_MANIFEST_JSON = "run_manifest_json"
    """Run manifest for audit (JSON)."""

    AUDIT_TRAIL_JSON = "audit_trail_json"
    """Full audit trail (JSON)."""

    REVIEW_PACKET = "review_packet"
    """Reviewer packet."""

    REVIEW_PACKET_JSON = "review_packet_json"
    """Reviewer packet (JSON)."""


class GeneratedArtifact(BaseModel):
    """
    Record of a generated artifact.

    Supports both in-memory content storage for API responses
    and file-based storage for persistence.
    """

    artifact_id: str = Field(default_factory=lambda: str(__import__("uuid").uuid4())[:8])
    """Unique artifact identifier."""

    artifact_type: ArtifactType
    """Type of artifact."""

    format: str = "unknown"
    """File format (docx, xlsx, json, etc.)."""

    # In-memory content (for API responses)
    content_bytes: Optional[bytes] = None
    """Raw content bytes (excluded from JSON serialization)."""

    # File-based storage (for persistence)
    filename: Optional[str] = None
    """Generated filename."""

    filepath: Optional[str] = None
    """Full path to generated file."""

    # Metadata
    generated_at: datetime = Field(default_factory=datetime.now)
    """When artifact was generated."""

    content_hash: Optional[str] = None
    """SHA-256 hash of file contents."""

    source_session_hash: Optional[str] = None
    """Hash of session state used to generate this artifact."""

    # Optional context
    material_id: Optional[str] = None
    """Material ID if artifact is material-specific (e.g., MUA)."""

    mua_category: Optional[str] = None
    """MUA category if applicable."""

    source: str = "unknown"
    """Source of generation request."""

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
    }

    @field_validator("content_bytes", mode="before")
    @classmethod
    def decode_content_bytes(cls, value):
        """Decode persisted JSON/base64 content back into raw bytes."""
        if value is None or isinstance(value, bytes):
            return value
        if isinstance(value, str):
            try:
                return base64.b64decode(value.encode("ascii"))
            except Exception:
                return value.encode()
        return value

    @field_serializer("content_bytes", when_used="json")
    def serialize_content_bytes(self, value: Optional[bytes]) -> Optional[str]:
        """Persist binary artifact content as base64 in JSON mode."""
        if value is None:
            return None
        return base64.b64encode(value).decode("ascii")

    def model_dump(self, **kwargs):
        """Hide raw bytes from routine API dumps, but preserve them for storage."""
        data = super().model_dump(**kwargs)
        if kwargs.get("mode") != "json" and "content_bytes" in data:
            data["content_bytes"] = None
        return data
