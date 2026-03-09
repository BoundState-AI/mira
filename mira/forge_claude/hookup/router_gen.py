"""Route generation from question map."""

from __future__ import annotations

from mira.forge_claude.question_gen.question_map import QuestionMap


def _pascal(name: str) -> str:
    return "".join(word.capitalize() for word in name.split("_"))


def _generate_search_router(table: str, columns: list[str]) -> str:
    """Generate a search router module."""
    cols_str = ", ".join(f'"{c}"' for c in columns)
    return f'''"""Search endpoints for {table}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{table}", tags=["{table}"])


@router.get("/search")
def search_{table}(
    query: str = Query("", description="Search query"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Search {table} across columns: {cols_str}."""
    search_columns = [{cols_str}]
    # TODO: Implement full-text search
    results = db.execute(
        f"SELECT * FROM {table} LIMIT {{limit}} OFFSET {{skip}}"
    ).fetchall()
    return {{"items": [dict(r._mapping) for r in results], "total": len(results)}}
'''


def _generate_filter_router(table: str, filter_column: str) -> str:
    """Generate a filter router module."""
    return f'''"""Filter endpoints for {table}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{table}", tags=["{table}"])


@router.get("/filter")
def filter_{table}(
    {filter_column}: str = Query(None, description="Filter by {filter_column}"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Filter {table} by {filter_column}."""
    query = "SELECT * FROM {table}"
    params = {{}}
    if {filter_column}:
        query += " WHERE {filter_column} = :{filter_column}"
        params["{filter_column}"] = {filter_column}
    query += f" LIMIT {{limit}} OFFSET {{skip}}"
    results = db.execute(query, params).fetchall()
    return {{"items": [dict(r._mapping) for r in results], "total": len(results)}}
'''


def _generate_detail_router(table: str) -> str:
    """Generate a detail router module."""
    return f'''"""Detail endpoints for {table}."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{table}", tags=["{table}"])


@router.get("/{{{table}_id}}")
def get_{table}_detail(
    {table}_id: int,
    db: Session = Depends(get_db),
):
    """Get detailed view of a single {table} record."""
    result = db.execute(
        "SELECT * FROM {table} WHERE id = :id", {{"id": {table}_id}}
    ).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="{table} not found")
    return dict(result._mapping)
'''


def _generate_analysis_router(table: str, columns: list[str]) -> str:
    """Generate an analysis/stats router module."""
    return f'''"""Analysis endpoints for {table}."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{table}", tags=["{table}"])


@router.get("/stats")
def get_{table}_stats(
    db: Session = Depends(get_db),
):
    """Get aggregate statistics for {table}."""
    count = db.execute("SELECT COUNT(*) FROM {table}").scalar()
    return {{"table": "{table}", "count": count}}
'''


def _generate_crossref_router(table: str, join_table: str, columns: list[str]) -> str:
    """Generate a cross-reference router module."""
    cols_str = ", ".join(f'"{c}"' for c in columns) if columns else ""
    return f'''"""Cross-reference endpoints for {table} with {join_table}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{table}", tags=["{table}"])


@router.get("/cross-ref/{join_table}")
def cross_ref_{table}_with_{join_table}(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Cross-reference {table} with {join_table}."""
    # TODO: Implement join query between {table} and {join_table}
    results = db.execute(
        "SELECT * FROM {table} LIMIT {{limit}} OFFSET {{skip}}"
    ).fetchall()
    return {{"items": [dict(r._mapping) for r in results], "total": len(results)}}
'''


def _generate_join_router(table: str, join_table: str, columns: list[str]) -> str:
    """Generate a relationship join router module."""
    return f'''"""Relationship join endpoints for {table} with {join_table}."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/{table}", tags=["{table}"])


@router.get("/join/{join_table}")
def join_{table}_with_{join_table}(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Join {table} with {join_table} via relationship."""
    # TODO: Implement join query between {table} and {join_table}
    results = db.execute(
        "SELECT * FROM {table} LIMIT {{limit}} OFFSET {{skip}}"
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
            if table not in seen_tables:
                seen_tables[table] = set()

            if q.template_type == "text_search" and "search" not in seen_tables[table]:
                seen_tables[table].add("search")
                routers[f"search_{table}.py"] = _generate_search_router(
                    table, q.target_columns
                )

            elif q.template_type == "categorical_filter" and "filter" not in seen_tables[table]:
                seen_tables[table].add("filter")
                routers[f"filter_{table}.py"] = _generate_filter_router(
                    table, q.target_columns[0]
                )

            elif q.template_type == "detail_view" and "detail" not in seen_tables[table]:
                seen_tables[table].add("detail")
                routers[f"detail_{table}.py"] = _generate_detail_router(table)

            elif q.template_type in ("aggregation", "comparison", "time_series") and "analysis" not in seen_tables[table]:
                seen_tables[table].add("analysis")
                routers[f"analysis_{table}.py"] = _generate_analysis_router(
                    table, q.target_columns
                )

            elif q.template_type == "cross_reference":
                join_table = q.join_tables[0] if q.join_tables else "related"
                key = f"crossref_{join_table}"
                if key not in seen_tables[table]:
                    seen_tables[table].add(key)
                    routers[f"crossref_{table}_{join_table}.py"] = _generate_crossref_router(
                        table, join_table, q.target_columns
                    )

            elif q.template_type == "relationship_join":
                join_table = q.join_tables[0] if q.join_tables else "related"
                key = f"join_{join_table}"
                if key not in seen_tables[table]:
                    seen_tables[table].add(key)
                    routers[f"join_{table}_{join_table}.py"] = _generate_join_router(
                        table, join_table, q.target_columns
                    )

    return routers
