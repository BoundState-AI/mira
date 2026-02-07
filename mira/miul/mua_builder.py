#!/usr/bin/env python3
"""
Module: Mua Builder
Purpose: import logging

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

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd

from src.api.miul_enrichment import (
    MIULEnrichmentService,
    MIUL_RATING_COLUMNS,
)

logger = logging.getLogger(__name__)


@dataclass
class MUABuildStats:
    """MUA build statistics and coverage metrics.

    Compliance: SWE-013
    """

    total_materials: int
    enriched_materials: int
    coverage_pct: float
    ratings_by_type: Dict[str, int]
    source: str = ""  # NASA SWE-013 traceability



class MUABuilder:
    """Build MUA summary table from a MIUL DataFrame.

    The output is a unique-per-material table with the six core MAPTIS ratings
    (FLAMM, SCC, CORR, TVS, FS, TOX) aggregated conservatively (worst-case).

    Compliance: SWE-056 (Data consistency), SWE-061 (Traceability)
    """

    def __init__(self) -> None:
        self.enricher = MIULEnrichmentService()

    def build_from_miul(self, miul_df: pd.DataFrame) -> Tuple[pd.DataFrame, MUABuildStats]:
        """Build a MUA summary DataFrame from a MIUL DataFrame.

        Args:
            miul_df: MIUL DataFrame containing a 'Material Code' column.

        Returns:
            (mua_df, stats) where mua_df has one row per material code.

        Compliance: SWE-032 (Validate inputs)
        """
        if 'Material Code' not in miul_df.columns:
            raise ValueError("MIUL is missing required column 'Material Code'")

        # Collect unique, non-empty material codes
        codes_series = miul_df['Material Code'].dropna().astype(str)
        material_codes = sorted({c.strip() for c in codes_series if c.strip() and 'UNKNOWN' not in c})

        # Lookup ratings in bulk via MAPTIS
        ratings_map = self.enricher.get_ratings_bulk(material_codes)

        rows: List[Dict[str, Any]] = []
        for code in material_codes:
            # Try to pick a representative designation from the MIUL for this code
            designation = ''
            try:
                subset = miul_df[miul_df['Material Code'] == code]
                if 'Designation' in subset.columns and not subset['Designation'].isna().all():
                    designation = str(subset['Designation'].dropna().iloc[0])
            except Exception:
                designation = ''

            row: Dict[str, Any] = {
                'Material Code': code,
                'Designation': designation,
            }

            # Ensure all expected rating columns are present
            for _, col in MIUL_RATING_COLUMNS.items():
                if col not in row:
                    row[col] = ''

            # Populate ratings
            for rating_col, value in (ratings_map.get(code) or {}).items():
                row[rating_col] = value

            rows.append(row)

        mua_df = pd.DataFrame(rows)

        # Build stats
        total = len(material_codes)
        enriched = 0 if mua_df.empty else int(
            (mua_df[[c for c in MIUL_RATING_COLUMNS.values() if c in mua_df.columns]].notna() &
             (mua_df[[c for c in MIUL_RATING_COLUMNS.values() if c in mua_df.columns]] != '')).any(axis=1).sum()
        )
        ratings_by_type = {
            col: int(mua_df[col].astype(str).str.len().gt(0).sum()) if col in mua_df.columns else 0
            for col in MIUL_RATING_COLUMNS.values()
        }
        coverage = (enriched / total * 100.0) if total > 0 else 0.0

        stats = MUABuildStats(
            total_materials=total,
            enriched_materials=enriched,
            coverage_pct=coverage,
            ratings_by_type=ratings_by_type,
        )

        logger.info(
            "Built MUA summary: %d materials, %.1f%% coverage",
            stats.total_materials,
            stats.coverage_pct,
        )

        return mua_df, stats

