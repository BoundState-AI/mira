from __future__ import annotations

from mira.forge_claude.introspector.manifest import ConfidenceScore, SchemaManifest
from mira.forge_claude.introspector.manifest import ColumnInfo, ForeignKey, TableInfo
from mira.forge_claude.question_gen.curator import (
    _MatchedQuestion,
    _candidate_archetypes,
    _composite_score,
    _ensure_diversity,
    _get_archetype,
    _infer_capability_coverage,
    _semantic_dedup,
    StructuralMotif,
)
from mira.forge_claude.question_gen.deterministic import _is_identifierish
from mira.forge_claude.question_gen.enhanced import _template_score
from mira.forge_claude.question_gen.execution_plans import annotate_question_map_with_execution_plans
from mira.forge_claude.question_gen.question_map import Question, QuestionCategory, QuestionMap


def test_identifierish_columns_are_recognized() -> None:
    assert _is_identifierish("material_code")
    assert _is_identifierish("test_id")
    assert _is_identifierish("source_hash")
    assert not _is_identifierish("pressure_psia")
    assert not _is_identifierish("temperature_c")


def test_relationship_questions_outrank_identifier_aggregations() -> None:
    identifier_aggregation = Question(
        id="q1",
        natural_language="What is the min/max/average material code for flammability tests?",
        template_type="aggregation",
        target_table="flammability_tests",
        target_columns=["material_code"],
        join_tables=[],
        ui_component="StatsBar",
        priority="medium",
        confidence=ConfidenceScore(score=1.0, source="question_gen", method="quality_gated"),
    )
    relationship_question = Question(
        id="q2",
        natural_language="Which materials have flammability test results and what ratings did they receive?",
        template_type="relationship_join",
        target_table="flammability_tests",
        target_columns=["material_code", "nasa_6001_rating"],
        join_tables=["flammability_test_results", "materials"],
        ui_component="ResultsTable",
        priority="high",
        confidence=ConfidenceScore(score=0.92, source="question_gen", method="join_viability"),
        discovery_source="relationship",
    )

    assert _template_score(relationship_question) > _template_score(identifier_aggregation)


def test_curator_evidence_question_outranks_report_number_search() -> None:
    search_table = TableInfo(
        name="corrosion_tests",
        row_count=250,
        columns=[ColumnInfo(name="test_report_no", type="text", unique_count=250)],
    )
    evidence_table = TableInfo(
        name="toxicity_tests",
        row_count=400,
        columns=[ColumnInfo(name="material_code", type="text", unique_count=180)],
        foreign_keys=[ForeignKey(column="material_code", references_table="materials", references_column="material_code")],
    )

    report_search = _MatchedQuestion(
        archetype=_get_archetype("primary_search"),
        table=search_table,
        target_columns=["test_report_no"],
        join_tables=[],
        natural_language="Search corrosion test by test report no",
        value_score=0.83,
        data_quality_score=1.0,
        confidence=0.86,
    )
    evidence_question = _MatchedQuestion(
        archetype=_get_archetype("evidence_check"),
        table=evidence_table,
        target_columns=["material_code"],
        join_tables=["materials"],
        natural_language="What toxicity evidence exists for a given material?",
        value_score=1.06,
        data_quality_score=1.0,
        confidence=0.92,
    )

    assert _composite_score(evidence_question) > _composite_score(report_search)


def test_curator_diversity_caps_repetitive_material_parent_questions() -> None:
    matched = []
    for index, table_name in enumerate(
        [
            "fluid_compatibility_tests",
            "mechanical_impact_tests",
            "toxicity_tests",
        ],
        start=1,
    ):
        matched.append(
            _MatchedQuestion(
                archetype=_get_archetype("parent_child_nav"),
                table=TableInfo(
                    name=table_name,
                    row_count=200 + index,
                    columns=[ColumnInfo(name="material_code", type="text", unique_count=100)],
                    foreign_keys=[ForeignKey(column="material_code", references_table="materials", references_column="material_code")],
                ),
                target_columns=["material_code"],
                join_tables=["materials"],
                natural_language=f"Show all {table_name} for a given material",
                value_score=1.0,
                data_quality_score=1.0,
                confidence=0.95,
            )
        )

    matched.append(
        _MatchedQuestion(
            archetype=_get_archetype("detail_view"),
            table=TableInfo(
                name="mua_concerns",
                row_count=100,
                columns=[ColumnInfo(name="id", type="integer"), ColumnInfo(name="raw_issue_text", type="text")],
            ),
            target_columns=["*"],
            join_tables=["mua_records"],
            natural_language="Show complete details for a specific MUA concern",
            value_score=0.9,
            data_quality_score=1.0,
            confidence=0.95,
        )
    )

    selected = _ensure_diversity(sorted(matched, key=_composite_score, reverse=True), max_questions=4)
    material_parent_count = sum(1 for mq in selected if mq.join_tables and mq.join_tables[0] == "materials")

    assert material_parent_count <= 2
    assert any(mq.table.name == "mua_concerns" for mq in selected)


def test_semantic_dedup_keeps_higher_value_relationship_variant() -> None:
    evidence = _MatchedQuestion(
        archetype=_get_archetype("evidence_check"),
        table=TableInfo(name="toxicity_tests", row_count=300, columns=[]),
        target_columns=["material_code"],
        join_tables=["materials"],
        natural_language="What toxicity evidence exists for a given material?",
        value_score=1.05,
        data_quality_score=1.0,
        confidence=0.92,
    )
    navigation = _MatchedQuestion(
        archetype=_get_archetype("parent_child_nav"),
        table=TableInfo(name="toxicity_tests", row_count=300, columns=[]),
        target_columns=["material_code"],
        join_tables=["materials"],
        natural_language="Show all toxicity tests for a given material",
        value_score=0.96,
        data_quality_score=1.0,
        confidence=0.95,
    )

    deduped = _semantic_dedup([navigation, evidence])

    assert len(deduped) == 1
    assert deduped[0].archetype.intent_id == "evidence_check"


def test_capability_coverage_and_candidates_reflect_detected_motifs() -> None:
    selected = [
        _MatchedQuestion(
            archetype=_get_archetype("evidence_check"),
            table=TableInfo(name="toxicity_tests", row_count=300, columns=[]),
            target_columns=["material_code"],
            join_tables=["materials"],
            natural_language="What toxicity evidence exists for a given material?",
            value_score=1.05,
            data_quality_score=1.0,
            confidence=0.92,
        )
    ]
    motifs = [
        StructuralMotif(
            motif_type="evidence_chain",
            tables=["toxicity_tests", "materials"],
            columns=["material_code"],
            confidence=0.92,
            description="toxicity_tests forms an evidence chain into materials.",
        ),
        StructuralMotif(
            motif_type="record_context",
            tables=["mua_records", "materials"],
            columns=["material_code"],
            confidence=0.9,
            description="mua_records captures record context linked to materials.",
        ),
    ]

    coverage = _infer_capability_coverage(motifs, selected)
    candidates = _candidate_archetypes(motifs, selected)

    coverage_map = {entry.capability_id: entry.support_level for entry in coverage}
    assert coverage_map["evidence_trace"] == "strong"
    assert coverage_map["precedent_context"] == "partial"
    assert any(candidate.motif_type == "record_context" for candidate in candidates)


def test_execution_plan_annotation_adds_runtime_contract() -> None:
    manifest_table = TableInfo(
        name="h2_knowledge.evidence",
        row_count=371,
        columns=[
            ColumnInfo(name="material_name", type="text", unique_count=120),
            ColumnInfo(name="material_family", type="text", unique_count=18),
            ColumnInfo(name="hee_index", type="float", null_count=3),
            ColumnInfo(name="reference_gas", type="text", unique_count=4),
            ColumnInfo(name="pressure_mpa", type="float", unique_count=35),
        ],
    )
    question_map = QuestionMap(
        database_name="mira_h2",
        summary={
            "question_count": 1,
            "question_categories": 1,
            "top_tables": ["h2_knowledge.evidence"],
            "question_type_mix": {"Material Safety": 1},
        },
        question_categories=[
            QuestionCategory(
                category="Material Safety",
                questions=[
                    Question(
                        id="q_material_safety",
                        natural_language="Which materials show severe hydrogen embrittlement and should be avoided?",
                        template_type="filter",
                        target_table="h2_knowledge.evidence",
                        target_columns=["material_name", "material_family", "hee_index", "reference_gas", "pressure_mpa"],
                        join_tables=[],
                        ui_component="ResultsTable",
                        priority="high",
                        confidence=ConfidenceScore(score=0.96, source="question_gen", method="curated"),
                    )
                ],
            )
        ],
    )

    manifest = SchemaManifest(
        database_type="postgresql",
        database_name="mira_h2",
        tables=[manifest_table],
    )

    annotated = annotate_question_map_with_execution_plans(question_map, manifest)
    question = annotated.all_questions()[0]

    assert question.capability_id == "material_safety_ranking"
    assert question.intent_family == "risk_ranking"
    assert question.execution_plan["plan_type"] == "risk_ranking"
    assert question.execution_plan["entity_table"] == "h2_knowledge.evidence"
    assert "hee_index" in question.execution_plan["metrics"]
    assert "material_name" in question.execution_plan["group_by"]
