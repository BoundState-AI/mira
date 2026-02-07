#!/usr/bin/env python3
"""
Module: ID Utilities
Purpose: Hash-based ID generation for collision-resistant identifiers

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - ID Utilities

Hash-based ID generation for deterministic, collision-resistant identifiers.

Fran Fix #6: Hash-based IDs prevent collisions across environments and triggers.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

import hashlib
from typing import Optional

from mira.compliance.models.enums import FailureMode, GapTrigger


def compute_gap_id(
    material_id: str,
    environment_id: str,
    gap_type: FailureMode,
    trigger: GapTrigger,
    policy_rule: Optional[str] = None,
) -> str:
    """
    Compute a deterministic hash-based gap ID.

    Fran Fix #6: Prevents collisions across environments and triggers.
    The ID is reproducible given the same inputs.

    Args:
        material_id: Canonical material identifier (e.g., "MAPTIS:12345")
        environment_id: Environment identifier
        gap_type: Type of failure mode
        trigger: What triggered the gap
        policy_rule: Optional policy rule that caused the gap

    Returns:
        12-character hexadecimal hash string
    """
    components = f"{material_id}|{environment_id}|{gap_type.value}|{trigger.value}|{policy_rule or ''}"
    return hashlib.sha256(components.encode()).hexdigest()[:12]


def compute_constraint_id(
    material_id: str,
    parameter: str,
    limit_type: str,
    limit_value: str,
) -> str:
    """
    Compute a deterministic hash-based constraint ID.

    Args:
        material_id: Canonical material identifier
        parameter: Constrained parameter name
        limit_type: Type of limit (max, min, avoid)
        limit_value: Value of the limit

    Returns:
        12-character hexadecimal hash string
    """
    components = f"{material_id}|{parameter}|{limit_type}|{limit_value}"
    return hashlib.sha256(components.encode()).hexdigest()[:12]


def compute_mpr_determination_id(
    mpr_number: int,
    material_id: str,
    environment_id: str,
) -> str:
    """
    Compute a deterministic ID for an MPR determination.

    Args:
        mpr_number: MPR number from NASA-STD-6016C
        material_id: Canonical material identifier
        environment_id: Environment identifier

    Returns:
        12-character hexadecimal hash string
    """
    components = f"MPR-{mpr_number}|{material_id}|{environment_id}"
    return hashlib.sha256(components.encode()).hexdigest()[:12]


def compute_evidence_hash(content: str) -> str:
    """
    Compute a hash of evidence content for deduplication and tracking.

    Args:
        content: The evidence content or snippet

    Returns:
        Full SHA-256 hash string (64 characters)
    """
    return hashlib.sha256(content.encode()).hexdigest()


def compute_document_fingerprint(content: bytes) -> str:
    """
    Compute a fingerprint for a document file.

    Args:
        content: Raw bytes of the document

    Returns:
        Full SHA-256 hash string (64 characters)
    """
    return hashlib.sha256(content).hexdigest()


def compute_prompt_hash(prompt: str) -> str:
    """
    Compute a hash of an LLM prompt for reproducibility tracking.

    Fran Fix #7: Used in MUALLMInvocation for audit trail.

    Args:
        prompt: The full prompt sent to the LLM

    Returns:
        Full SHA-256 hash string (64 characters)
    """
    return hashlib.sha256(prompt.encode()).hexdigest()


def compute_inputs_hash(inputs: dict) -> str:
    """
    Compute a hash of structured inputs for reproducibility tracking.

    Fran Fix #7: Used in MUALLMInvocation for audit trail.

    Args:
        inputs: Dictionary of inputs to hash

    Returns:
        Full SHA-256 hash string (64 characters)
    """
    import json
    # Sort keys for deterministic serialization
    serialized = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()
