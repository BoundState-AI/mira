"""Route generation from question map."""

from __future__ import annotations

import re

from mira.forge_claude.question_gen.question_map import QuestionMap


def _pascal(name: str) -> str:
    return "".join(word.capitalize() for word in name.split("_"))


def _sql_identifier(name: str) -> str:
    """Bracket-quote a SQL identifier (safe inside Python string literals)."""
    return "[" + name.replace("]", "]]") + "]"


def _safe_py(name: str) -> str:
    """Convert a schema-qualified table name to a valid Python identifier.

    ``main.GAO_Protests`` → ``GAO_Protests``
    ``main.COSTS: FAR 31 & CAS`` → ``COSTS_FAR_31_CAS``
    """
    # Strip schema prefix (e.g. "main.")
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    # Replace non-identifier chars
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name and name[0].isdigit():
        name = f"t_{name}"
    return name or "unknown"


def _sql_table(name: str) -> str:
    """Return a bracket-quoted SQL table name, stripping schema prefix.

    Uses [brackets] instead of "double quotes" to avoid conflicts with
    Python string delimiters in generated f-string code.
    """
    bare = name.rsplit(".", 1)[-1] if "." in name else name
    return "[" + bare.replace("]", "]]") + "]"


def _api_slug(name: str) -> str:
    """URL-safe slug for API route prefix."""
    return _safe_py(name).lower()


def _generate_search_router(table: str, columns: list[str]) -> str:
    """Generate a search router module."""
    py = _safe_py(table)
    slug = _api_slug(table)
    sql_tbl = _sql_table(table)
    safe_cols = [_safe_py(c) for c in columns]
    cols_str = ", ".join(f'"{c}"' for c in safe_cols)
    return f'''"""Search endpoints for {py}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{slug}", tags=["{py}"])


@router.get("/search")
def search_{py}(
    query: str = Query("", description="Search query"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Search {py} across columns: {cols_str}."""
    search_columns = [{cols_str}]
    # TODO: Implement full-text search
    results = db.execute(
        text("SELECT * FROM {sql_tbl} LIMIT :limit OFFSET :skip"),
        {{"limit": limit, "skip": skip}},
    ).fetchall()
    return {{"items": [dict(r._mapping) for r in results], "total": len(results)}}
'''


def _generate_filter_router(table: str, filter_column: str) -> str:
    """Generate a filter router module."""
    py = _safe_py(table)
    slug = _api_slug(table)
    sql_tbl = _sql_table(table)
    col_py = _safe_py(filter_column)
    col_sql = _sql_identifier(filter_column)
    return f'''"""Filter endpoints for {py}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{slug}", tags=["{py}"])


@router.get("/filter")
def filter_{py}(
    {col_py}: str = Query(None, description="Filter by {filter_column}"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Filter {py} by {filter_column}."""
    query = "SELECT * FROM {sql_tbl}"
    params = {{}}
    if {col_py}:
        query += " WHERE {col_sql} = :{col_py}"
        params["{col_py}"] = {col_py}
    query += " LIMIT :limit OFFSET :skip"
    params["limit"] = limit
    params["skip"] = skip
    results = db.execute(text(query), params).fetchall()
    return {{"items": [dict(r._mapping) for r in results], "total": len(results)}}
'''


def _generate_detail_router(table: str) -> str:
    """Generate a detail router module."""
    py = _safe_py(table)
    slug = _api_slug(table)
    sql_tbl = _sql_table(table)
    return f'''"""Detail endpoints for {py}."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{slug}", tags=["{py}"])


@router.get("/detail/{{row_id}}")
def get_{py}_detail(
    row_id: int,
    db: Session = Depends(get_db),
):
    """Get detailed view of a single {py} record."""
    result = db.execute(
        text("SELECT * FROM {sql_tbl} WHERE rowid = :id"), {{"id": row_id}}
    ).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="{py} not found")
    return dict(result._mapping)
'''


def _generate_analysis_router(table: str, columns: list[str]) -> str:
    """Generate an analysis/stats router module."""
    py = _safe_py(table)
    slug = _api_slug(table)
    sql_tbl = _sql_table(table)
    return f'''"""Analysis endpoints for {py}."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{slug}", tags=["{py}"])


@router.get("/stats")
def get_{py}_stats(
    db: Session = Depends(get_db),
):
    """Get aggregate statistics for {py}."""
    count = db.execute(text("SELECT COUNT(*) FROM {sql_tbl}")).scalar()
    return {{"table": "{py}", "count": count}}
'''


def _generate_crossref_router(table: str, join_table: str, columns: list[str]) -> str:
    """Generate a cross-reference router module."""
    py = _safe_py(table)
    jpy = _safe_py(join_table)
    slug = _api_slug(table)
    sql_tbl = _sql_table(table)
    sql_join = _sql_table(join_table)
    return f'''"""Cross-reference endpoints for {py} with {jpy}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{slug}", tags=["{py}"])


@router.get("/cross-ref/{jpy}")
def cross_ref_{py}_with_{jpy}(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Cross-reference {py} with {jpy}."""
    # TODO: Implement join query between {py} and {jpy}
    results = db.execute(
        text("SELECT * FROM {sql_tbl} LIMIT :limit OFFSET :skip"),
        {{"limit": limit, "skip": skip}},
    ).fetchall()
    return {{"items": [dict(r._mapping) for r in results], "total": len(results)}}
'''


def _generate_join_router(table: str, join_table: str, columns: list[str]) -> str:
    """Generate a relationship join router module."""
    py = _safe_py(table)
    jpy = _safe_py(join_table)
    slug = _api_slug(table)
    sql_tbl = _sql_table(table)
    sql_join = _sql_table(join_table)
    return f'''"""Relationship join endpoints for {py} with {jpy}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{slug}", tags=["{py}"])


@router.get("/join/{jpy}")
def join_{py}_with_{jpy}(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Join {py} with {jpy} via relationship."""
    # TODO: Implement join query between {py} and {jpy}
    results = db.execute(
        text("SELECT * FROM {sql_tbl} LIMIT :limit OFFSET :skip"),
        {{"limit": limit, "skip": skip}},
    ).fetchall()
    return {{"items": [dict(r._mapping) for r in results], "total": len(results)}}
'''


def generate_routers(question_map: QuestionMap) -> dict[str, str]:
    """Generate router modules from question map.

    Returns:
        Dict mapping filename to file content.
    """
    routers: dict[str, str] = {}
    seen_tables: dict[str, set[str]] = {}  # table -> set of router types

    for cat in question_map.question_categories:
        for q in cat.questions:
            table = q.target_table
            tpy = _safe_py(table)
            if table not in seen_tables:
                seen_tables[table] = set()

            if q.template_type == "text_search" and "search" not in seen_tables[table]:
                seen_tables[table].add("search")
                routers[f"search_{tpy}.py"] = _generate_search_router(
                    table, q.target_columns
                )

            elif q.template_type == "categorical_filter" and "filter" not in seen_tables[table]:
                seen_tables[table].add("filter")
                routers[f"filter_{tpy}.py"] = _generate_filter_router(
                    table, q.target_columns[0]
                )

            elif q.template_type == "detail_view" and "detail" not in seen_tables[table]:
                seen_tables[table].add("detail")
                routers[f"detail_{tpy}.py"] = _generate_detail_router(table)

            elif q.template_type in ("aggregation", "comparison", "time_series") and "analysis" not in seen_tables[table]:
                seen_tables[table].add("analysis")
                routers[f"analysis_{tpy}.py"] = _generate_analysis_router(
                    table, q.target_columns
                )

            elif q.template_type == "cross_reference":
                join_table = q.join_tables[0] if q.join_tables else "related"
                jpy = _safe_py(join_table)
                key = f"crossref_{jpy}"
                if key not in seen_tables[table]:
                    seen_tables[table].add(key)
                    routers[f"crossref_{tpy}_{jpy}.py"] = _generate_crossref_router(
                        table, join_table, q.target_columns
                    )

            elif q.template_type == "relationship_join":
                join_table = q.join_tables[0] if q.join_tables else "related"
                jpy = _safe_py(join_table)
                key = f"join_{jpy}"
                if key not in seen_tables[table]:
                    seen_tables[table].add(key)
                    routers[f"join_{tpy}_{jpy}.py"] = _generate_join_router(
                        table, join_table, q.target_columns
                    )

    return routers
