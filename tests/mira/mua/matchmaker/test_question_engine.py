"""Tests for matchmaker v8 rule-pack loader and question interpreter."""

from __future__ import annotations

from copy import deepcopy

import pytest

from mira.core.models import SafetyCriticalError
from mira.mua.matchmaker.question_engine import (
    evaluate_answers,
    get_applicable_codes,
    get_next_question,
    load_rule_pack,
    validate_rule_pack,
)


def test_load_rule_pack_validates_default() -> None:
    rule_pack = load_rule_pack()
    assert rule_pack["rule_pack_id"] == "jsc-27301f-appendix-e"
    assert "FLAM" in rule_pack["domains"]


def test_validate_rule_pack_rejects_invalid_question_id() -> None:
    bad_pack = {
        "rule_pack_id": "jsc-27301f-appendix-e",
        "version": "1.0.0",
        "effective_date": "2026-02-16",
        "retired_date": None,
        "citation": "JSC 27301F Rev F, Appendix E",
        "domains": {
            "FLAM": {
                "applicable_codes": ["103"],
                "questions": [
                    {
                        "id": "BAD_ID",
                        "text": "Invalid ID shape",
                        "type": "yes_no",
                    }
                ],
            }
        },
    }

    with pytest.raises(SafetyCriticalError, match="Rule pack schema validation failed"):
        validate_rule_pack(bad_pack)


def test_get_next_question_respects_conditions() -> None:
    pack = load_rule_pack()
    flamm_pack = deepcopy(pack)
    flamm_pack["domains"]["FLAM"]["questions"] = [
        {
            "id": "Q1",
            "text": "Is sealed?",
            "type": "yes_no",
        },
        {
            "id": "Q2",
            "text": "Fallback question",
            "type": "yes_no",
            "condition": {"Q1": "No"},
        },
    ]
    validate_rule_pack(flamm_pack)

    assert get_next_question("FLAM", {}, flamm_pack)["id"] == "Q1"
    assert get_next_question("FLAM", {"Q1": "No"}, flamm_pack)["id"] == "Q2"


def test_evaluate_answers_multiple_cat3_requires_selection() -> None:
    pack = load_rule_pack()
    multi_pack = deepcopy(pack)
    multi_pack["domains"]["FLAM"]["questions"] = [
        {
            "id": "Q1",
            "text": "Path A",
            "type": "yes_no",
            "terminates": {"Yes": {"outcome": "CAT_III", "code": "106"}},
        },
        {
            "id": "Q2",
            "text": "Path B",
            "type": "yes_no",
            "condition": {"Q1": "Yes"},
            "terminates": {"Yes": {"outcome": "CAT_III", "code": "110"}},
        },
    ]
    validate_rule_pack(multi_pack)

    outcome = evaluate_answers("FLAM", {"Q1": "Yes", "Q2": "Yes"}, multi_pack)
    assert outcome.status == "MULTIPLE_CAT3"
    assert set(outcome.candidate_codes) == {"106", "110"}


def test_get_applicable_codes_includes_stowage_codes() -> None:
    pack = load_rule_pack()
    codes = get_applicable_codes("FLAM", pack)
    assert "103" in codes
    assert "S01" in codes

