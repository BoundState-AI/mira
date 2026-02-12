#!/usr/bin/env python3
"""
Targeted tests for MIUL material code placeholder handling.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from mira.miul.workflow import MIULWorkflow


def _workflow() -> MIULWorkflow:
    return MIULWorkflow(
        extractor_service=MagicMock(),
        enrichment_service=MagicMock(),
        tree_builder=MagicMock(),
    )


def test_lookup_treats_placeholder_material_code_as_missing() -> None:
    workflow = _workflow()
    df = pd.DataFrame(
        {
            "Designation": ["316L CRES"],
            "Material Code": ["-----"],
        }
    )

    with patch("mira.miul.workflow.MATERIAL_LOOKUP_AVAILABLE", False):
        workflow._enrichment.find_material_code_by_designation.return_value = "12345"
        result_df, count, quarantine = workflow.lookup_material_codes(df)

    assert count == 1
    assert quarantine == []
    assert result_df.at[0, "Material Code"] == "12345"


@patch("mira.miul.workflow.get_ratings_bulk")
def test_fetch_ratings_ignores_placeholder_material_codes(mock_bulk) -> None:
    mock_bulk.return_value = {"12345": {"FLAM": "A"}}

    workflow = _workflow()
    df = pd.DataFrame(
        {
            "Material Code": ["-----", "12345", None],
            "FLAM": ["", "", ""],
            "SCC": ["", "", ""],
            "CORR": ["", "", ""],
            "TVS": ["", "", ""],
            "TOX": ["", "", ""],
            "FS": ["", "", ""],
        }
    )

    result_df, stats = workflow.fetch_ratings(df)

    mock_bulk.assert_called_once_with(["12345"])
    assert stats["total_materials"] == 1
    assert stats["enriched_count"] == 1
    assert result_df.at[1, "FLAM"] == "A"
    assert result_df.at[0, "FLAM"] == ""
