from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from unified.canonical_store import CanonicalStore
from unified.chat.context import SourceAwareModuleContextManager
from unified.chat.routes import create_router
from unified.compiler import ICCompiler
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.pipeline.pipeline import UnifiedPipeline
from unified.schema import ICChunk, ICDocument


def test_chat_routes_expose_query_modules_and_health() -> None:
    store = CanonicalStore()
    store.insert_document(
        ICDocument(
            doc_id="doc-1",
            doc_hash="hash-1",
            source_path="/tmp/doc-1.pdf",
            source_type="pdf",
        )
    )
    store.insert_chunk(
        ICChunk(
            chunk_id="chunk-1",
            doc_id="doc-1",
            content_text="Titanium shall have strength of 42 MPa.",
            content_type="text",
            extraction_method="manual",
            extraction_confidence=1.0,
        )
    )

    context = SourceAwareModuleContextManager()
    context.register_module("default")
    pipeline = UnifiedPipeline(doc_provider=DocumentEvidenceProvider(store=store))
    compiler = ICCompiler(store=store)

    app = FastAPI()
    app.include_router(create_router(pipeline=pipeline, compiler=compiler, context_manager=context, store=store))
    client = TestClient(app)

    response = client.post("/ic/chat/query", json={"query": "Titanium strength", "source": "docs"})
    modules = client.get("/ic/chat/modules")
    health = client.get("/ic/health")
    verify = client.get("/ic/audit/verify")

    assert response.status_code == 200
    assert response.json()["citations"]
    assert modules.json()["active"] == "default"
    assert health.json()["status"] == "ok"
    assert verify.json()["valid"] is True


def test_compile_endpoint_updates_runtime_for_follow_on_queries() -> None:
    store = CanonicalStore()
    context = SourceAwareModuleContextManager()
    pipeline = UnifiedPipeline()
    compiler = ICCompiler(store=store)

    app = FastAPI()
    app.include_router(create_router(pipeline=pipeline, compiler=compiler, context_manager=context, store=store))
    client = TestClient(app)

    compile_response = client.post(
        "/ic/compile",
        json={
            "source": "docs",
            "module_name": "mission-docs",
            "documents": [
                {
                    "doc_id": "doc-1",
                    "content": "Titanium shall be tested per NASA-STD-6016 before acceptance.",
                    "file_type": "pdf",
                    "file_path": "/tmp/doc-1.pdf",
                }
            ],
        },
    )
    query_response = client.post(
        "/ic/chat/query",
        json={"query": "What does the document require for titanium?", "source": "docs"},
    )
    modules_response = client.get("/ic/chat/modules")

    assert compile_response.status_code == 200
    assert query_response.status_code == 200
    assert query_response.json()["citations"]
    assert modules_response.json()["active"] == "mission-docs"
