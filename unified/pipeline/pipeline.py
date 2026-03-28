from __future__ import annotations

from typing import Any

from unified.evidence.merger import EvidenceMerger
from unified.pipeline.bouncer import UnifiedBouncer
from unified.pipeline.query_router import QueryRouter
from unified.pipeline.synthesis import UnifiedSynthesisEngine
from unified.schema import QueryRequest, QueryResult, QueryRoute


class UnifiedPipeline:
    def __init__(
        self,
        db_provider: Any | None = None,
        doc_provider: Any | None = None,
        bouncer: UnifiedBouncer | None = None,
        query_router: QueryRouter | None = None,
        merger: EvidenceMerger | None = None,
        synthesis_engine: UnifiedSynthesisEngine | None = None,
    ) -> None:
        self.db_provider = db_provider
        self.doc_provider = doc_provider
        self.bouncer = bouncer or UnifiedBouncer()
        self.query_router = query_router or QueryRouter()
        self.merger = merger or EvidenceMerger()
        self.synthesis_engine = synthesis_engine or UnifiedSynthesisEngine()

    def query(self, request: QueryRequest | dict[str, Any]) -> QueryResult:
        parsed = QueryRequest.model_validate(request)
        bouncer = self.bouncer.evaluate(parsed.query)
        route = self.query_router.route(
            source=parsed.source,
            has_db=self.db_provider is not None,
            has_docs=self.doc_provider is not None,
        )

        if not bouncer.accepted:
            return QueryResult(
                query=parsed.query,
                route=route,
                answer=bouncer.reason,
                confidence=0.0,
                citations=[],
                conflicts=[],
                insufficient_evidence=True,
                audit={
                    "bouncer_verdict": bouncer.verdict,
                    "matched_contracts": bouncer.matched_contracts,
                    "intent": bouncer.intent,
                    "cache_hit": False,
                },
            )

        db_items = []
        doc_items = []
        if route in (QueryRoute.DB_ONLY, QueryRoute.CROSS_SOURCE) and self.db_provider is not None:
            db_items = self.db_provider.get_evidence(parsed.query, limit=parsed.limit, intent=bouncer.intent)
        if route in (QueryRoute.DOC_ONLY, QueryRoute.CROSS_SOURCE) and self.doc_provider is not None:
            doc_items = self.doc_provider.get_evidence(parsed.query, limit=parsed.limit, intent=bouncer.intent)

        merged = self.merger.merge(db_items=db_items, doc_items=doc_items, intent=bouncer.intent, max_items=parsed.limit)
        result = self.synthesis_engine.synthesize(parsed, route, merged)
        result.audit.update(
            {
                "bouncer_verdict": bouncer.verdict,
                "matched_contracts": bouncer.matched_contracts,
                "intent": bouncer.intent,
            }
        )
        return result

