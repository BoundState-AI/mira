"""Generate bouncer.py for a FORGE-generated BSMS application."""

from __future__ import annotations

from textwrap import dedent


def generate_bouncer_code() -> str:
    """Return the bouncer module source code.

    The bouncer is the first stage of the B-S-M-S pipeline:
    - Deterministic guardrail: blocks mutation/admin queries
    - LLM bouncer (optional): validates domain relevance
    - Fail-closed: if LLM fails and require_llm=True, rejects
    """
    return dedent('''\
        from __future__ import annotations

        import json

        from authority_pack import load_authority_pack
        from llm import complete_json, llm_status

        _MUTATION_TERMS = {
            "delete",
            "drop",
            "truncate",
            "update",
            "insert",
            "alter",
            "create",
            "grant",
            "revoke",
        }


        def _deterministic_bouncer(query: str, pack: dict) -> dict:
            lowered = query.lower()
            mutation_flags = sorted(term for term in _MUTATION_TERMS if term in lowered)
            if mutation_flags:
                return {
                    "status": "rejected",
                    "reason": "Mutation or administrative requests are outside the generated BSMS authority.",
                    "risk_flags": mutation_flags,
                    "decision_source": "deterministic_guardrail",
                }
            keywords = [str(keyword).lower() for keyword in pack["bouncer_keywords"]]
            keyword_match = any(keyword and keyword in lowered for keyword in keywords[:200])
            accepted = keyword_match or len(query.split()) >= 3
            return {
                "status": "accepted" if accepted else "rejected",
                "reason": None if accepted else "Query appears outside generated domain vocabulary",
                "risk_flags": [],
                "decision_source": "deterministic_guardrail",
            }


        def _llm_bouncer(query: str, pack: dict) -> tuple[dict, dict]:
            system = (
                "You are the FORGE BSMS bouncer. "
                "Allow only analytical read-only questions grounded in the generated database domain. "
                "Reject requests for mutation, privileged administration, credential handling, or out-of-domain tasks. "
                "Return only JSON."
            )
            user = json.dumps(
                {
                    "query": query,
                    "allowed_intents": pack["bouncer_intents"],
                    "domain_keywords": pack["bouncer_keywords"][:80],
                    "rejection_templates": pack["bouncer_rejection_templates"],
                    "required_json_schema": {
                        "status": "accepted|rejected",
                        "reason": "short string or null",
                        "matched_intent": "string or null",
                        "risk_flags": ["string"],
                        "confidence": 0.0,
                    },
                },
                indent=2,
            )
            parsed, meta = complete_json(system, user, max_tokens=300, temperature=0.0)
            return {
                "status": "accepted" if parsed.get("status") == "accepted" else "rejected",
                "reason": parsed.get("reason"),
                "matched_intent": parsed.get("matched_intent"),
                "risk_flags": [str(flag) for flag in parsed.get("risk_flags", [])][:8],
                "confidence": float(parsed.get("confidence", 0.0) or 0.0),
                "decision_source": "llm_bouncer",
                "llm": {"model": meta.get("model")},
            }, meta


        def run_bouncer(query: str) -> dict:
            pack = load_authority_pack()
            deterministic = _deterministic_bouncer(query, pack)
            status = llm_status()
            if deterministic["status"] == "rejected" and deterministic["decision_source"] == "deterministic_guardrail" and deterministic["risk_flags"]:
                deterministic["llm_runtime"] = status
                return deterministic
            if status["enabled"]:
                try:
                    llm_result, _ = _llm_bouncer(query, pack)
                    llm_result["llm_runtime"] = status
                    return llm_result
                except Exception as exc:
                    if status["require_llm"]:
                        return {
                            "status": "rejected",
                            "reason": f"BSMS LLM bouncer failed closed: {exc}",
                            "risk_flags": ["llm_failure"],
                            "decision_source": "llm_bouncer_failed_closed",
                            "llm_runtime": status,
                        }
                    deterministic["llm_error"] = str(exc)
            deterministic["llm_runtime"] = status
            return deterministic
    ''')
