from __future__ import annotations

import base64
import json

from unified._compat import bootstrap_forge_aliases, import_forge_contract_models, import_gptl_schema
from unified.constraints.contract_adapter import FORGE_PROMPT_PREFIX

bootstrap_forge_aliases()

forge_models = import_forge_contract_models()
gptl_schema = import_gptl_schema()

Contract = forge_models.Contract
ContractSeverity = forge_models.ContractSeverity
ContractType = forge_models.ContractType
ConstraintAction = gptl_schema.ConstraintAction


def _action_to_severity(action: ConstraintAction) -> ContractSeverity:
    mapping = {
        ConstraintAction.HARD_DROP: ContractSeverity.HARD,
        ConstraintAction.SOFT_DROP: ContractSeverity.SOFT,
        ConstraintAction.WARN: ContractSeverity.ADVISORY,
        ConstraintAction.PASS: ContractSeverity.ADVISORY,
    }
    return mapping[action]


def _guess_contract_type(rule_name: str, description: str) -> ContractType:
    combined = f"{rule_name} {description}".lower()
    if "authority" in combined or "standard" in combined:
        return ContractType.AUTHORITY
    if "boundary" in combined or "range" in combined:
        return ContractType.BOUNDARY
    if "evidence" in combined:
        return ContractType.EVIDENCE
    if "absence" in combined or "missing" in combined:
        return ContractType.ABSENCE
    return ContractType.HALLUCINATION


def gptl_constraint_to_forge_contract(rule) -> Contract:
    encoded = getattr(rule, "semantic_check_prompt", None) or ""
    if encoded.startswith(FORGE_PROMPT_PREFIX):
        payload = encoded.split(FORGE_PROMPT_PREFIX, 1)[1]
        decoded = base64.b64decode(payload.encode("ascii")).decode("utf-8")
        return Contract.model_validate(json.loads(decoded))

    contract_type = _guess_contract_type(rule.name, rule.description)
    severity = _action_to_severity(rule.action)
    keywords = []
    min_sources = 0
    conditions = rule.conditions if isinstance(rule.conditions, list) else []
    for condition in conditions:
        if getattr(condition, "field", "") == "query_terms" and isinstance(condition.value, list):
            keywords = list(condition.value)
        if getattr(condition, "field", "") == "evidence.source_count":
            min_sources = int(condition.value)

    return Contract(
        id=rule.rule_id,
        type=contract_type,
        severity=severity,
        rule=rule.description,
        reason=f"Generated from GPTL constraint '{rule.name}'",
        keywords=keywords,
        min_evidence_sources=min_sources,
        violation_response=rule.description,
        pack_origin="gptl_adapter",
    )

