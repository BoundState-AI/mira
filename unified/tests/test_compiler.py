from __future__ import annotations

import sqlite3
from pathlib import Path

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

