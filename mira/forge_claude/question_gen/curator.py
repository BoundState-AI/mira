"""Question curator — intent-first question selection.

Replaces the "generate hundreds, prune to fit" approach with:
  1. Define what questions an engineer would actually ask (intent archetypes)
  2. Check which ones the schema can answer (answerability gate)
  3. Score by engineering decision value, not schema shape
  4. Return a tight set of high-value questions (default 10)
  5. Optionally LLM-polish the natural language (no invention)

The key insight: instead of describing what's in the table,
describe what decisions the data supports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from mira.forge_claude.introspector.manifest import (
    ConfidenceScore,
    DataQualityReport,
    SchemaManifest,
    SemanticMap,
    RelationshipGraph,
    LatentRelationships,
    TableInfo,
)
from mira.forge_claude.question_gen.question_map import (
    CapabilityEntry,
    CandidateArchetypeEntry,
    CapabilityCoverageEntry,
    Question,
    QuestionCategory,
    QuestionMap,
    StructuralMotifEntry,
)

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent archetypes — what engineers actually ask
# ---------------------------------------------------------------------------

@dataclass
class IntentArchetype:
    """A question archetype that maps to a user intent, not a column type.

    Each archetype defines:
      - A natural language template (with {placeholders})
      - Required column signatures (semantic types or name patterns that must exist)
      - The tables/columns it would target if matched
      - Engineering value score (how useful is this question?)
    """
    intent_id: str
    category: str
    natural_language_template: str
    # Column signature requirements — at least one group must be fully satisfiable
    required_signatures: list[list[str]]  # OR of AND groups
    # What UI component best serves this question
    ui_component: str
    template_type: str
    # Base engineering value (0-1) — how useful is this to a decision-maker?
    base_value: float
    # Priority
    priority: str = "high"
    # Tags for domain matching
    domain_tags: list[str] = field(default_factory=list)


# These are domain-agnostic archetypes. FORGE should work on ANY database,
# but we weight toward engineering/science domains since that's the primary use case.
# The matching logic uses semantic types and column name patterns,
# not hardcoded table names.

INTENT_ARCHETYPES: list[IntentArchetype] = [
    # --- Search & Lookup (the first thing anyone does) ---
    IntentArchetype(
        intent_id="primary_search",
        category="Search",
        natural_language_template="Find records by {primary_search_fields}",
        required_signatures=[
            ["has_high_cardinality_text"],  # At least one searchable text field
        ],
        ui_component="SearchBar",
        template_type="text_search",
        base_value=0.95,
        priority="high",
    ),

    # --- Filter & Browse (narrowing down) ---
    IntentArchetype(
        intent_id="category_browse",
        category="Filter & Browse",
        natural_language_template="Browse {table_domain} by {category_field}",
        required_signatures=[
            ["has_categorical_field"],
        ],
        ui_component="FilterSidebar",
        template_type="categorical_filter",
        base_value=0.88,
        priority="high",
    ),

    # --- Relationship navigation (connecting the dots) ---
    IntentArchetype(
        intent_id="parent_child_nav",
        category="Filter & Browse",
        natural_language_template="Show all {child_domain} for a given {parent_domain}",
        required_signatures=[
            ["has_foreign_key"],
        ],
        ui_component="ResultsTable",
        template_type="relationship_join",
        base_value=0.92,
        priority="high",
    ),

    # --- Evidence & qualification (do we have data to support a decision?) ---
    IntentArchetype(
        intent_id="evidence_check",
        category="Analysis",
        natural_language_template="What {test_type} evidence exists for a given {entity}?",
        required_signatures=[
            ["has_test_or_result_table", "has_entity_reference"],
        ],
        ui_component="ResultsTable",
        template_type="relationship_join",
        base_value=0.96,
        priority="high",
        domain_tags=["materials", "testing", "qualification"],
    ),

    IntentArchetype(
        intent_id="precedent_lookup",
        category="Analysis",
        natural_language_template="Has anyone written a precedent or approval record for {entity} in this context?",
        required_signatures=[
            ["has_record_table_with_entity_and_context"],
        ],
        ui_component="ResultsTable",
        template_type="relationship_join",
        base_value=0.94,
        priority="high",
        domain_tags=["compliance", "precedent", "mua"],
    ),

    IntentArchetype(
        intent_id="concern_coverage",
        category="Analysis",
        natural_language_template="What concerns or patterns apply to this entity class?",
        required_signatures=[
            ["has_concern_or_domain_table_with_entity_link"],
        ],
        ui_component="ResultsTable",
        template_type="relationship_join",
        base_value=0.91,
        priority="high",
        domain_tags=["compliance", "risk", "concern"],
    ),

    IntentArchetype(
        intent_id="environment_suitability",
        category="Analysis",
        natural_language_template="Which entities are rated for a given environment or condition?",
        required_signatures=[
            ["has_rating_or_determination_with_environment"],
        ],
        ui_component="FilterSidebar",
        template_type="categorical_filter",
        base_value=0.93,
        priority="high",
        domain_tags=["materials", "environment", "qualification"],
    ),

    IntentArchetype(
        intent_id="failure_pattern",
        category="Analysis",
        natural_language_template="What failure modes or issues have been observed for this entity?",
        required_signatures=[
            ["has_failure_or_issue_field_with_entity_link"],
        ],
        ui_component="ResultsTable",
        template_type="relationship_join",
        base_value=0.90,
        priority="high",
        domain_tags=["failure", "risk", "pattern"],
    ),

    IntentArchetype(
        intent_id="rationale_retrieval",
        category="Analysis",
        natural_language_template="What rationale or justification exists for this decision?",
        required_signatures=[
            ["has_rationale_or_pattern_table"],
        ],
        ui_component="DetailPanel",
        template_type="detail_view",
        base_value=0.89,
        priority="high",
        domain_tags=["rationale", "justification", "evidence"],
    ),

    # --- Comparison (is A better than B?) ---
    IntentArchetype(
        intent_id="metric_comparison",
        category="Analysis",
        natural_language_template="Compare {metric_a} across different {grouping_field}",
        required_signatures=[
            ["has_meaningful_numeric", "has_categorical_field"],
        ],
        ui_component="ComparisonView",
        template_type="comparison",
        base_value=0.85,
        priority="medium",
    ),

    # --- Distribution (what does the landscape look like?) ---
    IntentArchetype(
        intent_id="distribution_overview",
        category="Analysis",
        natural_language_template="What is the distribution of {categorical_field} across {table_domain}?",
        required_signatures=[
            ["has_categorical_field_with_counts"],
        ],
        ui_component="StatsBar",
        template_type="aggregation",
        base_value=0.80,
        priority="medium",
    ),

    # --- Outlier / anomaly (what should I worry about?) ---
    IntentArchetype(
        intent_id="outlier_detection",
        category="Analysis",
        natural_language_template="Which {entities} have unusual {metric} values?",
        required_signatures=[
            ["has_meaningful_numeric_with_outliers"],
        ],
        ui_component="ResultsTable",
        template_type="aggregation",
        base_value=0.82,
        priority="medium",
        domain_tags=["quality", "anomaly"],
    ),

    # --- Trend (is something changing over time?) ---
    IntentArchetype(
        intent_id="temporal_trend",
        category="Analysis",
        natural_language_template="How has {metric_or_count} changed over time?",
        required_signatures=[
            ["has_date_field", "has_meaningful_numeric_or_countable"],
        ],
        ui_component="TimelineView",
        template_type="time_series",
        base_value=0.78,
        priority="medium",
    ),

    # --- Cross-reference (connecting independent data sources) ---
    IntentArchetype(
        intent_id="cross_reference",
        category="Analysis",
        natural_language_template="Which {table_a_domain} share {linking_field} with {table_b_domain}?",
        required_signatures=[
            ["has_latent_or_statistical_relationship"],
        ],
        ui_component="ResultsTable",
        template_type="cross_reference",
        base_value=0.72,
        priority="low",
    ),

    # --- Detail (show me everything about one record) ---
    IntentArchetype(
        intent_id="detail_view",
        category="Detail",
        natural_language_template="Show complete details for a specific {entity}",
        required_signatures=[
            ["has_primary_key", "has_multiple_columns"],
        ],
        ui_component="DetailPanel",
        template_type="detail_view",
        base_value=0.75,
        priority="high",
    ),

    # --- Gap analysis (what's missing?) ---
    IntentArchetype(
        intent_id="gap_analysis",
        category="Analysis",
        natural_language_template="Which {entities} are missing {required_data}?",
        required_signatures=[
            ["has_nullable_important_field"],
        ],
        ui_component="ResultsTable",
        template_type="aggregation",
        base_value=0.84,
        priority="medium",
        domain_tags=["compliance", "quality", "completeness"],
    ),
]


# ---------------------------------------------------------------------------
# Schema signature matching
# ---------------------------------------------------------------------------

def _humanize(name: str) -> str:
    """Convert snake_case to human-readable."""
    return name.replace("_", " ")


def _singularize(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


_IDENTIFIER_TOKENS = {
    "id", "pk", "key", "code", "index", "hash", "uuid",
    "line_number", "sequence_number", "sample_number",
    "revision", "revision_number", "source_hash", "report_hash",
}

_IDENTIFIER_SUFFIXES = ("_id", "_key", "_code", "_hash", "_number", "_idx")

_DOMAIN_ENTITY_TOKENS = (
    "material", "designation", "name", "application", "program",
    "environment", "issue", "concern", "pattern", "family",
    "specimen", "sample", "test", "result", "report",
    "approval", "determination", "rating", "failure",
)

_LOW_VALUE_TOKENS = (
    "source_hash", "source_file", "hash", "path", "filename",
    "backup", "archive", "diagnostic",
)

_LOW_VALUE_SEARCH_TOKENS = (
    "report", "source", "hash", "contract", "raw", "matched_text",
    "file", "path", "payload",
)

_HIGH_VALUE_TABLE_TOKENS = (
    "material", "evidence", "precedent", "approval", "mua",
    "result", "concern", "pattern", "requirement",
)

_HIGH_VALUE_COLUMN_TOKENS = (
    "material", "designation", "rating", "determination", "environment",
    "program", "application", "concern", "pattern", "failure",
)

_PRECEDENT_TOKENS = ("mua", "precedent", "approval", "evidence")
_CONCERN_TOKENS = ("concern", "pattern", "rationale", "issue", "domain")
_ENVIRONMENT_TOKENS = ("environment", "program", "condition", "context")
_RATING_TOKENS = ("rating", "determination", "status")
_FAILURE_TOKENS = ("failure", "issue", "remark", "defect")


def _is_identifier(col_name: str) -> bool:
    lowered = col_name.lower()
    if lowered in _IDENTIFIER_TOKENS:
        return True
    return any(lowered.endswith(s) for s in _IDENTIFIER_SUFFIXES)


def _is_meaningful_numeric(col_name: str, col_type: str) -> bool:
    """A numeric column that represents a real measurement, not an ID."""
    from mira.forge_claude.question_gen.patterns import is_numeric
    if not is_numeric(col_type):
        return False
    return not _is_identifier(col_name)


def _is_domain_entity_field(col_name: str) -> bool:
    lowered = col_name.lower()
    return any(token in lowered for token in _DOMAIN_ENTITY_TOKENS)


def _is_low_value(col_name: str, table_name: str) -> bool:
    lowered = col_name.lower() + " " + table_name.lower()
    return any(token in lowered for token in _LOW_VALUE_TOKENS)


def _is_low_value_search(col_name: str) -> bool:
    lowered = col_name.lower()
    return any(token in lowered for token in _LOW_VALUE_SEARCH_TOKENS)


def _table_value_bonus(table_name: str) -> float:
    lowered = table_name.lower()
    if any(token in lowered for token in _HIGH_VALUE_TABLE_TOKENS):
        return 0.06
    if "test" in lowered:
        return 0.03
    return 0.0


def _column_value_bonus(column_name: str) -> float:
    lowered = column_name.lower()
    if any(token in lowered for token in _HIGH_VALUE_COLUMN_TOKENS):
        return 0.04
    return 0.0


def _has_token(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


@dataclass
class _MatchedQuestion:
    """A question that matched an intent archetype against the schema."""
    archetype: IntentArchetype
    table: TableInfo
    target_columns: list[str]
    join_tables: list[str]
    natural_language: str
    value_score: float
    data_quality_score: float
    confidence: float


@dataclass
class StructuralMotif:
    motif_type: str
    tables: list[str]
    columns: list[str]
    confidence: float
    description: str


@dataclass
class CandidateArchetype:
    motif_type: str
    proposed_intent: str
    tables_involved: list[str]
    confidence: float
    reason: str


def detect_structural_motifs(
    manifest: SchemaManifest,
    relationship_graph: RelationshipGraph | None,
    semantic_map: SemanticMap | None,
) -> list[StructuralMotif]:
    """Detect high-value structural motifs from existing discovery artifacts."""
    inbound_counts: dict[str, int] = {}
    parent_to_children: dict[str, set[str]] = {}
    motifs: list[StructuralMotif] = []

    for table in manifest.tables:
        for fk in table.foreign_keys:
            inbound_counts[fk.references_table] = inbound_counts.get(fk.references_table, 0) + 1
            parent_to_children.setdefault(fk.references_table, set()).add(table.name)

    for table_name, inbound in inbound_counts.items():
        if inbound >= 3:
            motifs.append(
                StructuralMotif(
                    motif_type="hub_entity",
                    tables=[table_name],
                    columns=[],
                    confidence=min(0.99, 0.55 + (inbound * 0.08)),
                    description=f"{table_name} acts as a hub entity with {inbound} inbound foreign keys.",
                )
            )

    for table in manifest.tables:
        lowered = table.name.lower()
        if not any(token in lowered for token in ("test", "result", "precedent", "mua", "concern", "pattern", "evidence")):
            continue

        for fk in table.foreign_keys:
            if any(token in lowered for token in ("test", "result")) and _has_token(fk.references_table, ("material", "record", "mua")):
                motifs.append(
                    StructuralMotif(
                        motif_type="evidence_chain",
                        tables=[table.name, fk.references_table],
                        columns=[fk.column],
                        confidence=0.92,
                        description=f"{table.name} forms an evidence chain into {fk.references_table}.",
                    )
                )
            if _has_token(lowered, ("record", "mua", "precedent", "approval")) and any(
                _has_token(col.name, _ENVIRONMENT_TOKENS + _CONCERN_TOKENS + _FAILURE_TOKENS)
                for col in table.columns
            ):
                motifs.append(
                    StructuralMotif(
                        motif_type="record_context",
                        tables=[table.name, fk.references_table],
                        columns=[fk.column],
                        confidence=0.9,
                        description=f"{table.name} captures record context linked to {fk.references_table}.",
                    )
                )

    for parent, children in parent_to_children.items():
        test_children = sorted(child for child in children if _has_token(child, ("test", "result")))
        if len(test_children) >= 2:
            motifs.append(
                StructuralMotif(
                    motif_type="sibling_tests",
                    tables=[parent, *test_children[:6]],
                    columns=[],
                    confidence=min(0.97, 0.6 + (len(test_children) * 0.06)),
                    description=f"{parent} anchors multiple sibling test/result tables.",
                )
            )

    concern_tables = sorted(
        table.name for table in manifest.tables
        if _has_token(table.name, _CONCERN_TOKENS)
    )
    if len(concern_tables) >= 2:
        motifs.append(
            StructuralMotif(
                motif_type="concern_web",
                tables=concern_tables[:6],
                columns=[],
                confidence=min(0.96, 0.55 + (len(concern_tables) * 0.07)),
                description="Concern, pattern, or rationale tables form an interlinked reasoning web.",
            )
        )

    if semantic_map:
        environment_tables: dict[str, list[str]] = {}
        rating_tables: dict[str, list[str]] = {}
        for field in semantic_map.fields:
            if _has_token(field.column, _ENVIRONMENT_TOKENS):
                environment_tables.setdefault(field.table, []).append(field.column)
            if _has_token(field.column, _RATING_TOKENS):
                rating_tables.setdefault(field.table, []).append(field.column)
        for table_name, columns in environment_tables.items():
            if table_name not in rating_tables:
                continue
            motifs.append(
                StructuralMotif(
                    motif_type="environment_ratings",
                    tables=[table_name],
                    columns=sorted(set(columns + rating_tables.get(table_name, [])))[:4],
                    confidence=0.84,
                    description=f"{table_name} carries both environment/context and rating fields.",
                )
            )

    deduped: dict[tuple[str, tuple[str, ...], tuple[str, ...]], StructuralMotif] = {}
    for motif in motifs:
        key = (motif.motif_type, tuple(sorted(motif.tables)), tuple(sorted(motif.columns)))
        existing = deduped.get(key)
        if existing is None or motif.confidence > existing.confidence:
            deduped[key] = motif
    return list(deduped.values())


def _match_archetypes_to_schema(
    manifest: SchemaManifest,
    semantic_map: SemanticMap | None,
    relationship_graph: RelationshipGraph | None,
    latent_relationships: LatentRelationships | None,
    data_quality_report: DataQualityReport | None,
    motifs: list[StructuralMotif] | None = None,
) -> list[_MatchedQuestion]:
    """Match intent archetypes against the actual schema.

    For each archetype, find the best table(s) that satisfy its
    column signature requirements, then instantiate the question
    with concrete table/column names.
    """
    from mira.forge_claude.question_gen.patterns import is_numeric, is_date, is_text

    # Build quality lookup
    quality_lookup: dict[tuple[str, str], float] = {}
    if data_quality_report:
        for tq in data_quality_report.tables:
            for cq in tq.columns:
                quality_lookup[(cq.table, cq.column)] = cq.quality_score.score

    # Build semantic lookup
    sem_lookup: dict[tuple[str, str], dict] = {}
    if semantic_map:
        for field in semantic_map.fields:
            sem_lookup[(field.table, field.column)] = {
                "semantic_type": field.semantic_type,
                "detected_property": field.detected_property,
                "detected_units": field.detected_units,
            }

    # Classify tables for relationship-based archetypes
    test_tables = set()
    entity_tables = set()
    motif_types_by_table: dict[str, set[str]] = {}
    for motif in motifs or []:
        for table_name in motif.tables:
            motif_types_by_table.setdefault(table_name, set()).add(motif.motif_type)

    for table in manifest.tables:
        lowered = table.name.lower()
        if any(t in lowered for t in ("test", "result", "diagnostic")):
            test_tables.add(table.name)
        if any(t in lowered for t in ("material", "approval", "record", "mua", "pattern")):
            entity_tables.add(table.name)

    matched: list[_MatchedQuestion] = []

    for table in manifest.tables:
        # Skip trivially small or backup tables
        if table.row_count < 2:
            continue
        if any(t in table.name.lower() for t in ("backup", "archive", "import_batch")):
            continue

        table_domain = _humanize(_singularize(table.name))

        # Classify columns for this table
        high_card_text = []
        categorical = []
        meaningful_numeric = []
        date_cols = []
        nullable_important = []
        environment_fields = []
        rating_fields = []
        concern_fields = []
        failure_fields = []
        rationale_fields = []
        has_fks = bool(table.foreign_keys)
        table_motifs = motif_types_by_table.get(table.name, set())

        for col in table.columns:
            if col.primary_key:
                continue
            if _is_low_value(col.name, table.name):
                continue

            col_quality = quality_lookup.get((table.name, col.name), 1.0)

            if is_text(col.type):
                if col.unique_count and col.unique_count > 10:
                    high_card_text.append(col)
                elif col.unique_count and 1 < col.unique_count <= (table.row_count * 0.05 if table.row_count > 0 else 50):
                    categorical.append(col)
                elif col.unique_count and col.unique_count > 1:
                    categorical.append(col)
                if _has_token(col.name, _ENVIRONMENT_TOKENS):
                    environment_fields.append(col)
                if _has_token(col.name, _RATING_TOKENS):
                    rating_fields.append(col)
                if _has_token(col.name, _CONCERN_TOKENS):
                    concern_fields.append(col)
                if _has_token(col.name, _FAILURE_TOKENS):
                    failure_fields.append(col)
                if _has_token(col.name, ("rationale", "justification", "pattern")):
                    rationale_fields.append(col)
            elif _is_meaningful_numeric(col.name, col.type):
                meaningful_numeric.append(col)
            elif is_date(col.type):
                date_cols.append(col)

            # Nullable important fields (for gap analysis)
            if col.nullable and _is_domain_entity_field(col.name):
                null_rate = 0.0
                if data_quality_report:
                    for tq in data_quality_report.tables:
                        if tq.table == table.name:
                            for cq in tq.columns:
                                if cq.column == col.name:
                                    null_rate = cq.null_rate
                if 0.05 < null_rate < 0.8:  # Not totally empty, not totally full
                    nullable_important.append(col)

        # --- Match each archetype ---

        # primary_search
        if high_card_text:
            preferred_search = [
                c for c in high_card_text
                if _is_domain_entity_field(c.name) and not _is_low_value_search(c.name)
            ]
            acceptable_search = [
                c for c in high_card_text
                if not _is_low_value_search(c.name)
            ]
            best_search = sorted(
                preferred_search,
                key=lambda c: (
                    _column_value_bonus(c.name),
                    c.unique_count or 0,
                ),
                reverse=True,
            ) or sorted(
                acceptable_search,
                key=lambda c: (
                    _is_domain_entity_field(c.name),
                    _column_value_bonus(c.name),
                    c.unique_count or 0,
                ),
                reverse=True,
            )
            if not best_search:
                best_search = sorted(
                    high_card_text,
                    key=lambda c: (
                        not _is_low_value_search(c.name),
                        _is_domain_entity_field(c.name),
                        c.unique_count or 0,
                    ),
                    reverse=True,
                )
            cols = [c.name for c in best_search[:3]]
            col_labels = ", ".join(_humanize(c) for c in cols)
            low_value_penalty = 0.18 if any(_is_low_value_search(c) for c in cols) else 0.0
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("primary_search"),
                table=table,
                target_columns=cols,
                join_tables=[],
                natural_language=f"Search {table_domain} by {col_labels}",
                value_score=0.95 + _table_value_bonus(table.name) + max(_column_value_bonus(c) for c in cols) - low_value_penalty,
                data_quality_score=min(quality_lookup.get((table.name, c), 1.0) for c in cols),
                confidence=0.86 if any(_is_low_value_search(c) for c in cols) else 0.95,
            ))

        # category_browse
        if categorical:
            best_cat = sorted(
                categorical,
                key=lambda c: (
                    _is_domain_entity_field(c.name),
                    c.unique_count or 0,
                ),
                reverse=True,
            )
            for col in best_cat[:2]:  # Top 2 categorical columns max
                matched.append(_MatchedQuestion(
                    archetype=_get_archetype("category_browse"),
                    table=table,
                    target_columns=[col.name],
                    join_tables=[],
                    natural_language=f"Browse {table_domain} by {_humanize(col.name)}",
                    value_score=0.88 if _is_domain_entity_field(col.name) else 0.72,
                    data_quality_score=quality_lookup.get((table.name, col.name), 1.0),
                    confidence=0.90,
                ))

        # parent_child_nav
        for fk in table.foreign_keys:
            parent_domain = _humanize(_singularize(fk.references_table))
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("parent_child_nav"),
                table=table,
                target_columns=[fk.column],
                join_tables=[fk.references_table],
                natural_language=f"Show all {table_domain} for a given {parent_domain}",
                value_score=0.92 + _table_value_bonus(table.name) + _table_value_bonus(fk.references_table) + _column_value_bonus(fk.column) + (0.03 if "hub_entity" in table_motifs else 0.0),
                data_quality_score=quality_lookup.get((table.name, fk.column), 1.0),
                confidence=0.95,
            ))

        # evidence_check — only if this table looks like a test/result table
        # and references an entity table
        if table.name in test_tables and has_fks:
            for fk in table.foreign_keys:
                if fk.references_table in entity_tables or _is_domain_entity_field(fk.column):
                    parent_domain = _humanize(_singularize(fk.references_table))
                    test_type = _humanize(table.name).replace(" tests", "").replace(" results", "")
                    matched.append(_MatchedQuestion(
                        archetype=_get_archetype("evidence_check"),
                        table=table,
                        target_columns=[fk.column],
                        join_tables=[fk.references_table],
                        natural_language=f"What {test_type} evidence exists for a given {parent_domain}?",
                        value_score=0.96 + _table_value_bonus(table.name) + _table_value_bonus(fk.references_table) + _column_value_bonus(fk.column) + (0.04 if "evidence_chain" in table_motifs else 0.0),
                        data_quality_score=quality_lookup.get((table.name, fk.column), 1.0),
                        confidence=0.92,
                    ))

        if has_fks and (
            _has_token(table.name, _PRECEDENT_TOKENS)
            or "record_context" in table_motifs
        ):
            for fk in table.foreign_keys:
                if _has_token(fk.references_table, ("mua", "record", "material", "precedent", "approval")):
                    parent_domain = _humanize(_singularize(fk.references_table))
                    if "evidence" in table.name.lower():
                        prompt = f"What evidence exists for a given {parent_domain} decision?"
                    elif "pattern" in table.name.lower():
                        prompt = f"What rationale patterns support a given {parent_domain}?"
                    elif "concern" in table.name.lower():
                        prompt = f"What concerns are attached to a given {parent_domain}?"
                    else:
                        prompt = f"Has anyone written precedent context for a given {parent_domain}?"
                    matched.append(_MatchedQuestion(
                        archetype=_get_archetype("precedent_lookup"),
                        table=table,
                        target_columns=[fk.column],
                        join_tables=[fk.references_table],
                        natural_language=prompt,
                        value_score=0.94 + _table_value_bonus(table.name) + _table_value_bonus(fk.references_table) + 0.05,
                        data_quality_score=quality_lookup.get((table.name, fk.column), 1.0),
                        confidence=0.93,
                    ))

        if _has_token(table.name, ("precedent", "approval")) and not has_fks:
            precedent_columns = [
                col for col in high_card_text + categorical
                if _has_token(col.name, ("material", "designation", "application", "environment", "determination"))
            ]
            if precedent_columns:
                focus_fields = precedent_columns[:3]
                prompt_parts = ", ".join(_humanize(col.name) for col in focus_fields[:2])
                matched.append(_MatchedQuestion(
                    archetype=_get_archetype("precedent_lookup"),
                    table=table,
                    target_columns=[col.name for col in focus_fields],
                    join_tables=[],
                    natural_language=f"Has anyone written a precedent for {prompt_parts}?",
                    value_score=0.96 + _table_value_bonus(table.name) + max(_column_value_bonus(col.name) for col in focus_fields),
                    data_quality_score=min(quality_lookup.get((table.name, col.name), 1.0) for col in focus_fields),
                    confidence=0.9,
                ))

        if has_fks and (
            _has_token(table.name, _CONCERN_TOKENS)
            or "concern_web" in table_motifs
        ):
            relevant_fks = [
                fk for fk in table.foreign_keys
                if _has_token(fk.references_table, _CONCERN_TOKENS + ("mua", "material", "record"))
            ]
            join_tables = [fk.references_table for fk in relevant_fks]
            if relevant_fks:
                primary_join = relevant_fks[0].references_table
                matched.append(_MatchedQuestion(
                    archetype=_get_archetype("concern_coverage"),
                    table=table,
                    target_columns=[relevant_fks[0].column],
                    join_tables=join_tables[:2],
                    natural_language=f"What concerns or patterns apply to a given {_humanize(_singularize(primary_join))}?",
                    value_score=0.91 + _table_value_bonus(table.name) + _table_value_bonus(primary_join) + 0.05,
                    data_quality_score=quality_lookup.get((table.name, relevant_fks[0].column), 1.0),
                    confidence=0.92,
                ))

        if environment_fields and rating_fields and (
            _has_token(table.name, _PRECEDENT_TOKENS + _ENVIRONMENT_TOKENS + ("material",))
            or "environment_ratings" in table_motifs
        ):
            best_env = sorted(environment_fields, key=lambda c: (c.unique_count or 0, _column_value_bonus(c.name)), reverse=True)[0]
            best_rating = sorted(rating_fields, key=lambda c: (_column_value_bonus(c.name), c.unique_count or 0), reverse=True)[0]
            if _has_token(table.name, ("precedent", "approval", "mua", "record")):
                entity_label = "MUA records"
            else:
                entity_label = "materials"
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("environment_suitability"),
                table=table,
                target_columns=[best_env.name, best_rating.name],
                join_tables=[],
                natural_language=f"Which {entity_label} are suitable for {_humanize(best_env.name)} and what { _humanize(best_rating.name) } do they carry?",
                value_score=0.93 + _table_value_bonus(table.name) + _column_value_bonus(best_env.name) + _column_value_bonus(best_rating.name) + 0.05,
                data_quality_score=min(
                    quality_lookup.get((table.name, best_env.name), 1.0),
                    quality_lookup.get((table.name, best_rating.name), 1.0),
                ),
                confidence=0.9,
            ))

        if failure_fields and (has_fks or _has_token(table.name, _FAILURE_TOKENS)):
            join_tables = [fk.references_table for fk in table.foreign_keys][:2]
            if join_tables or _has_token(table.name, ("failure", "remark", "issue")):
                focus = _humanize(_singularize(join_tables[0])) if join_tables else table_domain
                best_failure = sorted(failure_fields, key=lambda c: _column_value_bonus(c.name), reverse=True)[0]
                matched.append(_MatchedQuestion(
                    archetype=_get_archetype("failure_pattern"),
                    table=table,
                    target_columns=[best_failure.name],
                    join_tables=join_tables,
                    natural_language=f"What failure modes or issues have been observed for {focus}?",
                    value_score=0.90 + _table_value_bonus(table.name) + _column_value_bonus(best_failure.name) + 0.04,
                    data_quality_score=quality_lookup.get((table.name, best_failure.name), 1.0),
                    confidence=0.89,
                ))

        if rationale_fields and (_has_token(table.name, ("pattern", "rationale", "precedent", "mua")) or "concern_web" in table_motifs):
            best_rationale = sorted(rationale_fields, key=lambda c: (_column_value_bonus(c.name), c.unique_count or 0), reverse=True)[0]
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("rationale_retrieval"),
                table=table,
                target_columns=[best_rationale.name],
                join_tables=[fk.references_table for fk in table.foreign_keys][:2],
                natural_language=f"What rationale or justification exists in {table_domain}?",
                value_score=0.89 + _table_value_bonus(table.name) + _column_value_bonus(best_rationale.name) + 0.04,
                data_quality_score=quality_lookup.get((table.name, best_rationale.name), 1.0),
                confidence=0.9,
            ))

        # metric_comparison
        if meaningful_numeric and categorical:
            best_metric = sorted(
                meaningful_numeric,
                key=lambda c: (
                    _is_domain_entity_field(c.name),
                    quality_lookup.get((table.name, c.name), 1.0),
                ),
                reverse=True,
            )[0]
            best_group = sorted(
                categorical,
                key=lambda c: _is_domain_entity_field(c.name),
                reverse=True,
            )[0]
            units = ""
            sem_info = sem_lookup.get((table.name, best_metric.name))
            if sem_info and sem_info.get("detected_units"):
                units = f" ({sem_info['detected_units']})"
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("metric_comparison"),
                table=table,
                target_columns=[best_metric.name, best_group.name],
                join_tables=[],
                natural_language=f"Compare {_humanize(best_metric.name)}{units} across different {_humanize(best_group.name)}",
                value_score=0.85,
                data_quality_score=min(
                    quality_lookup.get((table.name, best_metric.name), 1.0),
                    quality_lookup.get((table.name, best_group.name), 1.0),
                ),
                confidence=0.88,
            ))

        # distribution_overview
        if categorical:
            best_dist = sorted(
                categorical,
                key=lambda c: (c.unique_count or 0),
                reverse=True,
            )[0]
            if best_dist.unique_count and best_dist.unique_count >= 3:
                matched.append(_MatchedQuestion(
                    archetype=_get_archetype("distribution_overview"),
                    table=table,
                    target_columns=[best_dist.name],
                    join_tables=[],
                    natural_language=f"What is the distribution of {_humanize(best_dist.name)} across {table_domain}?",
                    value_score=0.80,
                    data_quality_score=quality_lookup.get((table.name, best_dist.name), 1.0),
                    confidence=0.90,
                ))

        # temporal_trend
        if date_cols and (meaningful_numeric or table.row_count > 20):
            best_date = date_cols[0]
            if meaningful_numeric:
                metric_label = _humanize(meaningful_numeric[0].name)
                target_cols = [best_date.name, meaningful_numeric[0].name]
            else:
                metric_label = f"{table_domain} count"
                target_cols = [best_date.name]
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("temporal_trend"),
                table=table,
                target_columns=target_cols,
                join_tables=[],
                natural_language=f"How has {metric_label} changed over time?",
                value_score=0.78,
                data_quality_score=quality_lookup.get((table.name, best_date.name), 1.0),
                confidence=0.85,
            ))

        # gap_analysis
        if nullable_important:
            best_gap = nullable_important[0]
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("gap_analysis"),
                table=table,
                target_columns=[best_gap.name],
                join_tables=[],
                natural_language=f"Which {table_domain} are missing {_humanize(best_gap.name)}?",
                value_score=0.84,
                data_quality_score=0.85,  # By definition, these have gaps
                confidence=0.88,
            ))

        # detail_view (one per non-trivial table, but scored lower)
        if len(table.columns) > 3:
            join_tables = [fk.references_table for fk in table.foreign_keys]
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("detail_view"),
                table=table,
                target_columns=["*"],
                join_tables=join_tables,
                natural_language=f"Show complete details for a specific {table_domain}",
                value_score=(
                    0.70 if table.name in test_tables or table.name in entity_tables else 0.55
                ) + _table_value_bonus(table.name) - (0.10 if "diagnostic" in table.name.lower() else 0.0),
                data_quality_score=1.0,
                confidence=0.95,
            ))

    # Cross-reference from latent/statistical relationships
    if relationship_graph:
        for rel in (relationship_graph.statistical or []) + (relationship_graph.join_viability or []):
            if rel.confidence.score < 0.6:
                continue
            from_domain = _humanize(_singularize(rel.from_table))
            to_domain = _humanize(_singularize(rel.to_table))
            # Find the table object
            table_obj = next((t for t in manifest.tables if t.name == rel.from_table), None)
            if table_obj is None:
                continue
            matched.append(_MatchedQuestion(
                archetype=_get_archetype("cross_reference"),
                table=table_obj,
                target_columns=[rel.from_column],
                join_tables=[rel.to_table],
                natural_language=f"Which {from_domain} share {_humanize(rel.from_column)} with {to_domain}?",
                value_score=0.72 * rel.confidence.score,
                data_quality_score=quality_lookup.get((rel.from_table, rel.from_column), 1.0),
                confidence=rel.confidence.score,
            ))

    return matched


def _get_archetype(intent_id: str) -> IntentArchetype:
    for arch in INTENT_ARCHETYPES:
        if arch.intent_id == intent_id:
            return arch
    raise ValueError(f"Unknown archetype: {intent_id}")


# ---------------------------------------------------------------------------
# Scoring & selection
# ---------------------------------------------------------------------------

def _composite_score(mq: _MatchedQuestion) -> float:
    """Compute final composite score for ranking.

    Weights:
      - Engineering value: 55% (is this a useful question?)
      - Data quality: 25% (can the DB actually answer it well?)
      - Confidence: 20% (how sure are we about the match?)
    """
    # Penalize diagnostic/backup tables
    table_penalty = 0.0
    lowered_table = mq.table.name.lower()
    if any(t in lowered_table for t in ("diagnostic", "backup", "archive")):
        table_penalty = 0.25

    search_penalty = 0.0
    if mq.archetype.intent_id == "primary_search" and any(_is_low_value_search(col) for col in mq.target_columns):
        search_penalty = 0.16

    identifier_penalty = 0.0
    if any(_is_identifier(col) for col in mq.target_columns):
        identifier_penalty = 0.04

    relationship_bonus = 0.0
    if mq.archetype.intent_id in {"evidence_check", "parent_child_nav"} and mq.join_tables:
        relationship_bonus += 0.06
        if any("material" in join.lower() for join in mq.join_tables):
            relationship_bonus += 0.05
    if mq.archetype.intent_id == "detail_view":
        relationship_bonus -= 0.03

    domain_bonus = _table_value_bonus(mq.table.name)
    domain_bonus += max((_table_value_bonus(join) for join in mq.join_tables), default=0.0)
    domain_bonus += max((_column_value_bonus(col) for col in mq.target_columns if col != "*"), default=0.0)

    # Bonus for high-row-count tables (more data = more useful)
    row_bonus = 0.0
    if mq.table.row_count > 1000:
        row_bonus = 0.08
    elif mq.table.row_count > 100:
        row_bonus = 0.05

    return (
        mq.value_score * 0.55
        + mq.data_quality_score * 0.25
        + mq.confidence * 0.20
        + relationship_bonus
        + domain_bonus
        + row_bonus
        - search_penalty
        - identifier_penalty
        - table_penalty
    )


def _deduplicate(questions: list[_MatchedQuestion]) -> list[_MatchedQuestion]:
    """Remove near-duplicate questions, keeping the highest-scored version."""
    seen_signatures: dict[str, _MatchedQuestion] = {}
    for mq in questions:
        # Signature: archetype + table + sorted columns
        sig = (
            mq.archetype.intent_id,
            mq.table.name,
            tuple(sorted(mq.target_columns)),
        )
        sig_key = str(sig)
        existing = seen_signatures.get(sig_key)
        if existing is None or _composite_score(mq) > _composite_score(existing):
            seen_signatures[sig_key] = mq
    return list(seen_signatures.values())


def _semantic_signature(mq: _MatchedQuestion) -> tuple[str, str, str, str]:
    join_target = mq.join_tables[0] if mq.join_tables else ""
    if mq.archetype.intent_id in {
        "evidence_check",
        "parent_child_nav",
        "precedent_lookup",
        "concern_coverage",
        "failure_pattern",
    }:
        return ("relationship", mq.table.name, join_target, "entity_link")
    if mq.archetype.intent_id == "environment_suitability":
        return ("suitability", mq.table.name, join_target, "environment")
    if mq.archetype.intent_id == "primary_search":
        return ("search", mq.table.name, "", ",".join(sorted(c for c in mq.target_columns if not _is_low_value_search(c))))
    return (mq.archetype.intent_id, mq.table.name, join_target, ",".join(sorted(mq.target_columns)))


def _semantic_dedup(questions: list[_MatchedQuestion]) -> list[_MatchedQuestion]:
    """Collapse engineering-equivalent questions across archetype variants."""
    seen: dict[tuple[str, str, str, str], _MatchedQuestion] = {}
    for mq in questions:
        sig = _semantic_signature(mq)
        existing = seen.get(sig)
        if existing is None or _composite_score(mq) > _composite_score(existing):
            seen[sig] = mq
    return list(seen.values())


def _selection_focus(mq: _MatchedQuestion) -> str:
    if mq.join_tables:
        return mq.join_tables[0]
    return mq.table.name


def _infer_capability_coverage(
    motifs: list[StructuralMotif],
    selected: list[_MatchedQuestion],
) -> list[CapabilityCoverageEntry]:
    selected_intents = {mq.archetype.intent_id for mq in selected}
    motif_types = {motif.motif_type for motif in motifs}

    def support_level(intent_ids: set[str], motif_ids: set[str]) -> str:
        if selected_intents.intersection(intent_ids):
            return "strong"
        if motif_types.intersection(motif_ids):
            return "partial"
        return "unsupported"

    capability_specs = [
        ("entity_lookup", "Entity lookup", {"primary_search", "detail_view"}, {"hub_entity"}),
        ("evidence_trace", "Evidence traceability", {"evidence_check"}, {"evidence_chain", "sibling_tests"}),
        ("precedent_context", "Precedent and approval context", {"precedent_lookup"}, {"record_context"}),
        ("concern_coverage", "Concern and rationale coverage", {"concern_coverage", "rationale_retrieval"}, {"concern_web"}),
        ("environment_suitability", "Environment suitability", {"environment_suitability"}, {"environment_ratings", "record_context"}),
        ("failure_patterns", "Failure and issue patterns", {"failure_pattern"}, {"record_context"}),
    ]

    coverage: list[CapabilityCoverageEntry] = []
    for capability_id, label, intents, motifs_required in capability_specs:
        level = support_level(intents, motifs_required)
        evidence = sorted(
            {
                motif.description
                for motif in motifs
                if motif.motif_type in motifs_required
            }
        )[:3]
        rationale = (
            "Curated questions promote this capability."
            if level == "strong"
            else "Discovery motifs suggest partial support."
            if level == "partial"
            else "No strong structural evidence found."
        )
        coverage.append(
            CapabilityCoverageEntry(
                capability_id=capability_id,
                label=label,
                support_level=level,
                evidence=evidence,
                rationale=rationale,
            )
        )
    return coverage


def _candidate_archetypes(
    motifs: list[StructuralMotif],
    selected: list[_MatchedQuestion],
) -> list[CandidateArchetype]:
    selected_intents = {mq.archetype.intent_id for mq in selected}
    candidates: list[CandidateArchetype] = []

    mapping = {
        "record_context": ("precedent_lookup", "Potential precedent/context question family"),
        "concern_web": ("concern_coverage", "Potential concern/rationale coverage family"),
        "environment_ratings": ("environment_suitability", "Potential environment suitability family"),
        "sibling_tests": ("comparison", "Potential cross-test comparison family"),
    }

    for motif in motifs:
        mapped = mapping.get(motif.motif_type)
        if mapped is None:
            continue
        intent_id, label = mapped
        if intent_id in selected_intents:
            continue
        candidates.append(
            CandidateArchetype(
                motif_type=motif.motif_type,
                proposed_intent=label,
                tables_involved=motif.tables,
                confidence=motif.confidence,
                reason=motif.description,
            )
        )
    deduped: dict[tuple[str, tuple[str, ...]], CandidateArchetype] = {}
    for candidate in candidates:
        key = (candidate.motif_type, tuple(sorted(candidate.tables_involved)))
        existing = deduped.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            deduped[key] = candidate
    return list(deduped.values())


def _ensure_diversity(
    ranked: list[_MatchedQuestion],
    max_questions: int,
) -> list[_MatchedQuestion]:
    """Select top questions while ensuring category diversity.

    Rules:
      - No more than 3 questions from any single category
      - No more than 2 questions from any single table
      - At least one Search question if available
      - At least one Analysis question if available
    """
    selected: list[_MatchedQuestion] = []
    cat_counts: dict[str, int] = {}
    table_counts: dict[str, int] = {}
    intent_counts: dict[str, int] = {}
    focus_counts: dict[str, int] = {}

    category_caps = {
        "Search": 2,
        "Filter & Browse": 3,
        "Analysis": 4,
        "Detail": 2,
    }

    def can_select(mq: _MatchedQuestion) -> bool:
        cat = mq.archetype.category
        tbl = mq.table.name
        intent = mq.archetype.intent_id
        focus = _selection_focus(mq)
        if cat_counts.get(cat, 0) >= category_caps.get(cat, 3):
            return False
        if table_counts.get(tbl, 0) >= 2:
            return False
        if intent_counts.get(intent, 0) >= 2:
            return False
        if mq.join_tables and focus_counts.get(focus, 0) >= 2:
            return False
        return True

    def add_selected(mq: _MatchedQuestion) -> None:
        selected.append(mq)
        cat_counts[mq.archetype.category] = cat_counts.get(mq.archetype.category, 0) + 1
        table_counts[mq.table.name] = table_counts.get(mq.table.name, 0) + 1
        intent_counts[mq.archetype.intent_id] = intent_counts.get(mq.archetype.intent_id, 0) + 1
        if mq.join_tables:
            focus = _selection_focus(mq)
            focus_counts[focus] = focus_counts.get(focus, 0) + 1

    # First pass: ensure we have at least one from key categories
    priority_cats = ["Search", "Filter & Browse", "Analysis", "Detail"]
    for cat in priority_cats:
        if len(selected) >= max_questions:
            break
        for mq in ranked:
            if mq.archetype.category == cat and mq not in selected and can_select(mq):
                add_selected(mq)
                break

    # Second pass: fill remaining slots by score
    for mq in ranked:
        if len(selected) >= max_questions:
            break
        if mq in selected:
            continue
        if not can_select(mq):
            continue
        add_selected(mq)

    # Final relaxed pass: if constraints were too strict, fill remaining slots by score.
    if len(selected) < max_questions:
        for mq in ranked:
            if len(selected) >= max_questions:
                break
            if mq in selected:
                continue
            if table_counts.get(mq.table.name, 0) >= 2:
                continue
            if mq.join_tables and focus_counts.get(_selection_focus(mq), 0) >= 2:
                continue
            add_selected(mq)

    return selected


def _promote_capability_gaps(
    ranked: list[_MatchedQuestion],
    selected: list[_MatchedQuestion],
    max_questions: int,
) -> list[_MatchedQuestion]:
    """Promote underrepresented high-value capability families into the final surface."""
    promoted = list(selected)
    selected_intents = {mq.archetype.intent_id for mq in promoted}
    desired_intents = ["precedent_lookup", "concern_coverage", "environment_suitability"]

    for desired in desired_intents:
        if desired in selected_intents:
            continue
        candidate = next((mq for mq in ranked if mq.archetype.intent_id == desired and mq not in promoted), None)
        if candidate is None:
            continue

        replacement_index = None
        replacement_score = None
        for index, existing in enumerate(promoted):
            if existing.archetype.intent_id == desired:
                replacement_index = None
                break
            if existing.archetype.intent_id in {"primary_search", "parent_child_nav", "detail_view", "category_browse"}:
                score = _composite_score(existing)
                if replacement_score is None or score < replacement_score:
                    replacement_index = index
                    replacement_score = score
        if replacement_index is None:
            continue
        promoted[replacement_index] = candidate
        selected_intents.add(desired)

    deduped: list[_MatchedQuestion] = []
    seen_ids: set[tuple[str, str, str, str]] = set()
    for mq in promoted:
        sig = _semantic_signature(mq)
        if sig in seen_ids:
            continue
        seen_ids.add(sig)
        deduped.append(mq)
    return deduped[:max_questions]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def curate_questions(
    manifest: SchemaManifest,
    semantic_map: SemanticMap | None = None,
    relationship_graph: RelationshipGraph | None = None,
    latent_relationships: LatentRelationships | None = None,
    data_quality_report: DataQualityReport | None = None,
    max_questions: int = 10,
    progress_callback: Callable[[str, float], None] | None = None,
) -> QuestionMap:
    """Curate the top N intent-driven questions for a database.

    This is the replacement for generate_questions_enhanced when you want
    a tight, high-value question set instead of an exhaustive one.

    Args:
        manifest: Schema manifest from introspection.
        semantic_map: Optional semantic type inferences.
        relationship_graph: Optional discovered relationships.
        latent_relationships: Optional entropy-discovered joins.
        data_quality_report: Optional data quality scores.
        max_questions: Maximum number of questions to return (default 10).

    Returns:
        A QuestionMap with at most max_questions high-value questions.
    """
    def emit(message: str, progress: float) -> None:
        if progress_callback is not None:
            progress_callback(message, progress)

    LOGGER.info("Curator: matching %d intent archetypes against %d tables",
                len(INTENT_ARCHETYPES), len(manifest.tables))

    # Step 1: Detect structural motifs from discovery artifacts
    emit("Detecting structural motifs from discovery artifacts.", 10.0)
    motifs = detect_structural_motifs(manifest, relationship_graph, semantic_map)
    LOGGER.info("Curator: detected %d structural motifs", len(motifs))

    # Step 2: Match archetypes against schema
    emit("Matching archetypes to the discovered schema.", 30.0)
    matches = _match_archetypes_to_schema(
        manifest, semantic_map, relationship_graph,
        latent_relationships, data_quality_report,
        motifs=motifs,
    )
    LOGGER.info("Curator: %d raw matches from archetype matching", len(matches))

    # Step 3: Deduplicate
    matches = _deduplicate(matches)
    LOGGER.info("Curator: %d matches after deduplication", len(matches))

    # Step 4: Semantic deduplication across equivalent question families
    emit("Removing semantically equivalent question variants.", 55.0)
    matches = _semantic_dedup(matches)
    LOGGER.info("Curator: %d matches after semantic deduplication", len(matches))

    # Step 5: Score and rank
    emit("Scoring and selecting a diverse question surface.", 72.0)
    ranked = sorted(matches, key=_composite_score, reverse=True)

    # Step 6: Select with diversity constraints
    selected = _ensure_diversity(ranked, max_questions)
    selected = _promote_capability_gaps(ranked, selected, max_questions)
    LOGGER.info("Curator: selected %d questions", len(selected))

    emit("Finalizing capability coverage and candidate archetypes.", 90.0)
    capability_coverage = _infer_capability_coverage(motifs, selected)
    candidates = _candidate_archetypes(motifs, selected)

    # Step 5: Build QuestionMap
    categories: dict[str, list[Question]] = {}
    capability_entries: list[CapabilityEntry] = []

    for i, mq in enumerate(selected):
        q = Question(
            id=f"curated_{i+1:03d}",
            natural_language=mq.natural_language,
            template_type=mq.archetype.template_type,
            target_table=mq.table.name,
            target_columns=mq.target_columns,
            join_tables=mq.join_tables,
            ui_component=mq.archetype.ui_component,
            priority=mq.archetype.priority,
            confidence=ConfidenceScore(
                score=round(mq.confidence, 2),
                source="curator",
                method="intent_archetype_match",
                inputs=[f"{mq.table.name}.{c}" for c in mq.target_columns if c != "*"],
            ),
            data_caveats=[],
            semantic_context={},
            discovery_source="intent_archetype",
        )
        categories.setdefault(mq.archetype.category, []).append(q)
        capability_entries.append(CapabilityEntry(
            question_id=q.id,
            reliable=mq.data_quality_score >= 0.7,
            reliability_score=round(mq.data_quality_score, 2),
            limiting_factors=[],
        ))

    # Build ordered categories
    cat_order = ["Search", "Filter & Browse", "Analysis", "Detail"]
    question_categories = []
    for cat_name in cat_order:
        if cat_name in categories:
            question_categories.append(
                QuestionCategory(category=cat_name, questions=categories[cat_name])
            )
    # Any remaining
    for cat_name, qs in categories.items():
        if cat_name not in cat_order:
            question_categories.append(QuestionCategory(category=cat_name, questions=qs))

    total_reliable = sum(1 for ce in capability_entries if ce.reliable)
    total_caveated = sum(1 for ce in capability_entries if not ce.reliable)

    # Domain summary
    table_names = [_humanize(t.name) for t in manifest.tables if t.row_count > 0]
    if len(table_names) <= 3:
        domain = f"covering {', '.join(table_names)}"
    else:
        domain = f"with {len(table_names)} active tables including {', '.join(table_names[:3])}"

    emit("Curator question map complete.", 100.0)
    return QuestionMap(
        database_name=manifest.database_name,
        domain_summary=f"Database {domain}. {len(selected)} curated questions targeting key decision points.",
        question_categories=question_categories,
        recommended_landing_page="SearchBar + FilterSidebar + ResultsTable",
        estimated_ui_pages=min(3, 1 + len(question_categories)),
        capability_map=capability_entries,
        total_reliable=total_reliable,
        total_caveated=total_caveated,
        structural_motifs=[
            StructuralMotifEntry(
                motif_type=motif.motif_type,
                tables=motif.tables,
                columns=motif.columns,
                confidence=round(motif.confidence, 2),
                description=motif.description,
            )
            for motif in motifs
        ],
        candidate_archetypes=[
            CandidateArchetypeEntry(
                motif_type=candidate.motif_type,
                proposed_intent=candidate.proposed_intent,
                tables_involved=candidate.tables_involved,
                confidence=round(candidate.confidence, 2),
                reason=candidate.reason,
            )
            for candidate in candidates
        ],
        capability_coverage=capability_coverage,
    )
