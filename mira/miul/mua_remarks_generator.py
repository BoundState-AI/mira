#!/usr/bin/env python3
"""
Module: MUA Remarks Generator
Purpose: Generate brief MUA rationale remarks for MIUL non-A rated materials.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C, SWE-013 (Traceability)
Safety Critical: False

This module generates brief but complete justifications for materials with
less-than-A ratings, using historic MUA precedents from the BOK (Body of Knowledge).

The remarks explain WHY a material can still be used despite non-A ratings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mira.miul.mua_bok_engine import (
    MUABOKEngine,
    MUAPrecedent,
    get_mua_bok_engine,
    RATING_PRIORITY,
)

logger = logging.getLogger(__name__)

# Rating values that indicate a gap (need rationale)
GAP_RATINGS = {"B", "C", "D", "I", "K", "N", "U"}

# Brief rationale templates by rating type and severity
# Format: {rating_type: {rating_value: template}}
BRIEF_RATIONALE_TEMPLATES = {
    "FLAM": {
        "B": "Flammability B: Limited use quantity mitigates ignition risk per NASA-STD-6001.",
        "C": "Flammability C: Enclosure/configuration limits fire propagation. See MUA {mua}.",
        "I": "Flammability I: Insufficient data - awaiting test results.",
        "U": "Flammability U: Use only with engineering controls per {mua}.",
    },
    "TVS": {
        "B": "Outgassing B: TML/CVCM borderline per ASTM E595. Vacuum shielding applied.",
        "C": "Outgassing C: Protected from vacuum exposure or enclosed volume.",
        "I": "TVS I: Test data pending. Material protected from vacuum.",
        "U": "TVS U: Not for vacuum-exposed surfaces without enclosure.",
    },
    "SCC": {
        "B": "SCC B: Stress levels controlled below threshold. Coating protection applied.",
        "C": "SCC C: Environment controlled to prevent stress corrosion. Per {mua}.",
        "I": "SCC I: Test pending - stress levels limited by design.",
        "U": "SCC U: Requires engineering controls per {mua}.",
    },
    "CORR": {
        "B": "Corrosion B: Protective coating applied. Compatible environment per {mua}.",
        "N": "Corrosion N: Not applicable - no corrosive environment exposure.",
        "U": "Corrosion U: Requires protective treatment per {mua}.",
    },
    "TOX": {
        "B": "Toxicity B: Volume limited. Combustion products within crew cabin limits.",
        "C": "Toxicity C: Non-habitable location or enclosed. Per {mua}.",
        "K": "Toxicity K: Known concern - located in non-habitable area.",
        "U": "Toxicity U: Non-habitable use only. See {mua}.",
    },
    "FS": {
        "B": "Fluid service B: Compatible under design conditions per test data.",
        "C": "Fluid service C: Conditional use per operating envelope. See {mua}.",
        "I": "Fluid service I: Compatibility testing in progress.",
        "U": "FS U: Requires additional qualification per {mua}.",
    },
}

# Default template when no specific template matches
DEFAULT_TEMPLATES = {
    "B": "{type} B: Borderline per NASA-STD-6001. Engineering controls applied. See {mua}.",
    "C": "{type} C: Conditional use with restrictions. Precedent: {mua}.",
    "I": "{type} I: Insufficient data - testing pending.",
    "N": "{type} N: Not applicable for this application.",
    "U": "{type} U: Requires engineering controls per {mua}.",
    "K": "{type} K: Known concern mitigated by design. Per {mua}.",
    "D": "{type} D: Deficient - limited use with restrictions. See {mua}.",
}


@dataclass
class RemarkResult:
    """Result of generating a remark for a material."""
    remarks: str
    gaps: Dict[str, str]  # {rating_type: rating_value}
    precedents_used: List[str]  # MUA numbers referenced
    confidence: float
    has_precedent: bool


def _get_template(rating_type: str, rating_value: str) -> str:
    """Get the appropriate template for a rating type and value."""
    # Try specific template first
    type_templates = BRIEF_RATIONALE_TEMPLATES.get(rating_type, {})
    if rating_value in type_templates:
        return type_templates[rating_value]

    # Fall back to default by rating value
    return DEFAULT_TEMPLATES.get(
        rating_value,
        "{type} {value}: Per precedent {mua}."
    )


def _detect_gaps(miul_row: Dict[str, Any]) -> Dict[str, str]:
    """Detect non-A ratings that need rationale.

    Args:
        miul_row: MIUL row with rating columns

    Returns:
        Dict of {rating_type: rating_value} for gaps
    """
    gaps = {}

    for rating_type in RATING_PRIORITY:
        # Try various column name patterns
        rating = None
        for key in [rating_type, f"{rating_type} Rating", f"{rating_type}_Rating"]:
            if key in miul_row:
                val = miul_row[key]
                if val and str(val).strip():
                    rating = str(val).strip().upper()
                    break

        if rating and rating in GAP_RATINGS:
            gaps[rating_type] = rating

    return gaps


def generate_remark(
    miul_row: Dict[str, Any],
    engine: Optional[MUABOKEngine] = None,
    max_chars: int = 200,
) -> RemarkResult:
    """Generate a brief but complete MUA rationale remark for a MIUL row.

    Args:
        miul_row: MIUL row dictionary with ratings and material info
        engine: MUA BOK engine (uses singleton if None)
        max_chars: Maximum characters for the remark

    Returns:
        RemarkResult with generated remark and metadata
    """
    if engine is None:
        engine = get_mua_bok_engine()

    # Detect gaps (non-A ratings)
    gaps = _detect_gaps(miul_row)

    if not gaps:
        return RemarkResult(
            remarks="",
            gaps={},
            precedents_used=[],
            confidence=1.0,
            has_precedent=True,
        )

    # Get material info for precedent search
    material = (
        miul_row.get("Designation") or
        miul_row.get("designation") or
        miul_row.get("Material") or
        "Unknown"
    )
    environment = (
        miul_row.get("Environment") or
        miul_row.get("environment") or
        miul_row.get("Fluid Type") or
        ""
    )

    # Search for relevant precedents
    precedents: List[MUAPrecedent] = []
    if engine and engine.index is not None:
        try:
            precedents = engine.search_precedents(
                material=material,
                environment=environment,
                gaps=gaps,
                k=3
            )
        except Exception as e:
            logger.warning(f"Precedent search failed: {e}")

    # Build remark from templates
    remark_parts = []
    precedents_used = []

    # Use best precedent MUA number for citations
    best_mua = precedents[0].mua_number if precedents else "TBD"
    if precedents:
        precedents_used = [p.mua_number for p in precedents[:3]]

    # Generate remark for each gap
    for rating_type, rating_value in gaps.items():
        template = _get_template(rating_type, rating_value)

        # Format template
        remark = template.format(
            type=rating_type,
            value=rating_value,
            mua=best_mua,
        )
        remark_parts.append(remark)

    # Join all parts
    full_remark = " ".join(remark_parts)

    # Truncate if needed (try to break at sentence boundary)
    if len(full_remark) > max_chars:
        truncated = full_remark[:max_chars]
        last_period = truncated.rfind('.')
        if last_period > max_chars // 2:
            full_remark = truncated[:last_period + 1]
        else:
            full_remark = truncated.rstrip() + "..."

    # Calculate confidence based on precedent quality
    confidence = 0.5  # Base confidence
    if precedents:
        confidence = min(0.5 + precedents[0].score * 0.3, 0.95)
        # Boost if all precedents are APPROVED
        if all(p.determination == "APPROVED" for p in precedents):
            confidence = min(confidence + 0.1, 0.95)

    return RemarkResult(
        remarks=full_remark,
        gaps=gaps,
        precedents_used=precedents_used,
        confidence=confidence,
        has_precedent=len(precedents) > 0,
    )


def generate_remarks_bulk(
    miul_rows: List[Dict[str, Any]],
    max_chars: int = 200,
) -> List[RemarkResult]:
    """Generate remarks for multiple MIUL rows.

    Args:
        miul_rows: List of MIUL row dictionaries
        max_chars: Maximum characters per remark

    Returns:
        List of RemarkResults in same order as input
    """
    # Initialize engine once for all rows
    engine = get_mua_bok_engine()

    results = []
    for row in miul_rows:
        try:
            result = generate_remark(row, engine=engine, max_chars=max_chars)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to generate remark: {e}")
            results.append(RemarkResult(
                remarks="",
                gaps={},
                precedents_used=[],
                confidence=0.0,
                has_precedent=False,
            ))

    return results


def populate_miul_remarks(
    miul_df: "pd.DataFrame",
    max_chars: int = 200,
    overwrite: bool = False,
) -> "pd.DataFrame":
    """Populate the Remarks column for all rows with non-A ratings.

    Args:
        miul_df: MIUL DataFrame with rating columns
        max_chars: Maximum characters per remark
        overwrite: If True, overwrite existing remarks; if False, skip rows with remarks

    Returns:
        Updated DataFrame with Remarks column populated
    """
    import pandas as pd

    logger.info(f"[MUARemarks] Populating remarks for {len(miul_df)} rows")

    engine = get_mua_bok_engine()
    remarks_added = 0

    for idx, row in miul_df.iterrows():
        # Skip if already has remarks and not overwriting
        existing_remarks = row.get("Remarks", "")
        if existing_remarks and not overwrite:
            continue

        # Convert row to dict for processing
        row_dict = row.to_dict()

        # Generate remark
        result = generate_remark(row_dict, engine=engine, max_chars=max_chars)

        if result.remarks:
            if existing_remarks and overwrite:
                # Append to existing
                miul_df.at[idx, "Remarks"] = f"{existing_remarks} {result.remarks}".strip()
            else:
                miul_df.at[idx, "Remarks"] = result.remarks
            remarks_added += 1

    logger.info(f"[MUARemarks] Added remarks to {remarks_added} rows")

    return miul_df


# ============================================================================
# Testing
# ============================================================================

def test_remarks_generator():
    """Test the remarks generator with sample data."""
    print("=" * 70)
    print("MUA REMARKS GENERATOR TEST")
    print("=" * 70)

    # Test rows with various gaps
    test_rows = [
        {
            "Designation": "316L Stainless Steel",
            "Material Code": "12345",
            "FLAM": "B",
            "SCC": "A",
            "CORR": "A",
            "TVS": "A",
            "TOX": "A",
            "FS": "A",
            "Environment": "GOX 3000 psia",
        },
        {
            "Designation": "INCONEL 625",
            "Material Code": "67890",
            "FLAM": "A",
            "SCC": "C",
            "CORR": "B",
            "TVS": "A",
            "TOX": "A",
            "FS": "A",
            "Environment": "Hydrogen service",
        },
        {
            "Designation": "PTFE Seal",
            "Material Code": "11111",
            "FLAM": "C",
            "SCC": "A",
            "CORR": "A",
            "TVS": "B",
            "TOX": "B",
            "FS": "A",
            "Environment": "Habitable cabin",
        },
        {
            "Designation": "Aluminum 6061-T6",
            "Material Code": "22222",
            "FLAM": "A",
            "SCC": "A",
            "CORR": "A",
            "TVS": "A",
            "TOX": "A",
            "FS": "A",  # All A - no gaps
        },
    ]

    print("\nGenerating remarks for test materials:\n")

    for row in test_rows:
        print(f"Material: {row['Designation']}")
        print(f"  Ratings: FLAM={row['FLAM']}, SCC={row.get('SCC','')}, "
              f"CORR={row.get('CORR','')}, TVS={row.get('TVS','')}")

        result = generate_remark(row)

        print(f"  Gaps detected: {result.gaps}")
        print(f"  Precedents: {result.precedents_used}")
        print(f"  Confidence: {result.confidence:.0%}")
        print(f"  Remark: {result.remarks or '(none needed)'}")
        print()

    print("=" * 70)
    print("REMARKS GENERATOR TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    test_remarks_generator()
