"""Question type to UI component mapping."""

from __future__ import annotations

# Map from template_type to default UI component
TEMPLATE_TO_COMPONENT = {
    "text_search": "SearchBar",
    "categorical_filter": "FilterSidebar",
    "aggregation": "StatsBar",
    "comparison": "ComparisonView",
    "time_series": "TimelineView",
    "detail_view": "DetailPanel",
    "cross_reference": "ResultsTable",
    "relationship_join": "ResultsTable",
}

# Components that require recharts
CHART_COMPONENTS = {"ComparisonView", "TimelineView", "StatsBar"}

# All available components
ALL_COMPONENTS = {
    "SearchBar",
    "FilterSidebar",
    "ResultsTable",
    "DetailPanel",
    "ComparisonView",
    "TimelineView",
    "StatsBar",
    "QualityOverview",
    "ConfidenceBadge",
}


def pick_component(template_type: str, explicit_component: str | None = None) -> str:
    """Pick the appropriate UI component for a question type."""
    if explicit_component and explicit_component in ALL_COMPONENTS:
        return explicit_component
    return TEMPLATE_TO_COMPONENT.get(template_type, "ResultsTable")


def needs_recharts(components: set[str]) -> bool:
    """Check if any component requires recharts."""
    return bool(components & CHART_COMPONENTS)
