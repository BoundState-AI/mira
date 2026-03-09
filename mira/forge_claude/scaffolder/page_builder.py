"""Page layout generation from question map."""

from __future__ import annotations

from dataclasses import dataclass, field

from mira.forge_claude.question_gen.question_map import QuestionMap


@dataclass
class PageSpec:
    """Specification for a generated page."""

    name: str
    filename: str
    route: str
    title: str
    components: list[str] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    extra_context: dict = field(default_factory=dict)


def build_pages(question_map: QuestionMap) -> list[PageSpec]:
    """Build page specifications from question map."""
    pages: list[PageSpec] = []

    # Home page — search + filter + results
    home_components = []
    home_questions = []
    for cat in question_map.question_categories:
        if cat.category in ("Search", "Filter & Browse"):
            for q in cat.questions:
                comp = q.ui_component
                if comp not in home_components:
                    home_components.append(comp)
                home_questions.append(q.model_dump())

    # Always include ResultsTable on home
    if "ResultsTable" not in home_components:
        home_components.append("ResultsTable")

    pages.append(
        PageSpec(
            name="Home",
            filename="Home.jsx",
            route="/",
            title=f"{question_map.database_name} Explorer",
            components=home_components,
            questions=home_questions,
        )
    )

    # Analysis page — aggregation, comparison, timeline
    analysis_components = []
    analysis_questions = []
    for cat in question_map.question_categories:
        if cat.category == "Analysis":
            for q in cat.questions:
                comp = q.ui_component
                if comp not in analysis_components:
                    analysis_components.append(comp)
                analysis_questions.append(q.model_dump())

    if analysis_questions:
        pages.append(
            PageSpec(
                name="Analysis",
                filename="Analysis.jsx",
                route="/analysis",
                title="Analysis",
                components=analysis_components,
                questions=analysis_questions,
            )
        )

    # Detail page — detail views
    detail_components = []
    detail_questions = []
    for cat in question_map.question_categories:
        if cat.category == "Detail":
            for q in cat.questions:
                comp = q.ui_component
                if comp not in detail_components:
                    detail_components.append(comp)
                detail_questions.append(q.model_dump())

    if detail_questions:
        pages.append(
            PageSpec(
                name="Detail",
                filename="Detail.jsx",
                route="/detail/:table/:id",
                title="Detail View",
                components=detail_components,
                questions=detail_questions,
            )
        )

    # Data Quality page — v4.1: if capability map is present
    if question_map.capability_map:
        pages.append(
            PageSpec(
                name="DataQuality",
                filename="DataQuality.jsx",
                route="/quality",
                title="Data Quality",
                components=["QualityOverview"],
                extra_context={
                    "capability_map": [e.model_dump() for e in question_map.capability_map],
                    "total_reliable": question_map.total_reliable,
                    "total_caveated": question_map.total_caveated,
                    "domain_summary": question_map.domain_summary,
                    "quality_summary": {},
                },
            )
        )

    return pages
