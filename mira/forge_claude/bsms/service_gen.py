"""Generate service.py for a FORGE-generated BSMS application."""

from __future__ import annotations

from textwrap import dedent


def generate_service_code() -> str:
    """Return the BSMS service module source code.

    Chains B -> S -> M -> S with rejection, clarification,
    human review, and success paths.
    """
    return dedent('''\
        from __future__ import annotations

        from bsms.bouncer import run_bouncer
        from bsms.formatter import format_response
        from bsms.parser import parse_query
        from bsms.rules import run_rules
        from llm import llm_status


        def run_bsms_query(query: str, limit: int = 25) -> dict:
            bouncer = run_bouncer(query)
            if bouncer["status"] != "accepted":
                return {
                    "status": "rejected",
                    "pipeline": "B-S-M-S",
                    "bouncer": bouncer,
                    "answer": bouncer["reason"],
                    "runtime": {"llm": llm_status()},
                }
            parsed_intent = parse_query(query)
            if parsed_intent.get("clarification_needed"):
                return {
                    "status": "needs_clarification",
                    "pipeline": "B-S-M-S",
                    "bouncer": bouncer,
                    "parsed_intent": parsed_intent,
                    "answer": parsed_intent.get("clarification_question") or "Clarification is required.",
                    "runtime": {"llm": llm_status()},
                }
            rules_packet = run_rules(parsed_intent, limit, query=query, bouncer=bouncer)
            formatted = format_response(query, parsed_intent, rules_packet)
            status = "ok" if rules_packet["verdict"] == "SUPPORTED" else "human_review_required"
            return {
                "status": status,
                "pipeline": "B-S-M-S",
                "bouncer": bouncer,
                "rules": {
                    "verdict": rules_packet["verdict"],
                    "gate": rules_packet.get("gate"),
                    "rules_applied": rules_packet.get("rules_applied", []),
                    "authority_pack_status": rules_packet.get("authority_pack_status"),
                    "confidence": rules_packet.get("confidence"),
                },
                "runtime": {"llm": llm_status()},
                **formatted,
            }
    ''')
