#!/usr/bin/env python3
"""
Module: Answer Authority
Purpose: Answer Authority System - Phase 2 of Fran's Battle Plan

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

from dataclasses import dataclass
from typing import Dict, Optional
import re


@dataclass
class AnswerAuthority:
    """
    Measures a document's ability to definitively answer the query.

    This is orthogonal to semantic similarity - a document can be semantically
    related but lack the authority to answer (e.g., research paper vs. standard).
    """
    prohibition_match: float  # 0-1: Contains explicit prohibition language
    limit_specificity: float  # 0-1: Has specific numeric limits
    standard_authority: float  # 0-1: NASA-STD > ASTM > research
    query_alignment: float    # 0-1: Directly answers the question asked

    @property
    def authority_score(self) -> float:
        """
        Weighted authority score.

        Weights based on Fran's analysis:
        - Prohibitions (40%): Most critical for safety
        - Limits (30%): Provide definitive thresholds
        - Authority (20%): Trust NASA over research
        - Alignment (10%): Answers the actual question
        """
        return (
            self.prohibition_match * 0.4 +
            self.limit_specificity * 0.3 +
            self.standard_authority * 0.2 +
            self.query_alignment * 0.1
        )


def calculate_prohibition_match(content: str) -> float:
    """
    Score how definitively the content prohibits or restricts use.

    Returns:
        1.0: Definitive prohibition (SHALL NOT, PROHIBITED)
        0.7: Strong restriction (NOT RECOMMENDED, NOT APPROVED)
        0.3: Weak caution (CAUTION, WARNING)
        0.0: No prohibition language
    """
    if not content:
        return 0.0

    content_lower = content.lower()

    # Definitive prohibitions
    definitive = [
        "shall not be used",
        "prohibited for use",
        "must not be used",
        "not approved for use",
        "not permitted"
    ]
    if any(phrase in content_lower for phrase in definitive):
        return 1.0

    # Strong restrictions
    strong = [
        "not recommended",
        "not suitable",
        "avoid use",
        "should not be used"
    ]
    if any(phrase in content_lower for phrase in strong):
        return 0.7

    # Weak cautions
    weak = ["caution", "warning", "note", "attention"]
    if any(phrase in content_lower for phrase in weak):
        return 0.3

    return 0.0


def calculate_limit_specificity(content: str) -> float:
    """
    Score how specifically the content defines limits.

    Returns:
        1.0: Exact numeric limit with units (e.g., "100 psia")
        0.7: Numeric limit without units (e.g., "100")
        0.3: Qualitative limit (e.g., "low pressure")
        0.0: No limit mentioned
    """
    if not content:
        return 0.0

    content_lower = content.lower()

    # Exact numeric limits with units
    pressure_patterns = [
        r"\d+\s*psi[a]?",
        r"\d+\s*mpa",
        r"\d+\s*bar",
        r"\d+\s*kpa"
    ]
    if any(re.search(pattern, content_lower) for pattern in pressure_patterns):
        return 1.0

    temp_patterns = [
        r"\d+\s*[°]?[cf]",
        r"\d+\s*kelvin",
        r"\d+\s*k\b"
    ]
    if any(re.search(pattern, content_lower) for pattern in temp_patterns):
        return 1.0

    # Numeric without clear units
    if re.search(r"\d+", content):
        return 0.7

    # Qualitative limits
    qualitative = ["low", "high", "moderate", "extreme"]
    if any(word in content_lower for word in qualitative):
        return 0.3

    return 0.0


def calculate_standard_authority(metadata: Optional[Dict]) -> float:
    """
    Score the authoritative weight of the source standard.

    Returns:
        1.0: NASA standards (JSC-27301, NASA-STD-6001B, etc.)
        0.8: Industry standards (ASTM, CGA, etc.)
        0.5: Government docs (SAND reports, KSC guides)
        0.3: Research papers
        0.0: Unknown source
    """
    if not metadata:
        return 0.0

    spec_id = metadata.get('spec_id', '').upper()

    # NASA standards (highest authority)
    nasa_standards = ['JSC-27301', 'JSC-2730', 'NASA-STD-6001', 'NASA-STD-6016', 'KSC-KTI']
    if any(std in spec_id for std in nasa_standards):
        return 1.0

    # Industry standards
    industry_standards = ['ASTM', 'CGA', 'ISO', 'NFPA']
    if any(std in spec_id for std in industry_standards):
        return 0.8

    # Government/lab reports
    gov_sources = ['SAND', 'OCA-GUIDE', 'SAFETY-STD']
    if any(src in spec_id for src in gov_sources):
        return 0.5

    # Unknown or research
    return 0.3


def calculate_query_alignment(content: str, query: str) -> float:
    """
    Score how directly the content answers the query.

    Returns:
        1.0: Directly addresses material + environment + parameter
        0.7: Addresses material + environment
        0.5: Addresses material only
        0.3: General information
        0.0: Unrelated
    """
    if not content or not query:
        return 0.0

    content_lower = content.lower()
    query_lower = query.lower()

    # Extract key terms from query
    materials = ['aluminum', 'steel', 'titanium', 'magnesium', 'ptfe', 'silicone']
    environments = ['oxygen', 'hydrogen', 'gox', 'lox', 'gh2', 'lh2']
    parameters = ['pressure', 'psi', 'temperature', 'psia']

    material_match = any(mat in query_lower and mat in content_lower for mat in materials)
    env_match = any(env in query_lower and env in content_lower for env in environments)
    param_match = any(param in query_lower and param in content_lower for param in parameters)

    # Score based on how many query components are addressed
    if material_match and env_match and param_match:
        return 1.0
    elif material_match and env_match:
        return 0.7
    elif material_match:
        return 0.5
    elif env_match:
        return 0.3

    return 0.0


def calculate_answer_authority(
    content: str,
    query: str,
    metadata: Optional[Dict] = None
) -> AnswerAuthority:
    """
    Calculate comprehensive answer authority for a document.

    Args:
        content: Document content text
        query: User's query
        metadata: Document metadata (spec_id, etc.)

    Returns:
        AnswerAuthority with all component scores
    """
    return AnswerAuthority(
        prohibition_match=calculate_prohibition_match(content),
        limit_specificity=calculate_limit_specificity(content),
        standard_authority=calculate_standard_authority(metadata),
        query_alignment=calculate_query_alignment(content, query)
    )


def apply_authority_boost(
    base_score: float,
    authority: AnswerAuthority,
    max_boost: float = 3.0
) -> float:
    """
    Apply authority-based boost to semantic similarity score.

    Args:
        base_score: Base semantic similarity score
        authority: Calculated answer authority
        max_boost: Maximum multiplier (default 3.0x)

    Returns:
        Boosted score
    """
    # Authority score ranges 0-1, boost ranges 1.0-max_boost
    boost_factor = 1.0 + (authority.authority_score * (max_boost - 1.0))

    return base_score * boost_factor


# Export public API
__all__ = [
    'AnswerAuthority',
    'calculate_answer_authority',
    'apply_authority_boost',
    'calculate_prohibition_match',
    'calculate_limit_specificity',
    'calculate_standard_authority',
    'calculate_query_alignment'
]
