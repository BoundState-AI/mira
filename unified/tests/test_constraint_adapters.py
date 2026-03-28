from __future__ import annotations

from unified._compat import import_forge_contract_models
from unified.constraints.constraint_adapter import gptl_constraint_to_forge_contract
from unified.constraints.contract_adapter import forge_contract_to_constraint_rule
from unified.constraints.unified_pack import UnifiedRulePack


forge_models = import_forge_contract_models()
Contract = forge_models.Contract
ContractSeverity = forge_models.ContractSeverity
ContractType = forge_models.ContractType
RulePack = forge_models.RulePack


def test_forge_to_gptl_round_trip_preserves_contract() -> None:
    contract = Contract(
        id="C-001",
        type=ContractType.AUTHORITY,
        severity=ContractSeverity.HARD,
        rule="Never override Body of Knowledge prohibitions",
        reason="Authority tables were detected.",
        keywords=["prohibited", "authority"],
        regex_patterns=[r"\\bprohibited\\b"],
        min_evidence_sources=2,
        violation_response="This cannot be overridden.",
    )

    adapted = forge_contract_to_constraint_rule(contract)
    restored = gptl_constraint_to_forge_contract(adapted)

    assert restored.model_dump(mode="json") == contract.model_dump(mode="json")


def test_sensitivity_and_domain_contracts_remain_pass_through() -> None:
    sensitivity = Contract(
        id="C-002",
        type=ContractType.SENSITIVITY,
        severity=ContractSeverity.HARD,
        rule="Never disclose controlled data",
        reason="PII and controlled markers exist",
    )
    domain = Contract(
        id="C-003",
        type=ContractType.DOMAIN,
        severity=ContractSeverity.SOFT,
        rule="Stay within module vocabulary",
        reason="Domain-scoped assistant",
    )
    pack = UnifiedRulePack.from_forge_rule_pack(
        RulePack(contracts=[sensitivity, domain]).finalize()
    )

    assert pack.gptl_constraints == []
    assert [contract.id for contract in pack.pass_through_contracts] == ["C-002", "C-003"]

