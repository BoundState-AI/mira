from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from unified.canonical_store import CanonicalStore
from unified.discovery.unified_discovery import DocumentInput, UnifiedDiscovery
from unified.forge_contract_adapter import (
    build_capability_families,
    build_workspace_summary,
)
from unified.materializer.materializer import RelationalMaterializer
from unified.materializer.store_writer import AthenaExtractionBundle, CanonicalStoreWriter
from unified.personality.unified_personality import UnifiedPersonalityEngine
from unified.schema import CompilationArtifactRecord, CompileRequest, CompileResult, ICChunk, ICDocument, QuerySource


@dataclass(slots=True)
class CompileArtifact:
    compilation_id: str
    workspace_version: str
    request: CompileRequest
    result: CompileResult


class ICCompiler:
    def __init__(
        self,
        store: CanonicalStore | None = None,
        discovery: UnifiedDiscovery | None = None,
        personality_engine: UnifiedPersonalityEngine | None = None,
    ) -> None:
        self.store = store or CanonicalStore()
        self.discovery = discovery or UnifiedDiscovery()
        self.personality_engine = personality_engine or UnifiedPersonalityEngine()
        self.last_compile_result: CompileResult | None = None
        self.last_capabilities: dict[str, Any] = {}
        self.last_regression: dict[str, Any] = {}
        self._artifacts: dict[str, CompileArtifact] = {}
        self._latest_artifact_id: str | None = None

    def compile(self, request: CompileRequest | dict[str, Any]) -> CompileResult:
        parsed = CompileRequest.model_validate(request)
        compilation_id = uuid4().hex
        compiled_at = datetime.utcnow()
        workspace_version = f"{parsed.module_name}:{compiled_at.strftime('%Y%m%d%H%M%S')}:{compilation_id[:8]}"
        documents = [DocumentInput.model_validate(document) for document in parsed.documents]
        discovery_result = self.discovery.discover(
            db_url=parsed.db_url if parsed.source in (QuerySource.DB, QuerySource.HYBRID) and parsed.db_url else None,
            documents=documents,
        )

        if documents:
            writer = CanonicalStoreWriter(self.store)
            for payload, feature in zip(documents, discovery_result.document_features, strict=False):
                writer.write_bundle(
                    AthenaExtractionBundle(
                        document=ICDocument(
                            doc_id=payload.doc_id,
                            doc_hash=feature.doc_hash,
                            source_path=payload.file_path or payload.doc_id,
                            source_type=(payload.file_type or "pdf"),
                            module_name=parsed.module_name,
                            compilation_id=compilation_id,
                            features=feature,
                        ),
                        chunks=[
                            ICChunk(
                                chunk_id=f"{payload.doc_id}:chunk:0",
                                doc_id=payload.doc_id,
                                module_name=parsed.module_name,
                                compilation_id=compilation_id,
                                content_text=payload.content,
                                content_type="text",
                                extraction_method="athena_text",
                                extraction_confidence=1.0,
                            )
                        ],
                    )
                )

        materialized_db_url = parsed.materialized_db_url
        if parsed.materialize:
            materialized_db_url = materialized_db_url or f"sqlite:///{Path.cwd() / 'ic_materialized.db'}"
            RelationalMaterializer(self.store).materialize(materialized_db_url)

        personality = self.personality_engine.derive(discovery_result.capabilities)
        capabilities = discovery_result.capabilities.model_dump(mode="json")
        capabilities["personality"] = personality.model_dump(mode="json")

        result = CompileResult(
            source=parsed.source,
            compilation_id=compilation_id,
            workspace_version=workspace_version,
            module_name=parsed.module_name,
            compiled_at=compiled_at,
            canonical_record_count=self.store.audit_status()["record_count"],
            materialized_db_url=materialized_db_url,
            capabilities=capabilities,
            evaluation=self.last_regression,
            status="ok",
        )
        workspace_summary = build_workspace_summary(
            module_name=parsed.module_name,
            workspace_version=workspace_version,
            compiled_at=compiled_at.isoformat(),
            source=parsed.source.value,
            capabilities=capabilities,
            canonical_record_count=result.canonical_record_count,
            materialized_db_url=materialized_db_url,
            status=result.status,
        )
        result.workspace_summary = workspace_summary.model_dump(mode="json")
        result.capability_families = [
            family.model_dump(mode="json")
            for family in build_capability_families(capabilities)
        ]
        persisted = self.store.save_compilation_artifact(parsed, result)
        self._cache_artifact_record(persisted, mark_latest=True)
        return result

    def get_artifact(self, compilation_id: str) -> CompileArtifact | None:
        cached = self._artifacts.get(compilation_id)
        if cached is not None:
            return cached
        persisted = self.store.fetch_compilation_artifact(compilation_id)
        if persisted is None:
            return None
        return self._cache_artifact_record(persisted)

    def latest_artifact(self, module_name: str | None = None) -> CompileArtifact | None:
        if module_name is None:
            if self._latest_artifact_id:
                cached = self._artifacts.get(self._latest_artifact_id)
                if cached is not None:
                    return cached
            persisted = self.store.latest_compilation_artifact()
            if persisted is None:
                return None
            return self._cache_artifact_record(persisted, mark_latest=True)
        for artifact in reversed(list(self._artifacts.values())):
            if artifact.result.module_name == module_name:
                return artifact
        persisted = self.store.latest_compilation_artifact(module_name=module_name)
        if persisted is None:
            return None
        return self._cache_artifact_record(persisted)

    def list_artifacts(self, module_name: str | None = None, limit: int = 20) -> list[CompileArtifact]:
        persisted = self.store.list_compilation_artifacts(module_name=module_name, limit=limit)
        return [self._cache_artifact_record(record) for record in persisted]

    def _cache_artifact_record(
        self,
        record: CompilationArtifactRecord,
        *,
        mark_latest: bool = False,
    ) -> CompileArtifact:
        artifact = CompileArtifact(
            compilation_id=record.compilation_id,
            workspace_version=record.workspace_version,
            request=record.request,
            result=record.result,
        )
        self._artifacts[artifact.compilation_id] = artifact
        if mark_latest:
            self._latest_artifact_id = artifact.compilation_id
        self.last_compile_result = artifact.result
        self.last_capabilities = artifact.result.capabilities
        return artifact
