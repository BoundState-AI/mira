"""API client stub generation."""

from __future__ import annotations

from mira.forge_claude.question_gen.question_map import QuestionMap


def build_api_endpoints(question_map: QuestionMap) -> list[dict]:
    """Build API endpoint definitions from question map."""
    endpoints = []
    seen = set()

    for cat in question_map.question_categories:
        for q in cat.questions:
            if q.template_type == "text_search":
                key = f"search_{q.target_table}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"search{_pascal(q.target_table)}",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/search",
                        "params": "query",
                        "description": q.natural_language,
                    })

            elif q.template_type == "categorical_filter":
                key = f"filter_{q.target_table}_{q.target_columns[0]}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"filter{_pascal(q.target_table)}By{_pascal(q.target_columns[0])}",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/filter",
                        "params": q.target_columns[0],
                        "description": q.natural_language,
                    })

            elif q.template_type == "aggregation":
                key = f"stats_{q.target_table}_{q.target_columns[0]}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"get{_pascal(q.target_table)}Stats",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/stats",
                        "params": None,
                        "description": q.natural_language,
                    })

            elif q.template_type == "detail_view":
                key = f"detail_{q.target_table}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"get{_pascal(q.target_table)}Detail",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/{{id}}",
                        "params": "id",
                        "description": q.natural_language,
                    })

            elif q.template_type == "comparison":
                key = f"compare_{q.target_table}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"compare{_pascal(q.target_table)}",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/compare",
                        "params": ", ".join(q.target_columns),
                        "description": q.natural_language,
                    })

            elif q.template_type == "time_series":
                key = f"timeline_{q.target_table}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"get{_pascal(q.target_table)}Timeline",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/timeline",
                        "params": q.target_columns[0],
                        "description": q.natural_language,
                    })

            elif q.template_type == "cross_reference":
                join_table = q.join_tables[0] if q.join_tables else "related"
                key = f"crossref_{q.target_table}_{join_table}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"crossRef{_pascal(q.target_table)}With{_pascal(join_table)}",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/cross-ref/{join_table}",
                        "params": q.target_columns[0] if q.target_columns else None,
                        "description": q.natural_language,
                    })

            elif q.template_type == "relationship_join":
                join_table = q.join_tables[0] if q.join_tables else "related"
                key = f"join_{q.target_table}_{join_table}"
                if key not in seen:
                    seen.add(key)
                    endpoints.append({
                        "name": f"join{_pascal(q.target_table)}With{_pascal(join_table)}",
                        "method": "GET",
                        "path": f"/api/{q.target_table}/join/{join_table}",
                        "params": q.target_columns[0] if q.target_columns else None,
                        "description": q.natural_language,
                    })

    return endpoints


def _pascal(name: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in name.split("_"))
