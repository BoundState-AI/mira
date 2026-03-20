"""Unit tests for PG precedent search helpers."""

from mira.mua.v7.pg_precedent_search import _extract_material_anchor


def test_extract_material_anchor_aluminum_alloy_digits() -> None:
    anchor = _extract_material_anchor("AL 6061-O PLATE", "ALUMINUM")
    assert anchor == "6061"


def test_extract_material_anchor_uns_a_form() -> None:
    anchor = _extract_material_anchor("A96061", "ALUMINUM")
    assert anchor == "6061"


def test_extract_material_anchor_non_numeric_material_returns_none() -> None:
    anchor = _extract_material_anchor("PTFE FILM", "POLYMER")
    assert anchor is None

