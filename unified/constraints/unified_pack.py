from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from unified.constraints.conflict_rules import CrossSourceRule, DEFAULT_CROSS_SOURCE_RULES
from unified.constraints.contract_adapter import forge_contract_to_constraint_rule, is_pass_through_contract
from unified.schema import AUTHORITY_BOUNDARY_TEXT


class UnifiedRulePack(BaseModel):
    forge_rule_pack: Any | None = None
    gptl_constraints: list[Any] = Field(default_factory=list)
    pass_through_contracts: list[Any] = Field(default_factory=list)
    cross_source_rules: list[CrossSourceRule] = Field(default_factory=lambda: list(DEFAULT_CROSS_SOURCE_RULES))
    authority_boundary: str = AUTHORITY_BOUNDARY_TEXT

    @classmethod
    def from_forge_rule_pack(cls, forge_rule_pack: Any) -> "UnifiedRulePack":
        constraints = []
        pass_through = []
        for contract in getattr(forge_rule_pack, "contracts", []):
            if is_pass_through_contract(contract):
                pass_through.append(contract)
                continue
            adapted = forge_contract_to_constraint_rule(contract)
            if adapted is not None:
                constraints.append(adapted)
        return cls(
            forge_rule_pack=forge_rule_pack,
            gptl_constraints=constraints,
            pass_through_contracts=pass_through,
        )

