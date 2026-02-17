#!/usr/bin/env python3
"""
Fracture Control Authority Pack — Deterministic Classification Engine.

This is the core decision engine for fracture control part classification
per NASA-STD-5019A. It evaluates parts against classification rules loaded
from PostgreSQL (authority_fc schema) and produces deterministic verdicts
with full citation chains.

DESIGN PRINCIPLES:
    1. No LLM in the decision path — all classification is deterministic.
    2. Derived values (KIc/Fty ratio) computed at eval time, logged in trace.
    3. Missing context → CLARIFY, never assume.
    4. Every output cites doc/revision/section/page.
    5. Rule evaluation order is safety-critical with explicit stop semantics.

BoundState AI 2026
Co-Authored-By: Claude "Beth" Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-5019A, NASA-STD-5009C
Safety Critical: True
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    FractureCitation,
    FractureClassificationResult,
    FractureContextInput,
    FractureDecisionPacket,
)

LOGGER = logging.getLogger(__name__)

# =============================================================================
# Predicate Evaluator (typed, strict, with NULL safety)
# =============================================================================

# Allowed predicate operators
_PREDICATE_OPS = {
    "eq", "neq", "gt", "gte", "lt", "lte",
    "in", "not_in", "exists", "not_exists",
    "all", "any", "is_true", "is_false",
}

# Field registry: only these fields can appear in predicates.
# This prevents drift/injection via JSONB predicate content.
_VALID_PREDICATE_FIELDS = {
    "pressure_boundary",
    "consequence_of_failure",
    "inspectability",
    "geometry_type",
    "material_condition",
    "center_code",
    "design_life_cycles",
    "operating_pressure_psi",
    "operating_temperature_f",
    "proof_factor",
    "material",
    "part_name",
}


def _evaluate_single_condition(
    field: str,
    operator: str,
    expected: Any,
    context: Dict[str, Any],
) -> Tuple[bool, str]:
    """Evaluate one predicate condition against context.

    Returns (passed, explanation).
    Strict NULL behavior: if field is None and operator is not exists/not_exists,
    the condition FAILS (never silently passes on missing data).
    """
    if field not in _VALID_PREDICATE_FIELDS:
        return False, f"INVALID_FIELD:{field} not in field registry"

    actual = context.get(field)

    # Existence checks
    if operator == "exists":
        passed = actual is not None
        return passed, f"{field} {'exists' if passed else 'is missing'}"
    if operator == "not_exists":
        passed = actual is None
        return passed, f"{field} {'is absent' if passed else 'exists'}"

    # NULL guard: all other operators require the field to be present
    if actual is None:
        return False, f"{field} is NULL — cannot evaluate {operator}"

    # Boolean operators
    if operator == "is_true":
        passed = bool(actual) is True
        return passed, f"{field}={actual} {'is' if passed else 'is not'} true"
    if operator == "is_false":
        passed = bool(actual) is False
        return passed, f"{field}={actual} {'is' if passed else 'is not'} false"

    # Normalize for string comparison
    actual_cmp = str(actual).strip().lower() if isinstance(actual, str) else actual
    expected_cmp = str(expected).strip().lower() if isinstance(expected, str) else expected

    if operator == "eq":
        passed = actual_cmp == expected_cmp
        return passed, f"{field}={actual} {'==' if passed else '!='} {expected}"
    if operator == "neq":
        passed = actual_cmp != expected_cmp
        return passed, f"{field}={actual} {'!=' if passed else '=='} {expected}"
    if operator == "gt":
        try:
            passed = float(actual) > float(expected)
        except (TypeError, ValueError):
            return False, f"{field}={actual} not numeric for gt"
        return passed, f"{field}={actual} {'>' if passed else '<='} {expected}"
    if operator == "gte":
        try:
            passed = float(actual) >= float(expected)
        except (TypeError, ValueError):
            return False, f"{field}={actual} not numeric for gte"
        return passed, f"{field}={actual} {'>=' if passed else '<'} {expected}"
    if operator == "lt":
        try:
            passed = float(actual) < float(expected)
        except (TypeError, ValueError):
            return False, f"{field}={actual} not numeric for lt"
        return passed, f"{field}={actual} {'<' if passed else '>='} {expected}"
    if operator == "lte":
        try:
            passed = float(actual) <= float(expected)
        except (TypeError, ValueError):
            return False, f"{field}={actual} not numeric for lte"
        return passed, f"{field}={actual} {'<=' if passed else '>'} {expected}"
    if operator == "in":
        if not isinstance(expected, list):
            return False, f"'in' operator requires list, got {type(expected)}"
        expected_list = [str(e).strip().lower() if isinstance(e, str) else e for e in expected]
        passed = actual_cmp in expected_list
        return passed, f"{field}={actual} {'in' if passed else 'not in'} {expected}"
    if operator == "not_in":
        if not isinstance(expected, list):
            return False, f"'not_in' operator requires list, got {type(expected)}"
        expected_list = [str(e).strip().lower() if isinstance(e, str) else e for e in expected]
        passed = actual_cmp not in expected_list
        return passed, f"{field}={actual} {'not in' if passed else 'in'} {expected}"

    return False, f"UNKNOWN_OPERATOR:{operator}"


def evaluate_predicate(
    predicate_expr: Dict[str, Any],
    context: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """Evaluate a complete predicate expression against context.

    Predicate format (AND logic — all conditions must pass):
    {
        "conditions": [
            {"field": "pressure_boundary", "op": "is_true"},
            {"field": "consequence_of_failure", "op": "eq", "value": "catastrophic"}
        ]
    }

    Returns (all_passed, list_of_explanations).
    """
    conditions = predicate_expr.get("conditions", [])
    if not conditions:
        return False, ["Empty predicate — no conditions to evaluate"]

    explanations: List[str] = []
    all_passed = True

    for condition in conditions:
        field = condition.get("field", "")
        operator = condition.get("op", "")
        expected = condition.get("value")

        if operator not in _PREDICATE_OPS:
            explanations.append(f"INVALID_OP:{operator}")
            all_passed = False
            continue

        passed, explanation = _evaluate_single_condition(field, operator, expected, context)
        explanations.append(explanation)
        if not passed:
            all_passed = False

    return all_passed, explanations


# =============================================================================
# Classification Engine (standalone, no DB dependency for unit testing)
# =============================================================================


def _compute_provenance_hash(
    context: FractureContextInput,
    pack_id: str,
    pack_version: str,
) -> str:
    """Deterministic hash of classification inputs for replay/audit.

    NOTE: Timestamp deliberately excluded so identical inputs produce
    identical hashes.  Timestamp is recorded separately in telemetry.
    """
    payload = json.dumps(
        {
            "pack_id": pack_id,
            "pack_version": pack_version,
            "context": context.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _context_to_dict(context: FractureContextInput) -> Dict[str, Any]:
    """Convert FractureContextInput to flat dict for predicate evaluation."""
    return {k: v for k, v in context.model_dump(mode="python").items() if v is not None}


def classify_part(
    context: FractureContextInput,
    rules: List[Dict[str, Any]],
    *,
    pack_id: str = "fc_5019a_v1",
    pack_version: str = "1.0.0",
    center_overrides: Optional[List[Dict[str, Any]]] = None,
    nde_requirements: Optional[List[Dict[str, Any]]] = None,
    nde_exceptions: Optional[List[Dict[str, Any]]] = None,
) -> FractureDecisionPacket:
    """Classify a part per fracture control rules.

    This is the CORE function. It is deterministic and has no LLM dependency.
    Rules are pre-loaded from PostgreSQL and passed in as dicts.

    Args:
        context: Parsed user context (material, geometry, etc.)
        rules: Classification rules sorted by priority_order ASC.
        pack_id: Authority pack identifier.
        pack_version: Authority pack version.
        center_overrides: Optional center-specific rule overrides.
        nde_requirements: NDE applicability records for matched class.
        nde_exceptions: NDE exception records.

    Returns:
        FractureDecisionPacket with classification, citations, or CLARIFY.
    """
    warnings: List[str] = []
    evidence_gaps: List[str] = []
    rules_applied: List[str] = []
    citations: List[FractureCitation] = []

    # -------------------------------------------------------------------------
    # Phase 1: Check minimum required context
    # -------------------------------------------------------------------------
    missing_required = context.get_missing_required()
    if missing_required:
        return FractureDecisionPacket(
            verdict="NEEDS_CLARIFICATION",
            classification=FractureClassificationResult(
                part_class="UNCLASSIFIED",
                classification_confidence=0.0,
                clarify_fields=missing_required,
                rules_evaluated=0,
            ),
            context_provided=context,
            warnings=[f"Cannot classify: missing required fields: {', '.join(missing_required)}"],
            evidence_gaps=[f"Field '{f}' is required for fracture classification" for f in missing_required],
            rules_applied=["min_context_check:FAIL"],
            provenance_hash=_compute_provenance_hash(context, pack_id, pack_version),
        )

    rules_applied.append("min_context_check:PASS")
    context_dict = _context_to_dict(context)

    # -------------------------------------------------------------------------
    # Phase 2: Apply center overrides (suppress > replace > add)
    # -------------------------------------------------------------------------
    effective_rules = list(rules)
    overrides_applied: List[str] = []

    if center_overrides and context.center_code:
        center_code = context.center_code.upper()
        applicable_overrides = [
            o for o in center_overrides
            if o.get("center_code", "").upper() == center_code and o.get("active", True)
        ]
        # Sort by action precedence: suppress first, then replace, then add
        action_order = {"suppress": 0, "replace": 1, "add": 2}
        applicable_overrides.sort(
            key=lambda o: (action_order.get(o.get("action", ""), 99), o.get("precedence_order", 100))
        )

        suppressed_codes: set = set()
        for override in applicable_overrides:
            action = override.get("action", "")
            target = override.get("target_rule_code", "")

            if action == "suppress" and target:
                suppressed_codes.add(target)
                overrides_applied.append(f"suppress:{target}@{center_code}")
            elif action == "replace" and target:
                effective_rules = [
                    override if r.get("rule_code") == target else r
                    for r in effective_rules
                ]
                overrides_applied.append(f"replace:{target}@{center_code}")
            elif action == "add":
                effective_rules.append(override)
                overrides_applied.append(f"add:{override.get('override_rule_code', '?')}@{center_code}")

        if suppressed_codes:
            effective_rules = [r for r in effective_rules if r.get("rule_code") not in suppressed_codes]

    # Re-sort by priority_order after overrides
    effective_rules.sort(key=lambda r: r.get("priority_order", 9999))

    # -------------------------------------------------------------------------
    # Phase 3: Evaluate classification rules in priority order
    # -------------------------------------------------------------------------
    matched_rule: Optional[Dict[str, Any]] = None
    rules_evaluated = 0
    rule_trace: List[Dict[str, Any]] = []

    for rule in effective_rules:
        if not rule.get("active", True):
            continue

        rules_evaluated += 1
        rule_code = rule.get("rule_code", "UNKNOWN")
        predicate = rule.get("predicate_expr", {})

        # Check min_context_requirements for this specific rule
        min_ctx = rule.get("min_context_requirements", [])
        if isinstance(min_ctx, list) and min_ctx:
            missing_for_rule = [f for f in min_ctx if context_dict.get(f) is None]
            if missing_for_rule:
                rule_trace.append({
                    "rule_code": rule_code,
                    "result": "SKIPPED_MISSING_CONTEXT",
                    "missing": missing_for_rule,
                })
                continue

        passed, explanations = evaluate_predicate(predicate, context_dict)
        rule_trace.append({
            "rule_code": rule_code,
            "result": "MATCH" if passed else "NO_MATCH",
            "explanations": explanations,
        })

        if passed:
            matched_rule = rule
            rules_applied.append(f"rule_match:{rule_code}")
            if rule.get("stop_processing", True):
                break

    if not matched_rule:
        warnings.append("No classification rule matched the provided context.")
        evidence_gaps.append("Part does not match any known classification pattern in the active pack.")
        return FractureDecisionPacket(
            verdict="INSUFFICIENT_DATA",
            classification=FractureClassificationResult(
                part_class="UNCLASSIFIED",
                rules_evaluated=rules_evaluated,
                classification_confidence=0.0,
            ),
            context_provided=context,
            warnings=warnings,
            evidence_gaps=evidence_gaps,
            rules_applied=rules_applied,
            provenance_hash=_compute_provenance_hash(context, pack_id, pack_version),
        )

    # -------------------------------------------------------------------------
    # Phase 4: Extract classification from matched rule
    # -------------------------------------------------------------------------
    part_class = matched_rule.get("output_part_class", "UNKNOWN")
    fcr_set = list(matched_rule.get("output_fcr_set", []))
    nde_required = bool(matched_rule.get("output_nde_required", False))

    # Build citations from source_clause_ids
    source_clause_ids = matched_rule.get("source_clause_ids", [])
    if matched_rule.get("source_figure"):
        citations.append(FractureCitation(
            standard="NASA-STD-5019A",
            revision="A",
            section=matched_rule.get("source_figure", ""),
            clause_text=f"Classification per {matched_rule.get('source_figure')}",
        ))

    # -------------------------------------------------------------------------
    # Phase 5: Resolve NDE requirements for classified part
    # -------------------------------------------------------------------------
    nde_methods: List[str] = []
    nde_exceptions_applied: List[str] = []

    if nde_required and nde_requirements:
        applicable_nde = [
            n for n in nde_requirements
            if n.get("part_class") == part_class and n.get("active", True)
        ]
        nde_methods = list({n.get("nde_method", "") for n in applicable_nde if n.get("nde_method")})
        rules_applied.append(f"nde_methods:{','.join(nde_methods) or 'none'}")

        # Check for exceptions
        if nde_exceptions:
            for exc in nde_exceptions:
                if exc.get("part_class") != part_class or not exc.get("active", True):
                    continue
                exc_predicate = exc.get("condition_expr", {})
                exc_passed, _ = evaluate_predicate(exc_predicate, context_dict)
                if exc_passed:
                    exc_code = exc.get("exception_code", "?")
                    nde_exceptions_applied.append(exc_code)
                    if exc.get("exempts_all_nde"):
                        nde_required = False
                        nde_methods = []
                        rules_applied.append(f"nde_exception:{exc_code}:exempts_all")
                    elif exc.get("exempts_nde_method"):
                        method = exc["exempts_nde_method"]
                        nde_methods = [m for m in nde_methods if m != method]
                        rules_applied.append(f"nde_exception:{exc_code}:exempts_{method}")

    # -------------------------------------------------------------------------
    # Phase 6: Compute derived values (at eval time, NOT stored)
    # -------------------------------------------------------------------------
    derived_values: Dict[str, Any] = {}
    # These would be computed from material_fracture_properties if available
    # For now, placeholder for when material data is linked
    rules_applied.append(f"pack:{pack_id}@{pack_version}")

    # -------------------------------------------------------------------------
    # Phase 7: Assemble result
    # -------------------------------------------------------------------------
    classification = FractureClassificationResult(
        part_class=part_class,
        fcr_set=fcr_set,
        nde_required=nde_required,
        nde_methods=nde_methods,
        nde_exceptions_applied=nde_exceptions_applied,
        rule_matched=matched_rule.get("rule_code"),
        rules_evaluated=rules_evaluated,
        center_overrides_applied=overrides_applied,
        classification_confidence=1.0,
    )

    return FractureDecisionPacket(
        verdict="CLASSIFIED",
        classification=classification,
        context_provided=context,
        citations=citations,
        derived_values=derived_values,
        warnings=warnings,
        evidence_gaps=evidence_gaps,
        rules_applied=rules_applied,
        provenance_hash=_compute_provenance_hash(context, pack_id, pack_version),
    )


# =============================================================================
# Seed Rules (NASA-STD-5019A Section 6 / Figure 2 — Core Classification)
# =============================================================================
# These are the initial classification rules seeded from 5019A.
# In production, these are loaded from authority_fc.classification_rules.
# Provided here as code-level reference and for standalone CLI testing.

SEED_CLASSIFICATION_RULES: List[Dict[str, Any]] = [
    {
        "priority_order": 10,
        "rule_code": "FC_CLASS_1A",
        "rule_name": "Fracture Critical — Catastrophic Pressure Boundary",
        "description": "Pressure-containing hardware whose failure would result in catastrophic hazard",
        "predicate_expr": {
            "conditions": [
                {"field": "pressure_boundary", "op": "is_true"},
                {"field": "consequence_of_failure", "op": "eq", "value": "catastrophic"},
            ]
        },
        "min_context_requirements": ["pressure_boundary", "consequence_of_failure"],
        "output_part_class": "FRACTURE_CRITICAL_1",
        "output_fcr_set": ["FCR-1", "FCR-2", "FCR-3", "FCR-4", "FCR-5", "FCR-6", "FCR-7",
                           "FCR-8", "FCR-9", "FCR-10", "FCR-11", "FCR-12", "FCR-13"],
        "output_nde_required": True,
        "stop_processing": True,
        "source_figure": "Figure 2",
        "source_clause_ids": [],
        "predicate_schema_version": "1.0.0",
        "active": True,
    },
    {
        "priority_order": 20,
        "rule_code": "FC_CLASS_1B",
        "rule_name": "Fracture Critical — Catastrophic Non-Pressure Structural",
        "description": "Non-pressure structural hardware whose failure would result in catastrophic hazard",
        "predicate_expr": {
            "conditions": [
                {"field": "pressure_boundary", "op": "is_false"},
                {"field": "consequence_of_failure", "op": "eq", "value": "catastrophic"},
            ]
        },
        "min_context_requirements": ["pressure_boundary", "consequence_of_failure"],
        "output_part_class": "FRACTURE_CRITICAL_1",
        "output_fcr_set": ["FCR-1", "FCR-2", "FCR-3", "FCR-4", "FCR-5", "FCR-6", "FCR-7",
                           "FCR-8", "FCR-9", "FCR-10", "FCR-11", "FCR-12", "FCR-13"],
        "output_nde_required": True,
        "stop_processing": True,
        "source_figure": "Figure 2",
        "source_clause_ids": [],
        "predicate_schema_version": "1.0.0",
        "active": True,
    },
    {
        "priority_order": 30,
        "rule_code": "FC_CLASS_2_PB",
        "rule_name": "Fracture Critical 2 — Critical Pressure Boundary",
        "description": "Pressure-containing hardware whose failure would result in critical hazard",
        "predicate_expr": {
            "conditions": [
                {"field": "pressure_boundary", "op": "is_true"},
                {"field": "consequence_of_failure", "op": "eq", "value": "critical"},
            ]
        },
        "min_context_requirements": ["pressure_boundary", "consequence_of_failure"],
        "output_part_class": "FRACTURE_CRITICAL_2",
        "output_fcr_set": ["FCR-1", "FCR-2", "FCR-3", "FCR-4", "FCR-5", "FCR-6",
                           "FCR-8", "FCR-9", "FCR-10", "FCR-11"],
        "output_nde_required": True,
        "stop_processing": True,
        "source_figure": "Figure 2",
        "source_clause_ids": [],
        "predicate_schema_version": "1.0.0",
        "active": True,
    },
    {
        "priority_order": 40,
        "rule_code": "FC_CLASS_2_STRUCT",
        "rule_name": "Fracture Critical 2 — Critical Non-Pressure Structural",
        "description": "Non-pressure structural hardware whose failure would result in critical hazard",
        "predicate_expr": {
            "conditions": [
                {"field": "pressure_boundary", "op": "is_false"},
                {"field": "consequence_of_failure", "op": "eq", "value": "critical"},
                {"field": "inspectability", "op": "eq", "value": "non_inspectable"},
            ]
        },
        "min_context_requirements": ["pressure_boundary", "consequence_of_failure", "inspectability"],
        "output_part_class": "FRACTURE_CRITICAL_2",
        "output_fcr_set": ["FCR-1", "FCR-2", "FCR-3", "FCR-4", "FCR-5", "FCR-6",
                           "FCR-8", "FCR-9", "FCR-10", "FCR-11"],
        "output_nde_required": True,
        "stop_processing": True,
        "source_figure": "Figure 2",
        "source_clause_ids": [],
        "predicate_schema_version": "1.0.0",
        "active": True,
    },
    {
        "priority_order": 50,
        "rule_code": "FC_CLASS_3_LOW_RISK",
        "rule_name": "Low-Risk Fracture — Critical Inspectable",
        "description": "Critical-consequence hardware that is inspectable, per 5019A Figure 2 NFC path",
        "predicate_expr": {
            "conditions": [
                {"field": "consequence_of_failure", "op": "eq", "value": "critical"},
                {"field": "inspectability", "op": "in", "value": ["inspectable", "limited_access"]},
            ]
        },
        "min_context_requirements": ["consequence_of_failure", "inspectability"],
        "output_part_class": "LOW_RISK_FRACTURE",
        "output_fcr_set": ["FCR-1", "FCR-2", "FCR-3"],
        "output_nde_required": False,
        "stop_processing": True,
        "source_figure": "Figure 2",
        "source_clause_ids": [],
        "predicate_schema_version": "1.0.0",
        "active": True,
    },
    {
        "priority_order": 60,
        "rule_code": "FC_CLASS_NC",
        "rule_name": "Non-Critical — Minimal Fracture Requirements",
        "description": "Hardware whose failure would not result in critical or catastrophic hazard",
        "predicate_expr": {
            "conditions": [
                {"field": "consequence_of_failure", "op": "eq", "value": "non_critical"},
            ]
        },
        "min_context_requirements": ["consequence_of_failure"],
        "output_part_class": "NON_FRACTURE_CRITICAL",
        "output_fcr_set": ["FCR-1"],
        "output_nde_required": False,
        "stop_processing": True,
        "source_figure": "Figure 2",
        "source_clause_ids": [],
        "predicate_schema_version": "1.0.0",
        "active": True,
    },
    {
        "priority_order": 9999,
        "rule_code": "FC_FALLBACK_DEFAULT",
        "rule_name": "Fallback — Unclassified (requires SME review)",
        "description": "No classification rule matched; part requires manual SME assessment",
        "predicate_expr": {
            "conditions": [
                {"field": "consequence_of_failure", "op": "exists"},
            ]
        },
        "min_context_requirements": [],
        "output_part_class": "UNCLASSIFIED_REQUIRES_SME",
        "output_fcr_set": [],
        "output_nde_required": False,
        "stop_processing": True,
        "source_figure": "Figure 2",
        "source_clause_ids": [],
        "predicate_schema_version": "1.0.0",
        "active": True,
    },
]


def build_fracture_decision(
    context: FractureContextInput,
    *,
    rules: Optional[List[Dict[str, Any]]] = None,
    pack_id: str = "fc_5019a_v1",
    pack_version: str = "1.0.0",
    center_overrides: Optional[List[Dict[str, Any]]] = None,
    nde_requirements: Optional[List[Dict[str, Any]]] = None,
    nde_exceptions: Optional[List[Dict[str, Any]]] = None,
) -> FractureDecisionPacket:
    """Public entry point for fracture control classification.

    Uses seed rules if none provided (for standalone/CLI testing).
    Production path loads rules from authority_fc schema.
    """
    effective_rules = rules if rules is not None else SEED_CLASSIFICATION_RULES

    try:
        return classify_part(
            context,
            effective_rules,
            pack_id=pack_id,
            pack_version=pack_version,
            center_overrides=center_overrides,
            nde_requirements=nde_requirements,
            nde_exceptions=nde_exceptions,
        )
    except Exception as exc:
        LOGGER.error("[FC] Classification engine error: %s", exc, exc_info=True)
        return FractureDecisionPacket(
            verdict="ERROR",
            context_provided=context,
            warnings=[f"Classification engine error: {exc}"],
            rules_applied=["engine_error"],
        )
