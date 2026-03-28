from __future__ import annotations

from pathlib import Path
from typing import Any

from unified.canonical_store import CanonicalStore
from unified.discovery.unified_discovery import DocumentInput, UnifiedDiscovery
from unified.materializer.materializer import RelationalMaterializer
from unified.materializer.store_writer import AthenaExtractionBundle, CanonicalStoreWriter
from unified.personality.unified_personality import UnifiedPersonalityEngine
from unified.schema import CompileRequest, CompileResult, ICChunk, ICDocument, QuerySource


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

    def compile(self, request: CompileRequest | dict[str, Any]) -> CompileResult:
        parsed = CompileRequest.model_validate(request)
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
                            features=feature,
                        ),
                        chunks=[
                            ICChunk(
                                chunk_id=f"{payload.doc_id}:chunk:0",
                                doc_id=payload.doc_id,
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
            canonical_record_count=self.store.audit_status()["record_count"],
            materialized_db_url=materialized_db_url,
            capabilities=capabilities,
            evaluation=self.last_regression,
            status="ok",
        )
        self.last_compile_result = result
        self.last_capabilities = capabilities
        return result

