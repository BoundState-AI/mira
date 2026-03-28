from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from unified._compat import import_gptl_feature_extractor
from unified.discovery.capabilities import UnifiedCapabilities

feature_extractor_module = import_gptl_feature_extractor()
FeatureExtractor = feature_extractor_module.FeatureExtractor
RawDocument = feature_extractor_module.RawDocument


class DocumentInput(BaseModel):
    doc_id: str
    content: str
    title: str | None = None
    file_path: str | None = None
    file_type: str | None = None
    metadata: dict[str, Any] | None = None


class UnifiedDiscoveryResult(BaseModel):
    db_result: Any | None = None
    document_features: list[Any] = Field(default_factory=list)
    capabilities: UnifiedCapabilities = Field(default_factory=UnifiedCapabilities)


class UnifiedDiscovery:
    def __init__(self, feature_extractor: Any | None = None) -> None:
        self._feature_extractor = feature_extractor or FeatureExtractor()

    def discover_documents(self, documents: list[DocumentInput | dict[str, Any]]) -> list[Any]:
        features: list[Any] = []
        for document in documents:
            payload = DocumentInput.model_validate(document)
            raw = RawDocument(
                doc_id=payload.doc_id,
                content=payload.content,
                title=payload.title,
                file_path=payload.file_path,
                file_type=payload.file_type,
                metadata=payload.metadata,
            )
            features.append(
                self._feature_extractor.extract(
                    raw,
                    validate_with_llm=False,
                    detect_noise_with_llm=False,
                )
            )
        return features

    def discover_database(self, db_url: str, **kwargs: Any) -> Any:
        from mira.forge_claude.introspector.engine import introspect_database_full

        return introspect_database_full(db_url, **kwargs)

    def discover(
        self,
        db_url: str | None = None,
        documents: list[DocumentInput | dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> UnifiedDiscoveryResult:
        db_result = self.discover_database(db_url, **kwargs) if db_url else None
        document_features = self.discover_documents(documents or [])
        capabilities = UnifiedCapabilities.from_sources(db_result=db_result, document_features=document_features)
        return UnifiedDiscoveryResult(
            db_result=db_result,
            document_features=document_features,
            capabilities=capabilities,
        )

