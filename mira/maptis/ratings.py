#!/usr/bin/env python3
"""
Module: Ratings
Purpose: MAPTIS Rating System Constants and Validators

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from enum import Enum
from typing import Set, Dict, Optional
import uuid


class MaptisRatingCategory(str, Enum):
    """MAPTIS rating categories"""
    CORROSION = "corrosion"
    ELECTRIC_OVERLOAD = "electric_overload"
    ELECTRIC_WIRE_INSULATION = "electric_wire_insulation"
    FLAMMABILITY = "flammability"
    FLASH_FIRE = "flash_fire"
    FLUID_COMPATIBILITY = "fluid_compatibility"
    FUNGUS = "fungus"
    MECHANICAL_IMPACT = "mechanical_impact"
    ODOR = "odor"
    PNEUMATIC_IMPACT = "pneumatic_impact"
    PROMOTED_COMBUSTION = "promoted_combustion"
    STRESS_CORROSION_CRACKING = "stress_corrosion_cracking"
    TENSILE_STRENGTH = "tensile_strength"
    TOXICITY = "toxicity"
    TVS_OUTGASSING = "tvs_outgassing"
    VCM_OPTICAL = "vcm_optical"


# Valid ratings for each category (case-insensitive)
MAPTIS_VALID_RATINGS: Dict[MaptisRatingCategory, Set[str]] = {
    MaptisRatingCategory.CORROSION: {'a', 'b', 'n', 'u', 'x'},
    MaptisRatingCategory.ELECTRIC_OVERLOAD: {'a', 'b', 'c', 'i', 's', 'u', 'x'},
    MaptisRatingCategory.ELECTRIC_WIRE_INSULATION: {'a', 'b', 'c', 'i', 's', 'u', 'x'},
    MaptisRatingCategory.FLAMMABILITY: {'a', 'b', 'c', 'c7', 'i', 's', 'x'},
    MaptisRatingCategory.FLASH_FIRE: {'a', 'x'},
    MaptisRatingCategory.FLUID_COMPATIBILITY: {'a', 'b', 'c', 'i', 's', 'u', 'x'},
    MaptisRatingCategory.FUNGUS: {'a', 'b', 'c', 'x', 'z'},
    MaptisRatingCategory.MECHANICAL_IMPACT: {'a', 'c', 'i', 's', 'x'},
    MaptisRatingCategory.ODOR: {'a', 'b', 'x'},
    MaptisRatingCategory.PNEUMATIC_IMPACT: {'a', 'i', 's', 'x'},
    MaptisRatingCategory.PROMOTED_COMBUSTION: {'a', 'c', 'i', 's', 'u'},
    MaptisRatingCategory.STRESS_CORROSION_CRACKING: {'a', 'b', 'c', 'n', 'u'},
    MaptisRatingCategory.TENSILE_STRENGTH: {'a', 'b', 'c', 'd', 'u', 'x'},
    MaptisRatingCategory.TOXICITY: {'a', 'h', 'k', 'n', 's', 'v', 'x'},
    MaptisRatingCategory.TVS_OUTGASSING: {'a', 'b', 'c', 'i', 's', 'u', 'x'},
    MaptisRatingCategory.VCM_OPTICAL: {'f', 'i', 'p'},
}


# Commonly used rating categories (shortened names for convenience)
COMMON_RATING_CATEGORIES = {
    'flamm': MaptisRatingCategory.FLAMMABILITY,
    'scc': MaptisRatingCategory.STRESS_CORROSION_CRACKING,
    'corr': MaptisRatingCategory.CORROSION,
    'tvs': MaptisRatingCategory.TVS_OUTGASSING,
}


def validate_rating(rating: Optional[str], category: MaptisRatingCategory) -> bool:
    """
    Validate that a rating is valid for the given category.

    Args:
        rating: Rating letter (case-insensitive) or None
        category: MAPTIS rating category

    Returns:
        True if rating is valid or None, False otherwise
    """
    if rating is None:
        return True  # None is allowed (missing rating)

    # Normalize to lowercase for comparison
    rating_lower = rating.lower().strip()

    # Check if rating is valid for this category
    valid_ratings = MAPTIS_VALID_RATINGS.get(category, set())
    return rating_lower in valid_ratings


def get_valid_ratings_for_category(category: MaptisRatingCategory) -> Set[str]:
    """
    Get the set of valid ratings for a given category.

    Args:
        category: MAPTIS rating category

    Returns:
        Set of valid rating strings (lowercase)
    """
    return MAPTIS_VALID_RATINGS.get(category, set()).copy()


def normalize_rating(rating: Optional[str]) -> Optional[str]:
    """
    Normalize a rating to lowercase for consistent storage.

    Args:
        rating: Raw rating string

    Returns:
        Normalized rating (lowercase, stripped) or None
    """
    if rating is None:
        return None

    if isinstance(rating, str):
        normalized = rating.lower().strip()
        return normalized if normalized else None

    return None


# Rating descriptions for documentation
RATING_DESCRIPTIONS = {
    'a': 'Acceptable - Material meets all requirements',
    'b': 'Borderline - May be acceptable with restrictions',
    'c': 'Conditional - Acceptable only under specific conditions',
    'c7': 'Conditional 7-day - Special flammability rating',
    'd': 'Deficient - Does not meet requirements',
    'f': 'Fair - Moderate performance',
    'h': 'High toxicity',
    'i': 'Insufficient data - More testing needed',
    'k': 'Known toxicity concern',
    'n': 'Not applicable - Category does not apply',
    'p': 'Poor performance',
    's': 'Special consideration required',
    'u': 'Unacceptable - Material fails requirements',
    'v': 'Very high toxicity',
    'x': 'Extreme concern - Critical issue',
    'z': 'Zero resistance - Fungus susceptible',
}


def get_rating_description(rating: str) -> str:
    """
    Get human-readable description of a rating.

    Args:
        rating: Rating letter

    Returns:
        Description string
    """
    return RATING_DESCRIPTIONS.get(rating.lower(), 'Unknown rating')


# Query helpers for NLP interface
def parse_rating_query(query: str) -> Optional[tuple[str, MaptisRatingCategory]]:
    """
    Parse a natural language query for material ratings.

    Examples:
        "show me materials A rated for flammability" -> ('a', FLAMMABILITY)
        "materials with B SCC rating" -> ('b', SCC)
        "A rated corrosion" -> ('a', CORROSION)

    Args:
        query: Natural language query string

    Returns:
        Tuple of (rating_letter, category) or None if cannot parse
    """
    query_lower = query.lower()

    # Extract rating letter (look for single letter or c7)
    rating = None
    for potential_rating in ['c7', 'a', 'b', 'c', 'd', 'f', 'h', 'i', 'k', 'n', 'p', 's', 'u', 'v', 'x', 'z']:
        if f" {potential_rating} " in f" {query_lower} " or f" {potential_rating}-" in query_lower:
            rating = potential_rating
            break

    if not rating:
        return None

    # Extract category
    category = None
    for short_name, cat in COMMON_RATING_CATEGORIES.items():
        if short_name in query_lower:
            category = cat
            break

    # Check for full category names
    if not category:
        for cat in MaptisRatingCategory:
            if cat.value.replace('_', ' ') in query_lower:
                category = cat
                break

    if not category:
        return None

    return (rating, category)


def test_ratings_system():
    """Test the ratings system"""
    print("Testing MAPTIS Ratings System")
    print("=" * 60)

    # Test validation
    print("\n1. Validation Tests:")
    test_cases = [
        ('a', MaptisRatingCategory.FLAMMABILITY, True),
        ('x', MaptisRatingCategory.FLAMMABILITY, True),
        ('c7', MaptisRatingCategory.FLAMMABILITY, True),
        ('z', MaptisRatingCategory.FLAMMABILITY, False),  # Invalid for flammability
        ('a', MaptisRatingCategory.CORROSION, True),
        ('d', MaptisRatingCategory.CORROSION, False),  # Invalid for corrosion
        (None, MaptisRatingCategory.FLAMMABILITY, True),  # None is valid
    ]

    for rating, category, expected in test_cases:
        result = validate_rating(rating, category)
        status = "✓" if result == expected else "✗"
        print(f"  {status} validate_rating('{rating}', {category.value}): {result}")

    # Test normalization
    print("\n2. Normalization Tests:")
    test_normalize = [
        ('A', 'a'),
        ('  b  ', 'b'),
        ('C7', 'c7'),
        (None, None),
    ]

    for raw, expected in test_normalize:
        result = normalize_rating(raw)
        status = "✓" if result == expected else "✗"
        print(f"  {status} normalize_rating('{raw}'): '{result}'")

    # Test query parsing
    print("\n3. Query Parsing Tests:")
    test_queries = [
        "show me materials A rated for flammability",
        "materials with B SCC rating",
        "A rated corrosion",
        "give me X rated TVS materials",
    ]

    for query in test_queries:
        result = parse_rating_query(query)
        print(f"  Query: '{query}'")
        if result:
            rating, category = result
            print(f"    → Rating: {rating}, Category: {category.value}")
        else:
            print(f"    → Could not parse")

    # Test valid ratings for each category
    print("\n4. Valid Ratings by Category:")
    for category in [MaptisRatingCategory.FLAMMABILITY,
                     MaptisRatingCategory.CORROSION,
                     MaptisRatingCategory.STRESS_CORROSION_CRACKING,
                     MaptisRatingCategory.TVS_OUTGASSING]:
        valid = get_valid_ratings_for_category(category)
        print(f"  {category.value}: {sorted(valid)}")

    print("\n✓ All tests complete")


if __name__ == "__main__":
    test_ratings_system()
