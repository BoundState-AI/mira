#!/usr/bin/env python3
"""
Module: Matching
Purpose: Knowledge Twins - Material Matching

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

import logging
import re
from typing import TYPE_CHECKING, List, Optional, Set

from .types import (
    EvidenceObject,
    HEMechanism,
    HeatTreatCondition,
)

if TYPE_CHECKING:
    from .h2.query import H2Query

logger = logging.getLogger(__name__)


class CandidateFinder:
    """
    Find candidate evidence objects for a material query.

    Handles:
    - Material name normalization and tokenization
    - Condition filtering (annealed, STA, etc.)
    - Alloy number matching (prevents 625 matching 718)
    - Generic query detection
    - PM variant exclusion
    """

    # Condition keywords for filtering
    CONDITION_KEYWORDS = {
        "normalized": ["normalized"],
        "annealed": ["annealed"],
        "q&t": ["q&t", "q", "quenched", "tempered"],
        "quenched": ["q&t", "q", "quenched", "tempered"],
        "tempered": ["q&t", "tempered"],
        "st": ["st", "solution"],
        "sta": ["sta", "aged"],
        "aged": ["sta", "aged"],
        "solution": ["st", "solution"],
        "as-received": ["as_received", "as-received"],
        "cold-worked": ["cold_worked", "cold-worked", "cw"],
    }

    # Map explicit condition enum to filter keywords
    CONDITION_ENUM_MAP = {
        HeatTreatCondition.ANNEALED: ["annealed"],
        HeatTreatCondition.SOLUTION_TREATED: ["st", "solution", "solution_treated"],
        HeatTreatCondition.SOLUTION_TREATED_AGED: ["sta", "aged", "solution_treated_aged"],
        HeatTreatCondition.QUENCHED_TEMPERED: ["q&t", "quenched", "tempered"],
        HeatTreatCondition.NORMALIZED: ["normalized"],
        HeatTreatCondition.AS_RECEIVED: ["as_received", "as-received"],
    }

    # Valid specifiers that make a generic family name specific
    VALID_SPECIFIERS = {
        "ofhc", "pure", "cp",  # Purity/form
        "electroformed", "electrodeposited",
        "270", "200", "201",  # Nickel grades
        "k-monel", "k", "n",  # Alloy prefixes
    }

    # Generic families that need alloy specification
    GENERIC_FAMILIES = {
        "steel": "Please specify the alloy (e.g., 316 SS, 1042, 4340)",
        "stainless": "Please specify the alloy (e.g., 304, 316, 321)",
        "inconel": "Please specify the alloy (e.g., Inconel 625, 718, 706)",
        "aluminum": "Please specify the alloy (e.g., 6061, 7075, 2024)",
        "aluminium": "Please specify the alloy (e.g., 6061, 7075, 2024)",
        "titanium": "Please specify the alloy (e.g., Ti-6Al-4V, CP Ti)",
        "nickel": "Please specify the alloy (e.g., Monel 400, Hastelloy X)",
        "copper": "Please specify the alloy (e.g., CuNi 70/30, OFHC)",
        "hastelloy": "Please specify the alloy (e.g., Hastelloy X, C-276)",
        "monel": "Please specify the alloy (e.g., Monel 400, K-500)",
        "waspaloy": None,  # Specific enough
        "haynes": "Please specify the alloy (e.g., Haynes 188, 230)",
    }

    def __init__(self, evidence_store: List[EvidenceObject]):
        self.evidence_store = evidence_store
        self.generic_query_prompt: Optional[str] = None

    def find_candidates(self, q: "H2Query") -> List[EvidenceObject]:
        """
        Find candidate evidence objects for query.

        CRITICAL: Filter by HE mechanism to avoid mixing HEE and IHE data.
        """
        candidates = []
        self.generic_query_prompt = None

        # Normalize query name
        query_lower = q.material_name.lower()
        query_tokens = self._tokenize(query_lower)

        # Detect condition requirements
        query_condition = self._get_query_condition(q, query_lower, query_tokens)

        # Extract alloy numbers (handles SS316L, 316L, etc. without word boundaries)
        # Pattern matches 2-4 digit numbers optionally followed by L/H/N suffix
        query_numbers = set(re.findall(r'(\d{2,4}[LHN]?)', q.material_name, re.IGNORECASE))
        # Also extract pure numbers without suffix
        query_pure_numbers = set(re.findall(r'(\d{2,4})', q.material_name))

        # Check for valid specifiers
        query_has_specifier = bool(query_tokens & self.VALID_SPECIFIERS)

        # Check for generic query
        if self._is_generic_query(q, query_lower, query_numbers, query_has_specifier):
            return []

        # Filter evidence
        for ev in self.evidence_store:
            if self._matches_query(ev, q, query_lower, query_tokens, query_condition,
                                   query_numbers, query_pure_numbers):
                candidates.append(ev)

        return candidates

    def _tokenize(self, text: str) -> Set[str]:
        """Tokenize text for matching.

        Handles cases like:
        - "SS316" -> {"ss", "316", "ss316"}
        - "316L" -> {"316", "l", "316l"}
        - "SS316L" -> {"ss", "316", "l", "ss316l"}
        - "Inconel-625" -> {"inconel", "625"}
        """
        # Basic tokenization
        text = text.replace("_", " ").replace("-", " ").replace("(", " ").replace(")", " ")
        tokens = set(text.split())

        # Split letter/number boundaries recursively
        expanded = set()
        to_process = list(tokens)

        while to_process:
            token = to_process.pop()
            expanded.add(token.lower())

            # Split at letter->number boundary: "SS316" -> "SS", "316"
            parts = re.split(r'(?<=[A-Za-z])(?=\d)', token)
            if len(parts) > 1:
                for p in parts:
                    if p and p.lower() not in expanded:
                        to_process.append(p)

            # Split at number->letter boundary: "316L" -> "316", "L"
            parts = re.split(r'(?<=\d)(?=[A-Za-z])', token)
            if len(parts) > 1:
                for p in parts:
                    if p and p.lower() not in expanded:
                        to_process.append(p)

        return expanded

    def _get_query_condition(
        self,
        q: "H2Query",
        query_lower: str,
        query_tokens: Set[str]
    ) -> Optional[List[str]]:
        """Extract condition filter keywords from query."""
        # Check explicit condition field first
        if q.condition and q.condition in self.CONDITION_ENUM_MAP:
            return self.CONDITION_ENUM_MAP[q.condition]

        # Check material name for condition keywords
        for kw, matches in self.CONDITION_KEYWORDS.items():
            if kw in query_lower or kw in query_tokens:
                return matches

        return None

    def _is_generic_query(
        self,
        q: "H2Query",
        query_lower: str,
        query_numbers: Set[str],
        query_has_specifier: bool
    ) -> bool:
        """Check if query is too generic and needs clarification."""
        query_words = set(query_lower.split())

        for family, prompt in self.GENERIC_FAMILIES.items():
            if family in query_words and not query_numbers and not query_has_specifier and prompt is not None:
                # Check for exact evidence match before blocking
                exact_match = any(
                    q.material_name.lower().strip() == ev.material_key.lower().strip()
                    for ev in self.evidence_store if ev.he_mechanism != HEMechanism.IHE
                )
                if exact_match:
                    return False

                self.generic_query_prompt = prompt
                logger.info(f"Generic query detected: '{q.material_name}' -> {prompt}")
                return True

        return False

    def _matches_query(
        self,
        ev: EvidenceObject,
        q: "H2Query",
        query_lower: str,
        query_tokens: Set[str],
        query_condition: Optional[List[str]],
        query_numbers: Set[str],
        query_pure_numbers: Set[str]
    ) -> bool:
        """Check if evidence matches query criteria."""

        # Filter by HE mechanism - exclude IHE for HEE queries
        if ev.he_mechanism == HEMechanism.IHE:
            return False

        # Normalize evidence
        ev_lower = ev.material_key.lower()
        ev_tokens = self._tokenize(ev_lower)

        # Condition filter
        if query_condition:
            if not self._condition_matches(ev, ev_lower, ev_tokens, query_condition):
                return False

        # Alloy number filter
        if query_pure_numbers or query_numbers:
            if not self._numbers_match(ev.material_key, query_numbers, query_pure_numbers):
                return False

        # PM variant filter
        if not self._pm_variant_matches(query_tokens, ev_tokens):
            return False

        # Token overlap matching
        overlap = query_tokens & ev_tokens
        if len(overlap) >= 1:
            # Numeric alloy identifiers (316, 625, 718) are meaningful even at 3 chars
            meaningful = any(len(t) > 3 or (t.isdigit() and len(t) >= 3) for t in overlap)
            if meaningful or len(overlap) >= 2:
                return True

        # Direct substring match as fallback
        query_clean = self._clean_for_substring(query_lower)
        ev_clean = self._clean_for_substring(ev_lower)
        if query_clean in ev_clean or ev_clean in query_clean:
            return True

        return False

    def _condition_matches(
        self,
        ev: EvidenceObject,
        ev_lower: str,
        ev_tokens: Set[str],
        query_condition: List[str]
    ) -> bool:
        """Check if evidence condition matches query condition."""
        condition_match = any(
            cond_kw in ev_lower or cond_kw in ev_tokens
            for cond_kw in query_condition
        )

        if ev.material_condition:
            ev_cond_lower = ev.material_condition.lower()
            condition_match = condition_match or any(
                cond_kw in ev_cond_lower for cond_kw in query_condition
            )

        return condition_match

    def _numbers_match(
        self,
        ev_material_key: str,
        query_numbers: Set[str],
        query_pure_numbers: Set[str]
    ) -> bool:
        """Check if alloy numbers match.

        Handles cases like:
        - Query "440A" (numbers={"440"}) vs Evidence "440A Steel" (numbers={"440"})
        - Query "316L" (numbers={"316L", "316"}) vs Evidence "316 SS" (numbers={"316"})
        """
        # Extract numbers without word boundaries (handles "440A" -> "440")
        ev_pure_numbers = set(re.findall(r'(\d{2,4})', ev_material_key))
        # Also extract with optional suffix
        ev_alphanum = set(re.findall(r'(\d{2,4}[A-Za-z]?)', ev_material_key, re.IGNORECASE))
        return bool(query_pure_numbers & ev_pure_numbers) or bool(query_numbers & ev_alphanum)

    def _pm_variant_matches(self, query_tokens: Set[str], ev_tokens: Set[str]) -> bool:
        """Check PM variant compatibility."""
        query_is_pm = "pm" in query_tokens or "powder" in query_tokens
        ev_is_pm = "pm" in ev_tokens or "powder" in ev_tokens

        if ev_is_pm and not query_is_pm:
            return False
        if query_is_pm and not ev_is_pm:
            return False

        return True

    def _clean_for_substring(self, text: str) -> str:
        """Clean text for substring matching."""
        return text.replace(" ", "").replace("-", "").replace("_", "").replace("(", "").replace(")", "")
