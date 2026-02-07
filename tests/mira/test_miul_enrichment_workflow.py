#!/usr/bin/env python3
"""
Tests for the MIUL enrichment workflow - building first, then enriching.
"""

import pandas as pd
import pytest
from unittest.mock import Mock, patch

from mira.miul.builder import MIULBuilder
from mira.miul.enrichment import (
    MIULEnrichmentService,
    enrich_miul_with_maptis_ratings
)
from mira.miul.models import MIULBuildResult, MIULMetadata


@pytest.fixture
def sample_bom_data():
    """Sample BOM DataFrames for testing."""
    bom_df = pd.DataFrame({
        "Part Number": ["P001", "P002", "P003"],
        "Quantity": [4, 8, 1],
        "Drawing": ["DWG-001", "DWG-002", "DWG-003"]
    })

    crosswalk_df = pd.DataFrame({
        "Part Number": ["P001", "P002", "P003"],
        "Material Code": ["M001", "M002", "M003"]
    })

    specs_df = pd.DataFrame({
        "Material Code": ["M001", "M002", "M003"],
        "Nomenclature": ["Steel 1", "Aluminum 1", "Titanium 1"],
        "Designation": ["316L SST", "6061-T6", "Ti-6Al-4V"],
        "Material Specification": ["ASTM-A276", "ASTM-B221", "AMS-4928"],
        "Weight (lb)": [0.5, 0.2, 0.3]
    })

    return bom_df, crosswalk_df, specs_df


def test_enrich_miul_result_creates_new_result(sample_bom_data):
    """Test that enrich_miul_result returns a new MIULBuildResult."""
    bom_df, crosswalk_df, specs_df = sample_bom_data

    # Build initial MIUL
    builder = MIULBuilder(enable_audit=True)
    bom_doc = builder.load_bom_from_dataframe(bom_df)
    crosswalk = builder.load_material_crosswalk(crosswalk_df)
    specs = builder.load_material_specs(specs_df)
    result = builder.build_miul_from_bom(bom_doc, crosswalk, specs)

    assert isinstance(result, MIULBuildResult)
    assert len(result.miul_data) == 3

    # Mock the enrichment service to avoid DB calls
    with patch.object(MIULEnrichmentService, 'enrich_miul_dataframe') as mock_enrich:
        # Setup mock to return enriched data with fake ratings
        def mock_enrich_df(df):
            enriched_df = df.copy()
            enriched_df["FLAM"] = "A"
            enriched_df["SCC"] = "B"
            enriched_df["CORR"] = "A"
            enriched_df["TVS"] = "1"
            enriched_df["TOX"] = "1"
            enriched_df["FS"] = "A"

            stats = {
                "total_materials": 3,
                "enriched_count": 3,
                "coverage_pct": 100.0,
                "total_ratings_added": 18,
                "codes_looked_up": 0,
                "ratings_by_type": {
                    "FLAM": 3,
                    "SCC": 3,
                    "CORR": 3,
                    "TVS": 3,
                    "TOX": 3,
                    "FS": 3
                }
            }
            return enriched_df, stats

        mock_enrich.side_effect = mock_enrich_df

        # Enrich the MIUL result
        service = MIULEnrichmentService()
        enriched_result = service.enrich_miul_result(result)

    # Verify enriched result
    assert isinstance(enriched_result, MIULBuildResult)
    assert len(enriched_result.miul_data) == 3

    # Verify ratings were added
    assert "FLAM" in enriched_result.miul_data.columns
    assert "SCC" in enriched_result.miul_data.columns

    # Verify enrichment summary in warnings
    assert any("MAPTIS Enrichment" in w for w in enriched_result.warnings)

    # Verify metadata is preserved
    assert enriched_result.metadata.build_id == result.metadata.build_id
    assert enriched_result.metadata.source_bom_items == result.metadata.source_bom_items

    # Verify processing time increased
    assert enriched_result.metadata.processing_time_seconds >= result.metadata.processing_time_seconds


def test_convenience_function_enrich_miul_with_maptis_ratings(sample_bom_data):
    """Test the convenience function for enrichment."""
    bom_df, crosswalk_df, specs_df = sample_bom_data

    # Build initial MIUL
    builder = MIULBuilder(enable_audit=True)
    bom_doc = builder.load_bom_from_dataframe(bom_df)
    crosswalk = builder.load_material_crosswalk(crosswalk_df)
    specs = builder.load_material_specs(specs_df)
    result = builder.build_miul_from_bom(bom_doc, crosswalk, specs)

    # Mock the enrichment
    with patch.object(MIULEnrichmentService, 'enrich_miul_dataframe') as mock_enrich:
        def mock_enrich_df(df):
            enriched_df = df.copy()
            enriched_df["FLAM"] = "A"

            stats = {
                "total_materials": 3,
                "enriched_count": 3,
                "coverage_pct": 100.0,
                "total_ratings_added": 3,
                "codes_looked_up": 0
            }
            return enriched_df, stats

        mock_enrich.side_effect = mock_enrich_df

        # Use convenience function
        enriched_result = enrich_miul_with_maptis_ratings(result)

    # Verify result
    assert isinstance(enriched_result, MIULBuildResult)
    assert len(enriched_result.miul_data) == 3
    assert "FLAM" in enriched_result.miul_data.columns


def test_enriched_result_preserves_original_data(sample_bom_data):
    """Test that enrichment preserves original MIUL data."""
    bom_df, crosswalk_df, specs_df = sample_bom_data

    # Build initial MIUL
    builder = MIULBuilder(enable_audit=True)
    bom_doc = builder.load_bom_from_dataframe(bom_df)
    crosswalk = builder.load_material_crosswalk(crosswalk_df)
    specs = builder.load_material_specs(specs_df)
    result = builder.build_miul_from_bom(bom_doc, crosswalk, specs)

    original_part_numbers = result.miul_data["part_number"].tolist()

    # Mock enrichment
    with patch.object(MIULEnrichmentService, 'enrich_miul_dataframe') as mock_enrich:
        def mock_enrich_df(df):
            enriched_df = df.copy()
            enriched_df["FLAM"] = "A"

            stats = {
                "total_materials": 3,
                "enriched_count": 3,
                "coverage_pct": 100.0,
                "total_ratings_added": 3,
                "codes_looked_up": 0
            }
            return enriched_df, stats

        mock_enrich.side_effect = mock_enrich_df

        enriched_result = enrich_miul_with_maptis_ratings(result)

    # Verify original data is preserved
    enriched_part_numbers = enriched_result.miul_data["part_number"].tolist()
    assert enriched_part_numbers == original_part_numbers

    # Verify errors and audit trail are preserved
    assert enriched_result.errors == result.errors
    assert enriched_result.audit_trail == result.audit_trail
