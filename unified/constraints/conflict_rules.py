from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from unified.schema import AuthorityClass


class CrossSourceRule(BaseModel):
    rule_id: str
    name: str
    description: str
    conflict_policy: Literal[
        "db_wins",
        "doc_wins",
        "newest_wins",
        "highest_authority",
        "require_both",
        "flag_conflict",
    ]
    min_db_evidence: int = 0
    min_doc_evidence: int = 0
    authority_ranking_by_intent: dict[str, list[AuthorityClass]] = Field(
        default_factory=lambda: {
            "material_lookup": [
                AuthorityClass.PRIMARY_TEST_DATA,
                AuthorityClass.SPECIFICATION_REQUIREMENT,
                AuthorityClass.HANDBOOK_VALUE,
                AuthorityClass.HERITAGE_PRECEDENT,
                AuthorityClass.ENGINEERING_JUDGMENT,
                AuthorityClass.VENDOR_DATASHEET,
                AuthorityClass.DERIVED_CALCULATION,
            ],
            "compatibility_check": [
                AuthorityClass.PRIMARY_TEST_DATA,
                AuthorityClass.SPECIFICATION_REQUIREMENT,
                AuthorityClass.HANDBOOK_VALUE,
                AuthorityClass.HERITAGE_PRECEDENT,
                AuthorityClass.ENGINEERING_JUDGMENT,
                AuthorityClass.VENDOR_DATASHEET,
                AuthorityClass.DERIVED_CALCULATION,
            ],
            "compliance_check": [
                AuthorityClass.SPECIFICATION_REQUIREMENT,
                AuthorityClass.PRIMARY_TEST_DATA,
                AuthorityClass.HANDBOOK_VALUE,
                AuthorityClass.HERITAGE_PRECEDENT,
                AuthorityClass.ENGINEERING_JUDGMENT,
                AuthorityClass.VENDOR_DATASHEET,
                AuthorityClass.DERIVED_CALCULATION,
            ],
            "liability_assessment": [
                AuthorityClass.SPECIFICATION_REQUIREMENT,
                AuthorityClass.PRIMARY_TEST_DATA,
                AuthorityClass.HANDBOOK_VALUE,
                AuthorityClass.HERITAGE_PRECEDENT,
                AuthorityClass.ENGINEERING_JUDGMENT,
                AuthorityClass.VENDOR_DATASHEET,
                AuthorityClass.DERIVED_CALCULATION,
            ],
            "default": [
                AuthorityClass.PRIMARY_TEST_DATA,
                AuthorityClass.SPECIFICATION_REQUIREMENT,
                AuthorityClass.HANDBOOK_VALUE,
                AuthorityClass.HERITAGE_PRECEDENT,
                AuthorityClass.ENGINEERING_JUDGMENT,
                AuthorityClass.VENDOR_DATASHEET,
                AuthorityClass.DERIVED_CALCULATION,
            ],
        }
    )
    human_review_triggers: list[str] = Field(default_factory=list)
    stale_threshold_days: int = 365 * 3


DEFAULT_CROSS_SOURCE_RULES = [
    CrossSourceRule(
        rule_id="CSR-001",
        name="safety_critical_always_flag",
        description="Never auto-resolve safety-critical conflicts.",
        conflict_policy="flag_conflict",
    ),
    CrossSourceRule(
        rule_id="CSR-002",
        name="test_data_wins_for_evidence",
        description="Evidence questions prioritize test data.",
        conflict_policy="highest_authority",
    ),
    CrossSourceRule(
        rule_id="CSR-003",
        name="spec_wins_for_compliance",
        description="Compliance questions prioritize specifications.",
        conflict_policy="highest_authority",
    ),
    CrossSourceRule(
        rule_id="CSR-004",
        name="default_flag",
        description="Surface unresolved conflicts.",
        conflict_policy="flag_conflict",
    ),
]


def authority_ranking_for_intent(intent: str | None, rules: list[CrossSourceRule] | None = None) -> list[AuthorityClass]:
    selected_rules = rules or DEFAULT_CROSS_SOURCE_RULES
    intent_key = (intent or "default").lower()
    for rule in selected_rules:
        if intent_key in rule.authority_ranking_by_intent:
            return rule.authority_ranking_by_intent[intent_key]
    return selected_rules[0].authority_ranking_by_intent["default"]

