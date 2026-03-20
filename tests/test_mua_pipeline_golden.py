"""Golden regression cases for MUA v10 runtime pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from mira.mua.classifier.pipeline import process_miul_row

CASES_PATH = Path(__file__).resolve().parent / "golden_mua_cases.json"


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text())


def test_golden_pack_has_20_cases() -> None:
    cases = _load_cases()
    assert len(cases) == 20


def test_golden_pipeline_outcomes() -> None:
    cases = _load_cases()

    for case in cases:
        payload = case["input"]
        expected = case.get("expected", {})

        result = process_miul_row(
            ratings=payload["ratings"],
            maptis_code=payload["maptis_code"],
            material_designation=payload.get("material_designation", ""),
            material_class=payload.get("material_class"),
            media=payload.get("media", ""),
            environment=payload.get("environment", "non-habitable"),
            o2_percent=payload.get("o2_percent"),
            batch_verified=payload.get("batch_verified", False),
        )

        assert result.classifications, f"{case['id']}: no classifications returned"

        # Most golden cases are single-flag; use first classification by default.
        cls = result.classifications[0]

        if "mua_type" in expected:
            assert cls.mua_type.value == expected["mua_type"], case["id"]

        if "automatable" in expected:
            assert cls.automatable is bool(expected["automatable"]), case["id"]

        if "category" in expected:
            expected_category = expected["category"]
            actual = cls.category.value if cls.category else None
            assert actual == expected_category, case["id"]

        must_contain = [s.lower() for s in expected.get("rationale_must_contain", [])]
        if must_contain and result.forms:
            rationale = (result.forms[0].rationale or "").lower()
            for needle in must_contain:
                assert needle in rationale, f"{case['id']}: missing rationale phrase '{needle}'"

        disp_contains = [s.lower() for s in expected.get("disposition_must_contain", [])]
        if disp_contains and result.forms:
            disposition = (result.forms[0].disposition or "").lower()
            for needle in disp_contains:
                assert needle in disposition, f"{case['id']}: missing disposition phrase '{needle}'"
