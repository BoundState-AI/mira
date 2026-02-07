#!/usr/bin/env python3
"""
Module: Aggregated Ratings
Purpose: Hierarchical rating aggregation across related MAPTIS material codes.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True

BACKGROUND:
A single alloy like A-286 (UNS S66286) may have 38+ different MAPTIS codes,
each representing a different product form (bar, sheet, forging) or strength
grade (130 ksi, 160 ksi). Most ratings data is sparse - only a few codes
have comprehensive test coverage.

This module provides intelligent rating aggregation:
1. Finds all related material codes for a base alloy
2. Aggregates ratings using chemistry-based vs form-dependent rules
3. Returns the most relevant rating with clear provenance

RATING INHERITANCE RULES:
- CORR (Corrosion): Chemistry-driven → INHERIT across all forms
- TOX (Toxicity): Chemistry-driven → INHERIT across all forms
- FLAM (Flammability): Mostly chemistry → INHERIT with caution (thin forms may differ)
- PROM (Promoted Combustion): Alloy family behavior → INHERIT within family
- SCC (Stress Corrosion): Form/temper dependent → PREFER same form, allow inherit
- TVS (Outgassing): Form dependent → PREFER same form
- FS (Fluid Compatibility): Test-specific → DO NOT INHERIT
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Set

import psycopg2
from psycopg2.extras import DictCursor

from mira.miul.maptis_ratings import EXPIRE_FLAG_MAP, INVALID_RATINGS

__all__ = [
    "get_aggregated_ratings",
    "AggregatedRatingsClient",
    "RatingSource",
    "AggregatedRating",
    "InheritanceRule",
]

logger = logging.getLogger(__name__)


class InheritanceRule(str, Enum):
    """Rating inheritance rules by category."""
    INHERIT = "inherit"  # Safe to inherit from any related code
    PREFER_SAME_FORM = "prefer_same_form"  # Prefer same form, allow inherit if none
    DO_NOT_INHERIT = "do_not_inherit"  # Only use exact code match


# Inheritance rules per rating category
RATING_INHERITANCE_RULES: Dict[str, Tuple[InheritanceRule, str]] = {
    "CORR": (InheritanceRule.INHERIT, "Corrosion is chemistry-driven; same alloy = same behavior"),
    "TOX": (InheritanceRule.INHERIT, "Toxicity is chemistry-driven; same alloy = same offgassing"),
    "FLAM": (InheritanceRule.PREFER_SAME_FORM, "Flammability mostly chemistry but thin forms may ignite easier"),
    "PROM": (InheritanceRule.INHERIT, "Promoted combustion is alloy-family behavior"),
    "SCC": (InheritanceRule.PREFER_SAME_FORM, "SCC depends on cold work and temper; form matters"),
    "TVS": (InheritanceRule.PREFER_SAME_FORM, "Outgassing varies with surface-to-volume ratio"),
    "FS": (InheritanceRule.DO_NOT_INHERIT, "Fluid compatibility is test-condition-specific"),
}

# Rating severity for worst-case aggregation
RATING_SEVERITY = {"A": 1, "B": 2, "C": 3, "D": 4, "I": 5, "K": 6, "N": 7, "U": 8, "X": 9}

# Contract ID → (JSON field, MIUL column) mapping
RATING_MAP = {
    "flammability_report": ("flam_rating", "FLAM"),
    "promoted_combustion_report": ("prom_rating", "PROM"),
    "stress_corrosion_cracking_report": ("stress_rating", "SCC"),
    "corrosion_report": ("cor_rating", "CORR"),
    "tvs_outgassing_report": ("tvs_rating", "TVS"),
    "toxicity_report": ("tox_spacestationrating", "TOX"),
    "fluid_compatibility_report": ("fluc_rating", "FS"),
}

# Product form normalization
FORM_ALIASES = {
    "BAR": ["BAR", "ROD", "ROUND"],
    "SHEET": ["SHEET", "SKIN", "SHIM"],
    "PLATE": ["PLATE"],
    "FORGING": ["FORGING", "FORGED", "SUPER FORGING"],
    "TUBE": ["TUBE", "TUBING", "PIPE"],
    "WIRE": ["WIRE", "CABLE"],
    "FASTENER": ["FASTENER", "BOLT", "SCREW", "NUT"],
    "SHAPES": ["SHAPES", "SHAPE", "EXTRUSION"],
    "STRIP": ["STRIP", "BAND"],
    "WELDED": ["WELDED", "WELD"],
}


@dataclass
class RatingSource:
    """Provenance for a single rating value."""
    rating: str  # The rating value (A, B, C, etc.)
    material_code: str  # MAPTIS code this came from
    designation: str  # Material designation
    is_exact_match: bool  # True if from the requested code
    is_same_form: bool  # True if product form matches
    confidence: float  # 0.0-1.0 confidence in this rating
    test_count: int = 0  # Number of tests this rating is based on


@dataclass
class AggregatedRating:
    """Aggregated rating with provenance."""
    category: str  # FLAM, SCC, CORR, etc.
    rating: Optional[str]  # Aggregated rating value (None if no data)
    primary_source: Optional[RatingSource]  # Best source for this rating
    all_sources: List[RatingSource] = field(default_factory=list)  # All sources considered
    inheritance_rule: InheritanceRule = InheritanceRule.INHERIT
    note: str = ""  # Explanation of aggregation logic


@dataclass
class AggregatedRatingsResult:
    """Complete aggregated ratings for a material."""
    requested_code: str
    requested_designation: str
    related_codes_count: int
    ratings: Dict[str, AggregatedRating]
    warnings: List[str] = field(default_factory=list)


class AggregatedRatingsClient:
    """Client for aggregated ratings lookup with inheritance logic."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize client with database connection params.

        Uses centralized db_config module for credentials. Environment variables:
            POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
        """
        try:
            from mira.core.db_config import get_db_connection_params
            self._conn_params = get_db_connection_params(
                host=host, port=port, database=database, user=user, password=password
            )
        except ImportError:
            # Fallback if db_config not available
            self._conn_params = {
                "host": host or os.environ.get("POSTGRES_HOST", "localhost"),
                "port": port or int(os.environ.get("POSTGRES_PORT", "5432")),
                "database": database or os.environ.get("POSTGRES_DB", "mira"),
                "user": user or os.environ.get("POSTGRES_USER", "postgres"),
                "password": password or os.environ.get("POSTGRES_PASSWORD", "postgres"),
            }
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._conn_params)
        return self._conn

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def get_aggregated_ratings(
        self,
        material_code: str,
        material_form: Optional[str] = None,
    ) -> AggregatedRatingsResult:
        """Get aggregated ratings for a material code with inheritance.

        Args:
            material_code: Primary MAPTIS material code (e.g., "10011")
            material_form: Optional product form for preferential matching (e.g., "BAR")

        Returns:
            AggregatedRatingsResult with ratings from primary and related codes
        """
        if not material_code:
            return AggregatedRatingsResult(
                requested_code="",
                requested_designation="",
                related_codes_count=0,
                ratings={},
                warnings=["No material code provided"],
            )

        material_code = str(material_code).strip()
        conn = self._get_conn()
        cursor = conn.cursor(cursor_factory=DictCursor)

        try:
            # Step 1: Get the primary material's info (designation, UNS)
            primary_info = self._get_material_info(cursor, material_code)
            if not primary_info:
                return AggregatedRatingsResult(
                    requested_code=material_code,
                    requested_designation="",
                    related_codes_count=0,
                    ratings={},
                    warnings=[f"Material code {material_code} not found in database"],
                )

            designation = primary_info["designation"]
            uns_code = self._extract_uns(designation)
            base_alloy = self._extract_base_alloy(designation)

            # Step 2: Find all related material codes (same UNS or base alloy)
            related_codes = self._find_related_codes(cursor, uns_code, base_alloy, material_code)
            all_codes = [material_code] + [r["material_code"] for r in related_codes]

            logger.info(
                f"[AggRatings] Code {material_code} ({designation}): "
                f"found {len(related_codes)} related codes"
            )

            # Step 3: Get ratings for all related codes
            all_ratings = self._get_ratings_for_codes(cursor, all_codes)

            # Step 4: Aggregate ratings per category with inheritance rules
            aggregated = {}
            warnings = []

            for category in ["FLAM", "PROM", "SCC", "CORR", "TVS", "TOX", "FS"]:
                rule, rule_reason = RATING_INHERITANCE_RULES.get(
                    category, (InheritanceRule.INHERIT, "")
                )

                agg_rating = self._aggregate_category(
                    category=category,
                    primary_code=material_code,
                    related_codes=related_codes,
                    all_ratings=all_ratings,
                    material_form=material_form,
                    rule=rule,
                )
                agg_rating.note = rule_reason
                aggregated[category] = agg_rating

                # Add warning if using inherited rating
                if agg_rating.primary_source and not agg_rating.primary_source.is_exact_match:
                    warnings.append(
                        f"{category} rating '{agg_rating.rating}' inherited from "
                        f"{agg_rating.primary_source.material_code} "
                        f"({agg_rating.primary_source.designation})"
                    )

            return AggregatedRatingsResult(
                requested_code=material_code,
                requested_designation=designation,
                related_codes_count=len(related_codes),
                ratings=aggregated,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"[AggRatings] Error for {material_code}: {e}")
            return AggregatedRatingsResult(
                requested_code=material_code,
                requested_designation="",
                related_codes_count=0,
                ratings={},
                warnings=[f"Database error: {str(e)}"],
            )
        finally:
            cursor.close()

    def _get_material_info(self, cursor, material_code: str) -> Optional[Dict]:
        """Get basic info for a material code."""
        cursor.execute(
            """
            SELECT material_code, designation, composition, use_type
            FROM materials
            WHERE material_code = %s
            """,
            (material_code,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def _extract_uns(self, designation: str) -> Optional[str]:
        """Extract UNS code from designation (e.g., S66286 from 'A-286 UNS S66286')."""
        match = re.search(r'\b([SNCGKJT]\d{5})\b', designation.upper())
        return match.group(1) if match else None

    def _extract_base_alloy(self, designation: str) -> Optional[str]:
        """Extract base alloy identifier for fuzzy matching.

        Examples:
            "A-286 CRES BAR 140KSI" → "A-286"
            "INCONEL 718 FORGING" → "INCONEL 718"
            "6061-T6 ALUMINUM PLATE" → "6061"
            "SS 316L BAR" → "316"
        """
        text = designation.upper()

        # A-286 family
        if "A-286" in text or "A286" in text:
            return "A-286"

        # Inconel family
        match = re.search(r'INCONEL\s*(\d{3})', text)
        if match:
            return f"INCONEL {match.group(1)}"

        # Hastelloy family
        match = re.search(r'HASTELLOY\s*([A-Z]-?\d+)', text)
        if match:
            return f"HASTELLOY {match.group(1)}"

        # Aluminum alloys (4-digit)
        match = re.search(r'\b(\d{4})[-]?[TFHOW]?\d*\b', text)
        if match:
            return match.group(1)

        # Stainless steel (3-digit)
        match = re.search(r'\b(3\d{2})[LNH]?\b', text)
        if match:
            return match.group(1)

        return None

    def _find_related_codes(
        self,
        cursor,
        uns_code: Optional[str],
        base_alloy: Optional[str],
        exclude_code: str,
    ) -> List[Dict]:
        """Find all material codes related to the same base alloy."""
        conditions = []
        params = []

        if uns_code:
            conditions.append("designation ILIKE %s")
            params.append(f"%{uns_code}%")

        if base_alloy:
            # Use word boundaries to avoid false matches
            conditions.append("designation ~* %s")
            # Escape regex special chars in alloy name
            escaped = re.escape(base_alloy)
            params.append(f"\\y{escaped}\\y")

        if not conditions:
            return []

        query = f"""
            SELECT material_code, designation, use_type
            FROM materials
            WHERE ({" OR ".join(conditions)})
              AND material_code != %s
            ORDER BY designation
            LIMIT 100
        """
        params.append(exclude_code)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def _get_ratings_for_codes(
        self, cursor, material_codes: List[str]
    ) -> Dict[str, Dict[str, List[RatingSource]]]:
        """Get all ratings for a list of material codes.

        Returns:
            Dict[material_code][category] = List[RatingSource]
        """
        result: Dict[str, Dict[str, List[RatingSource]]] = {
            code: {cat: [] for cat in ["FLAM", "PROM", "SCC", "CORR", "TVS", "TOX", "FS"]}
            for code in material_codes
        }

        # First, get designations for all codes
        cursor.execute(
            """
            SELECT material_code::text, designation
            FROM materials
            WHERE material_code::text = ANY(%s)
            """,
            (material_codes,),
        )
        designations = {row["material_code"]: row["designation"] for row in cursor.fetchall()}

        # Query silver_report_rows for all ratings
        contract_ids = list(RATING_MAP.keys())
        cursor.execute(
            """
            SELECT
                normalized_payload->>'materialkey' as material_code,
                contract_id,
                normalized_payload as payload,
                COUNT(*) OVER (
                    PARTITION BY normalized_payload->>'materialkey', contract_id
                ) as test_count
            FROM silver_report_rows
            WHERE contract_id = ANY(%s)
              AND normalized_payload->>'materialkey' = ANY(%s)
            """,
            (contract_ids, material_codes),
        )

        for row in cursor.fetchall():
            mat_code = row["material_code"]
            contract_id = row["contract_id"]
            payload = row["payload"]
            test_count = row["test_count"]

            if contract_id not in RATING_MAP:
                continue

            # Filter out expired data (expire_flag = '1')
            expire_flag_field = EXPIRE_FLAG_MAP.get(contract_id)
            if expire_flag_field:
                expire_flag = payload.get(expire_flag_field)
                if expire_flag == "1":
                    continue  # Skip expired records

            json_field, miul_col = RATING_MAP[contract_id]
            rating_value = payload.get(json_field)

            if rating_value and isinstance(rating_value, str):
                rating_clean = rating_value.strip().upper()

                # Filter out invalid ratings (X = data invalidated/superseded)
                if rating_clean in INVALID_RATINGS:
                    continue

                designation = designations.get(mat_code, "")
                form = self._extract_form_from_designation(designation)

                source = RatingSource(
                    rating=rating_clean,
                    material_code=mat_code,
                    designation=designation,
                    is_exact_match=(mat_code == material_codes[0]),
                    is_same_form=False,  # Will be set later
                    confidence=0.9 if mat_code == material_codes[0] else 0.7,
                    test_count=test_count,
                )

                if mat_code in result:
                    result[mat_code][miul_col].append(source)

        return result

    def _extract_form_from_designation(self, designation: str) -> Optional[str]:
        """Extract product form from designation string."""
        text = designation.upper()
        for form, aliases in FORM_ALIASES.items():
            for alias in aliases:
                if re.search(rf'\b{alias}\b', text):
                    return form
        return None

    def _forms_match(self, form1: Optional[str], form2: Optional[str]) -> bool:
        """Check if two product forms are equivalent."""
        if not form1 or not form2:
            return False

        form1_upper = form1.upper()
        form2_upper = form2.upper()

        # Check direct match
        if form1_upper == form2_upper:
            return True

        # Check aliases
        for canonical, aliases in FORM_ALIASES.items():
            if form1_upper in aliases and form2_upper in aliases:
                return True

        return False

    def _aggregate_category(
        self,
        category: str,
        primary_code: str,
        related_codes: List[Dict],
        all_ratings: Dict[str, Dict[str, List[RatingSource]]],
        material_form: Optional[str],
        rule: InheritanceRule,
    ) -> AggregatedRating:
        """Aggregate ratings for a single category with inheritance rules."""

        all_sources: List[RatingSource] = []

        # Collect all sources
        for code, ratings_by_cat in all_ratings.items():
            sources = ratings_by_cat.get(category, [])
            for source in sources:
                # Update is_same_form flag
                source_form = self._extract_form_from_designation(source.designation)
                source.is_same_form = self._forms_match(material_form, source_form)
                all_sources.append(source)

        if not all_sources:
            return AggregatedRating(
                category=category,
                rating=None,
                primary_source=None,
                all_sources=[],
                inheritance_rule=rule,
            )

        # Apply inheritance rule
        if rule == InheritanceRule.DO_NOT_INHERIT:
            # Only use exact match
            exact_sources = [s for s in all_sources if s.is_exact_match]
            if exact_sources:
                best = self._select_best_source(exact_sources)
                return AggregatedRating(
                    category=category,
                    rating=best.rating,
                    primary_source=best,
                    all_sources=exact_sources,
                    inheritance_rule=rule,
                )
            else:
                return AggregatedRating(
                    category=category,
                    rating=None,
                    primary_source=None,
                    all_sources=all_sources,
                    inheritance_rule=rule,
                    note="No exact match; inheritance not allowed for this category",
                )

        elif rule == InheritanceRule.PREFER_SAME_FORM:
            # Prefer exact match, then same form, then any
            exact_sources = [s for s in all_sources if s.is_exact_match]
            same_form_sources = [s for s in all_sources if s.is_same_form]

            if exact_sources:
                best = self._select_best_source(exact_sources)
            elif same_form_sources:
                best = self._select_best_source(same_form_sources)
                best.confidence *= 0.9  # Slight confidence reduction
            else:
                best = self._select_best_source(all_sources)
                best.confidence *= 0.8  # More confidence reduction

            return AggregatedRating(
                category=category,
                rating=best.rating,
                primary_source=best,
                all_sources=all_sources,
                inheritance_rule=rule,
            )

        else:  # InheritanceRule.INHERIT
            # Any source is acceptable; prefer exact match
            exact_sources = [s for s in all_sources if s.is_exact_match]
            if exact_sources:
                best = self._select_best_source(exact_sources)
            else:
                best = self._select_best_source(all_sources)
                best.confidence *= 0.85  # Slight confidence reduction

            return AggregatedRating(
                category=category,
                rating=best.rating,
                primary_source=best,
                all_sources=all_sources,
                inheritance_rule=rule,
            )

    def _select_best_source(self, sources: List[RatingSource]) -> RatingSource:
        """Select the best rating source from a list.

        Priority:
        1. Highest confidence
        2. Most tests
        3. Best (lowest severity) rating
        """
        if not sources:
            raise ValueError("Cannot select from empty source list")

        def score(s: RatingSource) -> Tuple[float, int, int]:
            severity = RATING_SEVERITY.get(s.rating, 5)
            return (s.confidence, s.test_count, -severity)

        return max(sources, key=score)


# Module-level convenience function
def get_aggregated_ratings(
    material_code: str,
    material_form: Optional[str] = None,
) -> AggregatedRatingsResult:
    """Get aggregated ratings for a material code.

    Convenience function that creates client, queries, and closes.

    Args:
        material_code: MAPTIS material code
        material_form: Optional product form for preferential matching

    Returns:
        AggregatedRatingsResult with ratings and provenance
    """
    client = AggregatedRatingsClient()
    try:
        return client.get_aggregated_ratings(material_code, material_form)
    finally:
        client.close()


# =============================================================================
# QUICK TEST
# =============================================================================
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Test with A-286 code
    test_code = sys.argv[1] if len(sys.argv) > 1 else "10011"
    test_form = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"\n{'='*60}")
    print(f"AGGREGATED RATINGS TEST: Code {test_code}, Form={test_form}")
    print(f"{'='*60}")

    result = get_aggregated_ratings(test_code, test_form)

    print(f"\nRequested: {result.requested_code} ({result.requested_designation})")
    print(f"Related codes found: {result.related_codes_count}")

    print(f"\n{'CATEGORY':<8} {'RATING':<8} {'SOURCE':<15} {'EXACT?':<8} {'FORM?':<8} {'CONF':<8}")
    print("-" * 60)

    for cat in ["FLAM", "PROM", "SCC", "CORR", "TVS", "TOX", "FS"]:
        agg = result.ratings.get(cat)
        if agg and agg.rating:
            src = agg.primary_source
            print(
                f"{cat:<8} {agg.rating:<8} {src.material_code:<15} "
                f"{'Yes' if src.is_exact_match else 'No':<8} "
                f"{'Yes' if src.is_same_form else 'No':<8} "
                f"{src.confidence:.2f}"
            )
        else:
            print(f"{cat:<8} {'--':<8} {'No data':<15}")

    if result.warnings:
        print(f"\nWarnings:")
        for w in result.warnings:
            print(f"  - {w}")
