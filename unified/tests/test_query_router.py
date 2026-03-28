from __future__ import annotations

from unified.pipeline.query_router import QueryRouter
from unified.schema import QueryRoute, QuerySource


def test_query_router_respects_requested_source_and_availability() -> None:
    router = QueryRouter()

    assert router.route(QuerySource.DB, has_db=True, has_docs=True) == QueryRoute.DB_ONLY
    assert router.route(QuerySource.DOCS, has_db=True, has_docs=True) == QueryRoute.DOC_ONLY
    assert router.route(QuerySource.HYBRID, has_db=True, has_docs=True) == QueryRoute.CROSS_SOURCE
    assert router.route(QuerySource.HYBRID, has_db=False, has_docs=True) == QueryRoute.DOC_ONLY

