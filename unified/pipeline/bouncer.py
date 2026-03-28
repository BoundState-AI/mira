from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from unified.constraints.unified_pack import UnifiedRulePack
from unified.schema import AUTHORITY_BOUNDARY_TEXT


class BouncerDecision(BaseModel):
    accepted: bool
    verdict: str
    reason: str
    intent: str
    matched_contracts: list[str] = Field(default_factory=list)
    guidance: str = ""


_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?|prompts?)",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(a|an)\s+",
    r"override\s+(your|the)\s+(rules?|instructions?|contracts?)",
    r"system\s*prompt",
    r"jailbreak",
]

_AUTHORITY_BOUNDARY_TERMS = [
    "approve",
    "approval",
    "acceptance authority",
    "sign off",
    "allowable",
    "design-value",
    "design value",
    "alternative design-value method",
]


class UnifiedBouncer:
    def __init__(self, rule_pack: UnifiedRulePack | None = None) -> None:
        self._rule_pack = rule_pack or UnifiedRulePack()
        self._compiled_injection = [re.compile(pattern, re.IGNORECASE) for pattern in _INJECTION_PATTERNS]

    def evaluate(self, query: str) -> BouncerDecision:
        lower = query.lower()
        if any(pattern.search(query) for pattern in self._compiled_injection):
            return BouncerDecision(
                accepted=False,
                verdict="rejected",
                reason="Prompt injection detected.",
                intent="general_query",
            )

        if any(term in lower for term in _AUTHORITY_BOUNDARY_TERMS):
            return BouncerDecision(
                accepted=False,
                verdict="rejected",
                reason=AUTHORITY_BOUNDARY_TEXT,
                intent="liability_assessment",
                guidance="Provide draft rationale only; do not request approval or acceptance authority.",
            )

        matched_contracts: list[str] = []
        for contract in self._rule_pack.pass_through_contracts:
            for keyword in getattr(contract, "keywords", []) or []:
                if keyword.lower() in lower:
                    matched_contracts.append(contract.id)
                    if getattr(contract, "severity", None).value == "HARD":
                        return BouncerDecision(
                            accepted=False,
                            verdict="rejected",
                            reason=contract.rule,
                            intent=self.classify_intent(query),
                            matched_contracts=matched_contracts,
                        )

        return BouncerDecision(
            accepted=True,
            verdict="accepted",
            reason="Query accepted.",
            intent=self.classify_intent(query),
            matched_contracts=matched_contracts,
        )

    @staticmethod
    def classify_intent(query: str) -> str:
        lower = query.lower()
        heuristics: list[tuple[list[str], str]] = [
            (["comply", "requirement", "meets spec", "shall"], "compliance_check"),
            (["compatible", "compatibility", "incompatible"], "compatibility_check"),
            (["compare", "difference", "versus", "vs"], "property_comparison"),
            (["process", "procedure", "how to"], "process_guidance"),
            (["risk", "liability"], "liability_assessment"),
            (["substitute", "replacement"], "substitution_analysis"),
            (["failure", "crack", "rupture"], "failure_prediction"),
            (["material", "strength", "property"], "material_lookup"),
        ]
        for tokens, intent in heuristics:
            if any(token in lower for token in tokens):
                return intent
        return "general_query"

