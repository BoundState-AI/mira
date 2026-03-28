from __future__ import annotations

from unified.schema import QueryRoute, QuerySource


class QueryRouter:
    def route(self, source: QuerySource, has_db: bool, has_docs: bool) -> QueryRoute:
        if source == QuerySource.DB:
            return QueryRoute.DB_ONLY
        if source == QuerySource.DOCS:
            return QueryRoute.DOC_ONLY

        if has_db and has_docs:
            return QueryRoute.CROSS_SOURCE
        if has_db:
            return QueryRoute.DB_ONLY
        return QueryRoute.DOC_ONLY

