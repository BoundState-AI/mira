#!/usr/bin/env python3
"""
Module: Cost
Purpose: ATHENA Cost Tracking Models.

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

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# Bedrock Pricing (Verified)
BEDROCK_PRICING: dict[str, tuple[float, float]] = {
    # Model: (input_per_1k_tokens, output_per_1k_tokens)

    # Haiku 4.5
    "us.anthropic.claude-3-5-haiku-20241022-v1:0": (0.001, 0.005),
    "us-gov.anthropic.claude-3-5-haiku-20241022-v1:0": (0.001, 0.005),

    # Sonnet 4.5
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": (0.003, 0.015),
    "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0": (0.003, 0.015),
}


class CostEvent(BaseModel):
    """Single cost tracking event."""
    event_id: UUID = Field(default_factory=uuid4)
    batch_id: str
    document_id: UUID
    stage: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    model: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BatchBudget(BaseModel):
    """Budget configuration for a batch."""
    budget_usd: float
    warn_threshold_pct: float = 0.80
    stop_threshold_pct: float = 0.95
    per_document_cap_usd: float = 5.0
    on_budget_exceeded: str = "pause"  # "pause"|"fail"|"notify_continue"
