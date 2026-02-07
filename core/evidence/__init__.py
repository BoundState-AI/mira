#!/usr/bin/env python3
"""
Module:   Init  
Purpose: Evidence selection, scoring, and answer generation primitives.

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

from __future__ import annotations

# Core boundary checking (deterministic)
from .boundary_checker import (
    BOKBoundaryChecker,
    BOKLimit,
    BoundaryCheckResult,
    BoundaryVerdict,
    check_material_boundary,
    get_boundary_checker,
)

# LLM explanation generator (EXPLAINS decisions, does not MAKE them)
from .llm_answer_generator import (
    LLMAnswerGenerator,
    MaterialDecision,
    EvidenceBundle,
    EXPLANATION_SYSTEM_PROMPT,
    explain_material_decision,
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
)

# Material utilities (shared matching functions)
from .material_utils import (
    materials_match,
    normalize_material_name,
    extract_alloy_number,
    FAMILY_ALIASES,
)

# Material decider (Pydantic-based decisions)
from .material_decider import (
    MaterialDecision as PydanticMaterialDecision,
    MaterialDecider,
)

# Constraint interpreter (query parsing)
from .constraint_interpreter import (
    ConstraintInterpreter,
    MaterialConstraints,
)

__all__ = [
    # Boundary checking
    "BOKBoundaryChecker",
    "BOKLimit",
    "BoundaryCheckResult",
    "BoundaryVerdict",
    "check_material_boundary",
    "get_boundary_checker",
    # LLM explanation
    "LLMAnswerGenerator",
    "MaterialDecision",
    "EvidenceBundle",
    "EXPLANATION_SYSTEM_PROMPT",
    "explain_material_decision",
    "ValidationResult",
    "ValidationIssue",
    "ValidationSeverity",
    # Material utilities
    "materials_match",
    "normalize_material_name",
    "extract_alloy_number",
    "FAMILY_ALIASES",
    # Material decider
    "PydanticMaterialDecision",
    "MaterialDecider",
    # Constraint interpreter
    "ConstraintInterpreter",
    "MaterialConstraints",
]
