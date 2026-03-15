"""Compiled execution-plan generation for FORGE questions.

These plans turn a question surface into a deterministic runtime contract.
The BSMS runtime selects and executes these plans rather than inferring SQL
from natural language at request time.

DESIGN PRINCIPLE: Plans are built entirely from schema metadata (column names,
types, cardinality) and question template_type. No table names, domain keywords,
or question text are matched. This makes FORGE data-agnostic — point it at any
database and it produces executable plans.
"""

from __future__ import annotations

from typing import Any

from mira.forge_claude.introspector.manifest import ColumnInfo, SchemaManifest, TableInfo
from mira.forge_claude.question_gen.patterns import is_date, is_numeric, is_text
from mira.forge_claude.question_gen.question_map import Question, QuestionMap


def annotate_question_map_with_execution_plans(
    question_map: QuestionMap,
    manifest: SchemaManifest,
) -> QuestionMap:
    """Annotate every question in the map with a compiled execution plan."""
    table_lookup = {table.name: table for table in manifest.tables}
    for category in question_map.question_categories:
        for question in category.questions:
            plan = build_execution_plan(question, table_lookup.get(question.target_table))
            if not plan:
                continue
            question.capability_id = str(plan.get("capability_id", ""))
            question.intent_family = str(plan.get("intent_family", ""))
            question.execution_plan = plan
    return question_map


def build_execution_plan(question: Question, table: TableInfo | None) -> dict[str, Any]:
    """Build an execution plan from question template_type and table schema.

    The plan contract fields:
      - capability_id: unique identifier for this capability
      - intent_family: semantic family (detail_lookup, entity_lookup, etc.)
      - plan_type: execution strategy (detail_rows, search_lookup, etc.)
      - entity_table: target table name
      - entity_key: primary entity column (for filtering/grouping)
      - selected_columns: columns to SELECT
      - group_by: columns for GROUP BY
      - metrics: numeric columns for aggregation
      - filters: columns available for WHERE predicates
      - sort: ordering specification
      - support_thresholds: minimum evidence requirements
    """
    if table is None:
        return {}

    table_name = question.target_table
    columns = {column.name: column for column in table.columns}
    target_columns = [column for column in question.target_columns if column != "*"]

    # Derive column classes from schema
    text_columns = [col for col in table.columns if is_text(col.type)]
    numeric_columns = [col for col in table.columns if is_numeric(col.type)]
    date_columns = [col for col in table.columns if is_date(col.type)]
    categorical_columns = [col for col in table.columns if _is_categorical_column(col)]
    lookup_columns = [col for col in table.columns if _is_lookup_column(col)]
    entity_key = _infer_entity_key(table)

    if question.template_type == "detail_view":
        return _plan(
            capability_id=f"{table_name}_detail_view",
            intent_family="detail_lookup",
            plan_type="detail_rows",
            entity_table=table_name,
            entity_key=entity_key,
            selected_columns=[col.name for col in table.columns],
            filters=[col.name for col in lookup_columns],
            support_thresholds={"min_rows": 1},
        )

    if question.template_type == "text_search":
        search_columns = [col for col in target_columns if col in columns]
        if not search_columns:
            search_columns = [col.name for col in text_columns][:3]
        return _plan(
            capability_id=f"{table_name}_search_lookup",
            intent_family="entity_lookup",
            plan_type="search_lookup",
            entity_table=table_name,
            entity_key=entity_key,
            selected_columns=search_columns or [col.name for col in table.columns[:3]],
            filters=search_columns,
            sort=[{"column": search_columns[0], "direction": "asc"}] if search_columns else [],
            support_thresholds={"min_rows": 1},
        )

    if question.template_type in {"categorical_filter", "filter"}:
        filter_cols = [col for col in target_columns if col in columns]
        if not filter_cols:
            filter_cols = [col.name for col in categorical_columns][:2]
        return _plan(
            capability_id=f"{table_name}_categorical_browse",
            intent_family="categorical_browse",
            plan_type="categorical_browse",
            entity_table=table_name,
            entity_key=entity_key,
            selected_columns=filter_cols,
            group_by=filter_cols[:1],
            filters=filter_cols,
            support_thresholds={"min_rows": 1},
        )

    if question.template_type == "aggregation":
        agg_metrics = [col for col in target_columns if col in columns and is_numeric(columns[col].type)]
        if not agg_metrics:
            agg_metrics = [col.name for col in numeric_columns][:1]
        agg_group = [col.name for col in categorical_columns][:1]
        return _plan(
            capability_id=f"{table_name}_aggregation",
            intent_family="grouped_aggregation",
            plan_type="grouped_aggregation",
            entity_table=table_name,
            entity_key=entity_key,
            group_by=agg_group,
            metrics=agg_metrics,
            filters=[col.name for col in categorical_columns][:4],
            support_thresholds={"min_rows": 1, "required_metric_non_null": agg_metrics},
        )

    if question.template_type == "comparison":
        cmp_metrics = [col for col in target_columns if col in columns and is_numeric(columns[col].type)]
        if len(cmp_metrics) < 2:
            cmp_metrics = [col.name for col in numeric_columns][:2]
        cmp_group = [col.name for col in categorical_columns][:1]
        return _plan(
            capability_id=f"{table_name}_comparison",
            intent_family="metric_comparison",
            plan_type="grouped_comparison" if cmp_group else "raw_comparison",
            entity_table=table_name,
            entity_key=entity_key,
            group_by=cmp_group,
            metrics=cmp_metrics,
            filters=[col.name for col in categorical_columns][:4],
            support_thresholds={"min_rows": 1, "required_metric_non_null": cmp_metrics},
        )

    if question.template_type == "time_series":
        ts_columns = [col for col in target_columns if col in columns and is_date(columns[col].type)]
        ts_metrics = [col for col in target_columns if col in columns and is_numeric(columns[col].type)]
        if not ts_columns:
            ts_columns = [col.name for col in date_columns][:1]
        if not ts_metrics:
            ts_metrics = [col.name for col in numeric_columns][:1]
        return _plan(
            capability_id=f"{table_name}_time_series",
            intent_family="time_series",
            plan_type="time_series",
            entity_table=table_name,
            entity_key=entity_key,
            group_by=ts_columns[:1],
            metrics=ts_metrics[:1],
            filters=[col.name for col in categorical_columns][:2],
            sort=[{"column": ts_columns[0], "direction": "asc"}] if ts_columns else [],
            support_thresholds={"min_rows": 1, "required_metric_non_null": ts_metrics[:1]},
        )

    if question.template_type == "relationship_join":
        join_key = target_columns[0] if target_columns else entity_key
        return _plan(
            capability_id=f"{table_name}_relationship_trace",
            intent_family="relationship_trace",
            plan_type="relationship_trace",
            entity_table=table_name,
            entity_key=join_key,
            join_tables=question.join_tables,
            group_by=[join_key] if join_key else [],
            filters=[join_key] if join_key else [],
            support_thresholds={"min_rows": 1, "required_join_tables": question.join_tables},
        )

    if question.template_type == "cross_reference":
        xref_key = entity_key or (target_columns[0] if target_columns else "")
        xref_group = [col.name for col in categorical_columns][:2]
        return _plan(
            capability_id=f"{table_name}_cross_reference",
            intent_family="cross_reference",
            plan_type="grouped_aggregation" if xref_group else "detail_rows",
            entity_table=table_name,
            entity_key=xref_key,
            group_by=xref_group,
            metrics=[col.name for col in numeric_columns][:1],
            filters=[col.name for col in lookup_columns][:4],
            join_tables=question.join_tables,
            support_thresholds={"min_rows": 1},
        )

    # Fallback: if the question has numeric targets, do aggregation; otherwise detail
    if numeric_columns and categorical_columns:
        return _plan(
            capability_id=f"{table_name}_auto_aggregation",
            intent_family="grouped_aggregation",
            plan_type="grouped_aggregation",
            entity_table=table_name,
            entity_key=entity_key,
            group_by=[categorical_columns[0].name],
            metrics=[numeric_columns[0].name],
            filters=[col.name for col in categorical_columns][:4],
            support_thresholds={"min_rows": 1},
        )

    return _plan(
        capability_id=f"{table_name}_detail_view",
        intent_family="detail_lookup",
        plan_type="detail_rows",
        entity_table=table_name,
        entity_key=entity_key,
        selected_columns=[col.name for col in table.columns],
        filters=[col.name for col in lookup_columns],
        support_thresholds={"min_rows": 1},
    )


def _plan(**payload: Any) -> dict[str, Any]:
    payload.setdefault("selected_columns", [])
    payload.setdefault("group_by", [])
    payload.setdefault("metrics", [])
    payload.setdefault("filters", [])
    payload.setdefault("join_tables", [])
    payload.setdefault("sort", [])
    payload.setdefault("support_thresholds", {})
    return payload


def _infer_entity_key(table: TableInfo) -> str:
    """Infer the primary entity column from schema heuristics."""
    # Prefer columns with "name" in them, then "id", then first text column
    for col in table.columns:
        if "name" in col.name.lower() and is_text(col.type):
            return col.name
    for col in table.columns:
        if col.name.lower().endswith("_id") and is_text(col.type):
            return col.name
    for col in table.columns:
        if is_text(col.type):
            return col.name
    return table.columns[0].name if table.columns else ""


def _is_lookup_column(column: ColumnInfo) -> bool:
    lowered = column.name.lower()
    return any(token in lowered for token in ("id", "name", "material", "type", "family", "document", "source", "key", "code"))


def _is_categorical_column(column: ColumnInfo) -> bool:
    return is_text(column.type) and (column.unique_count or 0) > 1
