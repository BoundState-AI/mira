#!/usr/bin/env python3
"""
Module: Query Context
Purpose: Shared state bag for the MIRA V3 query pipeline.

Every pipeline stage reads from and writes to this context.
No globals. No side channels. This is the single source of truth.

BoundState AI 2026
Version: 3.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class QueryIntent(str, Enum):
    """Classified query intent. See RULES.md §3.1."""
    COMPATIBILITY = "compatibility"
    MATERIALS_SEARCH = "materials_search"
    DOCUMENT_LOOKUP = "document_lookup"
    COMPARISON = "comparison"
    GENERAL = "general"
    UNKNOWN = "unknown"


class EnvironmentClass(str, Enum):
    """Coarse environment classification for safety decisions."""
    OXYGEN = "oxygen"
    HYDROGEN = "hydrogen"
    AIR_VACUUM = "air_vacuum"
    OTHER = "other"


class Verdict(str, Enum):
    """Final material decision outcomes."""
    YES = "YES"
    YES_WITH_CAVEATS = "YES_WITH_CAVEATS"
    NO = "NO"
    CONDITIONAL = "CONDITIONAL"
    REQUIRES_TESTING = "REQUIRES_TESTING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class MaterialConstraints:
    """Parsed query constraints. Canonical units: psi, °C."""
    material: Optional[str] = None
    configuration: Optional[str] = None
    pressure_psi: Optional[float] = None
    temp_c_min: Optional[float] = None
    temp_c_max: Optional[float] = None
    o2_pct: Optional[float] = None
    environment: Optional[str] = None
    environment_class: Optional[EnvironmentClass] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "material": self.material,
            "configuration": self.configuration,
            "pressure_psi": self.pressure_psi,
            "temp_c_min": self.temp_c_min,
            "temp_c_max": self.temp_c_max,
            "o2_pct": self.o2_pct,
            "environment": self.environment,
            "environment_class": self.environment_class.value if self.environment_class else None,
        }


@dataclass
class StageResult:
    """Metadata about a single stage execution."""
    stage_name: str
    duration_ms: float
    skipped: bool = False
    error: Optional[str] = None


@dataclass
class QueryContext:
    """
    Shared state bag for the entire query pipeline.

    Every stage reads what it needs and writes what it produces.
    Fields are Optional because not every stage runs for every query.
    """

    # ── Input ──────────────────────────────────────────────────────
    raw_query: str
    created_at: float = field(default_factory=time.time)

    # ── Stage 1: Parse ─────────────────────────────────────────────
    constraints: Optional[MaterialConstraints] = None

    # ── Stage 2: Classify ──────────────────────────────────────────
    intent: QueryIntent = QueryIntent.UNKNOWN
    intent_scores: Dict[str, float] = field(default_factory=dict)
    intent_evidence: List[str] = field(default_factory=list)

    # ── Stage 3: Route (sets which sub-pipeline runs) ──────────────
    pipeline_name: str = "unknown"

    # ── Stage 4: Boundary Check (O2/H2 hard rules) ────────────────
    boundary_verdict: Optional[Verdict] = None
    boundary_rationale: Optional[str] = None
    boundary_short_circuited: bool = False

    # ── Stage 5: MUA Retrieval ─────────────────────────────────────
    mua_precedents: List[Dict[str, Any]] = field(default_factory=list)

    # ── Stage 6: Test Retrieval ────────────────────────────────────
    test_results: List[Dict[str, Any]] = field(default_factory=list)

    # ── Stage 7: Semantic Search ───────────────────────────────────
    semantic_evidence: Optional[Dict[str, Any]] = None

    # ── Stage 8: Evidence Evaluation ───────────────────────────────
    has_sufficient_evidence: bool = False
    evidence_eval_reason: Optional[str] = None

    # ── Stage 9: Material Decisions ────────────────────────────────
    decisions: List[Dict[str, Any]] = field(default_factory=list)

    # ── Stage 10: LLM Answer Generation ───────────────────────────
    llm_answer: Optional[str] = None

    # ── Alt Pipeline: Materials Search ─────────────────────────────
    materials_found: List[Dict[str, Any]] = field(default_factory=list)

    # ── Requirements (shared across stages) ────────────────────────
    requirements: List[Dict[str, Any]] = field(default_factory=list)

    # ── Pipeline metadata ──────────────────────────────────────────
    stage_results: List[StageResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # ── Response building ──────────────────────────────────────────

    def to_response(self) -> Dict[str, Any]:
        """Build the final API response from accumulated context."""
        elapsed_ms = (time.time() - self.created_at) * 1000

        # Short-circuit response for boundary violations
        if self.boundary_short_circuited:
            return {
                "status": "SUCCESS",
                "query": self.raw_query,
                "deterministic_decision": self.boundary_verdict.value,
                "decision_source": "O2_BOUNDARY_CHECK",
                "decision_rationale": self.boundary_rationale,
                "constraints": self.constraints.to_dict() if self.constraints else {},
                "mua_precedents_found": 0,
                "test_results_found": 0,
                "decisions": [{
                    "material_name": self.constraints.material if self.constraints else "unknown",
                    "verdict": self.boundary_verdict.value,
                    "reason": self.boundary_rationale,
                    "source": "O2_DETERMINISTIC_BOUNDARY",
                }],
                "llm_answer": f"**{self.boundary_verdict.value}** — {self.boundary_rationale}",
                "pipeline": self.pipeline_name,
                "elapsed_ms": round(elapsed_ms, 1),
            }

        # Materials search response
        if self.pipeline_name == "materials_search":
            return {
                "status": "SUCCESS",
                "query": self.raw_query,
                "query_type": "materials_search",
                "constraints": self.constraints.to_dict() if self.constraints else {},
                "materials_found": len(self.materials_found),
                "materials": self.materials_found,
                "note": (
                    "Simple materials lookup — no compatibility rules applied. "
                    "For compatibility assessment, ask 'Is X compatible with O2?'"
                ),
                "pipeline": self.pipeline_name,
                "elapsed_ms": round(elapsed_ms, 1),
            }

        # Insufficient data response
        if not self.has_sufficient_evidence and self.pipeline_name == "compatibility":
            mat = self.constraints.material if self.constraints else "unknown"
            return {
                "status": "INSUFFICIENT_DATA",
                "query": self.raw_query,
                "message": self.evidence_eval_reason or f"No evidence found for '{mat}'",
                "recommendation": "Testing required per NASA-STD-6001B before use",
                "constraints": self.constraints.to_dict() if self.constraints else {},
                "pipeline": self.pipeline_name,
                "elapsed_ms": round(elapsed_ms, 1),
            }

        # Full compatibility response
        return {
            "status": "SUCCESS",
            "query": self.raw_query,
            "constraints": self.constraints.to_dict() if self.constraints else {},
            "mua_precedents_found": len(self.mua_precedents),
            "mua_precedents": self.mua_precedents[:5],
            "test_results_found": len(self.test_results),
            "requirements_evaluated": len(self.requirements),
            "decisions": self.decisions,
            "material_decisions": self.decisions,  # Alias for backward compat
            "evidence_first_verified": True,
            "semantic_evidence": self.semantic_evidence,
            "llm_answer": self.llm_answer,
            "pipeline": self.pipeline_name,
            "elapsed_ms": round(elapsed_ms, 1),
        }
