"""Generate formatter.py for a FORGE-generated BSMS application."""

from __future__ import annotations

from textwrap import dedent


def generate_formatter_code() -> str:
    """Return the formatter module source code.

    The formatter is the fourth stage (S) of B-S-M-S:
    - Deterministic answer: template-based from rules packet
    - LLM format (optional): natural language grounded in payload
    - Evidence-first citation
    - Fail-closed: if LLM fails and require_llm=True, raises
    """
    return dedent('''\
        from __future__ import annotations

        import json

        from llm import complete_json, llm_status


        def _preview_payload(result: dict) -> dict:
            results = result.get("results", {})
            preview = {}
            for key, value in results.items():
                if key == "rows" and isinstance(value, list):
                    preview[key] = value[:5]
                else:
                    preview[key] = value
            return {
                "question": result.get("question"),
                "results": preview,
                "executed_query": result.get("executed_query"),
                "lineage": result.get("lineage"),
            }


        def _deterministic_answer(rules_packet: dict) -> str:
            if rules_packet["verdict"] == "HUMAN_REVIEW_REQUIRED":
                return "This request requires human review before FORGE can return an authoritative answer."
            result = rules_packet["payload"]
            question = result["question"]
            results = result["results"]
            if "summary" in results:
                summary = results["summary"]
                return (
                    f"FORGE ran \\'{question['question']}\\' on \\'{question['table']}\\' "
                    f"and computed min={summary.get('min')}, max={summary.get('max')}, avg={summary.get('avg')}."
                )
            if "rows" in results:
                return (
                    f"FORGE matched \\'{question['question']}\\' on \\'{question['table']}\\' "
                    f"and returned {len(results['rows'])} row(s)."
                )
            return f"FORGE matched \\'{question['question']}\\' on \\'{question['table']}\\'."


        def _llm_format(query: str, parsed_intent: dict, rules_packet: dict) -> tuple[dict, dict]:
            system = (
                "You are the FORGE BSMS formatter. "
                "Write a concise answer grounded only in the provided result packet. "
                "Do not invent facts or claim certainty beyond the payload. "
                "Return only JSON."
            )
            user = json.dumps(
                {
                    "query": query,
                    "parsed_intent": parsed_intent,
                    "rules_packet": {
                        "verdict": rules_packet["verdict"],
                        "confidence": rules_packet["confidence"],
                        "gate": rules_packet.get("gate"),
                        "rules_applied": rules_packet.get("rules_applied"),
                        "payload_preview": _preview_payload(rules_packet["payload"]) if rules_packet.get("payload") else None,
                    },
                    "required_json_schema": {
                        "answer": "string",
                        "follow_up": "string or null",
                        "confidence_label": "low|medium|high",
                    },
                },
                indent=2,
            )
            return complete_json(system, user, max_tokens=500, temperature=0.1)


        def format_response(query: str, parsed_intent: dict, rules_packet: dict) -> dict:
            result = rules_packet.get("payload")
            citations = result["lineage"]["evidence_sources"] if result else []
            answer = _deterministic_answer(rules_packet)
            rendering_source = "deterministic_formatter"
            status = llm_status()
            llm_meta = None
            if status["enabled"]:
                try:
                    formatted, meta = _llm_format(query, parsed_intent, rules_packet)
                    answer = formatted.get("answer") or answer
                    llm_meta = {"model": meta.get("model"), "confidence_label": formatted.get("confidence_label")}
                    rendering_source = "llm_formatter"
                except Exception as exc:
                    if status["require_llm"]:
                        raise RuntimeError(f"BSMS formatter failed closed: {exc}") from exc
                    llm_meta = {"error": str(exc)}
            return {
                "answer": answer,
                "citations": citations,
                "lineage": result["lineage"] if result else None,
                "parsed_intent": parsed_intent,
                "result": result,
                "rendering_source": rendering_source,
                "llm_runtime": status,
                "llm": llm_meta,
            }
    ''')
