from __future__ import annotations

import re
from typing import Any

from unified.canonical_store import CanonicalStore
from unified.schema import AuthorityClass, EvidenceSourceType, ICEvidenceItem, ICChunk, ICDocument, ProvenanceRecord


def _tokenize(text_value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", text_value.lower()) if len(token) >= 2]


class DocumentEvidenceProvider:
    def __init__(
        self,
        store: CanonicalStore | None = None,
        documents: list[ICDocument] | None = None,
        chunks: list[ICChunk] | None = None,
        compilation_id: str | None = None,
        module_name: str | None = None,
    ) -> None:
        self._store = store
        self._documents = documents or []
        self._chunks = chunks or []
        self._compilation_id = compilation_id
        self._module_name = module_name

    def _load_documents(self) -> tuple[dict[str, ICDocument], list[ICChunk]]:
        if self._store is not None:
            loaded_documents = self._store.list_records("document")
            loaded_chunks = self._store.list_records("chunk")
            documents = {
                document.doc_id: document
                for document in loaded_documents
                if self._matches_scope(document.module_name, document.compilation_id)
            }
            chunks = [
                chunk
                for chunk in loaded_chunks
                if self._matches_scope(chunk.module_name, chunk.compilation_id)
                and chunk.doc_id in documents
            ]
            return documents, chunks
        documents = {
            document.doc_id: document
            for document in self._documents
            if self._matches_scope(document.module_name, document.compilation_id)
        }
        chunks = [
            chunk
            for chunk in self._chunks
            if self._matches_scope(chunk.module_name, chunk.compilation_id)
            and chunk.doc_id in documents
        ]
        return documents, chunks

    def _matches_scope(self, module_name: str | None, compilation_id: str | None) -> bool:
        if self._compilation_id is not None and compilation_id != self._compilation_id:
            return False
        if self._module_name is not None and module_name != self._module_name:
            return False
        return True

    def get_evidence(self, query: str, limit: int = 20, intent: str | None = None) -> list[ICEvidenceItem]:
        query_terms = set(_tokenize(query))
        documents, chunks = self._load_documents()
        evidence: list[ICEvidenceItem] = []

        for chunk in chunks:
            terms = set(_tokenize(chunk.content_text))
            overlap = query_terms & terms
            if not overlap:
                continue

            document = documents.get(chunk.doc_id)
            authority_class = AuthorityClass.UNKNOWN
            if "shall" in chunk.content_text.lower() or "must" in chunk.content_text.lower():
                authority_class = AuthorityClass.SPECIFICATION_REQUIREMENT
            elif "test" in chunk.content_text.lower():
                authority_class = AuthorityClass.PRIMARY_TEST_DATA

            evidence.append(
                ICEvidenceItem(
                    evidence_id=f"doc:{chunk.chunk_id}",
                    source_type=EvidenceSourceType.DOC,
                    source_label=document.doc_id if document else chunk.doc_id,
                    source_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    content=chunk.content_text,
                    snippet=chunk.content_text[:240],
                    score=min(1.0, len(overlap) / max(1, len(query_terms))),
                    authority_class=authority_class,
                    provenance=ProvenanceRecord(
                        source_doc_id=chunk.doc_id,
                        source_chunk_id=chunk.chunk_id,
                        page=chunk.page,
                        location=chunk.location,
                        extraction_method=chunk.extraction_method,
                        extraction_confidence=chunk.extraction_confidence,
                        extraction_model=chunk.extraction_model,
                        authority_class=authority_class,
                    ),
                    claim_key=(chunk.location or chunk.content_type),
                    claim_value=chunk.content_text[:80],
                    metadata={
                        "intent": intent,
                        "doc_hash": document.doc_hash if document else None,
                        "source_path": document.source_path if document else None,
                    },
                )
            )

        evidence.sort(key=lambda item: item.score, reverse=True)
        return evidence[:limit]
