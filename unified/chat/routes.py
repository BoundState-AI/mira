from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from unified.audit.integrity import AuditIntegrityService
from unified.chat.context import SourceAwareModuleContextManager
from unified.compiler import ICCompiler
from unified.evidence.db_provider import DBEvidenceProvider
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.pipeline.pipeline import UnifiedPipeline
from unified.schema import CompileRequest, QueryRequest, QuerySource


def create_router(
    pipeline: UnifiedPipeline,
    compiler: ICCompiler | None = None,
    context_manager: SourceAwareModuleContextManager | None = None,
    audit_service: AuditIntegrityService | None = None,
    store=None,
    evaluator=None,
) -> APIRouter:
    compiler = compiler or ICCompiler(store=store)
    context_manager = context_manager or SourceAwareModuleContextManager()
    if not context_manager.available_modules:
        context_manager.register_module("default")
    audit_service = audit_service or AuditIntegrityService()

    router = APIRouter(prefix="/ic", tags=["ic"])

    def _sync_runtime(compiled_request: CompileRequest) -> None:
        if compiled_request.source in (QuerySource.DOCS, QuerySource.HYBRID) and store is not None:
            pipeline.doc_provider = DocumentEvidenceProvider(store=store)
        else:
            pipeline.doc_provider = None

        db_url = None
        if compiled_request.source in (QuerySource.DB, QuerySource.HYBRID):
            last_materialized_db_url = compiler.last_compile_result.materialized_db_url if compiler.last_compile_result else None
            db_url = compiled_request.db_url or last_materialized_db_url

        if db_url:
            pipeline.db_provider = DBEvidenceProvider(db_url)
        else:
            pipeline.db_provider = None

        if compiled_request.module_name not in context_manager.available_modules:
            context_manager.register_module(
                compiled_request.module_name,
                source=compiled_request.source,
                description=f"IC workspace for {compiled_request.source.value} intelligence.",
            )
        context_manager.switch_module(compiled_request.module_name)

    @router.post("/compile")
    def compile_endpoint(request: CompileRequest) -> dict[str, Any]:
        result = compiler.compile(request)
        _sync_runtime(request)
        return result.model_dump(mode="json")

    @router.post("/chat/query")
    def query_endpoint(request: QueryRequest) -> dict[str, Any]:
        result = pipeline.query(request)
        active = context_manager.active
        if active is not None:
            active.add_message("user", request.query)
            active.add_message("assistant", result.answer)
        return result.model_dump(mode="json")

    @router.post("/chat/stream")
    def stream_endpoint(request: QueryRequest) -> StreamingResponse:
        result = pipeline.query(request)

        def _events():
            yield f"data: {json.dumps(result.model_dump(mode='json'))}\n\n"

        return StreamingResponse(_events(), media_type="text/event-stream")

    @router.get("/chat/modules")
    def list_modules() -> dict[str, Any]:
        return {
            "active": context_manager.active.module_name if context_manager.active else None,
            "modules": context_manager.available_modules,
        }

    @router.post("/chat/modules/{name}/activate")
    def activate_module(name: str) -> dict[str, Any]:
        try:
            module = context_manager.switch_module(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown module: {name}") from exc
        return module.model_dump(mode="json")

    @router.get("/capabilities")
    def capabilities() -> dict[str, Any]:
        return compiler.last_capabilities

    @router.get("/sources")
    def sources() -> dict[str, Any]:
        return {
            "db": pipeline.db_provider is not None,
            "docs": pipeline.doc_provider is not None,
            "hybrid": pipeline.db_provider is not None and pipeline.doc_provider is not None,
        }

    @router.get("/provenance/{fact_id}")
    def provenance(fact_id: str) -> list[dict[str, Any]]:
        if store is None:
            return []
        return [edge.model_dump(mode="json") for edge in store.provenance_chain(fact_id)]

    @router.get("/audit")
    def audit() -> dict[str, Any]:
        return store.audit_status() if store is not None else {}

    @router.get("/audit/verify")
    def audit_verify() -> dict[str, Any]:
        return audit_service.verify(store) if store is not None else {}

    @router.get("/eval/metrics")
    def eval_metrics() -> dict[str, Any]:
        return evaluator.current_metrics() if evaluator else {}

    @router.get("/eval/regression")
    def eval_regression() -> dict[str, Any]:
        return evaluator.last_report() if evaluator else compiler.last_regression

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return router
