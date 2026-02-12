#!/usr/bin/env python3
"""
Module: Material Code Lookup
Purpose: Represents a potential material code match with confidence scoring.

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

import logging
import re
import psycopg2
from psycopg2.extras import DictCursor
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Try to import rapidfuzz for better fuzzy matching
try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    fuzz = None
    process = None

# Import the deterministic UNS-based alloy normalizer
import uuid

try:
    # Try relative import first (when running as part of mira package)
    from .alloy_normalizer import normalize_alloy, AlloyNormalizer
    NORMALIZER_AVAILABLE = True
except ImportError:
    try:
        # Fallback to absolute import (when mira is in PYTHONPATH)
        from mira.miul.alloy_normalizer import normalize_alloy, AlloyNormalizer
        NORMALIZER_AVAILABLE = True
    except ImportError:
        try:
            # Fallback for running from mira directory directly
            from miul.alloy_normalizer import normalize_alloy, AlloyNormalizer
            NORMALIZER_AVAILABLE = True
        except ImportError:
            NORMALIZER_AVAILABLE = False
            normalize_alloy = None
            AlloyNormalizer = None

# Import AI-powered material code selector
try:
    from .material_code_selector import (
        MaterialCodeSelector,
        SelectionResult,
        get_material_code_selector,
    )
    AI_SELECTOR_AVAILABLE = True
except ImportError:
    try:
        from mira.miul.material_code_selector import (
            MaterialCodeSelector,
            SelectionResult,
            get_material_code_selector,
        )
        AI_SELECTOR_AVAILABLE = True
    except ImportError:
        AI_SELECTOR_AVAILABLE = False
        MaterialCodeSelector = None
        SelectionResult = None
        get_material_code_selector = None

logger = logging.getLogger(__name__)

# Compiled regex patterns for family detection (word boundaries)
# Prevents false positives like SS in ASSY, IN in text
# Order matters: more specific patterns first (TITANIUM before ALUMINUM)
# because "TI-6AL-4V" contains both "TI" and "AL"
FAMILY_PATTERNS = {
    'TITANIUM': re.compile(r'\b(TITANIUM|TI)\b', re.IGNORECASE),
    'NICKEL': re.compile(r'\b(INCONEL|HASTELLOY|MONEL|NICKEL)\b', re.IGNORECASE),
    'STAINLESS': re.compile(r'\b(SST|SS|CRES|STAINLESS)\b', re.IGNORECASE),
    'ALUMINUM': re.compile(r'\b(ALUMINUM|ALUMINIUM|AL)\b', re.IGNORECASE),
}

# Pattern to extract temper from designation (e.g., T6, T651, T4, O, H13)
TEMPER_PATTERN = re.compile(r'-?(T\d{1,4}|O|H\d{1,2}|F)\b', re.IGNORECASE)

# Material form keywords for filtering
# Note: BAR and ROD are kept separate to allow precise matching
# When user specifies ROD, only ROD should match (not BAR)
FORM_KEYWORDS = {
    'PLATE': ['PLATE'],
    'SHEET': ['SHEET'],
    'BAR': ['BAR'],
    'ROD': ['ROD'],
    'TUBE': ['TUBE', 'TUBING', 'PIPE'],
    'WIRE': ['WIRE', 'CABLE'],
    'FORGING': ['FORGING', 'FORGED'],
    'SHAPES': ['SHAPES', 'SHAPE'],
    'STRIP': ['STRIP'],
    'EXTRUSION': ['EXTRUDED', 'EXTRUSION'],
}

# PostgreSQL regex patterns for family keywords (using \y word boundary)
FAMILY_SQL_PATTERNS = {
    'STAINLESS': r'\y(STAINLESS|CRES|SS|SST)\y',
    'NICKEL': r'\y(INCONEL|HASTELLOY|MONEL|NICKEL)\y',
    'ALUMINUM': r'\y(ALUMINUM|ALUMINIUM|AL)\y',
    'TITANIUM': r'\y(TITANIUM|TI)\y',
}


@dataclass
class MaterialMatch:
    """Represents a potential material code match with confidence scoring.

    Updated 2026-01: material_code is now Optional (None for ambiguous/unresolved).
    Added candidates field for ambiguous cases requiring human review.
    """
    material_code: Optional[str]  # None for ambiguous/unresolved
    designation: str
    confidence: str  # 'high', 'medium', 'low'
    method: str  # 'uns_normalized', 'exact_match', 'family_filtered', 'ambiguous', 'unresolved'
    score: float  # 0.0-1.0
    specs: List[str]  # Associated specifications
    source: str = ""  # NASA SWE-013 traceability
    candidates: Optional[List["MaterialMatch"]] = None  # For ambiguous cases



class MaterialCodeLookupService:
    """Service for translating Material Specs to Material Codes"""

    # Direct material code mappings for non-UNS materials (polymers, bronzes, etc.)
    # These bypass UNS normalization and map directly to MAPTIS codes
    DIRECT_MATERIAL_CODES = {
        # Polymers - VESPEL polyimide family
        'VESPEL SP-21': '05122',
        'VESPEL SP21': '05122',
        'SP-21': '05122',
        'VESPEL SP-1': '05123',
        'VESPEL SP-3': '05057',
        'VESPEL SP-211': '05182',
        # Polymers - PCTFE (Polychlorotrifluoroethylene)
        'PCTFE': '09430',
        'KEL-F': '09430',
        # Bronze alloys
        'ALUMINUM BRONZE': '50678',
        'ALUMINUM BRONZE ALLOY': '50678',
        'BRONZE C63000': '50678',
        'C63000': '50678',
        # Generic SST defaults (when no specific alloy given)
        'SST': '10090',  # Default to 304 SST
        '300 SERIES SST': '10090',  # Default to 304 SST
        '300 SERIES STAINLESS': '10090',
    }

    # Material name equivalences for fuzzy matching
    MATERIAL_ALIASES = {
        'ALUMINUM': {'AL', 'ALUMINIUM'},
        'AL': {'ALUMINUM', 'ALUMINIUM'},
        'STAINLESS': {'CRES', 'SS', 'SST', 'CORROSION RESISTANT'},
        'CRES': {'STAINLESS', 'SS', 'SST', 'CORROSION RESISTANT'},
        'SS': {'STAINLESS', 'CRES', 'SST', 'CORROSION RESISTANT'},
        'SST': {'STAINLESS', 'CRES', 'SS', 'CORROSION RESISTANT'},
        'TITANIUM': {'TI'},
        'TI': {'TITANIUM'},
        'INCONEL': {'INC', 'IN'},
        'NICKEL': {'NI'},
    }

    def __init__(self):
        """Initialize the lookup service"""
        self.conn = None
        self._conn_params = None

    def _get_connection(self):
        """Get PostgreSQL database connection using centralized config."""
        if self.conn is None or self.conn.closed:
            if self._conn_params is None:
                try:
                    from mira.core.db_config import get_db_connection_params
                    self._conn_params = get_db_connection_params()
                except ImportError:
                    import os
                    self._conn_params = {
                        "host": os.environ.get("POSTGRES_HOST", "localhost"),
                        "port": int(os.environ.get("POSTGRES_PORT", "5432")),
                        "database": os.environ.get("POSTGRES_DB", "mira"),
                        "user": os.environ.get("POSTGRES_USER", "postgres"),
                        "password": os.environ.get("POSTGRES_PASSWORD", "postgres"),
                    }
            self.conn = psycopg2.connect(**self._conn_params)
        return self.conn

    def close(self):
        """Close database connection"""
        if self.conn and not self.conn.closed:
            self.conn.close()

    def _extract_temper(self, designation: str) -> Optional[str]:
        """Extract temper designation from material name.

        Examples:
            "AL 6061-T6" → "T6"
            "AL 6061-T651 PLATE" → "T651"
            "SS 316L" → None (L is not a temper, it's low carbon)
            "AL 7075-O" → "O"
        """
        match = TEMPER_PATTERN.search(designation.upper())
        if match:
            return match.group(0).lstrip('-').upper()
        return None

    def _get_form_keywords(self, material_form: str) -> List[str]:
        """Get SQL ILIKE patterns for a material form.

        Args:
            material_form: Form like "PLATE", "SHEET", "BAR", etc.

        Returns:
            List of keywords to search for in designation
        """
        form_upper = material_form.upper().strip()
        return FORM_KEYWORDS.get(form_upper, [form_upper] if form_upper else [])

    def _lookup_by_uns(
        self,
        uns_code: str,
        temper: Optional[str] = None,
        material_form: Optional[str] = None,
    ) -> List[MaterialMatch]:
        """
        Look up materials in MAPTIS by UNS code.

        Uses boundary-safe regex matching (\y) to prevent false positives like:
        - "302" matching "AMS 3302" (should only match "302" as a word)
        - "625" matching part numbers containing 625

        Also extracts base alloy number from UNS code to search:
        - A97075 → search for "7075"
        - S31603 → search for "316"
        - N07718 → search for "718"

        Args:
            uns_code: UNS code (e.g., "A96061")
            temper: Optional temper to filter by (e.g., "T6")
            material_form: Optional form to filter by (e.g., "PLATE")
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        matches = []

        # Extract base alloy number from UNS code and material family
        base_alloy = None
        material_family = None  # Used to filter results

        if uns_code.startswith('A9') and len(uns_code) >= 6:
            # Aluminum: A97075 → 7075
            base_alloy = uns_code[2:]
            material_family = 'AL'
        elif uns_code.startswith('S') and len(uns_code) >= 4:
            # Stainless steel: S30400 → 304, S66286 → A286
            if uns_code == 'S66286':
                base_alloy = 'A-?286'  # Regex pattern for A286 or A-286
            elif uns_code == 'S30200':
                base_alloy = '302'
            elif uns_code == 'S30400':
                base_alloy = '304'
            elif uns_code == 'S30403':
                base_alloy = '304L'
            elif uns_code == 'S31600':
                base_alloy = '316'
            elif uns_code == 'S31603':
                base_alloy = '316L'
            else:
                # Extract 3-digit alloy from UNS (e.g., S30100 → 301)
                base_alloy = uns_code[1:4].lstrip('0') or uns_code[1:4]
            material_family = 'SS'
        elif uns_code.startswith('N0') and len(uns_code) >= 5:
            # Nickel alloys: N07718 → 718, N06625 → 625
            base_alloy = uns_code[3:].lstrip('0') or uns_code[3:]
            material_family = 'NI'

        try:
            # Build search query using boundary-safe regex (~*)
            # CRITICAL: Use \y word boundary to prevent "302" matching "3302"

            # Build base WHERE clause based on material family
            if material_family in ('SS', 'AL', 'NI') and base_alloy:
                alloy_pattern = rf'\y{base_alloy}\y'

                # Special-case A286 (UNS S66286): MAPTIS designations can appear as
                # "A-286", "A286 SST", or "INCONEL A-286" and may not include
                # explicit "STAINLESS" family keywords.
                if uns_code == 'S66286':
                    base_where = """
                        (
                            designation ILIKE %s
                            OR designation ILIKE %s
                            OR designation ~* %s
                        )
                        AND material_code IS NOT NULL
                        AND material_code != 'UNKNOWN'
                    """
                    params = [f'%{uns_code}%', f'%UNS {uns_code}%', alloy_pattern]
                else:
                    family_key = {'SS': 'STAINLESS', 'AL': 'ALUMINUM', 'NI': 'NICKEL'}[material_family]
                    family_pattern = FAMILY_SQL_PATTERNS.get(family_key)

                    base_where = """
                        (
                            designation ILIKE %s
                            OR designation ILIKE %s
                            OR (designation ~* %s AND designation ~* %s)
                        )
                        AND material_code IS NOT NULL
                        AND material_code != 'UNKNOWN'
                    """
                    params = [f'%{uns_code}%', f'%UNS {uns_code}%', alloy_pattern, family_pattern]
            else:
                # Generic search - only search for UNS code directly
                base_where = """
                    (designation ILIKE %s OR designation ILIKE %s)
                    AND material_code IS NOT NULL
                    AND material_code != 'UNKNOWN'
                """
                params = [f'%{uns_code}%', f'%UNS {uns_code}%']

            # Build additional filters for temper and form
            extra_filters = []

            # Add temper filter if specified (e.g., T6, T651)
            if temper:
                # Use word boundary to match temper exactly
                temper_pattern = rf'\y{temper}\y'
                extra_filters.append("designation ~* %s")
                params.append(temper_pattern)

            # Add form filter if specified (e.g., PLATE, SHEET)
            if material_form:
                form_keywords = self._get_form_keywords(material_form)
                if form_keywords:
                    # Build OR condition for form keywords
                    form_conditions = " OR ".join(["designation ILIKE %s" for _ in form_keywords])
                    extra_filters.append(f"({form_conditions})")
                    params.extend([f'%{kw}%' for kw in form_keywords])

            # Combine filters
            where_clause = base_where
            if extra_filters:
                where_clause += " AND " + " AND ".join(extra_filters)

            # Use higher limit when filtering by temper/form (more specific = fewer results)
            # Without filters, use lower limit to avoid overwhelming AI selector
            limit = 50 if (temper or material_form) else 30

            query = f"""
                SELECT material_code, designation, LENGTH(designation) as desig_len
                FROM materials
                WHERE {where_clause}
                GROUP BY material_code, designation
                ORDER BY desig_len, material_code
                LIMIT {limit}
            """

            cursor.execute(query, params)
            results = cursor.fetchall()

            # Log what we searched for
            filter_desc = []
            if temper:
                filter_desc.append(f"temper={temper}")
            if material_form:
                filter_desc.append(f"form={material_form}")
            filter_str = f" [{', '.join(filter_desc)}]" if filter_desc else ""
            logger.debug(f"UNS lookup for {uns_code}{filter_str}: query returned {len(results)} rows")

            for row in results:
                material_code = str(row['material_code'])
                designation = row['designation'] or ''

                matches.append(MaterialMatch(
                    material_code=material_code,
                    designation=designation,
                    confidence='high',
                    method='uns_lookup',
                    score=0.95,
                    specs=[uns_code]
                ))

        except Exception as e:
            logger.error(f"Error looking up UNS {uns_code}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

        finally:
            cursor.close()

        return matches

    def _deterministic_fallback(
        self,
        designation: str,
        candidates: List[MaterialMatch],
        temper: Optional[str],
        material_form: Optional[str],
    ) -> MaterialMatch:
        """Deterministic fallback when AI selection is unavailable.

        Uses a scoring system that prioritizes:
        1. Exact temper match (T6 matches T6, not T4 or T651)
        2. Material form match (PLATE matches PLATE)
        3. Avoids composites/coatings
        4. Prefers shorter/simpler designations

        Args:
            designation: Original material designation
            candidates: List of MaterialMatch candidates
            temper: Extracted temper (e.g., "T6")
            material_form: Specified material form (e.g., "PLATE")

        Returns:
            Best matching MaterialMatch
        """
        if not candidates:
            raise ValueError("No candidates provided for fallback selection")

        if len(candidates) == 1:
            return candidates[0]

        # Composite indicators to avoid
        composite_indicators = [
            'ON ', 'HONEYCOMB', 'CORE', 'COATING', 'COATED',
            'CLAD', 'BONDED', 'LAMINATE', 'COMPOSITE'
        ]

        # Get form keywords to match
        form_keywords = self._get_form_keywords(material_form) if material_form else []

        scored_candidates = []
        for c in candidates:
            desig_upper = c.designation.upper()
            score = 0

            # Score 1: Exact temper match (+100 points)
            if temper:
                # Check for exact temper at word boundary
                temper_pattern = re.compile(rf'\b{re.escape(temper)}\b', re.IGNORECASE)
                if temper_pattern.search(c.designation):
                    score += 100
                    # Penalize if there are extra digits (T6 vs T651)
                    # T6 should prefer "T6" over "T651"
                    if re.search(rf'\b{re.escape(temper)}\d', c.designation, re.IGNORECASE):
                        score -= 10  # Slight penalty for extended temper

            # Score 2: Material form match (+50 points)
            if form_keywords:
                for kw in form_keywords:
                    if kw.upper() in desig_upper:
                        score += 50
                        break

            # Score 3: Avoid composites (-200 points)
            if any(ind in desig_upper for ind in composite_indicators):
                score -= 200

            # Score 4: Prefer shorter designations (+10 minus length penalty)
            # Shorter = simpler = better (within 100 chars)
            length_penalty = min(len(c.designation), 100) // 10
            score += 10 - length_penalty

            scored_candidates.append((score, c))
            logger.debug(
                f"Fallback scoring: {c.material_code} '{c.designation}' -> score={score}"
            )

        # Sort by score descending, then by material_code for stability
        scored_candidates.sort(key=lambda x: (-x[0], x[1].material_code))

        best = scored_candidates[0][1]
        logger.info(
            f"Deterministic fallback: '{designation}' -> {best.material_code} "
            f"(temper={temper}, form={material_form}, score={scored_candidates[0][0]})"
        )
        return best

    def lookup_by_designation(self, material_name: str) -> List[MaterialMatch]:
        """
        Find materials using UNS normalization + database lookup.

        Multi-tier approach:
        0. UNS Normalization (deterministic) - converts "SS 316L" → UNS S31603
        1. Database lookup by UNS code
        2. Fuzzy string matching fallback
        """
        matches = []

        # Tier 0: UNS Normalization (deterministic)
        if NORMALIZER_AVAILABLE and normalize_alloy:
            try:
                normalized = normalize_alloy(material_name)
                if normalized.is_resolved:
                    uns_matches = self._lookup_by_uns(normalized.uns)
                    if uns_matches:
                        logger.info(
                            f"Normalized '{material_name}' -> UNS {normalized.uns} "
                            f"({normalized.canonical_name}) -> {len(uns_matches)} MAPTIS materials"
                        )
                        return uns_matches
                    else:
                        matches.append(MaterialMatch(
                            material_code=normalized.uns,
                            designation=normalized.canonical_name,
                            confidence='high',
                            method='uns_normalized',
                            score=normalized.confidence,
                            specs=[normalized.uns]
                        ))
                        return matches
                else:
                    logger.debug(
                        f"Could not normalize '{material_name}' to UNS: {normalized.warnings}"
                    )
            except Exception as e:
                logger.warning(f"Normalizer error for '{material_name}': {e}")

        # Tier 1: Fuzzy database lookup (fallback)
        # CRITICAL: Use word-boundary regex (~* with \y) for numeric tokens
        # to prevent false positives like "302" matching "AMS 3302"
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        try:
            query_clean = material_name.upper().strip()
            query_tokens = set(re.findall(r'\b([A-Z0-9][-A-Z0-9]*)\b', query_clean))
            filler_words = {'ALLOY', 'TYPE', 'GRADE', 'CLASS', 'SPEC', 'PER', 'THE', 'AND', 'OR'}
            query_tokens = query_tokens - filler_words

            # Separate numeric tokens (need word boundary) from text tokens
            numeric_tokens = {t for t in query_tokens if re.match(r'^\d+[A-Z]?$', t)}
            text_tokens = query_tokens - numeric_tokens

            # Build WHERE clause with proper boundary matching
            where_parts = []
            params = []

            # Full query string match (ILIKE is OK for complete phrases)
            where_parts.append("designation ILIKE %s")
            params.append(f'%{query_clean}%')

            # Text tokens can use ILIKE (less risk of substring collision)
            for token in text_tokens:
                if len(token) >= 2:
                    where_parts.append("designation ILIKE %s")
                    params.append(f'%{token}%')

            # Numeric tokens MUST use word-boundary regex to prevent
            # "302" matching "3302" or "625" matching "182625D-01"
            for token in numeric_tokens:
                if len(token) >= 2:
                    where_parts.append("designation ~* %s")
                    params.append(rf'\y{token}\y')

            where_clauses = " OR ".join(where_parts)

            query = f"""
                SELECT DISTINCT material_code, designation
                FROM materials
                WHERE ({where_clauses})
                  AND material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                LIMIT 50
            """

            cursor.execute(query, params)
            candidates = cursor.fetchall()

            for row in candidates:
                material_code = row['material_code']
                designation = row['designation'] or ''
                desig_upper = designation.upper()

                score = self._calculate_fuzzy_score(query_clean, desig_upper, query_tokens)

                if score >= 0.3:
                    confidence = 'high' if score >= 0.8 else 'medium' if score >= 0.5 else 'low'

                    matches.append(MaterialMatch(
                        material_code=str(material_code),
                        designation=designation,
                        confidence=confidence,
                        method='fuzzy_designation',
                        score=score,
                        specs=[designation]
                    ))

            matches.sort(key=lambda m: m.score, reverse=True)

            logger.info(f"Fuzzy lookup for '{material_name}' found {len(matches)} matches")

        except Exception as e:
            logger.error(f"Error in fuzzy lookup '{material_name}': {e}")
            try:
                conn.rollback()
            except Exception:
                pass

        finally:
            cursor.close()

        return matches

    def _calculate_fuzzy_score(self, query: str, candidate: str, query_tokens: set) -> float:
        """Calculate fuzzy match score between query and candidate.

        CRITICAL: Only matches numbers at word boundaries to prevent
        "302" matching "3302" or "625" matching "182625D-01".
        """
        if query == candidate:
            return 1.0

        if query in candidate:
            return 0.95

        if candidate in query:
            return 0.9

        # ONLY use word-boundary number matching (no embedded matches!)
        # This prevents "302" from matching "AMS 3302" or "625" matching "182625D-01"
        query_key_numbers = set(re.findall(r'\b(\d{3,5}[A-Z]?)\b', query))
        candidate_key_numbers = set(re.findall(r'\b(\d{3,5}[A-Z]?)\b', candidate))

        key_number_match = False
        if query_key_numbers:
            # Numbers must match at word boundaries in BOTH query and candidate
            if query_key_numbers & candidate_key_numbers:
                key_number_match = True

        # If query has key numbers but candidate doesn't have matching ones, penalize
        if query_key_numbers and not key_number_match:
            return 0.1

        base_score = 0.7 if key_number_match else 0.0

        material_type_match = False
        for q_token in query_tokens:
            if q_token in self.MATERIAL_ALIASES:
                aliases = self.MATERIAL_ALIASES[q_token] | {q_token}
                for alias in aliases:
                    if alias in candidate:
                        material_type_match = True
                        break

        if material_type_match:
            base_score += 0.15

        if RAPIDFUZZ_AVAILABLE and base_score > 0:
            token_set = fuzz.token_set_ratio(query, candidate) / 100.0
            partial = fuzz.partial_ratio(query, candidate) / 100.0
            fuzzy_bonus = (token_set * 0.1 + partial * 0.05)
            base_score = min(base_score + fuzzy_bonus, 1.0)
        elif not RAPIDFUZZ_AVAILABLE:
            candidate_tokens = set(re.findall(r'\b([A-Z0-9][-A-Z0-9]*)\b', candidate))
            filler_words = {'ALLOY', 'TYPE', 'GRADE', 'CLASS', 'SPEC', 'PER', 'THE', 'AND', 'OR'}
            candidate_tokens = candidate_tokens - filler_words
            if query_tokens and candidate_tokens:
                intersection = query_tokens & candidate_tokens
                if intersection:
                    base_score += 0.1

        return min(base_score, 1.0)

    def _detect_material_family(self, designation: str) -> Optional[str]:
        """Detect material family using word-boundary regex.

        Prevents false positives like:
        - SS in ASSY
        - IN in text
        - AL in ALLOY
        """
        for family, pattern in FAMILY_PATTERNS.items():
            if pattern.search(designation):
                return family
        return None

    def _family_filtered_partial_match(
        self, designation: str, family: Optional[str]
    ) -> List[MaterialMatch]:
        """Partial match requiring alloy number (boundary-safe) + family keyword.

        Uses PostgreSQL regex ~* with word boundary \\y instead of ILIKE %302%
        to prevent 302 matching 3302 or AMS3302.
        """
        if not family:
            return []

        # Extract alloy number with word boundary
        alloy_match = re.search(r'\b(\d{3,4}[A-Z]?)\b', designation)
        if not alloy_match:
            return []
        alloy = alloy_match.group(1)

        family_pattern = FAMILY_SQL_PATTERNS.get(family)
        if not family_pattern:
            return []

        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        matches = []

        try:
            # Boundary-safe alloy match: \y302\y NOT %302%
            # This prevents 302 matching 3302 or AMS3302
            query = """
                SELECT material_code, designation
                FROM materials
                WHERE designation ~* %s
                  AND designation ~* %s
                  AND material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                ORDER BY LENGTH(designation)
                LIMIT 5
            """
            alloy_pattern = rf'\y{alloy}\y'  # e.g., \y302\y
            params = [alloy_pattern, family_pattern]

            cursor.execute(query, params)
            rows = cursor.fetchall()

            for row in rows:
                matches.append(MaterialMatch(
                    material_code=str(row['material_code']),
                    designation=row['designation'] or '',
                    confidence='medium',
                    method='family_filtered',
                    score=0.75,
                    specs=[],
                ))

            logger.debug(
                f"Family-filtered partial match for '{designation}' "
                f"(family={family}, alloy={alloy}): {len(matches)} matches"
            )

        except Exception as e:
            logger.error(f"Error in family-filtered partial match: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

        finally:
            cursor.close()

        return matches

    def _exact_designation_match(self, designation: str) -> Optional[MaterialMatch]:
        """Find exact designation match in MAPTIS."""
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        try:
            query = """
                SELECT material_code, designation
                FROM materials
                WHERE UPPER(TRIM(designation)) = UPPER(TRIM(%s))
                  AND material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                LIMIT 1
            """
            cursor.execute(query, [designation])
            row = cursor.fetchone()

            if row:
                return MaterialMatch(
                    material_code=str(row['material_code']),
                    designation=row['designation'] or '',
                    confidence='high',
                    method='exact_match',
                    score=0.90,
                    specs=[],
                )

        except Exception as e:
            logger.error(f"Error in exact designation match: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

        finally:
            cursor.close()

        return None

    def lookup_material_code(
        self,
        designation: str,
        part_description: str = "",
        material_form: str = "",
    ) -> MaterialMatch:
        """Single authoritative lookup path. All other lookups should delegate here.

        Pipeline:
        0. Direct material code lookup (polymers, bronzes, generic SST)
        1. UNS normalization → MAPTIS lookup → AI selection from candidates
        2. Exact designation match
        3. Family-filtered partial match (boundary-safe)
        4. Ambiguous → quarantine (material_code=None)
        5. No match → unresolved (material_code=None)

        Args:
            designation: Material designation from drawing (e.g., "AL 6061-T6")
            part_description: Part description for form inference (e.g., "SKIN, FUSELAGE")
            material_form: Explicit material form if known (e.g., "SHEET")

        Returns:
            MaterialMatch with resolved code or None for ambiguous/unresolved
        """
        designation_clean = designation.strip()
        designation_upper = designation_clean.upper()

        # Step 0: Check direct material code mappings (polymers, bronzes, generic SST)
        # First try exact match, then try prefix/contains match for extended designations
        if designation_upper in self.DIRECT_MATERIAL_CODES:
            material_code = self.DIRECT_MATERIAL_CODES[designation_upper]
            logger.info(f"Direct lookup (exact): '{designation_clean}' -> {material_code}")
            return MaterialMatch(
                material_code=material_code,
                designation=designation_clean,
                confidence='high',
                method='direct_lookup',
                score=0.95,
                specs=[],
            )

        # Try partial match for extended designations like "PCTFE PER ASTM D1710, TYPE II"
        for key, code in self.DIRECT_MATERIAL_CODES.items():
            if designation_upper.startswith(key + ' ') or designation_upper.startswith(key + ','):
                logger.info(f"Direct lookup (prefix): '{designation_clean}' -> {code} (matched '{key}')")
                return MaterialMatch(
                    material_code=code,
                    designation=designation_clean,
                    confidence='high',
                    method='direct_lookup',
                    score=0.90,
                    specs=[],
                )

        # Step 1: UNS normalization (deterministic) → AI selection from candidates
        if NORMALIZER_AVAILABLE and normalize_alloy:
            try:
                normalized = normalize_alloy(designation_clean)
                if normalized.is_resolved:
                    # Extract temper from original designation for filtering
                    temper = self._extract_temper(designation_clean)

                    # First try: lookup with temper and form filters for precise matching
                    matches = self._lookup_by_uns(
                        normalized.uns,
                        temper=temper,
                        material_form=material_form,
                    )

                    # If no matches with filters, try without form filter
                    if not matches and material_form:
                        logger.debug(
                            f"No matches with form filter '{material_form}', trying without"
                        )
                        matches = self._lookup_by_uns(normalized.uns, temper=temper)

                    # If still no matches, try without any filters
                    if not matches and temper:
                        logger.debug(
                            f"No matches with temper filter '{temper}', trying without"
                        )
                        matches = self._lookup_by_uns(normalized.uns)

                    if matches:
                        # Use AI to select best match when multiple candidates
                        if len(matches) > 1 and AI_SELECTOR_AVAILABLE:
                            selector = get_material_code_selector()
                            candidates = [
                                {"material_code": m.material_code, "designation": m.designation}
                                for m in matches
                            ]
                            result = selector.select_best_match(
                                designation=designation_clean,
                                candidates=candidates,
                                part_description=part_description,
                                material_form=material_form,
                            )
                            # Check if AI selection succeeded (not fallback methods)
                            if result and result.method == "ai_selection":
                                logger.info(
                                    f"UNS normalized + AI: '{designation_clean}' -> {normalized.uns} "
                                    f"-> {result.material_code} ({result.confidence}: {result.reasoning})"
                                )
                                return MaterialMatch(
                                    material_code=result.material_code,
                                    designation=result.designation,
                                    confidence=result.confidence,
                                    method=f'uns_normalized_{result.method}',
                                    score=0.95 if result.confidence == 'high' else 0.85,
                                    specs=[normalized.uns],
                                )

                            # AI selection unavailable or failed - use deterministic fallback
                            # which properly considers temper and form
                            logger.info(
                                f"Using deterministic fallback for '{designation_clean}' "
                                f"(temper={temper}, form={material_form})"
                            )
                            best = self._deterministic_fallback(
                                designation_clean, matches, temper, material_form
                            )
                            return MaterialMatch(
                                material_code=best.material_code,
                                designation=best.designation,
                                confidence='medium',
                                method='uns_normalized_deterministic',
                                score=0.85,
                                specs=[normalized.uns],
                            )

                        # Single match - use it directly
                        best = matches[0]
                        logger.info(
                            f"UNS normalized: '{designation_clean}' -> {normalized.uns} "
                            f"-> {best.material_code}"
                        )
                        return MaterialMatch(
                            material_code=best.material_code,
                            designation=best.designation,
                            confidence='high',
                            method='uns_normalized',
                            score=0.95,
                            specs=best.specs,
                        )
            except Exception as e:
                logger.warning(f"Normalizer error for '{designation_clean}': {e}")

        # Step 2: Exact designation match
        exact = self._exact_designation_match(designation_clean)
        if exact:
            logger.info(f"Exact match: '{designation_clean}' -> {exact.material_code}")
            return exact

        # Step 3: Family-filtered partial match (boundary-safe)
        family = self._detect_material_family(designation_clean)
        candidates = self._family_filtered_partial_match(designation_clean, family)

        if len(candidates) == 1:
            c = candidates[0]
            logger.info(
                f"Family-filtered match: '{designation_clean}' -> {c.material_code}"
            )
            return MaterialMatch(
                material_code=c.material_code,
                designation=c.designation,
                confidence='medium',
                method='family_filtered',
                score=0.75,
                specs=c.specs,
            )
        elif len(candidates) > 1:
            # Ambiguous - quarantine (material_code=None, NEVER set code)
            logger.warning(
                f"Ambiguous match: '{designation_clean}' has {len(candidates)} candidates"
            )
            return MaterialMatch(
                material_code=None,
                designation=designation_clean,
                confidence='low',
                method='ambiguous',
                score=0.3,
                specs=[],
                candidates=candidates,
            )

        # No match - unresolved
        logger.warning(f"Unresolved: '{designation_clean}' - no matching material found")
        return MaterialMatch(
            material_code=None,
            designation=designation_clean,
            confidence='low',
            method='unresolved',
            score=0.0,
            specs=[],
        )


# Global service instance
_lookup_service = None


def get_lookup_service() -> MaterialCodeLookupService:
    """Get singleton lookup service instance"""
    global _lookup_service
    if _lookup_service is None:
        _lookup_service = MaterialCodeLookupService()
    return _lookup_service


def reset_lookup_service() -> None:
    """Reset singleton for testing."""
    global _lookup_service
    if _lookup_service is not None:
        _lookup_service.close()
    _lookup_service = None


__all__ = [
    "MaterialMatch",
    "MaterialCodeLookupService",
    "get_lookup_service",
    "reset_lookup_service",
    "FAMILY_PATTERNS",
    "FAMILY_SQL_PATTERNS",
]
