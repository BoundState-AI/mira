#!/usr/bin/env python3
"""API tests for the additive FORGE router."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest


def _create_api_fixture(db_path: Path) -> str:
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.executescript(
        """
        CREATE TABLE suppliers (
            supplier_id INTEGER PRIMARY KEY,
            supplier_name TEXT NOT NULL
        );

        CREATE TABLE parts (
            part_id INTEGER PRIMARY KEY,
            supplier_id INTEGER NOT NULL,
            part_name TEXT NOT NULL,
            weight_g REAL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id)
        );
        """
    )
    cursor.executemany(
        "INSERT INTO suppliers (supplier_id, supplier_name) VALUES (?, ?)",
        [(1, "North Fabrication"), (2, "Delta Alloys")],
    )
    cursor.executemany(
        "INSERT INTO parts (part_id, supplier_id, part_name, weight_g, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (1, 1, "Bracket", 22.5, "2026-02-01T00:00:00"),
            (2, 2, "Valve Body", 85.2, "2026-02-02T00:00:00"),
        ],
    )
    connection.commit()
    connection.close()
    return f"sqlite:///{db_path}"


def _create_h2_semantic_fixture(db_path: Path) -> str:
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.executescript(
        """
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY,
            material_name TEXT,
            material_family TEXT,
            heat_treatment TEXT,
            product_form TEXT,
            pressure_mpa REAL,
            reference_gas TEXT,
            nts_ratio REAL,
            el_ratio REAL,
            ra_ratio REAL,
            hee_index REAL,
            hee_band TEXT,
            he_mechanism TEXT
        );

        CREATE TABLE degradation_ratios (
            id INTEGER PRIMARY KEY,
            ratio_type TEXT,
            reference_value REAL,
            hydrogen_value REAL,
            ratio_h2_over_ref REAL,
            degradation_pct REAL,
            ref_environment TEXT,
            h2_environment TEXT,
            material TEXT,
            form TEXT,
            temper TEXT
        );

        CREATE TABLE coverage_gaps (
            id INTEGER PRIMARY KEY,
            material TEXT,
            event TEXT,
            source_file TEXT
        );
        """
    )
    cursor.executemany(
        """
        INSERT INTO evidence (
            evidence_id, material_name, material_family, heat_treatment, product_form,
            pressure_mpa, reference_gas, nts_ratio, el_ratio, ra_ratio,
            hee_index, hee_band, he_mechanism
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("e1", "Nickel 270", "nickel_alloy", "annealed", "plate", 68.9, "helium", 0.70, 0.92, 0.75, 0.70, "high", "HEE"),
            ("e2", "Nickel 301", "nickel_alloy", "as_received", "sheet", 68.9, "helium", 0.35, None, None, 0.35, "extreme", "HEE"),
            ("e3", "Monel K-500", "nickel_alloy", "solution_treated_aged", "bar", 34.5, "hydrogen", 0.45, 0.40, 0.41, 0.45, "extreme", "HEDE"),
        ],
    )
    cursor.executemany(
        """
        INSERT INTO degradation_ratios (
            id, ratio_type, reference_value, hydrogen_value, ratio_h2_over_ref,
            degradation_pct, ref_environment, h2_environment, material, form, temper
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "fracture_toughness_KIC", 44.0, 26.0, 0.59, 40.9, "air", "H2", "X42", "pipe", "None"),
            (2, "fracture_toughness_JIC", 30.0, 11.0, 0.37, 63.3, "air", "H2", "X42", "pipe", "None"),
            (3, "tensile_yield_strength_MPa", 500.0, 452.0, 0.90, 9.6, "air", "H2", "X42", "pipe", "None"),
            (4, "fracture_toughness_KIC", 55.0, 56.0, 1.02, -2.3, "air", "H2", "7475", "plate", "T7351"),
        ],
    )
    cursor.executemany(
        "INSERT INTO coverage_gaps (id, material, event, source_file) VALUES (?, ?, ?, ?)",
        [
            (1, "Kalrez FFKM", "material_not_in_evidence_index", "coverage_gaps.jsonl"),
            (2, "Kalrez FFKM", "material_not_in_evidence_index", "coverage_gaps.jsonl"),
            (3, "INCONEL", "material_not_in_evidence_index", "coverage_gaps.jsonl"),
        ],
    )
    connection.commit()
    connection.close()
    return f"sqlite:///{db_path}"


def test_forge_compile_endpoint(api_client, tmp_path: Path) -> None:
    db_url = _create_api_fixture(tmp_path / "forge_api.sqlite")

    response = api_client.post(
        "/api/forge/compile",
        json={
            "database_url": db_url,
            "app_name": "API Forge",
            "sample_rows_per_table": 20,
            "require_llm_refinement": False,
        },
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "accepted"

    deadline = time.monotonic() + 10.0
    payload = None
    while time.monotonic() < deadline:
        status_response = api_client.get(f"/api/forge/compile/{accepted['job_id']}")
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload["status"] == "completed":
            payload = payload["result"]
            break
        if payload["status"] == "failed":
            pytest.fail(payload["error"] or payload["message"])
        time.sleep(0.05)

    assert payload is not None, "FORGE compile job never produced a payload."
    assert payload["status"] == "ok"
    assert payload["summary"]["table_count"] == 2
    question_counts = payload["question_map"].get("question_type_counts", {})
    if question_counts:
        assert question_counts["relationship"] >= 1
    else:
        categories = payload["question_map"].get("question_categories", [])
        assert categories
    assert payload["generated_bundle"]["backend_dir"]
    files = {path.replace("\\", "/") for path in payload["generated_bundle"]["files"]}
    assert files
    assert any(path.endswith("bsms/bouncer.py") for path in files)
    assert any(path.endswith("bsms/parser.py") for path in files)


def test_forge_compile_rejects_remote_database_urls(api_client) -> None:
    response = api_client.post(
        "/api/forge/compile",
        json={
            "database_url": "postgresql://user:secret@example.com/forge",
            "app_name": "Unsafe Forge",
            "sample_rows_per_table": 20,
        },
    )

    assert response.status_code == 400
    assert "Remote database URLs are disabled by default" in response.json()["detail"]


def test_forge_compile_respects_question_budget(api_client, tmp_path: Path) -> None:
    db_url = _create_api_fixture(tmp_path / "forge_budget.sqlite")

    response = api_client.post(
        "/api/forge/compile",
        json={
            "database_url": db_url,
            "app_name": "Budget Forge",
            "sample_rows_per_table": 20,
            "require_llm_refinement": False,
            "max_generated_questions": 4,
            "max_questions_per_table": 2,
        },
    )

    assert response.status_code == 202
    accepted = response.json()

    deadline = time.monotonic() + 10.0
    payload = None
    while time.monotonic() < deadline:
        status_response = api_client.get(f"/api/forge/compile/{accepted['job_id']}")
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload["status"] == "completed":
            payload = payload["result"]
            break
        if payload["status"] == "failed":
            pytest.fail(payload["error"] or payload["message"])
        time.sleep(0.05)

    assert payload is not None
    assert payload["summary"]["generated_question_count"] <= 4
    per_table: dict[str, int] = {}
    for category in payload["question_map"].get("question_categories", []):
        for question in category.get("questions", []):
            table = question.get("target_table")
            if not table:
                continue
            per_table[table] = per_table.get(table, 0) + 1
    assert per_table
    assert max(per_table.values()) <= 2


def test_forge_compile_status_returns_404_for_unknown_job(api_client) -> None:
    response = api_client.get("/api/forge/compile/not-a-real-job")

    assert response.status_code == 404
    assert "Unknown FORGE job" in response.json()["detail"]


def test_forge_compile_fails_closed_when_llm_is_required(api_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_url = _create_api_fixture(tmp_path / "forge_required_llm.sqlite")

    def _boom(*args, **kwargs):
        raise RuntimeError("sonnet unavailable")

    monkeypatch.setattr("mira.forge_claude.compiler.refine_questions_with_llm", _boom)

    response = api_client.post(
        "/api/forge/compile",
        json={
            "database_url": db_url,
            "app_name": "Strict Forge",
            "sample_rows_per_table": 20,
            "require_llm_refinement": True,
        },
    )

    assert response.status_code == 202
    accepted = response.json()

    deadline = time.monotonic() + 10.0
    payload = None
    while time.monotonic() < deadline:
        status_response = api_client.get(f"/api/forge/compile/{accepted['job_id']}")
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload["status"] == "failed":
            break
        time.sleep(0.05)

    assert payload is not None
    assert payload["status"] == "failed"
    assert "requires Sonnet refinement" in (payload["error"] or "")


def test_forge_bsms_query_fails_closed_when_llm_is_required(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mira.api.routers.forge.bsms_runtime.llm_status",
        lambda *, require_llm=None: {
            "provider": "anthropic",
            "configured": False,
            "enabled": False,
            "model": "claude-sonnet",
            "require_llm": True if require_llm is None else require_llm,
        },
    )

    response = api_client.post(
        "/api/forge/bsms/query",
        json={
            "query": "show supplier records",
            "question_map": {
                "questions": [
                    {"id": "q1", "question": "Show supplier records", "question_type": "detail_view", "table": "suppliers"}
                ]
            },
            "bsms_pipeline": {
                "bouncer_config": {"domain_keywords": ["supplier"], "allowed_intents": ["detail_view"]},
                "parser_config": {"field_mappings": {"suppliers": ["supplier_name"]}},
            },
            "authority_pack": {},
            "require_llm": True,
        },
    )

    assert response.status_code == 503
    assert "requires LLM runtime" in response.json()["detail"]


def test_forge_bsms_query_allows_explicit_fallback_when_llm_not_required(
    api_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = _create_api_fixture(tmp_path / "forge_bsms_fallback.sqlite")
    monkeypatch.setattr(
        "mira.api.routers.forge.bsms_runtime.llm_status",
        lambda *, require_llm=None: {
            "provider": "anthropic",
            "configured": False,
            "enabled": False,
            "model": "claude-sonnet",
            "require_llm": False if require_llm is None else require_llm,
        },
    )

    response = api_client.post(
        "/api/forge/bsms/query",
        json={
            "query": "show supplier records",
            "database_url": db_url,
            "question_map": {
                "questions": [
                    {"id": "q1", "question": "Show supplier records", "question_type": "detail_view", "table": "suppliers"}
                ]
            },
            "bsms_pipeline": {
                "bouncer_config": {"domain_keywords": ["supplier"], "allowed_intents": ["detail_view"]},
                "parser_config": {"field_mappings": {"suppliers": ["supplier_name"]}},
            },
            "authority_pack": {},
            "require_llm": False,
            "persist_lineage": True,
            "lineage_dir": str(tmp_path / "lineage"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["rules"]["verdict"] == "SUPPORTED"
    assert payload["rules"]["payload"]["results"]["rows"]
    assert payload["parsed_intent"]["decision_source"] == "deterministic_parser"
    lineage_log = tmp_path / "lineage" / "decision_lineage.jsonl"
    assert lineage_log.exists()
    record = json.loads(lineage_log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["rendering_source"] == "deterministic_formatter"
    assert record["parsed_intent"]["decision_source"] == "deterministic_parser"


def test_forge_bsms_query_uses_llm_and_persists_lineage(
    api_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = _create_api_fixture(tmp_path / "forge_bsms_llm.sqlite")
    calls = iter(
        [
            ({"status": "accepted", "reason": None, "matched_intent": "detail_view", "risk_flags": [], "confidence": 0.97}, {"model": "claude-sonnet"}),
            (
                {
                    "question_id": "q1",
                    "filters": {"supplier_name": "North Fabrication"},
                    "confidence": 0.93,
                    "rationale": "Supplier query maps cleanly to the supplier detail question.",
                    "clarification_needed": False,
                    "clarification_question": None,
                },
                {"model": "claude-sonnet"},
            ),
            ({"answer": "North Fabrication is the matched supplier record.", "follow_up": None, "confidence_label": "high"}, {"model": "claude-sonnet"}),
        ]
    )

    monkeypatch.setattr(
        "mira.api.routers.forge.bsms_runtime.llm_status",
        lambda *, require_llm=None: {
            "provider": "anthropic",
            "configured": True,
            "enabled": True,
            "model": "claude-sonnet",
            "require_llm": True if require_llm is None else require_llm,
        },
    )
    monkeypatch.setattr("mira.api.routers.forge.bsms_runtime.complete_json", lambda *args, **kwargs: next(calls))

    response = api_client.post(
        "/api/forge/bsms/query",
        json={
            "query": "show supplier records for North Fabrication",
            "database_url": db_url,
            "question_map": {
                "questions": [
                    {
                        "id": "q1",
                        "question": "Show supplier records",
                        "question_type": "detail_view",
                        "table": "suppliers",
                        "target_columns": ["supplier_name"],
                    }
                ]
            },
            "bsms_pipeline": {
                "bouncer_config": {"domain_keywords": ["supplier", "fabrication"], "allowed_intents": ["detail_view"]},
                "parser_config": {"field_mappings": {"suppliers": ["supplier_name"]}},
            },
            "authority_pack": {},
            "require_llm": True,
            "persist_lineage": True,
            "lineage_dir": str(tmp_path / "lineage"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["bouncer"]["decision_source"] == "llm_bouncer"
    assert payload["parsed_intent"]["decision_source"] == "llm_parser"
    assert payload["answer"] == "North Fabrication is the matched supplier record."
    assert payload["rules"]["verdict"] == "SUPPORTED"
    assert payload["rules"]["payload"]["results"]["rows"]
    lineage_log = tmp_path / "lineage" / "decision_lineage.jsonl"
    assert lineage_log.exists()
    record = json.loads(lineage_log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["rendering_source"] == "llm_formatter"
    assert record["parsed_intent"]["filters"] == {"supplier_name": "North Fabrication"}


def test_forge_bsms_query_marks_speculative_cross_reference_unsupported(
    api_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = _create_api_fixture(tmp_path / "forge_bsms_cross_reference.sqlite")
    monkeypatch.setattr(
        "mira.api.routers.forge.bsms_runtime.llm_status",
        lambda *, require_llm=None: {
            "provider": "anthropic",
            "configured": False,
            "enabled": False,
            "model": "claude-sonnet",
            "require_llm": False if require_llm is None else require_llm,
        },
    )

    response = api_client.post(
        "/api/forge/bsms/query",
        json={
            "query": "find connections between suppliers and parts",
            "database_url": db_url,
            "question_map": {
                "questions": [
                    {
                        "id": "q1",
                        "question": "Find connections between suppliers and parts using matching IDs",
                        "question_type": "cross_reference",
                        "table": "suppliers",
                        "target_columns": ["supplier_id"],
                        "join_tables": ["parts"],
                    }
                ]
            },
            "bsms_pipeline": {
                "bouncer_config": {"domain_keywords": ["supplier", "part"], "allowed_intents": ["cross_reference"]},
                "parser_config": {"field_mappings": {"suppliers": ["supplier_name"]}},
            },
            "authority_pack": {},
            "require_llm": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unsupported"
    assert payload["rules"]["verdict"] == "UNSUPPORTED"
    assert "speculative cross-reference" in payload["answer"].lower()


def test_forge_bsms_query_executes_compiled_risk_ranking_plan(
    api_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = _create_h2_semantic_fixture(tmp_path / "forge_bsms_h2_risk.sqlite")
    monkeypatch.setattr(
        "mira.api.routers.forge.bsms_runtime.llm_status",
        lambda *, require_llm=None: {
            "provider": "anthropic",
            "configured": False,
            "enabled": False,
            "model": "claude-sonnet",
            "require_llm": False if require_llm is None else require_llm,
        },
    )

    response = api_client.post(
        "/api/forge/bsms/query",
        json={
            "query": "Which materials show severe hydrogen embrittlement and should be avoided?",
            "database_url": db_url,
            "question_map": {
                "questions": [
                    {
                        "id": "q1",
                        "question": "Which materials show severe hydrogen embrittlement and should be avoided?",
                        "question_type": "filter",
                        "table": "evidence",
                        "capability_id": "material_safety_ranking",
                        "intent_family": "risk_ranking",
                        "execution_plan": {
                            "capability_id": "material_safety_ranking",
                            "intent_family": "risk_ranking",
                            "plan_type": "risk_ranking",
                            "entity_table": "evidence",
                            "entity_key": "material_name",
                            "group_by": ["material_name", "material_family"],
                            "metrics": ["hee_index"],
                            "filters": ["reference_gas", "pressure_mpa", "heat_treatment", "product_form", "hee_band"],
                            "sort": [{"column": "hee_index", "direction": "asc"}],
                            "support_thresholds": {"min_rows": 3, "required_metric_non_null": ["hee_index"]},
                        },
                    }
                ]
            },
            "bsms_pipeline": {
                "bouncer_config": {"domain_keywords": ["hydrogen", "material", "embrittlement"], "allowed_intents": ["filter"]},
                "parser_config": {"field_mappings": {"evidence": ["material_name", "material_family", "reference_gas"]}},
            },
            "authority_pack": {},
            "require_llm": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["rules"]["verdict"] == "SUPPORTED"
    assert payload["rules"]["payload"]["results"]["mode"] == "risk_ranking"
    assert payload["rules"]["payload"]["results"]["rows"]


def test_forge_bsms_query_executes_compiled_property_degradation_plan(
    api_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = _create_h2_semantic_fixture(tmp_path / "forge_bsms_h2_degradation.sqlite")
    monkeypatch.setattr(
        "mira.api.routers.forge.bsms_runtime.llm_status",
        lambda *, require_llm=None: {
            "provider": "anthropic",
            "configured": False,
            "enabled": False,
            "model": "claude-sonnet",
            "require_llm": False if require_llm is None else require_llm,
        },
    )

    response = api_client.post(
        "/api/forge/bsms/query",
        json={
            "query": "How do fracture toughness and tensile strength degrade under hydrogen exposure?",
            "database_url": db_url,
            "question_map": {
                "questions": [
                    {
                        "id": "q1",
                        "question": "How do fracture toughness and tensile strength degrade under hydrogen exposure?",
                        "question_type": "comparison",
                        "table": "degradation_ratios",
                        "capability_id": "property_degradation_comparison",
                        "intent_family": "metric_comparison",
                        "execution_plan": {
                            "capability_id": "property_degradation_comparison",
                            "intent_family": "metric_comparison",
                            "plan_type": "property_degradation_comparison",
                            "entity_table": "degradation_ratios",
                            "group_by": ["ratio_type"],
                            "metrics": ["ratio_h2_over_ref", "degradation_pct"],
                            "filters": ["material", "form", "temper"],
                            "sort": [{"column": "ratio_type", "direction": "asc"}],
                            "support_thresholds": {"min_rows": 2, "required_metric_non_null": ["ratio_h2_over_ref", "degradation_pct"]},
                        },
                    }
                ]
            },
            "bsms_pipeline": {
                "bouncer_config": {"domain_keywords": ["hydrogen", "fracture", "tensile"], "allowed_intents": ["comparison"]},
                "parser_config": {"field_mappings": {"degradation_ratios": ["material", "form", "temper"]}},
            },
            "authority_pack": {},
            "require_llm": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["rules"]["verdict"] == "SUPPORTED"
    assert payload["rules"]["payload"]["results"]["mode"] == "property_degradation_comparison"
    assert payload["rules"]["payload"]["results"]["rows"]
