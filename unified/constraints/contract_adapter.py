from __future__ import annotations

import base64
import json
from typing import Any

from unified._compat import bootstrap_forge_aliases, import_forge_contract_models, import_gptl_schema

bootstrap_forge_aliases()

forge_models = import_forge_contract_models()
gptl_schema = import_gptl_schema()

Contract = forge_models.Contract
ContractSeverity = forge_models.ContractSeverity
ContractType = forge_models.ContractType
ConstraintAction = gptl_schema.ConstraintAction
ConstraintCondition = gptl_schema.ConstraintCondition
ConstraintRule = gptl_schema.ConstraintRule


PASS_THROUGH_TYPES = {ContractType.SENSITIVITY, ContractType.DOMAIN}
FORGE_PROMPT_PREFIX = "__FORGE_CONTRACT__::"


def is_pass_through_contract(contract: Any) -> bool:
    return contract.type in PASS_THROUGH_TYPES


def _severity_to_action(severity: ContractSeverity) -> ConstraintAction:
    mapping = {
        ContractSeverity.HARD: ConstraintAction.HARD_DROP,
        ContractSeverity.SOFT: ConstraintAction.SOFT_DROP,
        ContractSeverity.ADVISORY: ConstraintAction.WARN,
    }
    return mapping[severity]


def _priority_for_severity(severity: ContractSeverity) -> int:
    return {
        ContractSeverity.HARD: 10,
        ContractSeverity.SOFT: 50,
        ContractSeverity.ADVISORY: 90,
    }[severity]


def serialize_contract(contract: Any) -> str:
    payload = json.dumps(contract.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    return FORGE_PROMPT_PREFIX + base64.b64encode(payload).decode("ascii")


def forge_contract_to_constraint_rule(contract: Any) -> Any | None:
    if is_pass_through_contract(contract):
        return None

    conditions = [
        ConstraintCondition(
            field="forge_contract_type",
            operator="eq",
            value=contract.type.value,
        )
    ]

    if contract.keywords:
        conditions.append(
            ConstraintCondition(
                field="query_terms",
                operator="contains_any",
                value=contract.keywords,
            )
        )
    if contract.min_evidence_sources:
        conditions.append(
            ConstraintCondition(
                field="evidence.source_count",
                operator="gte",
                value=contract.min_evidence_sources,
            )
        )

    return ConstraintRule(
        rule_id=contract.id,
        name=f"forge_{contract.type.value.lower()}",
        description=contract.rule,
        action=_severity_to_action(contract.severity),
        conditions=conditions,
        applies_to_intents=[],
        priority=_priority_for_severity(contract.severity),
        penalty_weight=1.0 if contract.severity == ContractSeverity.SOFT else None,
        requires_semantic_check=False,
        semantic_check_prompt=serialize_contract(contract),
        source="forge_contract_adapter",
    )

