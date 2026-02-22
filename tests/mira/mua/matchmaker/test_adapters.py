"""Contract tests for the v8 anti-corruption adapter layer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mira.mua.matchmaker import adapters
from mira.mua.matchmaker.models import (
    EnvironmentSpec,
    IssueCode,
    MaterialResolution,
    MaterialResolutionStatus,
)


@pytest.fixture
def sample_environment() -> EnvironmentSpec:
    return EnvironmentSpec(
        o2_percent=21.0,
        pressure_psia=14.7,
        temp_min_f=65.0,
        temp_max_f=75.0,
        medium="AIR",
        location="habitable",
        application="Cabin label",
    )


class TestResolveMaterialContract:
    def test_returns_material_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_resolution = SimpleNamespace(
            input_text="6061-T6",
            status=SimpleNamespace(value="resolved"),
            material_code="MAT-A00601",
            material_key=123,
            resolved_name="Aluminum 6061-T6",
            family="ALUMINUM",
            material_class=SimpleNamespace(value="metal"),
            is_process_sensitive=False,
            selection_method="exact",
            selection_confidence=0.99,
        )
        monkeypatch.setattr(adapters, "_v7_resolve_material", lambda _: fake_resolution)

        result = adapters.resolve_material("6061-T6")

        assert isinstance(result, MaterialResolution)
        assert result.status == MaterialResolutionStatus.RESOLVED
        assert result.material_code == "MAT-A00601"
        assert result.resolved_name == "Aluminum 6061-T6"

    def test_unknown_material_returns_unresolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_resolution = SimpleNamespace(
            input_text="unobtanium-9999",
            status=SimpleNamespace(value="unresolved"),
            material_code=None,
            resolved_name=None,
            family=None,
            material_class=None,
            is_process_sensitive=False,
            selection_method=None,
            selection_confidence=None,
        )
        monkeypatch.setattr(adapters, "_v7_resolve_material", lambda _: fake_resolution)

        result = adapters.resolve_material("unobtanium-9999")

        assert result.status == MaterialResolutionStatus.UNRESOLVED
        assert result.material_code is None


class TestSearchPrecedentsContract:
    def test_returns_list(self, monkeypatch: pytest.MonkeyPatch, sample_environment: EnvironmentSpec) -> None:
        monkeypatch.setattr(
            adapters,
            "_v7_search_precedents_pg",
            lambda **_: [],
        )

        results = adapters.search_precedents("6061-T6", sample_environment)

        assert isinstance(results, list)

    def test_results_have_required_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_environment: EnvironmentSpec,
    ) -> None:
        fake_result = SimpleNamespace(
            mua_number="1001-0152",
            determination="APPROVED",
            rationale="Accepted on metallic substrate",
            material_designation="AL 6061-T6",
            material_family="ALUMINUM",
            issues=["FLAM"],
            env_type="CABIN_AIR",
            o2_percent=21.0,
            pressure_psia=14.7,
            confidence=0.88,
        )
        monkeypatch.setattr(adapters, "_v7_search_precedents_pg", lambda **_: [fake_result])

        results = adapters.search_precedents("6061-T6", sample_environment, issue_code="FLAM")

        assert len(results) == 1
        first = results[0]
        assert first.mua_number == "1001-0152"
        assert first.determination == "approved"
        assert first.material_designation == "AL 6061-T6"
        assert first.rationale_text is not None
        assert first.issue_codes == [IssueCode.FLAM]

    def test_issue_filter_normalizes_alias(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_environment: EnvironmentSpec,
    ) -> None:
        captured: dict[str, object] = {}

        def _fake_search(**kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr(adapters, "_v7_search_precedents_pg", _fake_search)
        adapters.search_precedents("6061-T6", sample_environment, issue_code="O2_COMPAT")

        assert captured["issues"] == ["O2_COMPAT"]

    def test_invalid_issue_code_raises(
        self,
        sample_environment: EnvironmentSpec,
    ) -> None:
        with pytest.raises(ValueError, match="Invalid issue code"):
            adapters.search_precedents("6061-T6", sample_environment, issue_code="NOT_A_CODE")


class TestFamilyAliasMap:
    def test_alias_map_importable(self) -> None:
        aliases = adapters.get_family_aliases()
        assert isinstance(aliases, dict)
        assert len(aliases) > 0

    def test_canonical_families_present(self) -> None:
        aliases = adapters.get_family_aliases()
        canonical_families = {value.lower() for value in aliases.values()}
        expected = {"aluminum", "stainless_steel", "nickel_alloy", "titanium", "copper_alloy"}
        assert expected.issubset(canonical_families)

