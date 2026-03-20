#!/usr/bin/env python3
"""
Module: Enriched Search
Purpose: Enriched MUA Search with Precedent Classification.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from mira.miul.mua_faiss_search import MUAFAISSSearch, MUASearchResult

__all__ = [
    "FAMILY_MAP",
    "FAMILY_MAP_REVERSE",
    "SUPPORTING_DETERMINATIONS",
    "CONFLICTING_DETERMINATIONS",
    "EnrichedMUAResult",
    "EnrichedSearchResults",
    "EnrichedMUASearch",
    "search_enriched_precedents",
]

__safety_critical__ = True

LOGGER = logging.getLogger(__name__)


# Family translation map:
# MaterialCodeLookupService uses UPPERCASE: TITANIUM, NICKEL, STAINLESS, ALUMINUM
# MUAFAISSSearch metadata uses lowercase: titanium, nickel, stainless_steel, aluminum
FAMILY_MAP: Dict[str, str] = {
    # Lookup service format -> FAISS metadata format
    "TITANIUM": "titanium",
    "NICKEL": "nickel",
    "STAINLESS": "stainless_steel",
    "ALUMINUM": "aluminum",
    # Additional FAISS families (no direct lookup service equivalent)
    "COPPER": "copper",
    "POLYMER": "polymer",
    "ADHESIVE": "adhesive",
    "LUBRICANT": "lubricant",
    "COMPOSITE": "composite",
}

# Reverse map: FAISS metadata format -> Lookup service format
FAMILY_MAP_REVERSE: Dict[str, str] = {v: k for k, v in FAMILY_MAP.items()}
# Special case: inconel is a nickel alloy family in FAISS
FAMILY_MAP_REVERSE["inconel"] = "NICKEL"
# other -> OTHER for consistency
FAMILY_MAP_REVERSE["other"] = "OTHER"


# Determination values that count as supporting precedent
# APPROVED_WITH_LIMITS is supporting per user decision
SUPPORTING_DETERMINATIONS: Set[str] = {
    "APPROVED",
    "APPROVED_WITH_LIMITS",
}

# Determination values that count as conflicting precedent
CONFLICTING_DETERMINATIONS: Set[str] = {
    "REJECTED",
}

# Determinations that go to "other" (neither supporting nor conflicting)
# CANCELLED, DEFERRED, UNKNOWN, etc.


@dataclass
class EnrichedMUAResult:
    """Enriched MUA search result with precedent classification.

    Extends MUASearchResult fields with normalized family and classification flags.

    SWE-013: Includes source field for traceability.
    """
    # Core fields from MUASearchResult
    rank: int
    score: float
    semantic_score: float
    string_score: float
    file: str
    mua_number: Optional[str]
    material_designation: str
    material_family: Optional[str]  # Normalized to UPPERCASE (lookup service format)
    material_family_raw: Optional[str]  # Original FAISS metadata format
    is_umbrella: bool
    environment: Optional[str]
    category: Optional[str]
    determination: str
    rationale: Optional[str]
    application: Optional[str]

    # Enrichment fields
    is_supporting: bool = False
    is_conflicting: bool = False
    source: str = "MUAFAISSSearch"  # SWE-013 traceability

    @classmethod
    def from_search_result(cls, result: MUASearchResult, rank: int) -> "EnrichedMUAResult":
        """Create enriched result from base MUASearchResult.

        Args:
            result: Base search result from MUAFAISSSearch
            rank: Result rank (may differ from result.rank after filtering)

        Returns:
            EnrichedMUAResult with normalized family and classification
        """
        # Normalize family to lookup service format (UPPERCASE)
        normalized_family = None
        if result.material_family:
            normalized_family = FAMILY_MAP_REVERSE.get(
                result.material_family.lower(),
                result.material_family.upper()  # Fallback to uppercase
            )

        # Classify as supporting or conflicting based on determination
        determination_upper = (result.determination or "").upper().strip()
        is_supporting = determination_upper in SUPPORTING_DETERMINATIONS
        is_conflicting = determination_upper in CONFLICTING_DETERMINATIONS

        return cls(
            rank=rank,
            score=result.score,
            semantic_score=result.semantic_score,
            string_score=result.string_score,
            file=result.file,
            mua_number=result.mua_number,
            material_designation=result.material_designation,
            material_family=normalized_family,
            material_family_raw=result.material_family,
            is_umbrella=result.is_umbrella,
            environment=result.environment,
            category=result.category,
            determination=result.determination,
            rationale=result.rationale,
            application=result.application,
            is_supporting=is_supporting,
            is_conflicting=is_conflicting,
            source=f"MUAFAISSSearch:{result.file}",
        )


@dataclass
class EnrichedSearchResults:
    """Collection of enriched search results split by precedent type.

    Provides convenient access to supporting vs conflicting precedents.

    SWE-013: Includes source field for traceability.
    """
    query_material: str
    query_environment: Optional[str]
    query_family: Optional[str]  # Lookup service format if provided

    all_results: List[EnrichedMUAResult] = field(default_factory=list)
    supporting: List[EnrichedMUAResult] = field(default_factory=list)
    conflicting: List[EnrichedMUAResult] = field(default_factory=list)
    other: List[EnrichedMUAResult] = field(default_factory=list)

    source: str = "EnrichedMUASearch"  # SWE-013 traceability

    @property
    def has_supporting_precedent(self) -> bool:
        """True if any supporting precedent found (APPROVED or APPROVED_WITH_LIMITS)."""
        return len(self.supporting) > 0

    @property
    def has_conflicting_precedent(self) -> bool:
        """True if any conflicting precedent found (REJECTED)."""
        return len(self.conflicting) > 0

    @property
    def supporting_count(self) -> int:
        """Count of supporting precedents."""
        return len(self.supporting)

    @property
    def conflicting_count(self) -> int:
        """Count of conflicting precedents."""
        return len(self.conflicting)

    @property
    def total_count(self) -> int:
        """Total number of results."""
        return len(self.all_results)

    def get_best_supporting(self) -> Optional[EnrichedMUAResult]:
        """Get the best (lowest score) supporting precedent."""
        return self.supporting[0] if self.supporting else None

    def get_best_conflicting(self) -> Optional[EnrichedMUAResult]:
        """Get the best (lowest score) conflicting precedent."""
        return self.conflicting[0] if self.conflicting else None


class EnrichedMUASearch:
    """Enriched MUA search with family normalization and precedent splitting.

    Wraps MUAFAISSSearch to provide:
    - Family normalization between lookup service and FAISS metadata formats
    - Automatic splitting of results into supporting vs conflicting precedents
    - APPROVED_WITH_LIMITS treated as supporting precedent

    Example:
        >>> search = EnrichedMUASearch()
        >>> results = search.search("INCONEL 625", "Oxygen")
        >>> print(f"Supporting: {results.supporting_count}")
        >>> print(f"Conflicting: {results.conflicting_count}")
        >>> if results.has_supporting_precedent:
        ...     best = results.get_best_supporting()
        ...     print(f"Best precedent: {best.mua_number}")
    """

    def __init__(self, search: Optional[MUAFAISSSearch] = None):
        """Initialize enriched search.

        Args:
            search: Optional pre-initialized MUAFAISSSearch instance.
                   If None, creates a new instance (loads FAISS index).
        """
        self._search = search or MUAFAISSSearch()

    @property
    def using_gpu(self) -> bool:
        """Whether FAISS is using GPU acceleration."""
        return self._search.using_gpu

    @property
    def metadata_count(self) -> int:
        """Number of MUAs in the index."""
        return len(self._search.metadata) if self._search.metadata else 0

    def normalize_family(self, family: Optional[str]) -> Optional[str]:
        """Normalize family name to FAISS metadata format (lowercase with underscores).

        Args:
            family: Family name in any format (STAINLESS, stainless_steel, etc.)

        Returns:
            Family name in FAISS metadata format, or None
        """
        if not family:
            return None

        family_upper = family.upper().strip()
        return FAMILY_MAP.get(family_upper, family.lower().replace(" ", "_"))

    def normalize_family_to_lookup(self, family: Optional[str]) -> Optional[str]:
        """Normalize family name to lookup service format (UPPERCASE).

        Args:
            family: Family name in any format

        Returns:
            Family name in lookup service format (UPPERCASE), or None
        """
        if not family:
            return None

        family_lower = family.lower().strip().replace(" ", "_")
        return FAMILY_MAP_REVERSE.get(family_lower, family.upper())

    def search(
        self,
        material: str,
        environment: Optional[str] = None,
        application: Optional[str] = None,
        k: int = 10,
        filter_umbrella: bool = True,
        family_filter: Optional[str] = None,
        string_weight: float = 0.4,
    ) -> EnrichedSearchResults:
        """Search for MUA precedents with enrichment and classification.

        Args:
            material: Material designation (e.g., "INCONEL 625")
            environment: Optional environment (e.g., "Oxygen")
            application: Optional application context
            k: Number of results to return
            filter_umbrella: Filter out umbrella MUAs (default True)
            family_filter: Only return MUAs from this family
                          (accepts both formats: "STAINLESS" or "stainless_steel")
            string_weight: Weight for string matching (0-1)

        Returns:
            EnrichedSearchResults with results split by precedent type.

        SWE-013: Results traceable to MUAFAISSSearch:mua_bok_v2.
        """
        # Normalize family filter to FAISS format if provided
        normalized_family_filter = self.normalize_family(family_filter)

        # Perform base search
        base_results = self._search.search(
            material=material,
            environment=environment,
            application=application,
            k=k,
            filter_umbrella=filter_umbrella,
            family_filter=normalized_family_filter,
            string_weight=string_weight,
        )

        # Build enriched results collection
        enriched_results = EnrichedSearchResults(
            query_material=material,
            query_environment=environment,
            query_family=family_filter,
        )

        # Enrich and classify each result
        for i, result in enumerate(base_results, start=1):
            enriched = EnrichedMUAResult.from_search_result(result, rank=i)
            enriched_results.all_results.append(enriched)

            # Classify into supporting/conflicting/other
            if enriched.is_supporting:
                enriched_results.supporting.append(enriched)
            elif enriched.is_conflicting:
                enriched_results.conflicting.append(enriched)
            else:
                enriched_results.other.append(enriched)

        LOGGER.info(
            f"EnrichedMUASearch: '{material}' in '{environment or 'any'}' -> "
            f"{enriched_results.supporting_count} supporting, "
            f"{enriched_results.conflicting_count} conflicting, "
            f"{len(enriched_results.other)} other"
        )

        return enriched_results

    def search_supporting_only(
        self,
        material: str,
        environment: Optional[str] = None,
        k: int = 5,
        family_filter: Optional[str] = None,
    ) -> List[EnrichedMUAResult]:
        """Convenience method to get only supporting precedents.

        Searches for more results to ensure at least k supporting.

        Args:
            material: Material designation
            environment: Optional environment
            k: Desired number of supporting results
            family_filter: Optional family filter

        Returns:
            List of up to k supporting precedents (APPROVED or APPROVED_WITH_LIMITS)
        """
        # Search for more results to ensure we get k supporting
        results = self.search(
            material=material,
            environment=environment,
            k=k * 3,  # Over-fetch to account for non-supporting results
            family_filter=family_filter,
        )
        return results.supporting[:k]

    def search_conflicting_only(
        self,
        material: str,
        environment: Optional[str] = None,
        k: int = 5,
        family_filter: Optional[str] = None,
    ) -> List[EnrichedMUAResult]:
        """Convenience method to get only conflicting precedents.

        Args:
            material: Material designation
            environment: Optional environment
            k: Desired number of conflicting results
            family_filter: Optional family filter

        Returns:
            List of up to k conflicting precedents (REJECTED)
        """
        results = self.search(
            material=material,
            environment=environment,
            k=k * 5,  # Over-fetch more since rejections are rarer
            family_filter=family_filter,
        )
        return results.conflicting[:k]


def search_enriched_precedents(
    material: str,
    environment: Optional[str] = None,
    k: int = 10,
    family_filter: Optional[str] = None,
) -> EnrichedSearchResults:
    """Search for enriched MUA precedents.

    Convenience function that creates search instance and performs search.

    Args:
        material: Material designation
        environment: Optional environment
        k: Number of results
        family_filter: Optional family filter

    Returns:
        EnrichedSearchResults with supporting/conflicting split.

    Example:
        >>> results = search_enriched_precedents("316L SST", "Oxygen", k=5)
        >>> if results.has_supporting_precedent:
        ...     for p in results.supporting:
        ...         print(f"{p.mua_number}: {p.determination}")
    """
    search = EnrichedMUASearch()
    return search.search(
        material=material,
        environment=environment,
        k=k,
        family_filter=family_filter,
    )
