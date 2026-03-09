"""Column type to question template mappings."""

from __future__ import annotations

NUMERIC_TYPES = {"INTEGER", "INT", "BIGINT", "SMALLINT", "FLOAT", "REAL", "DOUBLE", "NUMERIC", "DECIMAL"}
DATE_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}
TEXT_TYPES = {"VARCHAR", "TEXT", "CHAR", "NVARCHAR", "NCHAR", "STRING", "CLOB"}


def is_numeric(col_type: str) -> bool:
    upper = col_type.upper()
    return any(t in upper for t in NUMERIC_TYPES)


def is_date(col_type: str) -> bool:
    upper = col_type.upper()
    return any(t in upper for t in DATE_TYPES)


def is_text(col_type: str) -> bool:
    upper = col_type.upper()
    return any(t in upper for t in TEXT_TYPES)


def is_boolean(col_type: str) -> bool:
    return "BOOL" in col_type.upper()


# Pattern detection templates
QUESTION_PATTERNS = {
    "numeric_aggregation": {
        "template": "What is the {agg} {column} for {table}?",
        "aggregations": ["min", "max", "average"],
        "category": "Analysis",
        "ui_component": "StatsBar",
        "priority": "medium",
    },
    "categorical_filter": {
        "template": "Show me {table} filtered by {column}",
        "category": "Filter & Browse",
        "ui_component": "FilterSidebar",
        "priority": "high",
    },
    "time_series": {
        "template": "Show me {table} over time by {column}",
        "category": "Analysis",
        "ui_component": "TimelineView",
        "priority": "medium",
    },
    "relationship_join": {
        "template": "Show me {parent} with their {children}",
        "category": "Filter & Browse",
        "ui_component": "ResultsTable",
        "priority": "high",
    },
    "numeric_comparison": {
        "template": "Compare {col_a} vs {col_b} for {table}",
        "category": "Analysis",
        "ui_component": "ComparisonView",
        "priority": "medium",
    },
    "text_search": {
        "template": "Search {table} by {column}",
        "category": "Search",
        "ui_component": "SearchBar",
        "priority": "high",
    },
    "cross_reference": {
        "template": "Cross-reference {table_a} with {table_b}",
        "category": "Analysis",
        "ui_component": "ResultsTable",
        "priority": "low",
    },
    "detail_view": {
        "template": "Show me everything about a specific {table_singular}",
        "category": "Detail",
        "ui_component": "DetailPanel",
        "priority": "high",
    },
}
