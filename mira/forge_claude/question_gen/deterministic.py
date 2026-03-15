"""Pass 1 — deterministic question generation from schema patterns."""

from __future__ import annotations

from mira.forge_claude.config import ENUM_LIKE_THRESHOLD
from mira.forge_claude.introspector.manifest import SchemaManifest, TableInfo
from mira.forge_claude.question_gen.patterns import is_date, is_numeric, is_text
from mira.forge_claude.question_gen.question_map import Question, QuestionCategory, QuestionMap


def _singularize(name: str) -> str:
    """Naive singularization: strip trailing 's'."""
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def _humanize(name: str) -> str:
    """Convert snake_case to human-readable."""
    return name.replace("_", " ")


def _is_identifierish(column_name: str) -> bool:
    lowered = column_name.lower()
    exact = {
        "id",
        "pk",
        "key",
        "code",
        "index",
        "parent",
        "line_number",
        "sequence_number",
        "sample_number",
        "revision",
        "revision_number",
        "source_hash",
        "report_hash",
    }
    if lowered in exact:
        return True
    suffixes = ("_id", "_key", "_code", "_hash", "_number", "_idx")
    if lowered.endswith(suffixes):
        return True
    return any(token in lowered for token in ("identifier", "uuid"))


def _search_column_score(column_name: str) -> int:
    lowered = column_name.lower()
    strong = (
        "material",
        "designation",
        "name",
        "issue",
        "application",
        "environment",
        "program",
        "rating",
        "family",
        "type",
        "category",
        "concern",
        "pattern",
        "rationale",
        "failure",
        "determination",
    )
    medium = ("report_number", "test_report", "mua_number", "reference_number", "standard")
    weak = ("source_file", "source_hash", "hash", "path", "filename")
    if any(token in lowered for token in strong):
        return 3
    if any(token in lowered for token in medium):
        return 2
    if any(token in lowered for token in weak):
        return 0
    return 1


def _categorical_column_score(column_name: str) -> int:
    lowered = column_name.lower()
    if any(token in lowered for token in ("material", "rating", "environment", "issue", "category", "program", "family", "type", "status", "determination", "domain")):
        return 3
    if any(token in lowered for token in ("description", "notes", "comment", "remark", "source_hash")):
        return 0
    return 1


def _table_priority(table_name: str) -> str:
    lowered = table_name.lower()
    if any(token in lowered for token in ("backup", "archive", "diagnostic")):
        return "low"
    return "high"


class _QuestionBuilder:
    """Accumulates questions and assigns sequential IDs."""

    def __init__(self) -> None:
        self._counter = 0
        self._categories: dict[str, list[Question]] = {}

    def add(self, category: str, **kwargs) -> None:
        self._counter += 1
        q = Question(id=f"q_{self._counter:03d}", **kwargs)
        self._categories.setdefault(category, []).append(q)

    def build(self) -> list[QuestionCategory]:
        # Fixed category ordering
        order = ["Search", "Filter & Browse", "Analysis", "Detail"]
        result = []
        for cat_name in order:
            if cat_name in self._categories:
                result.append(
                    QuestionCategory(category=cat_name, questions=self._categories[cat_name])
                )
        # Any remaining categories
        for cat_name, qs in self._categories.items():
            if cat_name not in order:
                result.append(QuestionCategory(category=cat_name, questions=qs))
        return result


def _is_enum_like(col, row_count: int) -> bool:
    """Check if column has low cardinality relative to row count."""
    if col.unique_count is None or row_count == 0:
        return False
    return col.unique_count / row_count <= ENUM_LIKE_THRESHOLD and col.unique_count > 1


def _process_table(builder: _QuestionBuilder, table: TableInfo, manifest: SchemaManifest) -> None:
    """Generate questions for a single table."""
    numeric_cols = []
    date_cols = []
    text_cols_high_unique = []
    categorical_cols = []

    for col in table.columns:
        if col.primary_key:
            continue

        if is_numeric(col.type):
            numeric_cols.append(col)
        elif is_date(col.type):
            date_cols.append(col)
        elif is_text(col.type):
            if _is_enum_like(col, table.row_count):
                categorical_cols.append(col)
            elif col.unique_count and col.unique_count > 10:
                text_cols_high_unique.append(col)
            else:
                # Low-unique text that's not enum-like — still categorical if > 1
                if col.unique_count and col.unique_count > 1:
                    categorical_cols.append(col)

    # Text search questions
    if text_cols_high_unique:
        ranked_text = sorted(
            text_cols_high_unique,
            key=lambda column: (_search_column_score(column.name), column.name),
            reverse=True,
        )
        col_names = [c.name for c in ranked_text[:3]]
        search_priority = "high" if _search_column_score(col_names[0]) >= 2 else "medium"
        builder.add(
            "Search",
            natural_language=f"Find {_humanize(table.name)} by {', '.join(_humanize(c) for c in col_names)}",
            template_type="text_search",
            target_table=table.name,
            target_columns=col_names,
            ui_component="SearchBar",
            priority=search_priority,
        )

    # Categorical filter questions
    ranked_categorical = sorted(
        categorical_cols,
        key=lambda column: (_categorical_column_score(column.name), column.name),
        reverse=True,
    )
    for col in ranked_categorical[:4]:
        if _categorical_column_score(col.name) <= 0:
            continue
        builder.add(
            "Filter & Browse",
            natural_language=f"Show me all {_humanize(table.name)} filtered by {_humanize(col.name)}",
            template_type="categorical_filter",
            target_table=table.name,
            target_columns=[col.name],
            ui_component="FilterSidebar",
            priority="high",
        )

    # Foreign key relationship filter questions
    for fk in table.foreign_keys:
        builder.add(
            "Filter & Browse",
            natural_language=f"Show me {_humanize(table.name)} by {_humanize(fk.references_table)}",
            template_type="categorical_filter",
            target_table=table.name,
            target_columns=[fk.column],
            join_tables=[fk.references_table],
            ui_component="FilterSidebar",
            priority="high",
        )

    # Numeric aggregation questions
    for col in numeric_cols:
        if _is_identifierish(col.name):
            continue
        builder.add(
            "Analysis",
            natural_language=f"What is the min/max/average {_humanize(col.name)} for {_humanize(table.name)}?",
            template_type="aggregation",
            target_table=table.name,
            target_columns=[col.name],
            ui_component="StatsBar",
            priority="medium",
        )

    # Numeric comparison (if >= 2 numeric cols)
    meaningful_numeric_cols = [col for col in numeric_cols if not _is_identifierish(col.name)]
    if len(meaningful_numeric_cols) >= 2:
        builder.add(
            "Analysis",
            natural_language=(
                f"Compare {_humanize(meaningful_numeric_cols[0].name)} vs "
                f"{_humanize(meaningful_numeric_cols[1].name)} for {_humanize(table.name)}"
            ),
            template_type="comparison",
            target_table=table.name,
            target_columns=[meaningful_numeric_cols[0].name, meaningful_numeric_cols[1].name],
            ui_component="ComparisonView",
            priority="medium",
        )

    # Time series questions
    for col in date_cols:
        builder.add(
            "Analysis",
            natural_language=f"Show me {_humanize(table.name)} over time by {_humanize(col.name)}",
            template_type="time_series",
            target_table=table.name,
            target_columns=[col.name],
            ui_component="TimelineView",
            priority="medium",
        )

    # Detail view (always generate one per non-trivial table)
    if len(table.columns) > 2:
        join_tables = [fk.references_table for fk in table.foreign_keys]
        builder.add(
            "Detail",
            natural_language=f"Show me everything about a specific {_humanize(_singularize(table.name))}",
            template_type="detail_view",
            target_table=table.name,
            target_columns=["*"],
            join_tables=join_tables,
            ui_component="DetailPanel",
            priority=_table_priority(table.name),
        )


def _determine_landing_page(categories: list[QuestionCategory]) -> str:
    """Determine recommended landing page components."""
    components = []
    cat_names = {c.category for c in categories}
    if "Search" in cat_names:
        components.append("SearchBar")
    if "Filter & Browse" in cat_names:
        components.append("FilterSidebar")
    if "Analysis" in cat_names:
        components.append("ResultsTable")
    if not components:
        components.append("ResultsTable")
    return " + ".join(components)


def _estimate_pages(categories: list[QuestionCategory]) -> int:
    """Estimate number of UI pages needed."""
    pages = 1  # Landing page
    cat_names = {c.category for c in categories}
    if "Detail" in cat_names:
        pages += 1
    if "Analysis" in cat_names:
        pages += 1
    return pages


def _build_domain_summary(manifest: SchemaManifest) -> str:
    """Build a short domain summary from table names."""
    table_names = [_humanize(t.name) for t in manifest.tables]
    if len(table_names) <= 3:
        return f"Database with {', '.join(table_names)}"
    return f"Database with {', '.join(table_names[:3])}, and more"


def generate_questions_deterministic(manifest: SchemaManifest) -> QuestionMap:
    """Generate questions from schema using deterministic pattern matching.

    This is Pass 1 — no LLM involved. Produces structured question templates
    based on column types, relationships, and statistics.
    """
    builder = _QuestionBuilder()

    for table in manifest.tables:
        _process_table(builder, table, manifest)

    # Cross-reference questions for tables sharing foreign keys
    table_pairs_seen: set[tuple[str, str]] = set()
    for rel in manifest.relationships:
        pair = tuple(sorted([rel.from_table, rel.to_table]))
        if pair not in table_pairs_seen:
            table_pairs_seen.add(pair)

    categories = builder.build()

    return QuestionMap(
        database_name=manifest.database_name,
        domain_summary=_build_domain_summary(manifest),
        question_categories=categories,
        recommended_landing_page=_determine_landing_page(categories),
        estimated_ui_pages=_estimate_pages(categories),
    )
