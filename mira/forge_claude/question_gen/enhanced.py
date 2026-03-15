"""v4.1 enhanced question generation.

Wraps the deterministic generator with:
  - Semantic context: uses SemanticMap to enrich question text with units,
    detected properties, and domain-specific language.
  - Quality gating: uses DataQualityReport to attach caveats and confidence
    scores to questions whose underlying data is unreliable.
  - Relationship-aware questions: uses RelationshipGraph and
    LatentRelationships to generate cross-table questions beyond FKs.
  - Capability mapping: summarises which questions the DB can reliably answer.
  - Enhanced domain summary from semantic analysis.
"""

from __future__ import annotations

from collections import defaultdict

from mira.forge_claude.introspector.manifest import (
    ConfidenceScore,
    DataQualityReport,
    LatentRelationships,
    RelationshipGraph,
    SchemaManifest,
    SemanticMap,
)
from mira.forge_claude.question_gen.deterministic import (
    _QuestionBuilder,
    _build_domain_summary,
    _determine_landing_page,
    _estimate_pages,
    _humanize,
    _process_table,
    _singularize,
)
from mira.forge_claude.question_gen.question_map import (
    CapabilityEntry,
    Question,
    QuestionCategory,
    QuestionMap,
)


# ---------------------------------------------------------------------------
# Semantic enrichment
# ---------------------------------------------------------------------------

def _build_semantic_lookup(
    semantic_map: SemanticMap | None,
) -> dict[tuple[str, str], dict]:
    """Build (table, column) -> semantic info lookup."""
    if not semantic_map:
        return {}
    lookup = {}
    for field in semantic_map.fields:
        lookup[(field.table, field.column)] = {
            "semantic_type": field.semantic_type,
            "detected_property": field.detected_property,
            "detected_units": field.detected_units,
            "confidence": field.confidence.score,
        }
    return lookup


def _enrich_question_text(
    text: str,
    target_table: str,
    target_columns: list[str],
    sem_lookup: dict[tuple[str, str], dict],
) -> tuple[str, dict]:
    """Enrich question text with semantic context (units, properties).

    Returns (enriched_text, semantic_context_dict).
    """
    context: dict = {}
    enriched = text

    for col in target_columns:
        if col == "*":
            continue
        info = sem_lookup.get((target_table, col))
        if not info:
            continue

        units = info.get("detected_units", "")
        prop = info.get("detected_property", "")
        sem_type = info.get("semantic_type", "")

        if units:
            context["units"] = units
            # Append units to column name in question text
            col_human = _humanize(col)
            if col_human in enriched and f"({units})" not in enriched:
                enriched = enriched.replace(col_human, f"{col_human} ({units})")

        if prop and prop not in ("primary_key", "name", "description"):
            context["property"] = prop

        if sem_type:
            context["semantic_type"] = sem_type

    return enriched, context


# ---------------------------------------------------------------------------
# Quality gating
# ---------------------------------------------------------------------------

def _build_quality_lookup(
    quality_report: DataQualityReport | None,
) -> dict[tuple[str, str], dict]:
    """Build (table, column) -> quality info lookup."""
    if not quality_report:
        return {}
    lookup = {}
    for tq in quality_report.tables:
        for cq in tq.columns:
            lookup[(cq.table, cq.column)] = {
                "null_rate": cq.null_rate,
                "quality_score": cq.quality_score.score,
                "flags": cq.flags,
                "outlier_count": cq.outlier_count,
            }
    return lookup


def _compute_question_confidence(
    target_table: str,
    target_columns: list[str],
    quality_lookup: dict[tuple[str, str], dict],
) -> tuple[float, list[str]]:
    """Compute confidence score and caveats for a question based on data quality.

    Returns (confidence_score, list_of_caveats).
    """
    if not quality_lookup or not target_columns:
        return 1.0, []

    scores = []
    caveats = []

    for col in target_columns:
        if col == "*":
            continue
        info = quality_lookup.get((target_table, col))
        if not info:
            continue

        q_score = info["quality_score"]
        scores.append(q_score)

        null_rate = info["null_rate"]
        if null_rate > 0.5:
            caveats.append(f"{col}: {null_rate:.0%} null — results may be incomplete")
        elif null_rate > 0.2:
            caveats.append(f"{col}: {null_rate:.0%} null — moderate data gaps")

        if info["outlier_count"] > 0:
            flags = info.get("flags", [])
            outlier_flags = [f for f in flags if "outlier" in f]
            if outlier_flags:
                caveats.append(f"{col}: outliers detected — aggregates may be skewed")

    if not scores:
        return 1.0, []

    avg_score = sum(scores) / len(scores)
    return round(avg_score, 2), caveats


# ---------------------------------------------------------------------------
# Relationship-aware questions
# ---------------------------------------------------------------------------

def _generate_relationship_questions(
    builder: _QuestionBuilder,
    manifest: SchemaManifest,
    relationship_graph: RelationshipGraph | None,
    latent_relationships: LatentRelationships | None,
    sem_lookup: dict[tuple[str, str], dict],
    quality_lookup: dict[tuple[str, str], dict],
) -> None:
    """Generate additional questions from discovered relationships."""
    if not relationship_graph and not latent_relationships:
        return

    # Track existing FK pairs to avoid duplicates
    known_fk_pairs = set()
    for table in manifest.tables:
        for fk in table.foreign_keys:
            known_fk_pairs.add((table.name, fk.column, fk.references_table, fk.references_column))

    # Statistical matches (mechanism 2) — cross-reference questions
    if relationship_graph:
        for rel in relationship_graph.statistical:
            pair = (rel.from_table, rel.from_column, rel.to_table, rel.to_column)
            if pair in known_fk_pairs:
                continue

            conf, caveats = _compute_question_confidence(
                rel.from_table, [rel.from_column], quality_lookup,
            )
            question_conf = min(conf, rel.confidence.score)

            text = (
                f"Cross-reference {_humanize(rel.from_table)} with "
                f"{_humanize(rel.to_table)} via matching {_humanize(rel.from_column)}"
            )
            text, ctx = _enrich_question_text(
                text, rel.from_table, [rel.from_column], sem_lookup,
            )
            caveats.append(f"Statistical match (overlap: {rel.overlap_ratio:.0%})")

            builder.add(
                "Analysis",
                natural_language=text,
                template_type="cross_reference",
                target_table=rel.from_table,
                target_columns=[rel.from_column],
                join_tables=[rel.to_table],
                ui_component="ResultsTable",
                priority="low",
                confidence=ConfidenceScore(
                    score=round(question_conf, 2),
                    source="question_gen",
                    method="statistical_relationship",
                    inputs=[f"{rel.from_table}.{rel.from_column}",
                            f"{rel.to_table}.{rel.to_column}"],
                ),
                data_caveats=caveats,
                semantic_context=ctx,
                discovery_source="relationship",
            )

        # Join-validated relationships (mechanism 3)
        for rel in relationship_graph.join_viability:
            pair = (rel.from_table, rel.from_column, rel.to_table, rel.to_column)
            if pair in known_fk_pairs:
                continue

            conf, caveats = _compute_question_confidence(
                rel.from_table, [rel.from_column], quality_lookup,
            )
            question_conf = min(conf, rel.confidence.score)

            text = (
                f"Show {_humanize(rel.from_table)} joined with "
                f"{_humanize(rel.to_table)} (verified join)"
            )
            text, ctx = _enrich_question_text(
                text, rel.from_table, [rel.from_column], sem_lookup,
            )

            builder.add(
                "Filter & Browse",
                natural_language=text,
                template_type="relationship_join",
                target_table=rel.from_table,
                target_columns=[rel.from_column],
                join_tables=[rel.to_table],
                ui_component="ResultsTable",
                priority="medium",
                confidence=ConfidenceScore(
                    score=round(question_conf, 2),
                    source="question_gen",
                    method="join_viability",
                    inputs=[f"{rel.from_table}.{rel.from_column}",
                            f"{rel.to_table}.{rel.to_column}"],
                ),
                data_caveats=caveats,
                semantic_context=ctx,
                discovery_source="relationship",
            )

    # Latent joins (entropy-discovered)
    if latent_relationships:
        for join in latent_relationships.joins:
            if join.composite_score < 0.5:
                continue  # Only promote strong candidates
            if join.conflict_with_fk:
                continue  # FK wins

            conf, caveats = _compute_question_confidence(
                join.from_table, [join.from_column], quality_lookup,
            )
            question_conf = min(conf, join.confidence.score)
            caveats.append(f"Entropy-discovered (MI: {join.mutual_information:.2f})")

            text = (
                f"Explore hidden relationship: {_humanize(join.from_table)}.{_humanize(join.from_column)} "
                f"↔ {_humanize(join.to_table)}.{_humanize(join.to_column)}"
            )
            text, ctx = _enrich_question_text(
                text, join.from_table, [join.from_column], sem_lookup,
            )

            builder.add(
                "Analysis",
                natural_language=text,
                template_type="cross_reference",
                target_table=join.from_table,
                target_columns=[join.from_column],
                join_tables=[join.to_table],
                ui_component="ResultsTable",
                priority="low",
                confidence=ConfidenceScore(
                    score=round(question_conf, 2),
                    source="question_gen",
                    method="entropy_discovery",
                    inputs=[f"{join.from_table}.{join.from_column}",
                            f"{join.to_table}.{join.to_column}"],
                ),
                data_caveats=caveats,
                semantic_context=ctx,
                discovery_source="entropy",
            )


# ---------------------------------------------------------------------------
# Enhanced domain summary
# ---------------------------------------------------------------------------

def _build_enhanced_domain_summary(
    manifest: SchemaManifest,
    semantic_map: SemanticMap | None,
) -> str:
    """Build a richer domain summary using semantic inference."""
    if not semantic_map or not semantic_map.fields:
        return _build_domain_summary(manifest)

    # Collect semantic types and properties
    sem_types: dict[str, int] = {}
    units_found: list[str] = []

    for field in semantic_map.fields:
        if field.semantic_type != "unknown":
            sem_types[field.semantic_type] = sem_types.get(field.semantic_type, 0) + 1
        if field.detected_units:
            units_found.append(field.detected_units)

    # Build summary
    table_names = [_humanize(t.name) for t in manifest.tables]
    parts = []

    if len(table_names) <= 3:
        parts.append(f"Database covering {', '.join(table_names)}")
    else:
        parts.append(f"Database with {len(table_names)} tables including {', '.join(table_names[:3])}")

    # Dominant data types
    top_types = sorted(sem_types.items(), key=lambda x: -x[1])[:3]
    if top_types:
        type_strs = [f"{t[0]} ({t[1]} fields)" for t in top_types]
        parts.append(f"Primary data: {', '.join(type_strs)}")

    # Units present
    unique_units = sorted(set(units_found))
    if unique_units:
        parts.append(f"Units: {', '.join(unique_units[:5])}")

    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Capability mapping
# ---------------------------------------------------------------------------

def _build_capability_map(
    questions: list[Question],
    quality_lookup: dict[tuple[str, str], dict],
) -> tuple[list[CapabilityEntry], int, int]:
    """Build capability map: which questions the DB can reliably answer.

    Returns (capability_entries, total_reliable, total_caveated).
    """
    entries = []
    reliable_count = 0
    caveated_count = 0

    for q in questions:
        score = q.confidence.score
        limiting = list(q.data_caveats)

        is_reliable = score >= 0.7 and not any(
            "null" in c.lower() and "incomplete" in c.lower() for c in limiting
        )

        entries.append(CapabilityEntry(
            question_id=q.id,
            reliable=is_reliable,
            reliability_score=score,
            limiting_factors=limiting,
        ))

        if is_reliable:
            reliable_count += 1
        else:
            caveated_count += 1

    return entries, reliable_count, caveated_count


def _template_score(question: Question) -> float:
    lowered_text = question.natural_language.lower()
    lowered_table = question.target_table.lower()
    lowered_columns = " ".join(question.target_columns).lower()
    low_value_table_penalty = 0.18 if any(token in lowered_table for token in ("backup", "archive", "diagnostic")) else 0.0
    identifier_metric_penalty = 0.0
    if question.template_type in {"aggregation", "comparison"} and any(
        token in lowered_columns
        for token in ("id", "key", "code", "number", "index", "parent", "sample", "sequence", "revision")
    ):
        identifier_metric_penalty = 0.26
    weak_search_penalty = 0.0
    if question.template_type in {"text_search", "categorical_filter"} and any(
        token in lowered_columns for token in ("source_hash", "source_file", "hash", "path", "filename")
    ):
        weak_search_penalty = 0.14
    domain_bonus = 0.0
    if any(
        token in (lowered_text + " " + lowered_table)
        for token in ("material", "test", "result", "approval", "precedent", "environment", "failure", "rationale", "concern")
    ):
        domain_bonus = 0.08
    priority_weight = {
        "high": 1.0,
        "medium": 0.72,
        "low": 0.45,
    }.get(question.priority, 0.6)
    template_weight = {
        "text_search": 0.88,
        "categorical_filter": 0.82,
        "detail_view": 0.72,
        "aggregation": 0.76,
        "relationship_join": 1.0,
        "comparison": 0.84,
        "time_series": 0.72,
        "cross_reference": 0.34,
    }.get(question.template_type, 0.55)
    discovery_bonus = {
        "schema_pattern": 0.05,
        "relationship": 0.08,
        "semantic": 0.02,
        "entropy": -0.16,
        "llm_refinement": -0.02,
    }.get(question.discovery_source, 0.0)
    caveat_penalty = min(len(question.data_caveats) * 0.03, 0.18)
    join_penalty = 0.04 * max(0, len(question.join_tables) - 1)
    text_penalty = 0.03 if "hidden relationship" in lowered_text else 0.0
    return round(
        (question.confidence.score * 0.62)
        + (priority_weight * 0.22)
        + (template_weight * 0.16)
        + discovery_bonus
        + domain_bonus
        - caveat_penalty
        - join_penalty
        - text_penalty
        - low_value_table_penalty
        - identifier_metric_penalty
        - weak_search_penalty,
        4,
    )


def _template_budgets(total_budget: int) -> dict[str, int]:
    budgets = {
        "text_search": max(6, round(total_budget * 0.05)),
        "categorical_filter": max(12, round(total_budget * 0.12)),
        "aggregation": max(16, round(total_budget * 0.14)),
        "comparison": max(12, round(total_budget * 0.1)),
        "time_series": max(10, round(total_budget * 0.08)),
        "detail_view": max(8, round(total_budget * 0.08)),
        "relationship_join": max(28, round(total_budget * 0.24)),
        "cross_reference": max(8, round(total_budget * 0.06)),
    }
    # Soft normalization if minimums overshoot the total budget.
    while sum(budgets.values()) > total_budget:
        largest = max(budgets, key=budgets.get)
        if budgets[largest] <= 1:
            break
        budgets[largest] -= 1
    return budgets


def _prune_questions(
    categories: list[QuestionCategory],
    *,
    max_generated_questions: int,
    max_questions_per_table: int,
) -> list[QuestionCategory]:
    if max_generated_questions <= 0:
        return categories

    flat_questions = [question for category in categories for question in category.questions]
    if len(flat_questions) <= max_generated_questions:
        return categories

    deduped: dict[tuple[str, str, tuple[str, ...], tuple[str, ...], str], Question] = {}
    for question in flat_questions:
        signature = (
            question.template_type,
            question.target_table,
            tuple(sorted(question.target_columns)),
            tuple(sorted(question.join_tables)),
            question.natural_language.strip().lower(),
        )
        existing = deduped.get(signature)
        if existing is None or _template_score(question) > _template_score(existing):
            deduped[signature] = question
    flat_questions = list(deduped.values())
    if len(flat_questions) <= max_generated_questions:
        kept_ids = {question.id for question in flat_questions}
        pruned_categories: list[QuestionCategory] = []
        for category in categories:
            questions = [question for question in category.questions if question.id in kept_ids]
            if questions:
                pruned_categories.append(QuestionCategory(category=category.category, questions=questions))
        return pruned_categories

    template_budgets = _template_budgets(max_generated_questions)
    table_counts: dict[str, int] = defaultdict(int)
    template_counts: dict[str, int] = defaultdict(int)

    ranked = sorted(
        flat_questions,
        key=lambda question: (
            _template_score(question),
            question.confidence.score,
            question.priority == "high",
            question.template_type != "cross_reference",
        ),
        reverse=True,
    )

    kept_ids: set[str] = set()
    kept: list[Question] = []
    for question in ranked:
        if len(kept) >= max_generated_questions:
            break
        if table_counts[question.target_table] >= max_questions_per_table:
            continue
        if template_counts[question.template_type] >= template_budgets.get(question.template_type, max_generated_questions):
            continue
        kept.append(question)
        kept_ids.add(question.id)
        table_counts[question.target_table] += 1
        template_counts[question.template_type] += 1

    pruned_categories: list[QuestionCategory] = []
    for category in categories:
        questions = [question for question in category.questions if question.id in kept_ids]
        if questions:
            pruned_categories.append(QuestionCategory(category=category.category, questions=questions))
    return pruned_categories


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def generate_questions_enhanced(
    manifest: SchemaManifest,
    semantic_map: SemanticMap | None = None,
    relationship_graph: RelationshipGraph | None = None,
    latent_relationships: LatentRelationships | None = None,
    data_quality_report: DataQualityReport | None = None,
    max_generated_questions: int = 240,
    max_questions_per_table: int = 6,
) -> QuestionMap:
    """Enhanced v4.1 question generation.

    Wraps the deterministic generator with semantic enrichment,
    quality gating, relationship-aware questions, and capability mapping.

    Falls back to basic deterministic generation if no v4.1 artifacts provided.
    """
    # Build lookups
    sem_lookup = _build_semantic_lookup(semantic_map)
    quality_lookup = _build_quality_lookup(data_quality_report)

    # Pass 1: Deterministic questions (existing logic)
    builder = _QuestionBuilder()
    for table in manifest.tables:
        _process_table(builder, table, manifest)

    # Pass 1b: Relationship-aware questions
    _generate_relationship_questions(
        builder, manifest, relationship_graph, latent_relationships,
        sem_lookup, quality_lookup,
    )

    categories = builder.build()

    # Enrich all questions with semantic context and quality scores
    for cat in categories:
        for q in cat.questions:
            # Semantic enrichment
            enriched_text, ctx = _enrich_question_text(
                q.natural_language, q.target_table, q.target_columns, sem_lookup,
            )
            q.natural_language = enriched_text
            if ctx:
                q.semantic_context = ctx

            # Quality gating
            conf, caveats = _compute_question_confidence(
                q.target_table, q.target_columns, quality_lookup,
            )
            if q.confidence.score == 1.0 and q.confidence.method == "deterministic":
                # Only override default confidence; don't override relationship-set ones
                q.confidence = ConfidenceScore(
                    score=conf,
                    source="question_gen",
                    method="quality_gated",
                    inputs=[f"{q.target_table}.{c}" for c in q.target_columns if c != "*"],
                    threshold=0.7,
                    action_if_below="add_caveat_to_ui",
                )
            q.data_caveats = caveats

    categories = _prune_questions(
        categories,
        max_generated_questions=max_generated_questions,
        max_questions_per_table=max_questions_per_table,
    )

    # Flatten for capability mapping
    all_questions = [q for cat in categories for q in cat.questions]

    # Build capability map
    cap_entries, reliable, caveated = _build_capability_map(all_questions, quality_lookup)

    # Enhanced domain summary
    domain_summary = _build_enhanced_domain_summary(manifest, semantic_map)

    return QuestionMap(
        database_name=manifest.database_name,
        domain_summary=domain_summary,
        question_categories=categories,
        recommended_landing_page=_determine_landing_page(categories),
        estimated_ui_pages=_estimate_pages(categories),
        capability_map=cap_entries,
        total_reliable=reliable,
        total_caveated=caveated,
    )
