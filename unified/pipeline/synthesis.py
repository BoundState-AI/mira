from __future__ import annotations

import hashlib
from datetime import datetime

from cachetools import TTLCache

from unified.schema import AUTHORITY_BOUNDARY_TEXT, MergedEvidence, QueryRequest, QueryResult, QueryRoute


class UnifiedSynthesisEngine:
    def __init__(self, cache_ttl_seconds: int = 24 * 60 * 60, cache_size: int = 256) -> None:
        self._cache = TTLCache(maxsize=cache_size, ttl=cache_ttl_seconds)

    def synthesize(self, request: QueryRequest, route: QueryRoute, merged: MergedEvidence) -> QueryResult:
        cache_key = self._cache_key(request, route, merged)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(
                deep=True,
                update={"audit": {**cached.audit, "cache_hit": True, "cached_at": datetime.utcnow().isoformat()}},
            )

        citations = merged.items
        if not citations:
            result = QueryResult(
                query=request.query,
                route=route,
                answer="Insufficient evidence to answer from the active sources.",
                confidence=0.0,
                citations=[],
                conflicts=[],
                insufficient_evidence=True,
                authority_boundary=AUTHORITY_BOUNDARY_TEXT,
                audit={"cache_hit": False, "source_counts": merged.source_counts},
            )
            self._cache[cache_key] = result
            return result

        source_labels = ", ".join(sorted({item.source_type.value for item in citations}))
        top_snippets = " ".join(item.snippet for item in citations[:2])
        conflict_note = ""
        confidence_penalty = 0.0
        if merged.conflicts:
            conflict_note = f" Conflicts detected: {merged.conflicts[0].description}"
            confidence_penalty = min(0.4, 0.15 * len(merged.conflicts))

        confidence = min(
            0.95,
            max(
                0.15,
                0.35
                + (0.1 * min(len(citations), 4))
                + (0.1 * min(len(merged.source_counts), 2))
                - confidence_penalty,
            ),
        )

        result = QueryResult(
            query=request.query,
            route=route,
            answer=f"Using {source_labels} evidence, the strongest support is: {top_snippets}.{conflict_note}".strip(),
            confidence=confidence,
            citations=citations,
            conflicts=merged.conflicts,
            authority_boundary=AUTHORITY_BOUNDARY_TEXT,
            insufficient_evidence=False,
            audit={"cache_hit": False, "source_counts": merged.source_counts},
        )
        self._cache[cache_key] = result
        return result

    @staticmethod
    def _cache_key(request: QueryRequest, route: QueryRoute, merged: MergedEvidence) -> str:
        payload = "|".join(
            [
                request.query,
                request.source.value,
                route.value,
                ",".join(item.evidence_id for item in merged.items),
                ",".join(conflict.conflict_id for conflict in merged.conflicts),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

