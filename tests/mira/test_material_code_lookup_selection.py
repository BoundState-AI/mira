#!/usr/bin/env python3
"""Tests for deterministic material-code fallback selection logic."""

from mira.miul.material_code_lookup import MaterialCodeLookupService, MaterialMatch


def _candidate(code: str, designation: str, score: float = 0.85) -> MaterialMatch:
    return MaterialMatch(
        material_code=code,
        designation=designation,
        confidence="medium",
        method="fuzzy_designation",
        score=score,
        specs=[],
    )


def _service_with_fallback_candidates(candidates):
    svc = MaterialCodeLookupService()
    svc._exact_designation_match = lambda _: None
    svc._family_filtered_partial_match = lambda *_: []
    svc.lookup_by_designation = lambda _: list(candidates)
    return svc


def test_prefers_rulon_lr_candidate_when_lr_present():
    svc = _service_with_fallback_candidates(
        [
            _candidate("01848", "RULON641"),
            _candidate("01862", "RULONF"),
            _candidate("07127", "RULONLR"),
        ]
    )

    match = svc.lookup_material_code("RULON LR")
    assert match.material_code == "07127"
    assert match.method == "fuzzy_designation"


def test_marks_silicon_nitride_as_ambiguous_with_weak_candidates():
    svc = _service_with_fallback_candidates(
        [
            _candidate("02092", "TITANIUM NITRIDE GOLD ON AMS 5630", score=0.52),
            _candidate("30187", "SILICON", score=0.90),
        ]
    )

    match = svc.lookup_material_code("SILICON NITRIDE (SI3N4)")
    assert match.material_code is None
    assert match.method == "ambiguous"


def test_prefers_silicon_nitride_candidate_when_present():
    svc = _service_with_fallback_candidates(
        [
            _candidate("60211", "SILICONE"),
            _candidate("77777", "SILICON NITRIDE CERAMIC"),
            _candidate("01168", "SILICON CARBIDE"),
        ]
    )

    match = svc.lookup_material_code("SILICON NITRIDE (SI3N4)")
    assert match.material_code == "77777"
    assert match.method == "fuzzy_designation"
