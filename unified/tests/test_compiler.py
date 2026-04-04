from __future__ import annotations

import sqlite3
from pathlib import Path

from unified.canonical_store import CanonicalStore
from unified.compiler import ICCompiler
from unified.schema import CompileRequest, QuerySource


def test_compiler_ingests_docs_and_materializes(tmp_path: Path) -> None:
    target = tmp_path / "compiled.db"
    compiler = ICCompiler()
    result = compiler.compile(
        CompileRequest(
            source=QuerySource.DOCS,
            materialize=True,
            materialized_db_url=f"sqlite:///{target}",
            documents=[
                {
                    "doc_id": "doc-1",
                    "content": "Titanium shall be tested per NASA-STD-6016.",
                    "file_type": "pdf",
                    "file_path": "/tmp/doc-1.pdf",
                }
            ],
        )
    )

    connection = sqlite3.connect(target)
    count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    connection.close()

    assert result.materialized_db_url == f"sqlite:///{target}"
    assert result.canonical_record_count > 0
    assert count == 1
    assert result.compilation_id
    assert result.workspace_version
    assert result.module_name == "default"


def test_compiler_restores_artifact_from_canonical_store(tmp_path: Path) -> None:
    store_url = f"sqlite:///{tmp_path / 'canonical.db'}"
    compiler = ICCompiler(store=CanonicalStore(db_url=store_url))
    result = compiler.compile(
        CompileRequest(
            source=QuerySource.DOCS,
            module_name="restore-docs",
            documents=[
                {
                    "doc_id": "doc-restore-1",
                    "content": "Restore path requires artifact-scoped persistence.",
                    "file_type": "pdf",
                    "file_path": "/tmp/restore.pdf",
                }
            ],
        )
    )

    reloaded = ICCompiler(store=CanonicalStore(db_url=store_url))
    artifact = reloaded.get_artifact(result.compilation_id)
    latest = reloaded.latest_artifact(module_name="restore-docs")

    assert artifact is not None
    assert artifact.compilation_id == result.compilation_id
    assert artifact.workspace_version == result.workspace_version
    assert artifact.result.workspace_summary["workspace_id"] == "restore-docs"
    assert latest is not None
    assert latest.compilation_id == result.compilation_id
