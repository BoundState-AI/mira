from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from unified.audit.integrity import AuditIntegrityService
from unified.chat.context import SourceAwareModuleContextManager
from unified.compiler import CompileArtifact, ICCompiler
from unified.evidence.db_provider import DBEvidenceProvider
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.forge_contract_adapter import (
    ChatResponseV2,
    WorkspaceCapabilitiesResponse,
    WorkspaceSummary,
    build_chat_response,
    build_workspace_capabilities_response,
)
from unified.pipeline.pipeline import UnifiedPipeline
from unified.schema import CompileRequest, QueryRequest, QueryResult, QuerySource


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

    def _ensure_module_registered(module_name: str, source: QuerySource) -> None:
        if module_name not in context_manager.available_modules:
            context_manager.register_module(
                module_name,
                source=source,
                description=f"IC workspace for {source.value} intelligence.",
            )

    def _resolve_artifact(request: QueryRequest) -> CompileArtifact | None:
        if request.compilation_id:
            return compiler.get_artifact(request.compilation_id)
        if request.module_name:
            return compiler.latest_artifact(module_name=request.module_name)
        active = context_manager.active
        if active is not None:
            artifact = compiler.latest_artifact(module_name=active.module_name)
            if artifact is not None:
                return artifact
        return compiler.latest_artifact()

    def _resolve_artifact_reference(
        *,
        compilation_id: str | None = None,
        module_name: str | None = None,
        use_active_module: bool = True,
    ) -> CompileArtifact | None:
        if compilation_id:
            return compiler.get_artifact(compilation_id)
        if module_name:
            return compiler.latest_artifact(module_name=module_name)
        if use_active_module and context_manager.active is not None:
            artifact = compiler.latest_artifact(module_name=context_manager.active.module_name)
            if artifact is not None:
                return artifact
        return compiler.latest_artifact()

    def _pipeline_for_artifact(artifact: CompileArtifact) -> UnifiedPipeline:
        compiled_request = artifact.request
        db_provider = None
        doc_provider = None

        if compiled_request.source in (QuerySource.DB, QuerySource.HYBRID):
            db_url = artifact.result.materialized_db_url or compiled_request.db_url
            if db_url:
                db_provider = DBEvidenceProvider(db_url)

        if compiled_request.source in (QuerySource.DOCS, QuerySource.HYBRID) and store is not None:
            doc_provider = DocumentEvidenceProvider(
                store=store,
                compilation_id=artifact.compilation_id,
                module_name=artifact.result.module_name,
            )

        return UnifiedPipeline(
            db_provider=db_provider,
            doc_provider=doc_provider,
            bouncer=pipeline.bouncer,
            query_router=pipeline.query_router,
            merger=pipeline.merger,
            synthesis_engine=pipeline.synthesis_engine,
        )

    def _run_query(parsed: QueryRequest) -> QueryResult:
        artifact = _resolve_artifact(parsed)
        if artifact is not None:
            if parsed.workspace_version and parsed.workspace_version != artifact.workspace_version:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Requested workspace_version '{parsed.workspace_version}' does not match "
                        f"artifact version '{artifact.workspace_version}'."
                    ),
                )
            runtime_pipeline = _pipeline_for_artifact(artifact)
            result = runtime_pipeline.query(parsed)
            result.audit.update(
                {
                    "compilation_id": artifact.compilation_id,
                    "workspace_version": artifact.workspace_version,
                    "module_name": artifact.result.module_name,
                }
            )
            _ensure_module_registered(artifact.result.module_name, artifact.request.source)
            context_manager.switch_module(artifact.result.module_name)
            return result

        result = pipeline.query(parsed)
        active = context_manager.active
        if active is not None:
            result.audit.setdefault("module_name", active.module_name)
        return result

    @router.post("/compile")
    def compile_endpoint(request: CompileRequest) -> dict[str, Any]:
        result = compiler.compile(request)
        _ensure_module_registered(result.module_name, request.source)
        return result.model_dump(mode="json")

    @router.post("/chat/query", deprecated=True)
    def query_endpoint(request: QueryRequest) -> dict[str, Any]:
        parsed = QueryRequest.model_validate(request)
        result = _run_query(parsed)
        active = context_manager.active
        if active is not None:
            active.add_message("user", parsed.query)
            active.add_message("assistant", result.answer)
        return result.model_dump(mode="json")

    @router.post("/chat/stream", deprecated=True)
    def stream_endpoint(request: QueryRequest) -> StreamingResponse:
        parsed = QueryRequest.model_validate(request)
        result = _run_query(parsed)

        def _events():
            yield f"data: {json.dumps(result.model_dump(mode='json'))}\n\n"

        return StreamingResponse(_events(), media_type="text/event-stream")

    @router.post("/v2/chat/query", response_model=ChatResponseV2)
    def query_v2_endpoint(request: QueryRequest) -> dict[str, Any]:
        parsed = QueryRequest.model_validate(request)
        result = _run_query(parsed)
        artifact = _resolve_artifact(parsed)
        workspace_version = artifact.workspace_version if artifact is not None else (
            parsed.workspace_version or "unknown"
        )
        response = build_chat_response(query_result=result, workspace_version=workspace_version)
        active = context_manager.active
        if active is not None:
            active.add_message("user", parsed.query)
            active.add_message("assistant", response.answer)
        return response.model_dump(mode="json")

    @router.post("/v2/chat/stream")
    def stream_v2_endpoint(request: QueryRequest) -> StreamingResponse:
        parsed = QueryRequest.model_validate(request)
        result = _run_query(parsed)
        artifact = _resolve_artifact(parsed)
        workspace_version = artifact.workspace_version if artifact is not None else (
            parsed.workspace_version or "unknown"
        )
        response = build_chat_response(query_result=result, workspace_version=workspace_version)

        def _events():
            yield f"data: {json.dumps({'done': True, 'response': response.model_dump(mode='json')})}\n\n"

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

    @router.get("/capabilities", deprecated=True)
    def capabilities(compilation_id: str | None = None, module_name: str | None = None) -> dict[str, Any]:
        artifact = _resolve_artifact_reference(compilation_id=compilation_id, module_name=module_name)
        return artifact.result.capabilities if artifact is not None else {}

    @router.get("/v2/status", response_model=WorkspaceSummary)
    def status_v2(compilation_id: str | None = None, module_name: str | None = None) -> dict[str, Any]:
        artifact = _resolve_artifact_reference(compilation_id=compilation_id, module_name=module_name)
        if artifact is None:
            raise HTTPException(status_code=404, detail="No compiled IC workspace available")
        return artifact.result.workspace_summary

    @router.get("/v2/capabilities", response_model=WorkspaceCapabilitiesResponse)
    def capabilities_v2(compilation_id: str | None = None, module_name: str | None = None) -> dict[str, Any]:
        artifact = _resolve_artifact_reference(compilation_id=compilation_id, module_name=module_name)
        if artifact is None:
            raise HTTPException(status_code=404, detail="No compiled IC workspace available")
        summary = WorkspaceSummary.model_validate(artifact.result.workspace_summary)
        response = build_workspace_capabilities_response(summary)
        return response.model_dump(mode="json")

    @router.get("/v2/artifacts")
    def list_artifacts(module_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return [
            artifact.result.model_dump(mode="json")
            for artifact in compiler.list_artifacts(module_name=module_name, limit=limit)
        ]

    @router.get("/v2/artifacts/{compilation_id}")
    def artifact_detail(compilation_id: str) -> dict[str, Any]:
        artifact = compiler.get_artifact(compilation_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Unknown compilation artifact")
        return artifact.result.model_dump(mode="json")

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
