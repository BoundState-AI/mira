#!/usr/bin/env python3
"""
Module: Engine Simple
Purpose: Compatibility verdict.

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

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    from .aliases import (
        CANONICAL_NAMES,
        detect_material_family,
        extract_alloy_numbers,
        get_canonical_name,
        normalize,
    )
except ImportError:
    # Direct execution - use absolute import
    from aliases import (
        CANONICAL_NAMES,
        detect_material_family,
        extract_alloy_numbers,
        get_canonical_name,
        normalize,
    )

LOGGER = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Path to evidence database (relative to this file)
DEFAULT_EVIDENCE_PATH = Path(__file__).parent.parent.parent / "data" / "h2_evidence_merged.json"

# HEE band severity order (worst to best)
HEE_BAND_ORDER = ["extreme", "severe", "high", "small", "negligible"]

# Fuzzy match threshold (0-1)
FUZZY_THRESHOLD = 0.75

# Pressure thresholds for warnings (in PSI)
HIGH_PRESSURE_PSI = 10000  # Most test data is below this

# Conversion: 1 MPa = 145.038 PSI
_MPA_PER_PSI = 0.00689476

# Envelope tolerance factors — how close query must be to evidence
_PRESSURE_LOG_TOLERANCE = 0.5   # ≤ ~3× ratio in pressure
_TEMPERATURE_TOLERANCE_C = 50   # ± 50°C considered "matching"
_CRYO_BOUNDARY_C = -150         # below this = cryogenic regime


# =============================================================================
# DATA CLASSES
# =============================================================================

class Verdict(str, Enum):
    """Compatibility verdict."""
    PROHIBITED = "prohibited"  # SEVERE or EXTREME HEE - do not use
    CAUTION = "caution"        # HIGH HEE - use with significant restrictions
    ACCEPTABLE = "acceptable"  # SMALL or NEGLIGIBLE HEE - generally safe
    UNKNOWN = "unknown"        # No evidence found
    CLARIFICATION_NEEDED = "clarification_needed"  # Multiple conditions with different bands


@dataclass
class EvidenceRecord:
    """Single piece of HEE evidence from the database."""
    evidence_id: str
    material_name: str
    material_family: str
    hee_band: str
    hee_index: float
    source_document: str
    source_table: str
    condition: Optional[str] = None
    pressure_mpa: Optional[float] = None
    temperature_c: Optional[float] = None

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceRecord":
        """Create from JSON record."""
        source = data.get("source", {})
        heat_treatment = data.get("heat_treatment", {})
        test_conditions = data.get("test_conditions", {})

        return cls(
            evidence_id=data.get("evidence_id", "unknown"),
            material_name=data.get("material_name", ""),
            material_family=data.get("material_family", "unknown"),
            hee_band=data.get("hee_band", "unknown"),
            hee_index=data.get("hee_index", 0.0),
            source_document=source.get("document", "unknown"),
            source_table=source.get("table", ""),
            condition=heat_treatment.get("condition"),
            pressure_mpa=test_conditions.get("pressure_mpa"),
            temperature_c=test_conditions.get("temperature_c"),
        )


@dataclass
class MatchedEvidence:
    """Evidence record with match metadata."""
    record: EvidenceRecord
    match_type: str  # "exact", "alias", "fuzzy", "alloy_number", "family"
    match_score: float = 1.0  # 0-1, higher is better match


@dataclass
class ConditionOption:
    """Option presented when clarification is needed due to multiple conditions.

    Used when a material has different HEE bands depending on heat treatment
    and the user didn't specify which condition they're asking about.
    """
    condition_name: str       # "ST 1750F", "ST 1900F", "Solution Treated + Aged"
    hee_band: str            # "severe", "small", "extreme"
    verdict_if_selected: str  # "prohibited", "acceptable", etc.
    evidence_count: int       # How many records support this
    source: str              # "NASA/TM-2016-218602", "Sandia"


@dataclass
class H2Result:
    """Result of an H2 compatibility query.

    This is the simplified output - designed to be easy to understand and debug.
    """
    # Core verdict
    verdict: Verdict
    hee_band: Optional[str]  # The worst-case band found

    # Explanation
    rationale: str
    warnings: list[str] = field(default_factory=list)

    # Evidence details
    evidence_count: int = 0
    band_distribution: dict[str, int] = field(default_factory=dict)
    top_evidence: list[dict] = field(default_factory=list)  # Simplified evidence records

    # Match quality
    match_type: str = "none"  # Best match type found
    canonical_name: Optional[str] = None  # Resolved canonical name if any

    # MUA precedents (from MIRA_V2 FAISS search)
    mua_precedents: list[dict] = field(default_factory=list)
    has_mua_denial: bool = False  # Safety flag - MUA denied for this material

    # Clarification data when verdict = CLARIFICATION_NEEDED
    available_conditions: list[ConditionOption] = field(default_factory=list)
    clarification_prompt: Optional[str] = None

    # Envelope context — populated when query includes pressure/temperature
    envelope_context: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "verdict": self.verdict.value,
            "hee_band": self.hee_band,
            "rationale": self.rationale,
            "warnings": self.warnings,
            "evidence_count": self.evidence_count,
            "band_distribution": self.band_distribution,
            "top_evidence": self.top_evidence,
            "match_type": self.match_type,
            "canonical_name": self.canonical_name,
            "mua_precedents": self.mua_precedents,
            "has_mua_denial": self.has_mua_denial,
        }
        # Add clarification data only when relevant
        if self.available_conditions:
            result["available_conditions"] = [
                {
                    "condition_name": c.condition_name,
                    "hee_band": c.hee_band,
                    "verdict_if_selected": c.verdict_if_selected,
                    "evidence_count": c.evidence_count,
                    "source": c.source,
                }
                for c in self.available_conditions
            ]
        if self.clarification_prompt:
            result["clarification_prompt"] = self.clarification_prompt
        if self.envelope_context:
            result["envelope_context"] = self.envelope_context
        return result


# =============================================================================
# H2 ENGINE
# =============================================================================

class H2Engine:
    """Simplified H2 Knowledge Twin engine.

    Performs material lookup and returns worst-case HEE assessment.

    Optionally integrates with MIRA_V2 MUA FAISS search for precedent lookup.
    """

    def __init__(
        self,
        evidence_path: Optional[Path] = None,
        enable_mua_search: bool = True,
    ):
        """Initialize the engine.

        Args:
            evidence_path: Path to h2_evidence_merged.json. Uses default if None.
            enable_mua_search: Enable MUA precedent search via FAISS (default: True)
        """
        self._evidence_path = evidence_path or DEFAULT_EVIDENCE_PATH
        self._evidence: list[EvidenceRecord] = []
        self._material_index: dict[str, list[EvidenceRecord]] = defaultdict(list)
        self._loaded = False

        # MUA search integration (optional - graceful degradation if unavailable)
        self._mua_search = None
        self._enable_mua_search = enable_mua_search
        if enable_mua_search:
            try:
                # Try relative import first (when imported as package)
                from mira_v2.mua_search import MUASearch
                self._mua_search = MUASearch()
                LOGGER.info("MUA search enabled")
            except ImportError:
                try:
                    # Try absolute import (when mira_v2 is installed)
                    import sys
                    mira_root = Path(__file__).parent.parent.parent
                    if str(mira_root) not in sys.path:
                        sys.path.insert(0, str(mira_root))
                    from mira_v2.mua_search import MUASearch
                    self._mua_search = MUASearch()
                    LOGGER.info("MUA search enabled (via path injection)")
                except ImportError:
                    LOGGER.debug("MUA search not available (mira_v2 not installed)")
            except Exception as e:
                LOGGER.warning(f"MUA search initialization failed: {e}")

    def _ensure_loaded(self) -> None:
        """Load evidence database if not already loaded."""
        if self._loaded:
            return

        if not self._evidence_path.exists():
            LOGGER.error(f"Evidence file not found: {self._evidence_path}")
            self._loaded = True
            return

        try:
            with open(self._evidence_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            evidence_list = data.get("evidence", [])
            self._evidence = [EvidenceRecord.from_dict(r) for r in evidence_list]

            # Build material name index for fast lookup
            for record in self._evidence:
                norm_name = normalize(record.material_name)
                self._material_index[norm_name].append(record)

            LOGGER.info(f"Loaded {len(self._evidence)} evidence records")
            self._loaded = True

        except Exception as e:
            LOGGER.error(f"Failed to load evidence: {e}")
            self._loaded = True

    def query(
        self,
        material: str,
        pressure_psi: Optional[float] = None,
        temperature_k: Optional[float] = None,
        condition: Optional[str] = None,
    ) -> H2Result:
        """Query hydrogen compatibility for a material.

        Args:
            material: Material name or alias (e.g., "Inconel 718", "718", "SS316L")
                      Can include condition suffix: "Inconel 718 ST", "Ti-6Al-4V annealed"
            pressure_psi: Optional operating pressure in PSI (for envelope matching)
            temperature_k: Optional operating temperature in Kelvin (for envelope matching)
            condition: Optional heat treatment condition filter (overrides parsed condition)

        Returns:
            H2Result with verdict, rationale, evidence, and envelope context.
        """
        self._ensure_loaded()

        # Step 0: Parse condition from query string if not explicitly provided
        parsed_material, parsed_condition = self._parse_query(material)
        effective_condition = condition or parsed_condition
        effective_material = parsed_material if parsed_condition else material

        # Step 1: Find matching evidence
        matches = self._find_matches(effective_material)

        # Step 2: Filter by condition if specified (explicit or parsed)
        condition_specified = effective_condition is not None
        if effective_condition and matches:
            matches = self._filter_by_condition(matches, effective_condition)

        # Step 3: Generate verdict from matches
        result = self._generate_verdict(matches, material, condition_specified)

        # Step 4: MUA precedent lookup (if available)
        if self._mua_search:
            try:
                mua_result = self._lookup_mua_precedents(effective_material)
                result.mua_precedents = mua_result.get("precedents", [])
                result.has_mua_denial = mua_result.get("has_denial", False)

                # SAFETY CRITICAL: If MUA denial found, override verdict to PROHIBITED
                if result.has_mua_denial:
                    result.verdict = Verdict.PROHIBITED
                    denial = mua_result.get("denial_precedent", {})
                    result.warnings.insert(0,
                        f"MUA DENIAL FOUND: {denial.get('mua_id', 'unknown')} - "
                        f"Material denied for hydrogen service. {denial.get('summary', '')[:100]}"
                    )
            except Exception as e:
                LOGGER.warning(f"MUA lookup failed for '{effective_material}': {e}")

        # Step 5: Envelope matching — compare query conditions to evidence range
        if matches and (pressure_psi is not None or temperature_k is not None):
            envelope = self._compute_envelope_context(
                matches, pressure_psi, temperature_k,
            )
            result.envelope_context = envelope

            # Add envelope warnings
            for warning in envelope.get("warnings", []):
                result.warnings.append(warning)
        elif pressure_psi and pressure_psi > HIGH_PRESSURE_PSI:
            # Fallback: simple high-pressure warning when no matches to compare
            result.warnings.append(
                f"Query pressure ({pressure_psi:,.0f} psi) exceeds most test data (~10,000 psi). "
                "Extrapolation may be required."
            )

        return result

    def _lookup_mua_precedents(self, material: str) -> dict:
        """Look up MUA precedents for a material via FAISS search.

        Args:
            material: Material name to search

        Returns:
            Dict with keys:
                - precedents: List of MUA precedent dicts
                - has_denial: True if any denied MUAs found
                - denial_precedent: The denied MUA if found
        """
        if not self._mua_search:
            return {"precedents": [], "has_denial": False}

        result = {
            "precedents": [],
            "has_denial": False,
            "denial_precedent": None,
        }

        # Check for denials first (safety critical)
        has_denial, denial = self._mua_search.has_denied_precedent(material, environment="hydrogen")
        if has_denial and denial:
            result["has_denial"] = True
            result["denial_precedent"] = {
                "mua_id": denial.mua_id,
                "material_name": denial.material_name,
                "determination": denial.determination,
                "summary": denial.summary,
                "score": denial.score,
            }
            LOGGER.warning(f"MUA denial found for '{material}': {denial.mua_id}")

        # Get hydrogen precedents
        precedents = self._mua_search.find_hydrogen_precedents(material, top_k=5)
        result["precedents"] = [
            {
                "mua_id": p.mua_id,
                "material_name": p.material_name,
                "environment": p.environment,
                "determination": p.determination,
                "summary": p.summary,
                "score": p.score,
                "pressure_max_psi": p.pressure_max_psi,
                "temp_min_c": p.temp_min_c,
                "temp_max_c": p.temp_max_c,
            }
            for p in precedents
        ]

        return result

    # Known condition suffix patterns — ordered longest-first to avoid partial matches.
    # Each entry: (regex_pattern, canonical_condition_label)
    _CONDITION_SUFFIXES: list[tuple[str, str]] = [
        # Multi-word
        (r"\bsolution\s+treated?\s*\+?\s*aged\b", "solution_treated_aged"),
        (r"\bsolution\s+treated?\s+and\s+aged\b", "solution_treated_aged"),
        (r"\bst\s*\+?\s*aged?\b", "solution_treated_aged"),
        (r"\bsolution\s+treated?\b", "solution_treated"),
        (r"\bcold\s+worked\b", "cold_worked"),
        (r"\bcold\s+drawn\b", "cold_drawn"),
        (r"\bhot\s+rolled\b", "hot_rolled"),
        (r"\bhot\s+finished\b", "hot_finished"),
        (r"\bas\s+received\b", "as_received"),
        (r"\bmill\s+annealed?\b", "mill_annealed"),
        (r"\bpeak\s+aged?\b", "peak_aged"),
        # Abbreviations (must come after multi-word to avoid partial matches)
        (r"\bSTA\b", "solution_treated_aged"),
        (r"\bST\s+(\d{3,4}\s*°?\s*F)\b", "solution_treated"),  # ST 1900F — keep temp in material
        (r"\bST\b", "solution_treated"),
        (r"\bCW\b", "cold_worked"),
        # Single-word conditions
        (r"\bannealed?\b", "annealed"),
        (r"\baged?\b", "aged"),
        (r"\bnormalized\b", "normalized"),
        (r"\bquenched\b", "quenched"),
        (r"\btempered\b", "tempered"),
        (r"\bwrought\b", "wrought"),
        (r"\bcast\b", "cast"),
        (r"\bforged\b", "forged"),
        (r"\bsintered\b", "sintered"),
    ]

    def _parse_query(self, query: str) -> tuple[str, Optional[str]]:
        """Extract material name and condition from query string.

        Deterministic suffix matching — no LLM calls. Patterns are tried
        longest-first against the tail of the query. Only matches at a word
        boundary are accepted to avoid false positives.

        Args:
            query: Raw query string, possibly with condition suffix

        Returns:
            Tuple of (material_name, condition) where condition is None if not found.

        Examples:
            "Inconel 718 ST" → ("Inconel 718", "solution_treated")
            "Inconel 718 STA" → ("Inconel 718", "solution_treated_aged")
            "Ti-6Al-4V annealed" → ("Ti-6Al-4V", "annealed")
            "K-Monel aged" → ("K-Monel", "aged")
            "316L" → ("316L", None)
            "316L at 5000 psi" → ("316L", None)  # pressure not a condition
        """
        import re

        text = query.strip()
        if not text:
            return query, None

        # Strip trailing pressure/temperature phrases before condition parsing
        # e.g., "Inconel 718 ST at 5000 psi" → "Inconel 718 ST"
        text = re.sub(
            r"\s+(?:at|@)\s+\d[\d,]*\.?\d*\s*(?:psi|psia|mpa|ksi|°?[FCK])\s*$",
            "", text, flags=re.IGNORECASE,
        ).strip()

        for pattern, canonical in self._CONDITION_SUFFIXES:
            # Only match at the end of the string (with optional trailing whitespace)
            full_pattern = pattern + r"\s*$"
            m = re.search(full_pattern, text, re.IGNORECASE)
            if m:
                # Special case: "ST 1900F" — the temperature is part of the condition
                # label but we want to keep it in the condition, not the material
                material = text[:m.start()].strip()
                if not material:
                    # The entire query was a condition — don't split
                    return query, None

                # Build display condition from matched text
                matched_text = m.group(0).strip()

                LOGGER.debug(
                    "Parsed query '%s' → material='%s', condition='%s' (matched '%s')",
                    query, material, canonical, matched_text,
                )
                return material, canonical

        return query, None

    def _find_matches(self, query: str) -> list[MatchedEvidence]:
        """Find all evidence records matching the query material.

        Uses a tiered matching strategy, but ALWAYS includes variant matches
        (e.g., "Incoloy 903 (ST + Aged)" when searching for "Incoloy 903")
        to ensure worst-case safety assessment.

        Tiers:
        1. Exact match + variants (normalized)
        2. Alias lookup + variants
        3. Alloy number match
        4. Fuzzy string match
        5. Material family match (last resort)
        """
        norm_query = normalize(query)
        matches: list[MatchedEvidence] = []
        matched_ids: set[str] = set()  # Track what we've added

        def add_match(record: EvidenceRecord, match_type: str, score: float) -> None:
            """Add a match if not already added."""
            if record.evidence_id not in matched_ids:
                matches.append(MatchedEvidence(record, match_type, score))
                matched_ids.add(record.evidence_id)

        # Tier 1: Exact match in material index
        exact_found = False
        if norm_query in self._material_index:
            for record in self._material_index[norm_query]:
                add_match(record, "exact", 1.0)
                exact_found = True

        # ALWAYS check for variants - materials with parenthetical conditions
        # e.g., "Incoloy 903" should also find "Incoloy 903 (ST + Aged)"
        # This is CRITICAL for safety - variants may have worse HEE bands!
        for norm_name, records in self._material_index.items():
            # Check if this is a variant of our query
            # "incoloy 903 st aged" starts with "incoloy 903"
            if norm_name.startswith(norm_query + " ") or norm_query.startswith(norm_name + " "):
                for record in records:
                    add_match(record, "variant", 0.95)

        if exact_found:
            return matches

        # Tier 2: Alias lookup + variants
        canonical = get_canonical_name(query)
        alias_found = False
        if canonical:
            norm_canonical = normalize(canonical)
            if norm_canonical in self._material_index:
                for record in self._material_index[norm_canonical]:
                    add_match(record, "alias", 0.95)
                    alias_found = True

            # Also check for variants of the canonical name
            for norm_name, records in self._material_index.items():
                if norm_name.startswith(norm_canonical + " ") or norm_canonical.startswith(norm_name + " "):
                    for record in records:
                        add_match(record, "variant", 0.90)

        if alias_found or matches:
            return matches

        # Tier 3: Alloy number matching (e.g., "718" matches "Inconel 718")
        query_numbers = extract_alloy_numbers(query)
        if query_numbers:
            for norm_name, records in self._material_index.items():
                record_numbers = extract_alloy_numbers(norm_name)
                # Match if query number is subset of record numbers
                if query_numbers & record_numbers:
                    for record in records:
                        add_match(record, "alloy_number", 0.85)

        if matches:
            return matches

        # Tier 4: Fuzzy string matching
        for norm_name, records in self._material_index.items():
            score = SequenceMatcher(None, norm_query, norm_name).ratio()
            if score >= FUZZY_THRESHOLD:
                for record in records:
                    add_match(record, "fuzzy", score)

        if matches:
            return matches

        # Tier 5: Material family fallback
        family = detect_material_family(query)
        if family:
            for record in self._evidence:
                if record.material_family == family:
                    add_match(record, "family", 0.5)

        return matches

    def _filter_by_condition(
        self,
        matches: list[MatchedEvidence],
        query_condition: str
    ) -> list[MatchedEvidence]:
        """Filter matches by heat treatment condition.

        Prefers condition-matched evidence but falls back to all matches
        if no condition matches found.
        """
        query_label = self._resolve_condition(query_condition, query_condition, "query").display_label
        query_norm = normalize(query_label)
        if not query_norm or query_norm in {"generic unknown", "unknown"}:
            return matches

        condition_matches: list[MatchedEvidence] = []
        for m in matches:
            record_label = self._condition_label(m.record)
            record_norm = normalize(record_label)
            if not record_norm:
                continue
            if query_norm == record_norm or query_norm in record_norm or record_norm in query_norm:
                condition_matches.append(m)

        return condition_matches if condition_matches else matches

    def _generate_verdict(
        self,
        matches: list[MatchedEvidence],
        original_query: str,
        condition_specified: bool = False,
    ) -> H2Result:
        """Generate verdict from matched evidence.

        Uses worst-case (most severe) HEE band for conservative safety,
        unless condition is unspecified and multiple conditions exist with
        different HEE bands - in which case, ask for clarification.
        """
        if not matches:
            return H2Result(
                verdict=Verdict.UNKNOWN,
                hee_band=None,
                rationale=f"No evidence found for '{original_query}'. "
                         "Please verify the material name or use a more specific designation.",
                match_type="none",
            )

        # Group by HEE band
        bands: dict[str, list[MatchedEvidence]] = defaultdict(list)
        for m in matches:
            bands[m.record.hee_band].append(m)

        # Build band distribution early (needed for clarification check)
        band_dist = {band: len(records) for band, records in bands.items()}

        # Get canonical name if resolved
        canonical = get_canonical_name(original_query)

        # Get best match type
        match_types = [m.match_type for m in matches]
        best_match = "exact" if "exact" in match_types else \
                     "alias" if "alias" in match_types else \
                     "alloy_number" if "alloy_number" in match_types else \
                     "fuzzy" if "fuzzy" in match_types else "family"

        # Get top evidence (up to 5)
        top_evidence = self._format_top_evidence(matches[:5])

        # Get the material name from best match
        best_match_record = max(matches, key=lambda m: m.match_score)
        material_name = best_match_record.record.material_name

        # =================================================================
        # CLARIFICATION CHECK: Multiple conditions with different HEE bands
        # =================================================================
        if not condition_specified and len(bands) > 1:
            # Check if we have multiple distinct conditions
            condition_options, unresolved_count, _unresolved_aliases = self._extract_condition_options(matches, bands)

            # Only ask for clarification if we have multiple condition options
            # with DIFFERENT HEE bands
            if len(condition_options) > 1:
                unique_bands = set(opt.hee_band for opt in condition_options)
                if len(unique_bands) > 1:
                    # Multiple conditions with different bands - ask for clarification
                    return H2Result(
                        verdict=Verdict.CLARIFICATION_NEEDED,
                        hee_band=None,
                        rationale=f"{material_name} shows varying HEE bands depending on "
                                  "heat treatment condition. Please specify the condition.",
                        evidence_count=len(matches),
                        band_distribution=band_dist,
                        top_evidence=top_evidence,
                        match_type=best_match,
                        canonical_name=canonical,
                        available_conditions=condition_options,
                        clarification_prompt="Multiple heat treatment conditions found with "
                                            "different hydrogen compatibility. Please specify:",
                        warnings=(
                            [f"{unresolved_count} condition label(s) need mapping review."]
                            if unresolved_count > 0
                            else []
                        ),
                    )

        # =================================================================
        # STANDARD VERDICT: Worst-case assessment
        #
        # Rule coverage (vs knowledge_twins/h2/rules.py):
        #   R001 Severe HEE Block     → severe/extreme → PROHIBITED (below)
        #   R002 Weld HAZ Warning     → requires weld_state input (not in query API yet)
        #   R003 Aged Condition Warn  → covered by clarification flow above
        #   R004 High Strength        → 150 ksi guardrail in mira/h2/engine.py
        # =================================================================

        # Find worst-case band
        worst_band = None
        for band in HEE_BAND_ORDER:
            if band in bands:
                worst_band = band
                break

        if not worst_band:
            # All evidence has unknown bands
            worst_band = "unknown"

        # Map band to verdict
        verdict_map = {
            "extreme": Verdict.PROHIBITED,
            "severe": Verdict.PROHIBITED,
            "high": Verdict.CAUTION,
            "small": Verdict.ACCEPTABLE,
            "negligible": Verdict.ACCEPTABLE,
            "unknown": Verdict.UNKNOWN,
        }
        verdict = verdict_map.get(worst_band, Verdict.UNKNOWN)

        # Generate rationale
        rationale = self._generate_rationale(bands, worst_band, matches)

        # Build warnings for varying evidence
        warnings = []
        if len(bands) > 1:
            warnings.append(
                f"Evidence shows variation across {len(bands)} HEE bands. "
                "Heat treatment and test conditions affect results."
            )

        return H2Result(
            verdict=verdict,
            hee_band=worst_band,
            rationale=rationale,
            warnings=warnings,
            evidence_count=len(matches),
            band_distribution=band_dist,
            top_evidence=top_evidence,
            match_type=best_match,
            canonical_name=canonical,
        )

    def _extract_condition_options(
        self,
        matches: list[MatchedEvidence],
        bands: dict[str, list[MatchedEvidence]],
    ) -> tuple[list[ConditionOption], int, list[dict]]:
        """Extract unique condition options from evidence matches.

        Groups evidence by condition and returns ConditionOption objects
        for each unique condition with its corresponding HEE band and verdict.
        """
        # Map band to verdict for condition options
        verdict_map = {
            "extreme": "prohibited",
            "severe": "prohibited",
            "high": "caution",
            "small": "acceptable",
            "negligible": "acceptable",
            "unknown": "unknown",
        }

        # Group by condition (including condition hints embedded in material_name)
        condition_groups: dict[str, list[MatchedEvidence]] = defaultdict(list)
        unresolved_count = 0
        unresolved_aliases: list[dict] = []
        seen_raw_keys: set[str] = set()
        for m in matches:
            resolved = self._resolve_condition(
                m.record.condition or "",
                m.record.material_name,
                m.record.source_document,
            )
            cond = resolved.display_label
            if resolved.needs_review:
                unresolved_count += 1
                if resolved.raw_key not in seen_raw_keys:
                    seen_raw_keys.add(resolved.raw_key)
                    unresolved_aliases.append({
                        "raw_key": resolved.raw_key,
                        "raw_text": resolved.raw_text,
                        "canonical_condition": resolved.canonical_condition,
                        "display_label": resolved.display_label,
                        "is_condition": resolved.is_condition,
                        "confidence": resolved.confidence,
                        "resolver_provider": resolved.resolver_provider,
                        "resolver_model": resolved.resolver_model,
                        "needs_review": True,
                        "human_verified": False,
                        "source_document": m.record.source_document,
                        "material_name": m.record.material_name,
                    })
            condition_groups[cond].append(m)

        # Build condition options
        options = []
        for cond_name, cond_matches in condition_groups.items():
            # Find the worst band for this condition
            cond_bands = defaultdict(int)
            sources = set()
            for m in cond_matches:
                cond_bands[m.record.hee_band] += 1
                sources.add(m.record.source_document)

            # Get worst band for this condition
            worst_cond_band = None
            for band in HEE_BAND_ORDER:
                if band in cond_bands:
                    worst_cond_band = band
                    break
            if not worst_cond_band:
                worst_cond_band = "unknown"

            options.append(ConditionOption(
                condition_name=cond_name,
                hee_band=worst_cond_band,
                verdict_if_selected=verdict_map.get(worst_cond_band, "unknown"),
                evidence_count=len(cond_matches),
                source=", ".join(sorted(sources)[:2]),  # Limit to 2 sources
            ))

        # Sort by HEE band severity (best to worst for user to see safest option first)
        band_priority = {band: i for i, band in enumerate(reversed(HEE_BAND_ORDER))}
        band_priority["unknown"] = len(HEE_BAND_ORDER)
        options.sort(key=lambda o: band_priority.get(o.hee_band, 999))

        return options, unresolved_count, unresolved_aliases

    def _resolve_condition(
        self,
        raw_condition: str,
        material_name: str,
        source_document: str,
    ):
        """Resolve condition label through cache-backed LLM normalizer."""
        from mira.h2.condition_resolver import resolve_condition_label

        return resolve_condition_label(
            raw_condition=raw_condition,
            material_name=material_name,
            source_document=source_document,
        )

    def _condition_label(self, record: EvidenceRecord) -> str:
        """Resolve display condition from alias table / LLM cache."""
        return self._resolve_condition(
            record.condition or "",
            record.material_name,
            record.source_document,
        ).display_label

    def _generate_rationale(
        self,
        bands: dict[str, list[MatchedEvidence]],
        worst_band: str,
        matches: list[MatchedEvidence]
    ) -> str:
        """Generate human-readable rationale for the verdict."""
        # Get the material name from best match
        best_match = max(matches, key=lambda m: m.match_score)
        material_name = best_match.record.material_name

        if len(bands) == 1:
            # Single band - simple case
            band = list(bands.keys())[0]
            count = len(bands[band])
            return (
                f"{material_name}: All {count} evidence record(s) show {band.upper()} "
                f"hydrogen embrittlement effect."
            )

        # Multiple bands - explain variation
        band_summary = ", ".join(
            f"{band} ({len(records)})"
            for band in HEE_BAND_ORDER
            if band in bands
            for records in [bands[band]]
        )

        # Check if variation is due to condition
        conditions = set()
        for m in matches:
            if m.record.condition:
                conditions.add(m.record.condition)

        variation_reason = ""
        if len(conditions) > 1:
            variation_reason = " Variation due to heat treatment condition."

        return (
            f"{material_name}: Evidence shows {band_summary} HEE bands. "
            f"Using {worst_band.upper()} for conservative assessment.{variation_reason}"
        )

    def _format_top_evidence(self, matches: list[MatchedEvidence]) -> list[dict]:
        """Format top evidence for output."""
        return [
            {
                "material": m.record.material_name,
                "hee_band": m.record.hee_band,
                "hee_index": m.record.hee_index,
                "source": m.record.source_document,
                "table": m.record.source_table,
                "condition": m.record.condition,
                "match_type": m.match_type,
                "pressure_mpa": m.record.pressure_mpa,
                "temperature_c": m.record.temperature_c,
            }
            for m in matches
        ]

    # -----------------------------------------------------------------
    # ENVELOPE MATCHING — pressure/temperature context
    # -----------------------------------------------------------------

    def _compute_envelope_context(
        self,
        matches: list[MatchedEvidence],
        query_pressure_psi: Optional[float],
        query_temperature_k: Optional[float],
    ) -> dict:
        """Compare query operating conditions against matched evidence envelopes.

        Returns a structured context dict with:
        - evidence_pressure_range_mpa: [min, max] across matched evidence
        - evidence_temperature_range_c: [min, max] across matched evidence
        - query_pressure_mpa / query_temperature_c: converted query values
        - pressure_match / temperature_match: "within", "extrapolation", or None
        - regime_match: whether query and evidence are in same thermal regime
        - warnings: list of human-readable extrapolation warnings
        """
        warnings: list[str] = []

        # Convert query values to metric
        query_pressure_mpa = (
            query_pressure_psi * _MPA_PER_PSI
            if query_pressure_psi is not None
            else None
        )
        query_temp_c = (
            query_temperature_k - 273.15
            if query_temperature_k is not None
            else None
        )

        # Collect evidence pressure and temperature ranges
        ev_pressures = [
            m.record.pressure_mpa
            for m in matches
            if m.record.pressure_mpa is not None
        ]
        ev_temps = [
            m.record.temperature_c
            for m in matches
            if m.record.temperature_c is not None
        ]

        context: dict = {
            "query_pressure_mpa": round(query_pressure_mpa, 2) if query_pressure_mpa is not None else None,
            "query_temperature_c": round(query_temp_c, 1) if query_temp_c is not None else None,
            "evidence_pressure_range_mpa": (
                [round(min(ev_pressures), 1), round(max(ev_pressures), 1)]
                if ev_pressures else None
            ),
            "evidence_temperature_range_c": (
                [round(min(ev_temps), 0), round(max(ev_temps), 0)]
                if ev_temps else None
            ),
            "pressure_match": None,
            "temperature_match": None,
            "regime_match": None,
            "warnings": warnings,
        }

        # --- Pressure envelope matching ---
        if query_pressure_mpa is not None and ev_pressures:
            p_min, p_max = min(ev_pressures), max(ev_pressures)

            if p_min > 0 and query_pressure_mpa > 0:
                # Use log-ratio to handle wide pressure ranges fairly
                log_ratio_low = abs(math.log10(query_pressure_mpa / p_min)) if p_min > 0 else 0
                log_ratio_high = abs(math.log10(query_pressure_mpa / p_max)) if p_max > 0 else 0

                within_range = p_min <= query_pressure_mpa <= p_max
                close_to_range = min(log_ratio_low, log_ratio_high) <= _PRESSURE_LOG_TOLERANCE

                if within_range:
                    context["pressure_match"] = "within"
                elif close_to_range:
                    context["pressure_match"] = "near"
                else:
                    context["pressure_match"] = "extrapolation"
                    ratio = query_pressure_mpa / p_max if query_pressure_mpa > p_max else p_min / query_pressure_mpa
                    warnings.append(
                        f"Pressure extrapolation: query {query_pressure_mpa:.1f} MPa "
                        f"({query_pressure_psi:,.0f} psi) is {ratio:.1f}× outside evidence range "
                        f"[{p_min:.1f}–{p_max:.1f} MPa]. HEE behavior may differ at this pressure."
                    )
            elif query_pressure_mpa > 0 and p_min == 0:
                context["pressure_match"] = "within"  # evidence at zero includes ambient

        # --- Temperature envelope matching ---
        if query_temp_c is not None and ev_temps:
            t_min, t_max = min(ev_temps), max(ev_temps)

            within_range = (t_min - _TEMPERATURE_TOLERANCE_C) <= query_temp_c <= (t_max + _TEMPERATURE_TOLERANCE_C)
            if within_range:
                context["temperature_match"] = "within"
            else:
                context["temperature_match"] = "extrapolation"
                if query_temp_c < t_min:
                    delta = t_min - query_temp_c
                    warnings.append(
                        f"Temperature extrapolation: query {query_temp_c:.0f}°C is "
                        f"{delta:.0f}°C below evidence minimum ({t_min:.0f}°C). "
                        "Cryogenic behavior may differ."
                    )
                else:
                    delta = query_temp_c - t_max
                    warnings.append(
                        f"Temperature extrapolation: query {query_temp_c:.0f}°C is "
                        f"{delta:.0f}°C above evidence maximum ({t_max:.0f}°C). "
                        "Elevated-temperature embrittlement behavior may differ."
                    )

            # Regime check — cryogenic vs ambient/elevated
            query_cryo = query_temp_c < _CRYO_BOUNDARY_C
            evidence_has_cryo = any(t < _CRYO_BOUNDARY_C for t in ev_temps)
            evidence_has_ambient = any(t >= _CRYO_BOUNDARY_C for t in ev_temps)

            if query_cryo and not evidence_has_cryo:
                context["regime_match"] = "mismatch"
                warnings.append(
                    "Thermal regime mismatch: query is cryogenic but evidence is "
                    "ambient/elevated only. Cryogenic HEE behavior can differ significantly."
                )
            elif not query_cryo and not evidence_has_ambient:
                context["regime_match"] = "mismatch"
                warnings.append(
                    "Thermal regime mismatch: query is ambient/elevated but evidence is "
                    "cryogenic only."
                )
            else:
                context["regime_match"] = "matched"

        return context

    def get_all_materials(self) -> list[str]:
        """Get list of all unique material names in the evidence database."""
        self._ensure_loaded()
        return sorted(set(r.material_name for r in self._evidence))

    def get_evidence_stats(self) -> dict:
        """Get statistics about the evidence database."""
        self._ensure_loaded()

        band_counts = defaultdict(int)
        family_counts = defaultdict(int)
        source_counts = defaultdict(int)

        for r in self._evidence:
            band_counts[r.hee_band] += 1
            family_counts[r.material_family] += 1
            source_counts[r.source_document] += 1

        return {
            "total_records": len(self._evidence),
            "unique_materials": len(set(r.material_name for r in self._evidence)),
            "band_distribution": dict(band_counts),
            "family_distribution": dict(family_counts),
            "source_distribution": dict(source_counts),
        }

    def get_condition_options(self, material: str) -> dict:
        """Return condition options for a material without requiring full query.

        This is used by UI dropdown/autocomplete to pre-populate known
        heat-treatment conditions before running a full compatibility check.
        """
        self._ensure_loaded()
        matches = self._find_matches(material)
        if not matches:
            return {
                "has_matches": False,
                "canonical_material": None,
                "match_type": "none",
                "available_conditions": [],
                "band_distribution": {},
                "requires_clarification": False,
            }

        bands = defaultdict(list)
        for m in matches:
            bands[m.record.hee_band].append(m)

        options, unresolved_count, unresolved_aliases = self._extract_condition_options(matches, bands)
        unique_bands = {opt.hee_band for opt in options}
        best_match = max(matches, key=lambda m: m.match_score)
        canonical = get_canonical_name(material)
        if not canonical:
            canonical = best_match.record.material_name

        return {
            "has_matches": True,
            "canonical_material": canonical,
            "match_type": best_match.match_type,
            "available_conditions": [
                {
                    "condition_name": opt.condition_name,
                    "hee_band": opt.hee_band,
                    "verdict_if_selected": opt.verdict_if_selected,
                    "evidence_count": opt.evidence_count,
                    "source": opt.source,
                }
                for opt in options
            ],
            "band_distribution": {band: len(records) for band, records in bands.items()},
            "requires_clarification": len(options) > 1 and len(unique_bands) > 1,
            "unresolved_condition_count": unresolved_count,
            "unresolved_aliases": unresolved_aliases,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Module-level singleton
_engine: Optional[H2Engine] = None


def get_engine() -> H2Engine:
    """Get the singleton H2Engine instance."""
    global _engine
    if _engine is None:
        _engine = H2Engine()
    return _engine


def query(
    material: str,
    pressure_psi: Optional[float] = None,
    temperature_k: Optional[float] = None,
    condition: Optional[str] = None,
) -> H2Result:
    """Convenience function to query H2 compatibility.

    Example:
        >>> result = query("Inconel 718", pressure_psi=3000)
        >>> print(result.verdict)
        prohibited
    """
    return get_engine().query(material, pressure_psi, temperature_k, condition)
