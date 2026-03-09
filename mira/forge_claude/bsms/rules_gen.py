"""Generate rules.py for a FORGE-generated BSMS application."""

from __future__ import annotations

from textwrap import dedent


def generate_rules_code() -> str:
    """Return the rules engine module source code.

    The rules engine is the third stage (M) of B-S-M-S:
    - Fully deterministic — no LLM in this stage
    - Human review gate: detects safety/compliance terms
    - Authority pack gate checking
    - Question execution against the database
    """
    return dedent('''\
        from __future__ import annotations

        from authority_pack import load_authority_pack
        from query_service import execute_question, find_question

        _HUMAN_REVIEW_TERMS = {
            "approve",
            "certify",
            "guarantee",
            "sign off",
            "safety critical",
            "compliance decision",
        }


        def _gate_query(query: str) -> dict:
            lowered = query.lower()
            hits = sorted(term for term in _HUMAN_REVIEW_TERMS if term in lowered)
            return {
                "status": "human_review_required" if hits else "approved",
                "matches": hits,
            }


        def run_rules(parsed_intent: dict, limit: int, *, query: str, bouncer: dict) -> dict:
            pack = load_authority_pack()
            question = find_question(parsed_intent["question_id"])
            filters = parsed_intent.get("filters", {})
            gate = _gate_query(query)
            rules_applied = [question["question_type"], "authority_pack", "gate_check"]
            if gate["status"] != "approved":
                return {
                    "verdict": "HUMAN_REVIEW_REQUIRED",
                    "confidence": parsed_intent.get("confidence", question.get("utility_score", 0.5)),
                    "payload": None,
                    "gate": gate,
                    "rules_applied": rules_applied,
                    "authority_pack_status": pack["manifest"].get("status"),
                }

            result = execute_question(
                parsed_intent["question_id"],
                limit=limit,
                filters=filters,
                execution_context={
                    "bouncer_verdict": "PASS" if bouncer["status"] == "accepted" else "REJECT",
                    "parsed_intent": parsed_intent,
                    "rules_applied": rules_applied,
                    "confidence": parsed_intent.get("confidence", question.get("utility_score", 0.5)),
                    "user": "generated_app_bsms",
                    "decision_source": parsed_intent.get("decision_source", "deterministic_parser"),
                    "original_query": query,
                    "bsms_runtime": parsed_intent.get("llm_runtime"),
                },
            )
            return {
                "verdict": "SUPPORTED",
                "confidence": parsed_intent.get("confidence", result["question"].get("utility_score", 0.5)),
                "payload": result,
                "gate": gate,
                "rules_applied": rules_applied,
                "authority_pack_status": pack["manifest"].get("status"),
            }
    ''')
