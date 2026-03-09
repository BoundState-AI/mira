"""Generate parser.py for a FORGE-generated BSMS application."""

from __future__ import annotations

from textwrap import dedent


def generate_parser_code() -> str:
    """Return the parser module source code.

    The parser is the second stage (S) of B-S-M-S:
    - Deterministic parse: best-match question by overlap ranking
    - LLM parse (optional): maps query to question + filters
    - Filter sanitization against allowed field mappings
    """
    return dedent('''\
        from __future__ import annotations

        import json
        from typing import Any

        from authority_pack import load_authority_pack
        from llm import complete_json, llm_status
        from query_service import candidate_questions, find_question, list_questions


        def _sanitize_filters(raw_filters: dict[str, Any], table: str, pack: dict) -> dict[str, Any]:
            allowed_columns = set(pack["parser_field_mappings"].get(table, {}).keys())
            sanitized = {}
            for key, value in raw_filters.items():
                if key not in allowed_columns:
                    continue
                if isinstance(value, (str, int, float, bool)) or value is None:
                    sanitized[key] = value
                else:
                    sanitized[key] = str(value)
            return sanitized


        def _deterministic_parse(query: str) -> dict:
            best_question = candidate_questions(query, limit=1)[0]
            return {
                "question_id": best_question["id"],
                "question_type": best_question["question_type"],
                "table": best_question["table"],
                "filters": {},
                "confidence": float(best_question.get("utility_score", 0.5)),
                "rationale": "Selected by deterministic overlap ranking.",
                "decision_source": "deterministic_parser",
            }


        def _llm_parse(query: str, pack: dict) -> tuple[dict, dict]:
            candidates = candidate_questions(query, limit=8)
            system = (
                "You are the FORGE BSMS parser. "
                "Map the user query onto exactly one generated question when possible. "
                "Only emit equality filters using fields that exist on the selected table. "
                "Return only JSON."
            )
            user = json.dumps(
                {
                    "query": query,
                    "candidate_questions": candidates,
                    "field_mappings": {
                        question["table"]: pack["parser_field_mappings"].get(question["table"], {})
                        for question in candidates
                    },
                    "examples": pack["parser_examples"][:6],
                    "required_json_schema": {
                        "question_id": "string",
                        "filters": {"field": "scalar"},
                        "confidence": 0.0,
                        "rationale": "short string",
                        "clarification_needed": False,
                        "clarification_question": "string or null",
                    },
                },
                indent=2,
            )
            parsed, meta = complete_json(system, user, max_tokens=500, temperature=0.0)
            question = find_question(str(parsed["question_id"]))
            return {
                "question_id": question["id"],
                "question_type": question["question_type"],
                "table": question["table"],
                "filters": _sanitize_filters(parsed.get("filters", {}), question["table"], pack),
                "confidence": float(parsed.get("confidence", question.get("utility_score", 0.5)) or 0.0),
                "rationale": parsed.get("rationale") or "Selected by LLM parser.",
                "clarification_needed": bool(parsed.get("clarification_needed", False)),
                "clarification_question": parsed.get("clarification_question"),
                "decision_source": "llm_parser",
                "llm": {"model": meta.get("model")},
            }, meta


        def parse_query(query: str) -> dict:
            if not list_questions()["questions"]:
                raise ValueError("No generated questions available")
            pack = load_authority_pack()
            fallback = _deterministic_parse(query)
            status = llm_status()
            if status["enabled"]:
                try:
                    parsed, _ = _llm_parse(query, pack)
                    parsed["llm_runtime"] = status
                    return parsed
                except Exception as exc:
                    if status["require_llm"]:
                        raise RuntimeError(f"BSMS parser failed closed: {exc}") from exc
                    fallback["llm_error"] = str(exc)
            fallback["llm_runtime"] = status
            return fallback
    ''')
