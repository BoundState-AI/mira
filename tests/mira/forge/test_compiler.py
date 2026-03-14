#!/usr/bin/env python3
"""Tests for the additive FORGE compiler."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mira.forge.compiler import ForgeCompiler
from mira.forge.differ import diff_schema_manifests
from mira.forge.models import ForgeCompileRequest


def _build_fixture_db(db_path: Path) -> str:
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    cursor.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            status TEXT,
            total_amount REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE materials (
            material_code TEXT PRIMARY KEY,
            material_name TEXT NOT NULL
        );

        CREATE TABLE test_results (
            id INTEGER PRIMARY KEY,
            material_code TEXT NOT NULL,
            tensile_strength_mpa REAL,
            recorded_at TEXT NOT NULL,
            notes TEXT
        );
        """
    )

    cursor.executemany(
        "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
        [
            (1, "ana@example.com", "2026-03-01T12:00:00"),
            (2, "ben@example.com", "2026-03-02T12:00:00"),
        ],
    )
    cursor.executemany(
        "INSERT INTO orders (id, user_id, status, total_amount) VALUES (?, ?, ?, ?)",
        [
            (10, 1, "submitted", 120.5),
            (11, 1, None, 220.0),
            (12, 2, "approved", 75.25),
        ],
    )
    cursor.executemany(
        "INSERT INTO materials (material_code, material_name) VALUES (?, ?)",
        [
            ("A286", "A286 CRES"),
            ("IN718", "Inconel 718"),
            ("SS316L", "316L Stainless"),
        ],
    )
    cursor.executemany(
        "INSERT INTO test_results (id, material_code, tensile_strength_mpa, recorded_at, notes) VALUES (?, ?, ?, ?, ?)",
        [
            (100, "A286", 896.0, "2026-01-01T00:00:00", "baseline"),
            (101, "IN718", 1240.0, "2026-01-02T00:00:00", None),
            (102, "SS316L", 515.0, "2026-01-03T00:00:00", None),
        ],
    )

    connection.commit()
    connection.close()
    return f"sqlite:///{db_path}"


def test_forge_compiler_generates_core_artifacts(tmp_path: Path) -> None:
    db_url = _build_fixture_db(tmp_path / "forge_fixture.sqlite")
    compiler = ForgeCompiler()

    response = compiler.compile_database(
        ForgeCompileRequest(
            database_url=db_url,
            app_name="Fixture Forge",
            sample_rows_per_table=25,
        )
    )

    assert response.status == "ok"
    assert response.summary.table_count == 4
    assert response.summary.relationship_count >= 2
    assert "orders" in response.semantic_map["tables"]
    assert "test_results" in response.capabilities["table_capabilities"]
    assert response.capabilities["table_capabilities"]["test_results"]["supported_operations"]
    assert any(
        relationship["discovery_method"] == "explicit_foreign_key"
        for relationship in response.relationship_graph["relationships"]
    )
    assert any(
        {"materials", "test_results"} == {relationship["source_table"], relationship["target_table"]}
        and relationship["discovery_method"] in {"statistical_key_matching", "latent_entropy"}
        for relationship in response.relationship_graph["relationships"]
    )
    assert any(
        question["question_type"] == "time_series"
        and question["table"] == "test_results"
        for question in response.question_map["questions"]
    )
    assert response.relationship_graph["graph_nodes"]
    assert response.relationship_graph["answerable_paths"]
    assert response.relationship_graph["join_depth_policy"]["default_depth"] == 2
    assert response.question_map["question_type_counts"]["relationship"] >= 1
    assert "question" in {field["name"] for field in response.lineage_schema["fields"]}
    assert response.bsms_pipeline["llm_runtime"]["provider"] == "anthropic"
    assert response.generated_bundle is not None
    assert Path(response.generated_bundle.backend_dir, "app.py").exists()
    assert Path(response.generated_bundle.backend_dir, "llm.py").exists()
    assert Path(response.generated_bundle.frontend_dir, "src", "App.jsx").exists()
    assert Path(response.generated_bundle.authority_pack_dir, "parser", "field_mappings.json").exists()
    assert Path(response.generated_bundle.bsms_pipeline_dir, "pipeline_config.json").exists()
    assert Path(response.generated_bundle.backend_dir, "query_service.py").exists()
    assert Path(response.generated_bundle.backend_dir, "routers", "generated.py").exists()
    assert Path(response.generated_bundle.backend_dir, "bsms", "service.py").exists()
    assert Path(response.generated_bundle.backend_dir, "tests", "test_health.py").exists()
    assert Path(response.generated_bundle.frontend_dir, "src", "pages", "Home.jsx").exists()
    assert Path(response.generated_bundle.frontend_dir, "src", "pages", "Admin.jsx").exists()
    assert Path(response.generated_bundle.app_dir, ".github", "workflows", "generated-ci.yml").exists()


def test_forge_compiler_can_persist_artifacts(tmp_path: Path) -> None:
    db_url = _build_fixture_db(tmp_path / "persist_fixture.sqlite")
    compiler = ForgeCompiler()

    response = compiler.compile_database(
        ForgeCompileRequest(
            database_url=db_url,
            app_name="Persisted Forge",
            sample_rows_per_table=20,
            persist_artifacts=True,
            output_dir=str(tmp_path / "artifacts"),
        )
    )

    assert response.output_dir is not None
    artifact_dir = Path(response.output_dir)
    assert (artifact_dir / "artifacts" / "schema_manifest.json").exists()
    assert (artifact_dir / "artifacts" / "authority_pack.json").exists()
    assert response.generated_bundle is not None
    assert (Path(response.generated_bundle.app_dir) / "README.md").exists()
    backend_text = Path(response.generated_bundle.backend_dir, "app.py").read_text(encoding="utf-8")
    assert "forge-generated-app" in backend_text
    assert "/api/audit" in backend_text
    llm_runtime = Path(response.generated_bundle.backend_dir, "llm.py").read_text(encoding="utf-8")
    assert "FORGE_BSMS_ENABLE_LLM" in llm_runtime
    assert "ANTHROPIC_API_KEY" in llm_runtime
    query_service = Path(response.generated_bundle.backend_dir, "query_service.py").read_text(encoding="utf-8")
    assert "execute_question" in query_service
    assert "candidate_questions" in query_service
    assert "join_path" in query_service
    requirements = Path(response.generated_bundle.backend_dir, "requirements.txt").read_text(encoding="utf-8")
    assert "anthropic>=" in requirements
    frontend_home = Path(response.generated_bundle.frontend_dir, "src", "pages", "Home.jsx").read_text(encoding="utf-8")
    assert "runBSMS" in frontend_home


def test_forge_schema_diff_reports_changes() -> None:
    old_manifest = {
        "tables": [
            {
                "qualified_name": "users",
                "columns": [{"name": "id", "data_type": "integer"}],
            }
        ]
    }
    new_manifest = {
        "tables": [
            {
                "qualified_name": "users",
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "email", "data_type": "text"},
                ],
            },
            {
                "qualified_name": "orders",
                "columns": [{"name": "id", "data_type": "integer"}],
            },
        ]
    }

    diff = diff_schema_manifests(old_manifest, new_manifest)

    assert any(change["change_type"] == "table_added" and change["table"] == "orders" for change in diff["changes"])
    assert any(change["change_type"] == "column_added" and change["column"] == "email" for change in diff["changes"])
    assert "def upgrade():" in diff["alembic_stub"]


# ---------------------------------------------------------------------------
# Bug-fix coverage: issues found in FORGE audit (2026-03-14)
# ---------------------------------------------------------------------------


def test_unsupported_dialect_raises_value_error() -> None:
    compiler = ForgeCompiler()
    with pytest.raises(ValueError, match="Unsupported database dialect"):
        compiler.compile_database(
            ForgeCompileRequest(
                database_url="mssql://localhost/testdb",
                app_name="Dialect Test",
            )
        )


def test_remote_database_blocked_by_default() -> None:
    compiler = ForgeCompiler()
    with pytest.raises(ValueError, match="Remote database URLs are disabled"):
        compiler.compile_database(
            ForgeCompileRequest(
                database_url="postgresql://some-cloud-host.rds.amazonaws.com/prod",
                app_name="Remote Test",
            )
        )


def test_empty_database_compiles_with_warning(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"
    sqlite3.connect(db_path).close()
    db_url = f"sqlite:///{db_path}"
    compiler = ForgeCompiler()

    response = compiler.compile_database(
        ForgeCompileRequest(
            database_url=db_url,
            app_name="Empty DB",
        )
    )

    assert response.status == "ok"
    assert response.summary.table_count == 0
    assert any("no user tables" in w.lower() for w in response.warnings)


def test_max_generated_questions_cap_is_respected(tmp_path: Path) -> None:
    db_url = _build_fixture_db(tmp_path / "cap_fixture.sqlite")
    compiler = ForgeCompiler()

    response = compiler.compile_database(
        ForgeCompileRequest(
            database_url=db_url,
            app_name="Cap Test",
            sample_rows_per_table=10,
            max_generated_questions=5,
        )
    )

    assert response.status == "ok"
    assert len(response.question_map["questions"]) <= 5


def test_max_questions_per_table_cap_is_respected(tmp_path: Path) -> None:
    db_url = _build_fixture_db(tmp_path / "per_table_fixture.sqlite")
    compiler = ForgeCompiler()

    response = compiler.compile_database(
        ForgeCompileRequest(
            database_url=db_url,
            app_name="Per Table Cap Test",
            sample_rows_per_table=10,
            max_questions_per_table=2,
        )
    )

    assert response.status == "ok"
    from collections import Counter
    table_counts = Counter(q["table"] for q in response.question_map["questions"])
    for table, count in table_counts.items():
        assert count <= 2, f"Table {table} has {count} questions, expected <= 2"


def test_progress_callback_fires_during_real_compile(tmp_path: Path) -> None:
    db_url = _build_fixture_db(tmp_path / "progress_fixture.sqlite")
    compiler = ForgeCompiler()
    events: list[tuple[str, str, float]] = []

    response = compiler.compile_database(
        ForgeCompileRequest(
            database_url=db_url,
            app_name="Progress Test",
            sample_rows_per_table=10,
        ),
        progress_callback=lambda stage, message, progress: events.append((stage, message, progress)),
    )

    assert response.status == "ok"
    assert len(events) >= 4, f"Expected at least 4 progress events, got {len(events)}"
    stages = [e[0] for e in events]
    assert "introspection" in stages
    assert "question_generation" in stages
    assert all(0.0 <= e[2] <= 100.0 for e in events)


def test_question_id_collision_resistance() -> None:
    compiler = ForgeCompiler()
    # Two questions that differ only after character 96 in their slugified form
    prefix = "a" * 90
    id_a = compiler._question_id("table", "filter", prefix + "_suffix_alpha")
    id_b = compiler._question_id("table", "filter", prefix + "_suffix_bravo")
    assert id_a != id_b, (
        f"Question IDs collided despite different inputs: {id_a!r}"
    )


def test_require_llm_refinement_emits_warning(tmp_path: Path) -> None:
    db_url = _build_fixture_db(tmp_path / "llm_warn_fixture.sqlite")
    compiler = ForgeCompiler()

    response = compiler.compile_database(
        ForgeCompileRequest(
            database_url=db_url,
            app_name="LLM Warn Test",
            sample_rows_per_table=10,
            require_llm_refinement=True,
        )
    )

    assert response.status == "ok"
    assert any("llm refinement" in w.lower() for w in response.warnings)
