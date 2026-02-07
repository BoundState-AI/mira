#!/usr/bin/env python3
"""
Example: MIUL Builder with Separate Enrichment

Demonstrates the two-step workflow:
1. Build a MIUL from BOM data
2. Enrich it with MAPTIS ratings

This allows you to create a MIUL first, then send it back for enrichment later.
"""

import pandas as pd
from mira.miul.builder import build_miul_from_bom
from mira.miul.enrichment import enrich_miul_with_maptis_ratings


def example_build_then_enrich():
    """Example: Build MIUL first, then enrich separately."""

    # Sample BOM data
    bom_data = {
        "Part Number": ["P001", "P002", "P003"],
        "Quantity": [4, 8, 1],
        "Drawing": ["DWG-001", "DWG-002", "DWG-003"]
    }
    bom_df = pd.DataFrame(bom_data)

    # Sample crosswalk (Part Number -> Material Code)
    crosswalk_data = {
        "Part Number": ["P001", "P002", "P003"],
        "Material Code": ["SS316L", "AL6061", "TI6AL4V"]
    }
    crosswalk_df = pd.DataFrame(crosswalk_data)

    # Sample material specifications
    specs_data = {
        "Material Code": ["SS316L", "AL6061", "TI6AL4V"],
        "Nomenclature": ["Stainless Steel 316L", "Aluminum 6061-T6", "Titanium 6Al-4V"],
        "Designation": ["316L SST", "6061-T6", "Ti-6Al-4V"],
        "Material Specification": ["ASTM-A276-316L", "ASTM-B221-6061", "AMS-4928"],
        "Weight (lb)": [0.5, 0.2, 0.3]
    }
    specs_df = pd.DataFrame(specs_data)

    print("=" * 80)
    print("STEP 1: Build MIUL from BOM")
    print("=" * 80)

    # Step 1: Build the MIUL
    miul_result = build_miul_from_bom(bom_df, crosswalk_df, specs_df)

    print(f"✓ Built MIUL with {len(miul_result.miul_data)} rows")
    print(f"  - Material coverage: {miul_result.metadata.material_coverage_percent:.1f}%")
    print(f"  - Processing time: {miul_result.metadata.processing_time_seconds:.2f}s")
    print(f"  - Warnings: {len(miul_result.warnings)}")
    print(f"  - Errors: {len(miul_result.errors)}")

    # Display the initial MIUL data (without ratings)
    print("\nInitial MIUL (no ratings):")
    print(miul_result.miul_data[["part_number", "material_code", "designation"]].head())

    print("\n" + "=" * 80)
    print("STEP 2: Enrich MIUL with MAPTIS Ratings")
    print("=" * 80)

    # Step 2: Enrich with MAPTIS ratings
    enriched_result = enrich_miul_with_maptis_ratings(miul_result)

    print(f"✓ Enriched MIUL")
    print(f"  - Total processing time: {enriched_result.metadata.processing_time_seconds:.2f}s")
    print(f"  - Enrichment info: {enriched_result.warnings[-1]}")

    # Display the enriched MIUL data (with ratings)
    rating_cols = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]
    available_rating_cols = [col for col in rating_cols if col in enriched_result.miul_data.columns]

    if available_rating_cols:
        print("\nEnriched MIUL (with ratings):")
        display_cols = ["part_number", "material_code"] + available_rating_cols
        print(enriched_result.miul_data[display_cols].head())
    else:
        print("\nNote: Rating columns not found in enriched data")

    print("\n" + "=" * 80)
    print("STEP 3: Export to Excel")
    print("=" * 80)

    # Step 3: Export to Excel
    output_file = "output/enriched_miul_example.xlsx"
    enriched_result.to_excel(output_file, include_metadata=True)
    print(f"✓ Exported to: {output_file}")

    return enriched_result


def example_direct_dataframe_enrichment():
    """Example: Enrich a DataFrame directly (legacy method)."""

    print("\n" + "=" * 80)
    print("ALTERNATIVE: Direct DataFrame Enrichment (Legacy)")
    print("=" * 80)

    # Create a simple MIUL DataFrame
    miul_data = {
        "Material Code": ["SS316L", "AL6061", None],
        "Designation": ["316L SST", "6061-T6", "Inconel 718"],
        "part_number": ["P001", "P002", "P003"]
    }
    miul_df = pd.DataFrame(miul_data)

    print("Initial DataFrame:")
    print(miul_df)

    # Enrich directly using the service
    from mira.miul.enrichment import get_enrichment_service

    service = get_enrichment_service()
    enriched_df, stats = service.enrich_miul_dataframe(miul_df)

    print(f"\n✓ Enriched DataFrame")
    print(f"  - Enriched: {stats['enriched_count']}/{stats['total_materials']}")
    print(f"  - Coverage: {stats['coverage_pct']:.1f}%")
    print(f"  - Codes looked up: {stats['codes_looked_up']}")

    print("\nEnriched DataFrame:")
    print(enriched_df[["Material Code", "Designation", "FLAM", "SCC", "CORR"]])

    return enriched_df, stats


if __name__ == "__main__":
    # Run the two-step workflow example
    enriched_result = example_build_then_enrich()

    # Run the direct DataFrame enrichment example
    # enriched_df, stats = example_direct_dataframe_enrichment()
