"""
Module: MIRA Chat -- Module Context Resolution
Purpose: Resolves pronouns and implicit references when chat is opened from
         within a MIRA module (OCA, H2, Galvanic, Fracture, etc.).

Per BS-SPEC-MIRA-CHAT-001-REV2 Section 9.2, when chat is opened from within
a MIRA module, the frontend populates ``module_context``:

    {
        "module": "oca",
        "case_id": "OCA-2026-0318-001",
        "material": "316L",
        "environment": "GOX",
        "pressure_psi": 3000
    }

The module context resolver:
  - Resolves "this material", "this assessment", "the current case" to
    entities from module_context
  - Pre-populates the query interpreter's entities if module_context is present
  - Overrides routing confidence to 0.99 for in-module queries
  - Handles pronoun resolution: "What about this material?" -> material from
    module_context

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Import must be deferred to avoid circular imports with query_interpreter
# We import ParsedQuery at function call time.


# ---------------------------------------------------------------------------
# Pronoun / reference patterns that refer to module context
# ---------------------------------------------------------------------------

_MODULE_PRONOUN_PATTERNS = re.compile(
    r"\b("
    r"this\s+material"
    r"|this\s+assessment"
    r"|this\s+case"
    r"|the\s+current\s+(?:material|case|assessment)"
    r"|the\s+active\s+(?:material|case|assessment)"
    r"|current\s+material"
    r"|active\s+case"
    r"|the\s+material"
    r"|my\s+material"
    r"|the\s+case"
    r"|it"
    r"|this"
    r")\b",
    re.IGNORECASE,
)

# Patterns for case-ID references
_CASE_REF_PATTERNS = re.compile(
    r"\b("
    r"this\s+case"
    r"|the\s+current\s+case"
    r"|the\s+active\s+case"
    r"|case\s+(?:id|number)?"
    r"|the\s+case"
    r"|my\s+case"
    r")\b",
    re.IGNORECASE,
)

# Environment mapping from module_context shorthand to gas_service
_ENVIRONMENT_TO_GAS: dict[str, str] = {
    "gox": "oxygen",
    "lox": "oxygen",
    "oxygen": "oxygen",
    "o2": "oxygen",
    "gh2": "hydrogen",
    "lh2": "hydrogen",
    "hydrogen": "hydrogen",
    "h2": "hydrogen",
}

# Module -> fine_routing mapping
_MODULE_TO_ROUTING: dict[str, str] = {
    "oca": "oca",
    "h2": "h2",
    "galvanic": "galvanic",
    "fracture": "fracture",
    "mp_plan": "mp_plan",
    "mua": "mua",
    "miul": "miul",
    "forge_build": "forge_build",
    "forge_explorer": "forge_explorer",
    "tocr": "tocr",
    "knowledge_twins": "knowledge_twins",
    "gpcm": "gpcm",
    "compliance": "gpcm",
    "maptis": "maptis_search",
    "maptis_search": "maptis_search",
    "bsmh": "bsmh",
}


def resolve_module_routing(module_context: dict[str, Any] | None) -> str | None:
    """Return the engine id implied by ``module_context``, if any."""
    if not module_context:
        return None
    module_name = str(module_context.get("module", "")).strip().lower()
    if not module_name:
        return None
    return _MODULE_TO_ROUTING.get(module_name)


# ---------------------------------------------------------------------------
# Core resolution function
# ---------------------------------------------------------------------------


def resolve_module_context(
    text: str,
    module_context: dict[str, Any] | None,
    parsed: Any,  # ParsedQuery -- imported lazily to avoid circular deps
) -> Any:
    """
    Resolve pronouns and implicit references from module context.

    When the user asks "What about this material?" or "Is it compatible?"
    from within a MIRA module, this function fills in the missing entities
    from the module_context supplied by the frontend.

    Parameters
    ----------
    text : str
        The raw user message.
    module_context : dict | None
        Module context from the frontend. Keys may include:
        - module: str (e.g. "oca", "h2", "galvanic", "fracture")
        - case_id: str (e.g. "OCA-2026-0318-001")
        - material: str (e.g. "316L")
        - environment: str (e.g. "GOX", "LH2")
        - pressure_psi: float
        - temperature: float
        - material_a: str (galvanic context)
        - material_b: str (galvanic context)
        - part_name: str (fracture context)
        - mission_class: str (fracture context)
    parsed : ParsedQuery
        The parsed query from the query interpreter (will be mutated).

    Returns
    -------
    ParsedQuery
        The same parsed object with module-context entities resolved.
    """
    if not module_context:
        return parsed

    module_name = str(module_context.get("module", "")).lower()

    logger.debug(
        "[MODULE_CONTEXT] Resolving for module=%s, context_keys=%s",
        module_name, list(module_context.keys()),
    )

    # --- Material resolution ---
    _resolve_material(text, module_context, parsed)

    # --- Environment / gas service resolution ---
    _resolve_environment(text, module_context, parsed)

    # --- Pressure resolution ---
    _resolve_pressure(module_context, parsed)

    # --- Temperature resolution ---
    _resolve_temperature(module_context, parsed)

    # --- Module-specific context ---
    _resolve_module_specific(module_name, module_context, parsed)

    # --- Routing override ---
    explicit_target = getattr(parsed, "explicit_engine_target", None)
    if module_name and not explicit_target:
        routing_target = _MODULE_TO_ROUTING.get(module_name)
        if routing_target:
            parsed.fine_routing = routing_target
            parsed.routing_confidence = 0.99
            logger.debug(
                "[MODULE_CONTEXT] Routing overridden to %s (conf=0.99) from module=%s",
                routing_target, module_name,
            )
    elif explicit_target:
        logger.debug(
            "[MODULE_CONTEXT] Preserving explicit cross-domain target=%s over module=%s",
            explicit_target, module_name,
        )

    # --- Case ID propagation ---
    case_id = module_context.get("case_id")
    if case_id:
        # Store in inherited_entities so downstream adapters can find it
        parsed.inherited_entities["case_id"] = case_id
        if _CASE_REF_PATTERNS.search(text):
            logger.debug(
                "[MODULE_CONTEXT] Case reference detected, propagating case_id=%s",
                case_id,
            )

    return parsed


# ---------------------------------------------------------------------------
# Sub-resolvers
# ---------------------------------------------------------------------------


def _resolve_material(
    text: str,
    module_context: dict[str, Any],
    parsed: Any,
) -> None:
    """Fill in material_designation from module_context if missing."""
    if parsed.material_designation:
        return  # User explicitly specified a material, respect it

    ctx_material = module_context.get("material")
    if not ctx_material:
        return

    # Check if the user's text references the module material
    has_pronoun = bool(_MODULE_PRONOUN_PATTERNS.search(text))
    has_no_material = parsed.material_designation is None

    if has_pronoun or has_no_material:
        parsed.material_designation = str(ctx_material)
        parsed.inherited_entities["material_designation"] = str(ctx_material)
        parsed.inherited_entities["_source"] = "module_context"
        logger.debug(
            "[MODULE_CONTEXT] Material resolved from context: %s",
            ctx_material,
        )


def _resolve_environment(
    text: str,
    module_context: dict[str, Any],
    parsed: Any,
) -> None:
    """Fill in gas_service from module_context environment."""
    if parsed.gas_service:
        return  # User explicitly specified gas service

    environment = str(module_context.get("environment", "")).lower()
    if not environment:
        return

    gas_service = _ENVIRONMENT_TO_GAS.get(environment)
    if gas_service:
        parsed.gas_service = gas_service
        parsed.inherited_entities["gas_service"] = gas_service
        logger.debug(
            "[MODULE_CONTEXT] Gas service resolved from context: %s -> %s",
            environment, gas_service,
        )


def _resolve_pressure(
    module_context: dict[str, Any],
    parsed: Any,
) -> None:
    """Fill in pressure from module_context if missing."""
    if parsed.pressure_value is not None:
        return  # User explicitly specified pressure

    ctx_pressure = module_context.get("pressure_psi")
    if ctx_pressure is None:
        return

    try:
        pressure_val = float(ctx_pressure)
    except (ValueError, TypeError):
        return

    parsed.pressure_value = pressure_val
    parsed.pressure = f"{pressure_val:g} psi"
    parsed.inherited_entities["pressure_value"] = pressure_val
    parsed.inherited_entities["pressure"] = parsed.pressure
    logger.debug(
        "[MODULE_CONTEXT] Pressure resolved from context: %s psi",
        pressure_val,
    )


def _resolve_temperature(
    module_context: dict[str, Any],
    parsed: Any,
) -> None:
    """Fill in temperature from module_context if missing."""
    if parsed.temperature_value is not None:
        return

    ctx_temp = module_context.get("temperature")
    if ctx_temp is None:
        ctx_temp = module_context.get("temperature_f")
    if ctx_temp is None:
        return

    try:
        temp_val = float(ctx_temp)
    except (ValueError, TypeError):
        return

    parsed.temperature_value = temp_val
    parsed.temperature = f"{temp_val:g} F"
    parsed.inherited_entities["temperature_value"] = temp_val
    parsed.inherited_entities["temperature"] = parsed.temperature
    logger.debug(
        "[MODULE_CONTEXT] Temperature resolved from context: %s",
        temp_val,
    )


def _resolve_module_specific(
    module_name: str,
    module_context: dict[str, Any],
    parsed: Any,
) -> None:
    """Handle module-specific context fields."""

    # Galvanic: two materials
    if module_name == "galvanic":
        material_a = module_context.get("material_a")
        material_b = module_context.get("material_b")
        if material_a:
            parsed.inherited_entities["material_a"] = material_a
            if not parsed.material_designation:
                parsed.material_designation = str(material_a)
        if material_b:
            parsed.inherited_entities["second_material"] = material_b
        # Set dissimilar_metals flag
        if material_a and material_b:
            parsed.dissimilar_metals = True

    # Fracture: part name, mission class
    elif module_name == "fracture":
        for field in (
            "part_name",
            "mission_class",
            "hazard_consequence",
            "load_path_type",
            "pressure_boundary",
            "lifecycle_phase",
            "structural_role",
            "material_system",
            "specific_hardware_type",
            "optional_approach_requested",
            "proof_test_used",
            "process_controls_used",
            "detected_flaw_accepted_for_flight",
            "corrosion_iccp_recommended",
            "low_risk_candidate",
            "additive_manufactured",
            "chloride_exposure",
            "sustained_load_expected",
            "approved_source_data_attached",
            "mua_present",
            "nasa_std_6016_qualified",
            "kic_fty_ratio",
            "ftu_ksi",
            "short_transverse_dimension_in",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value
        # Set fracture_context flag
        parsed.fracture_context = True

    # OCA / H2: case_id already handled above; nothing extra needed

    elif module_name == "mp_plan":
        for field in (
            "mp_plan_session_id",
            "program_name",
            "program_phase",
            "current_step",
            "environment_count",
            "material_count",
            "blocking_question_count",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value

    elif module_name == "mua":
        for field in (
            "workflow_step",
            "workflow_step_label",
            "material_key",
            "material_name",
            "material_class",
            "fluid_medium",
            "service_environment",
            "project",
            "system",
            "ratings_entered_count",
            "automatable_count",
            "human_required_count",
            "no_mua_needed_count",
            "form_count",
            "resolution_candidate_count",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value

    elif module_name == "miul":
        for field in (
            "current_stage",
            "submodule",
            "extraction_id",
            "project",
            "drawing_count",
            "review_item_count",
            "open_review_count",
            "auto_approved_count",
            "flagged_count",
            "build_complete",
            "tree_loaded",
            "top_level",
            "assembly_count",
            "detail_count",
            "total_nodes",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value

    elif module_name == "forge_build":
        for field in (
            "database_url_redacted",
            "app_name",
            "sample_rows",
            "output_dir",
            "compile_stage",
            "compile_progress",
            "compile_message",
            "build_in_progress",
            "has_compile_result",
            "table_count",
            "question_count",
            "relationship_count",
            "latent_relationship_count",
            "warnings_count",
            "bundle_file_count",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value

    elif module_name == "forge_explorer":
        for field in (
            "database_url_redacted",
            "compile_mode",
            "compile_stage",
            "compile_progress",
            "build_in_progress",
            "has_compile_result",
            "table_count",
            "question_count",
            "relationship_count",
            "latent_relationship_count",
            "capability_count",
            "candidate_archetype_count",
            "current_query",
            "has_query_result",
            "bsms_status",
            "bouncer_status",
            "rules_verdict",
            "lineage_available",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value

    elif module_name == "tocr":
        for field in (
            "mode",
            "agency",
            "vehicle",
            "policy_pack",
            "revision_status_override",
            "use_sonnet",
            "parser_summary",
            "has_result",
            "verdict",
            "raw_score",
            "findings_count",
            "remediation_count",
            "rules_fired",
            "active_rule_ids",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value

    elif module_name == "knowledge_twins":
        for field in (
            "mode",
            "active_fluid",
            "query",
            "llm_provider",
            "material_result_count",
            "bok_result_count",
            "has_hybrid_response",
            "deterministic_decision",
            "decision_source",
            "insufficient_data",
            "mua_precedents_found",
            "test_results_found",
            "requirements_evaluated",
            "semantic_results_found",
            "high_confidence_semantic",
            "bok_sources",
            "semantic_sources",
        ):
            value = module_context.get(field)
            if value is not None:
                parsed.inherited_entities[field] = value

    # GPCM: standard reference
    elif module_name in ("gpcm", "compliance"):
        standard_ref = module_context.get("standard_ref")
        if standard_ref and not parsed.standard_ref:
            parsed.standard_ref = str(standard_ref)
            parsed.inherited_entities["standard_ref"] = str(standard_ref)


# ---------------------------------------------------------------------------
# Convenience: detect if text has module-context pronouns
# ---------------------------------------------------------------------------


def has_module_references(text: str) -> bool:
    """Return True if the text contains pronouns that could resolve from module context."""
    return bool(_MODULE_PRONOUN_PATTERNS.search(text))


def extract_module_entities(module_context: dict[str, Any] | None) -> dict[str, Any]:
    """
    Extract a flat dict of entities from module_context for use in session state.

    Useful for pre-populating session accumulated_entities when a module
    context is first received.
    """
    if not module_context:
        return {}

    entities: dict[str, Any] = {}

    if module_context.get("material"):
        entities["material_designation"] = module_context["material"]

    environment = str(module_context.get("environment", "")).lower()
    gas_service = _ENVIRONMENT_TO_GAS.get(environment)
    if gas_service:
        entities["gas_service"] = gas_service

    if module_context.get("pressure_psi") is not None:
        try:
            entities["pressure_value"] = float(module_context["pressure_psi"])
            entities["pressure"] = f"{entities['pressure_value']:g} psi"
        except (ValueError, TypeError):
            pass

    if module_context.get("case_id"):
        entities["case_id"] = module_context["case_id"]

    if module_context.get("mp_plan_session_id"):
        entities["mp_plan_session_id"] = module_context["mp_plan_session_id"]

    for field in (
        "workflow_step",
        "workflow_step_label",
        "material_key",
        "material_name",
        "current_stage",
        "submodule",
        "extraction_id",
        "tree_loaded",
        "top_level",
        "compile_mode",
        "compile_stage",
        "compile_progress",
        "build_in_progress",
        "has_compile_result",
        "current_query",
        "has_query_result",
        "bsms_status",
        "bouncer_status",
        "rules_verdict",
        "mode",
        "active_fluid",
        "has_hybrid_response",
        "deterministic_decision",
        "decision_source",
    ):
        if module_context.get(field) is not None:
            entities[field] = module_context[field]

    for field in (
        "part_name",
        "mission_class",
        "hazard_consequence",
        "load_path_type",
        "pressure_boundary",
        "lifecycle_phase",
        "structural_role",
        "material_system",
        "specific_hardware_type",
        "optional_approach_requested",
        "proof_test_used",
        "process_controls_used",
        "detected_flaw_accepted_for_flight",
        "corrosion_iccp_recommended",
        "low_risk_candidate",
        "additive_manufactured",
        "chloride_exposure",
        "sustained_load_expected",
        "approved_source_data_attached",
        "mua_present",
        "nasa_std_6016_qualified",
        "kic_fty_ratio",
        "ftu_ksi",
        "short_transverse_dimension_in",
    ):
        if module_context.get(field) is not None:
            entities[field] = module_context[field]

    for field in (
        "table_count",
        "question_count",
        "relationship_count",
        "latent_relationship_count",
        "warnings_count",
        "bundle_file_count",
        "capability_count",
        "candidate_archetype_count",
        "findings_count",
        "remediation_count",
        "rules_fired",
        "material_result_count",
        "bok_result_count",
        "mua_precedents_found",
        "test_results_found",
        "requirements_evaluated",
        "semantic_results_found",
        "high_confidence_semantic",
    ):
        if module_context.get(field) is not None:
            entities[field] = module_context[field]

    if module_context.get("module"):
        entities["engine_used"] = _MODULE_TO_ROUTING.get(
            str(module_context["module"]).lower(),
            str(module_context["module"]),
        )

    return entities
