#!/usr/bin/env python3
"""
Module: Draft Text Box Model
Purpose: LLM output isolation for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #11: LLM output isolation

Fran: "Drafted text objects should live in a different namespace/type
and never be allowed as input to decision engines."

This type is NEVER used as input to any decision logic.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

__version__ = "2.0.0"
__safety_critical__ = False


class DraftTextBox(BaseModel):
    """
    LLM-generated text in isolated container.

    CRITICAL: This type is NEVER used as input to any decision logic.
    All DraftTextBox instances require human review before use.

    Fran Fix #11: "LLM output mixed with decisions" -> separate type.

    The validators enforce that:
    - is_authoritative is always False
    - requires_human_review is always True

    Compliance: SWE-013 (LLM isolation).
    """

    box_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this draft."""

    # What was drafted
    draft_type: str
    """Type of draft: 'mua_rationale', 'tailoring_narrative', 'config_analysis', etc."""

    content: str
    """The actual draft content."""

    # Provenance tracking
    prompt_template_id: str
    """ID of the prompt template used."""

    prompt_hash: str
    """SHA-256 hash of the actual prompt sent to LLM."""

    model_id: str
    """LLM model used (e.g., 'claude-sonnet-4-20250514')."""

    inputs_hash: str
    """SHA-256 hash of structured inputs to the prompt."""

    # Timestamps
    generated_at: datetime = Field(default_factory=datetime.now)
    """When this draft was generated."""

    # NOT AUTHORITATIVE - enforced by validator
    is_authoritative: bool = False
    """Always False. DraftTextBox is never authoritative."""

    requires_human_review: bool = True
    """Always True. All drafts require human review."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def enforce_non_authoritative(self) -> DraftTextBox:
        """
        Enforce that drafts are never authoritative.

        This validator ensures LLM outputs cannot accidentally
        be treated as authoritative decisions.
        """
        if self.is_authoritative:
            raise ValueError("DraftTextBox can never be authoritative")
        if not self.requires_human_review:
            raise ValueError("DraftTextBox always requires human review")
        return self

    def to_review_item(self) -> dict:
        """
        Convert to a review item for human approval workflow.

        Returns:
            Dict with review metadata.
        """
        return {
            "box_id": self.box_id,
            "draft_type": self.draft_type,
            "content": self.content,
            "model_id": self.model_id,
            "generated_at": self.generated_at.isoformat(),
            "requires_review": True,
            "status": "pending_review",
        }
