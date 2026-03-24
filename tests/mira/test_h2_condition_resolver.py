import mira.h2.condition_resolver as resolver
from mira.h2.condition_resolver import clear_condition_resolution_cache, resolve_condition_label


def test_known_condition_slug_is_humanized_without_review(monkeypatch):
    monkeypatch.setenv("MIRA_H2_RUNTIME_BACKEND", "json")
    monkeypatch.setenv("MIRA_H2_CONDITION_RESOLVER_PROVIDER", "off")
    clear_condition_resolution_cache()

    resolution = resolve_condition_label(
        raw_condition="solution_treated_aged",
        material_name="Inconel 718",
        source_document="HEE.pdf",
    )

    assert resolution.canonical_condition == "solution_treated_aged"
    assert resolution.display_label == "Solution Treated + Aged"
    assert resolution.is_condition is True
    assert resolution.needs_review is False
    assert resolution.confidence == 1.0


def test_known_condition_overrides_stale_unverified_persisted_alias(monkeypatch):
    monkeypatch.setenv("MIRA_H2_CONDITION_RESOLVER_PROVIDER", "off")
    monkeypatch.setattr(resolver, "_PG_TABLE_READY", False)
    monkeypatch.setattr(resolver, "get_runtime_backend", lambda: "pg")
    monkeypatch.setattr(resolver, "ensure_condition_alias_table", lambda: None)
    monkeypatch.setattr(
        resolver,
        "fetch_condition_alias",
        lambda raw_key: {
            "raw_text": raw_key,
            "canonical_condition": raw_key,
            "display_label": raw_key,
            "is_condition": True,
            "confidence": 0.4,
            "resolver_provider": "off",
            "resolver_model": "off",
            "human_verified": False,
        },
    )
    monkeypatch.setattr(resolver, "upsert_condition_alias", lambda **_: None)
    clear_condition_resolution_cache()

    resolution = resolver.resolve_condition_label(
        raw_condition="solution_treated_aged",
        material_name="Inconel 718",
        source_document="HEE.pdf",
    )

    assert resolution.canonical_condition == "solution_treated_aged"
    assert resolution.display_label == "Solution Treated + Aged"
    assert resolution.needs_review is False
    assert resolution.confidence == 1.0
