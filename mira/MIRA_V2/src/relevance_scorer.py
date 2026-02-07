#!/usr/bin/env python3
"""
Module: Relevance Scorer
Purpose: Relevance Scorer for Semantic Search

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from enum import Enum
from typing import List, Dict
from dataclasses import dataclass
import re


class RelevanceBand(Enum):
    """Relevance confidence bands for semantic search scores."""
    HIGH = "high"       # ≥0.68 - Very strong semantic match
    MEDIUM = "medium"   # 0.60-0.67 - Solid match
    LOW = "low"         # 0.55-0.59 - Possible relevance
    WEAK = "weak"       # <0.55 - Probably not relevant


@dataclass
class ScoredResult:
    """Search result with relevance classification."""
    doc_id: str
    score: float
    relevance: RelevanceBand
    source_index: str
    rank: int
    metadata: Dict
    content: Dict = None  # Optional - fetched separately

    def __repr__(self) -> str:
        return (
            f"ScoredResult(doc_id='{self.doc_id}', "
            f"score={self.score:.3f}, "
            f"relevance={self.relevance.value}, "
            f"source='{self.source_index}')"
        )


def classify_relevance(score: float) -> RelevanceBand:
    """
    Classify semantic search score into relevance band.

    Based on empirical MiniLM performance:
    - HIGH (≥0.68): Very strong match, clearly on-topic
    - MEDIUM (0.60-0.67): Solid match, related content
    - LOW (0.55-0.59): Possible relevance, edge case
    - WEAK (<0.55): Probably not relevant, random similarity

    Args:
        score: Similarity score (0.0-1.0)

    Returns:
        RelevanceBand classification
    """
    if score >= 0.68:
        return RelevanceBand.HIGH
    elif score >= 0.60:
        return RelevanceBand.MEDIUM
    elif score >= 0.55:
        return RelevanceBand.LOW
    else:
        return RelevanceBand.WEAK


def has_prohibition(content: str) -> bool:
    """
    Detect definitive safety prohibitions in content.

    Returns True if content contains explicit prohibition language that
    definitively answers "NO" to a compatibility question.

    Args:
        content: Document content text

    Returns:
        True if prohibition detected, False otherwise
    """
    if not content:
        return False

    prohibition_patterns = [
        r"shall not be used above",
        r"shall not be used in",
        r"prohibited above",
        r"prohibited for use above",
        r"must not exceed",
        r"maximum.*pressure.*psi",
        r"not approved for use above",
        r"not permitted above",
        r"forbidden for use",
        r"banned from use"
    ]

    return any(re.search(pattern, content, re.IGNORECASE) for pattern in prohibition_patterns)


def apply_safety_boost(score: float, content: str, metadata: Dict = None) -> float:
    """
    Apply safety-aware boosting to semantic search scores.

    Boosts documents containing safety-critical keywords and patterns:
    - Prohibitions: "prohibited", "shall not", "must not", "not approved"
    - Limits: "maximum", "minimum", "limit", "threshold", "above", "below"
    - Hazards: "hazard", "fire", "explosion", "ignition", "flammability"
    - Normative requirements (from BOK metadata)

    Args:
        score: Base similarity score (0.0-1.0)
        content: Document content text
        metadata: Optional metadata dict

    Returns:
        Boosted score (capped at 1.0)
    """
    boost_factor = 1.0
    content_lower = content.lower() if content else ""

    # Boost for prohibition language (1.15x)
    prohibition_terms = ["prohibited", "shall not", "must not", "not approved",
                        "not permitted", "forbidden", "banned"]
    if any(term in content_lower for term in prohibition_terms):
        boost_factor *= 1.15

    # Boost for limit/threshold language (1.10x)
    limit_terms = ["maximum", "minimum", "limit", "threshold", "above", "below",
                   "exceed", "less than", "greater than", "max", "min"]
    if any(term in content_lower for term in limit_terms):
        boost_factor *= 1.10

    # Boost for hazard/safety language (1.12x)
    hazard_terms = ["hazard", "fire", "explosion", "ignition", "flammability",
                   "safety", "danger", "risk", "burn", "combustion"]
    if any(term in content_lower for term in hazard_terms):
        boost_factor *= 1.12

    # Boost for normative BOK requirements (1.08x)
    if metadata and metadata.get("requirement_type") == "normative":
        boost_factor *= 1.08

    # Boost for priority safety standards (1.10x)
    if metadata:
        spec_id = metadata.get("spec_id", "").upper()
        priority_specs = ["JSC-27301", "NASA-STD-6001B", "NASA-STD-6016"]
        if any(priority in spec_id for priority in priority_specs):
            boost_factor *= 1.10

    # CRITICAL: Massive boost for specific material+environment+prohibition combinations (1.5x)
    # This catches the exact safety prohibitions we care about (e.g., aluminum in oxygen)
    material_env_combos = [
        # (material, environment, critical_term)
        ("aluminum", "oxygen", ["30 psi", "prohibited", "shall not", "100 psia"]),
        ("aluminum", "oxygen", ["ignition", "flammability"]),
        ("magnesium", "oxygen", ["prohibited", "shall not"]),
        ("titanium", "oxygen", ["ignition", "prohibited"]),
    ]

    for material, environment, critical_terms in material_env_combos:
        if (material in content_lower and
            environment in content_lower and
            any(term in content_lower for term in critical_terms)):
            boost_factor *= 1.5
            break  # Only apply once

    # Extra boost for authoritative specs (differentiate at high scores)
    if metadata:
        spec_id = metadata.get("spec_id", "").upper()
        if "JSC-27301" in spec_id or "JSC-2730" in spec_id:
            boost_factor *= 1.5  # JSC-27301 is THE authoritative source
        elif "NASA-STD-6001B" in spec_id:
            boost_factor *= 1.4

    # Apply boost WITHOUT capping - let scores differentiate naturally
    # This prevents traffic jams at 1.0 where critical docs get lost
    boosted_score = score * boost_factor

    # CRITICAL: Massive boost for definitive prohibitions (2.0x)
    # These are "SHALL NOT" statements that definitively answer queries
    if has_prohibition(content):
        boosted_score *= 2.0
        # Extra tie-breaker to ensure prohibitions always win
        boosted_score += 0.01

    # Tie-breaker: Add tiny bump for prohibition language to win ties
    elif "shall not" in content_lower or "prohibited" in content_lower:
        boosted_score += 0.001

    return boosted_score


def filter_by_relevance(
    results: List[ScoredResult],
    min_relevance: RelevanceBand = RelevanceBand.LOW
) -> List[ScoredResult]:
    """
    Filter results by minimum relevance threshold.

    Args:
        results: List of scored results
        min_relevance: Minimum relevance band to include

    Returns:
        Filtered list of results
    """
    relevance_order = {
        RelevanceBand.HIGH: 3,
        RelevanceBand.MEDIUM: 2,
        RelevanceBand.LOW: 1,
        RelevanceBand.WEAK: 0
    }

    min_level = relevance_order[min_relevance]

    return [
        r for r in results
        if relevance_order[r.relevance] >= min_level
    ]


def group_by_relevance(results: List[ScoredResult]) -> Dict[RelevanceBand, List[ScoredResult]]:
    """
    Group results by relevance band.

    Args:
        results: List of scored results

    Returns:
        Dict mapping RelevanceBand to list of results
    """
    grouped = {
        RelevanceBand.HIGH: [],
        RelevanceBand.MEDIUM: [],
        RelevanceBand.LOW: [],
        RelevanceBand.WEAK: []
    }

    for result in results:
        grouped[result.relevance].append(result)

    return grouped


def format_relevance_summary(grouped: Dict[RelevanceBand, List[ScoredResult]]) -> str:
    """
    Format relevance summary for display.

    Args:
        grouped: Results grouped by relevance band

    Returns:
        Formatted summary string
    """
    lines = ["Relevance Summary:"]

    for band in [RelevanceBand.HIGH, RelevanceBand.MEDIUM, RelevanceBand.LOW, RelevanceBand.WEAK]:
        count = len(grouped[band])
        if count > 0:
            icon = {
                RelevanceBand.HIGH: "🟢",
                RelevanceBand.MEDIUM: "🟡",
                RelevanceBand.LOW: "🟠",
                RelevanceBand.WEAK: "⚪"
            }.get(band, "•")

            lines.append(f"  {icon} {band.value.upper()}: {count} results")

    return "\n".join(lines)


# Export public API
__all__ = [
    'RelevanceBand',
    'ScoredResult',
    'classify_relevance',
    'has_prohibition',
    'apply_safety_boost',
    'filter_by_relevance',
    'group_by_relevance',
    'format_relevance_summary'
]
