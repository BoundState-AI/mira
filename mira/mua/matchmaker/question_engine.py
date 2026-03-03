"""JSON-driven question engine for MUA Matchmaker v8."""

from __future__ import annotations

import copy
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional

from jsonschema import Draft7Validator
from pydantic import BaseModel, Field

from mira.core.models import SafetyCriticalError

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).resolve().parent / "rules"
DEFAULT_RULE_PACK_PATH = RULES_DIR / "jsc_27301f_appendix_e_v1.0.0.json"
RULE_PACK_SCHEMA_PATH = RULES_DIR / "rule_pack_schema.json"

ALLOWED_CONDITION_OPERATORS = frozenset(
    {"eq", "not_in", "in", "lt", "lte", "gt", "gte", "default"}
)


class EvaluationOutcome(BaseModel):
    """Outcome contract for question-tree evaluation."""

    status: str
    code: Optional[str] = None
    candidate_codes: list[str] = Field(default_factory=list)
    note: Optional[str] = None


def validate_rule_pack(
    rule_pack: Mapping[str, Any],
    schema_path: str | Path | None = None,
) -> None:
    """Validate a rule pack against frozen schema and operator grammar."""

    schema = _load_json_cached(str(Path(schema_path or RULE_PACK_SCHEMA_PATH).resolve()))
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(rule_pack), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.path) or "<root>"
        raise SafetyCriticalError(
            message=f"Rule pack schema validation failed at {path}: {first.message}",
            error_code="MUA-MM-RULEPACK-INVALID",
            severity="CRITICAL",
            safety_domain="MUA",
        )

    _validate_condition_operators(rule_pack)


def load_rule_pack(rule_pack_path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate a rule pack, returning an isolated copy."""

    path = Path(rule_pack_path or DEFAULT_RULE_PACK_PATH).resolve()
    rule_pack = _load_json_cached(str(path))
    validate_rule_pack(rule_pack, RULE_PACK_SCHEMA_PATH)
    return copy.deepcopy(rule_pack)


def get_applicable_codes(domain: str, rule_pack: Mapping[str, Any]) -> list[str]:
    """Return all Cat III codes that can apply for a domain."""

    domain_obj = _get_domain(domain, rule_pack)
    if not domain_obj:
        return []
    codes = list(domain_obj.get("applicable_codes", []))
    codes.extend(domain_obj.get("stowage_codes", []))
    return _dedupe(codes)


def get_next_question(
    domain: str,
    answers: Mapping[str, Any],
    rule_pack: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """Return the next visible unanswered question for this domain."""

    domain_obj = _get_domain(domain, rule_pack)
    if not domain_obj:
        return None

    for question in domain_obj.get("questions", []):
        if not _condition_matches(question.get("condition"), answers):
            continue
        if question["id"] not in answers:
            return question

    return None


def evaluate_answers(
    domain: str,
    answers: Mapping[str, Any],
    rule_pack: Mapping[str, Any],
) -> EvaluationOutcome:
    """Evaluate domain answers and resolve PASS/CAT_III/CAT_I_II state."""

    domain_obj = _get_domain(domain, rule_pack)
    if not domain_obj:
        return EvaluationOutcome(status="UNKNOWN_DOMAIN")

    cat3_codes: list[str] = []
    for question in domain_obj.get("questions", []):
        if not _condition_matches(question.get("condition"), answers):
            continue
        if question["id"] not in answers:
            continue

        answer_value = answers[question["id"]]
        termination = question.get("terminates", {}).get(str(answer_value))
        if not termination:
            continue

        outcome = termination.get("outcome")
        if outcome == "PASS":
            return EvaluationOutcome(status="PASS", note=termination.get("note"))
        if outcome == "CAT_III":
            code = termination.get("code")
            if code:
                cat3_codes.append(code)

    if len(cat3_codes) > 1:
        return EvaluationOutcome(
            status="MULTIPLE_CAT3",
            candidate_codes=_dedupe(cat3_codes),
        )
    if len(cat3_codes) == 1:
        return EvaluationOutcome(status="CAT_III", code=cat3_codes[0])

    required = _required_cat_i_ii_questions(domain_obj)
    missing = [qid for qid in required if not str(answers.get(qid, "")).strip()]
    if missing:
        return EvaluationOutcome(status="IN_PROGRESS", note=f"Missing: {', '.join(missing)}")

    if required:
        return EvaluationOutcome(status="CAT_I_II")

    return EvaluationOutcome(status="IN_PROGRESS")


def _required_cat_i_ii_questions(domain_obj: Mapping[str, Any]) -> list[str]:
    required: list[str] = []
    for q in domain_obj.get("questions", []):
        if q.get("required_for") == "CAT_I_II":
            required.append(q["id"])
    return required


def _validate_condition_operators(rule_pack: Mapping[str, Any]) -> None:
    domains = rule_pack.get("domains", {})
    for domain_name, domain_obj in domains.items():
        for question in domain_obj.get("questions", []):
            condition = question.get("condition") or {}
            if not isinstance(condition, Mapping):
                raise SafetyCriticalError(
                    message=f"Condition for {domain_name}.{question['id']} must be an object",
                    error_code="MUA-MM-RULEPACK-INVALID-CONDITION",
                    severity="CRITICAL",
                    safety_domain="MUA",
                )
            for key, clause in condition.items():
                if key.startswith("_") or isinstance(clause, str):
                    continue
                if not isinstance(clause, Mapping):
                    raise SafetyCriticalError(
                        message=(
                            f"Condition clause for {domain_name}.{question['id']}:{key} "
                            "must be string or operator object"
                        ),
                        error_code="MUA-MM-RULEPACK-INVALID-CONDITION",
                        severity="CRITICAL",
                        safety_domain="MUA",
                    )
                unknown_ops = set(clause.keys()) - ALLOWED_CONDITION_OPERATORS
                if unknown_ops:
                    ops = ", ".join(sorted(unknown_ops))
                    raise SafetyCriticalError(
                        message=(
                            f"Unsupported condition operator(s) [{ops}] in "
                            f"{domain_name}.{question['id']}:{key}"
                        ),
                        error_code="MUA-MM-RULEPACK-INVALID-OP",
                        severity="CRITICAL",
                        safety_domain="MUA",
                    )


def _condition_matches(condition: Any, answers: Mapping[str, Any]) -> bool:
    if not condition:
        return True
    if not isinstance(condition, Mapping):
        return False

    for key, expected in condition.items():
        if key.startswith("_"):
            if key == "_no_cat3" and bool(expected):
                # CAT III is resolved iff any existing answer value resolved to CAT_III.
                # We use a conservative proxy here: explicit `_resolved_cat3_code` marker.
                if answers.get("_resolved_cat3_code"):
                    return False
            continue

        actual = _get_answer_value(answers, key)
        if isinstance(expected, Mapping):
            if not _match_operator_clause(actual, expected):
                return False
            continue
        if str(actual) != str(expected):
            return False

    return True


def _match_operator_clause(actual: Any, expected: Mapping[str, Any]) -> bool:
    for operator, operand in expected.items():
        if operator == "eq" and actual != operand:
            return False
        if operator == "not_in" and actual in (operand or []):
            return False
        if operator == "in" and actual not in (operand or []):
            return False
        if operator == "lt" and not _compare_numeric(actual, operand, "lt"):
            return False
        if operator == "lte" and not _compare_numeric(actual, operand, "lte"):
            return False
        if operator == "gt" and not _compare_numeric(actual, operand, "gt"):
            return False
        if operator == "gte" and not _compare_numeric(actual, operand, "gte"):
            return False
        if operator == "default" and bool(operand) and actual is not None:
            return False
    return True


def _compare_numeric(actual: Any, operand: Any, op: str) -> bool:
    try:
        actual_f = float(actual)
        operand_f = float(operand)
    except (TypeError, ValueError):
        return False

    if op == "lt":
        return actual_f < operand_f
    if op == "lte":
        return actual_f <= operand_f
    if op == "gt":
        return actual_f > operand_f
    if op == "gte":
        return actual_f >= operand_f
    return False


def _get_answer_value(answers: Mapping[str, Any], key: str) -> Any:
    if "." not in key:
        return answers.get(key)

    root, child = key.split(".", 1)
    root_value = answers.get(root)
    if isinstance(root_value, Mapping):
        return root_value.get(child)
    return None


def _get_domain(domain: str, rule_pack: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not domain:
        return None
    return rule_pack.get("domains", {}).get(domain.upper())


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


@lru_cache(maxsize=16)
def _load_json_cached(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # pragma: no cover - exercised via callers
        raise SafetyCriticalError(
            message=f"Failed to load JSON file: {path}",
            error_code="MUA-MM-RULEPACK-LOAD-ERROR",
            severity="CRITICAL",
            safety_domain="MUA",
        ) from exc
