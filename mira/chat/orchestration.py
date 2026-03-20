"""
Module: MIRA Chat — Orchestration Planner
Purpose: Plans and executes multi-engine chains for compound queries per
         BS-SPEC-MIRA-CHAT-001-REV2 Section 6.2.

Phase 1 dispatches to a single engine per query. Phase 2 (this module) handles
compound queries like "Check 316L in oxygen and write the MUA" by chaining
multiple engines in dependency order with approval gates between assessment
and draft-generation steps.

Execution rules (Section 6.2 — non-negotiable):
  - Engines execute in dependency order (assessment before artifact generation)
  - Partial failure returns results from completed steps with clear indication
  - Conflicting verdicts: present BOTH with sources, never merge
  - REFUSE from any engine stops the chain immediately
  - answer_only chains may include multiple assessment engines
  - draft_artifact chains require user confirmation before each generation step
  - When engines disagree, the more conservative verdict wins for display

Side-effect level enforcement (Section 3.3):
  - Chat may invoke engines at read_only or transient_generate level
  - persisted_draft requires explicit user confirmation (approval gate)
  - workflow_submit is NEVER available through chat

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
import traceback
from dataclasses import dataclass, field
from typing import Any

from .capability_registry import get_chaining_suggestion, get_engine
from .engine_adapter import EngineAdapter
from .models import EngineEnvelope, SideEffectLevel, Status, TaskMode
from .query_interpreter import ParsedQuery

LOGGER = logging.getLogger(__name__)

__safety_critical__ = True  # NASA SWE-032 compliance


# ---------------------------------------------------------------------------
# Verdict severity ordering — lower index = more conservative (worse)
# ---------------------------------------------------------------------------

_VERDICT_SEVERITY: dict[Status, int] = {
    Status.REFUSE: 0,
    Status.ERROR: 1,
    Status.FAIL: 2,
    Status.INSUFFICIENT_DATA: 3,
    Status.CONDITIONAL_PASS: 4,
    Status.PASS: 5,
}

# Side-effect levels that chat is allowed to invoke
_CHAT_ALLOWED_SIDE_EFFECTS: frozenset[str] = frozenset({
    SideEffectLevel.READ_ONLY.value,
    SideEffectLevel.TRANSIENT_GENERATE.value,
})

# Side-effect levels that require an approval gate
_APPROVAL_REQUIRED_SIDE_EFFECTS: frozenset[str] = frozenset({
    SideEffectLevel.PERSISTED_DRAFT.value,
})

# Side-effect levels that are NEVER allowed through chat
_FORBIDDEN_SIDE_EFFECTS: frozenset[str] = frozenset({
    SideEffectLevel.WORKFLOW_SUBMIT.value,
})


# ---------------------------------------------------------------------------
# Compound query detection patterns
# ---------------------------------------------------------------------------

# "... AND write/draft/generate the MUA"
_AND_DRAFT_PATTERN = re.compile(
    r"\b(?:and|then|also|after\s+that)\s+"
    r"(?:write|draft|generate|build|create|produce|compose|prepare)\b",
    re.IGNORECASE,
)

# "Check X in Y and Z" — multiple gas services in one query
_MULTI_GAS_PATTERN = re.compile(
    r"\b(GOX|LOX|oxygen|O2)\b.*\b(GH2|LH2|hydrogen|H2)\b"
    r"|\b(GH2|LH2|hydrogen|H2)\b.*\b(GOX|LOX|oxygen|O2)\b",
    re.IGNORECASE,
)

# "Is X safe in GOX and GH2?" — parallel assessments
_PARALLEL_GAS_PATTERN = re.compile(
    r"\b(?:in|for|with)\s+(?:both\s+)?(?:GOX|LOX|oxygen|O2)\s+"
    r"(?:and|&)\s+(?:GH2|LH2|hydrogen|H2)\b"
    r"|\b(?:in|for|with)\s+(?:both\s+)?(?:GH2|LH2|hydrogen|H2)\s+"
    r"(?:and|&)\s+(?:GOX|LOX|oxygen|O2)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """A single step in a multi-engine execution plan."""

    engine_id: str
    task_mode: TaskMode
    depends_on: list[str] = field(default_factory=list)
    requires_approval: bool = False
    parsed_input: dict[str, Any] = field(default_factory=dict)

    # Internal tracking (set during execution, not planning)
    _completed: bool = field(default=False, repr=False)
    _envelope: EngineEnvelope | None = field(default=None, repr=False)


@dataclass
class ExecutionPlan:
    """Ordered sequence of engine invocations."""

    steps: list[PlanStep]
    is_compound: bool
    original_query: str

    @property
    def engine_ids(self) -> list[str]:
        """Return the ordered list of engine IDs in this plan."""
        return [step.engine_id for step in self.steps]

    @property
    def step_count(self) -> int:
        return len(self.steps)


@dataclass
class ChainResult:
    """Result of executing an orchestration plan."""

    envelopes: list[EngineEnvelope] = field(default_factory=list)
    failed_step: PlanStep | None = None
    stopped_by_refuse: bool = False
    needs_approval: bool = False
    approval_prompt: str = ""
    pending_steps: list[PlanStep] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True if all steps completed (no pending, no failure)."""
        return (
            not self.needs_approval
            and self.failed_step is None
            and not self.pending_steps
        )

    @property
    def final_status(self) -> Status | None:
        """The most conservative status across all completed envelopes."""
        if not self.envelopes:
            return None
        return min(
            (e.status for e in self.envelopes),
            key=lambda s: _VERDICT_SEVERITY.get(s, 99),
        )


# ---------------------------------------------------------------------------
# Orchestration Planner
# ---------------------------------------------------------------------------


class OrchestrationPlanner:
    """Plans and executes multi-engine chains per Section 6.2.

    The planner is stateless — session context is passed in by the router.
    Pending steps (waiting for approval) are stored in the session by the
    caller, not by the planner itself.
    """

    # ------------------------------------------------------------------
    # Plan construction
    # ------------------------------------------------------------------

    def plan(
        self,
        parsed: ParsedQuery,
        session_context: dict[str, Any],
    ) -> ExecutionPlan:
        """Analyze a parsed query and produce an execution plan.

        Detects compound queries by checking:
        1. Multiple task modes (assessment + draft) in the same utterance
        2. Multiple domains (oxygen + hydrogen) in the same utterance
        3. Chaining hints from the capability registry
        4. Pending steps from a prior approval gate (session_context)

        For single-engine queries, returns a plan with is_compound=False
        and a single step — the Phase 1 path is preserved unchanged.
        """
        raw = parsed.raw_query

        # --- Resume from approval gate ---
        pending = session_context.get("pending_steps")
        if pending and self._is_approval_confirmation(raw):
            LOGGER.info(
                "[ORCH] Resuming %d pending steps after user approval",
                len(pending),
            )
            return ExecutionPlan(
                steps=pending,
                is_compound=True,
                original_query=raw,
            )

        steps: list[PlanStep] = []

        # --- Detect: multi-gas parallel assessments ---
        if _MULTI_GAS_PATTERN.search(raw) and parsed.material_designation:
            steps = self._plan_multi_gas(parsed, session_context)

        # --- Detect: assessment + draft chain ---
        elif _AND_DRAFT_PATTERN.search(raw):
            steps = self._plan_assessment_then_draft(parsed, session_context)

        # --- Detect: draft request with assessment needed ---
        elif (
            parsed.task_mode == TaskMode.DRAFT_ARTIFACT
            and not session_context.get("last_assessment")
            and parsed.material_designation
            and parsed.gas_service
        ):
            steps = self._plan_assessment_then_draft(parsed, session_context)

        # --- Single engine (Phase 1 path) ---
        if not steps:
            steps = [self._plan_single_step(parsed, session_context)]

        # --- Validate side-effect levels ---
        steps = self._enforce_side_effect_levels(steps)

        is_compound = len(steps) > 1

        LOGGER.info(
            "[ORCH] Plan: %d step(s), compound=%s, engines=%s",
            len(steps),
            is_compound,
            [s.engine_id for s in steps],
        )

        return ExecutionPlan(
            steps=steps,
            is_compound=is_compound,
            original_query=raw,
        )

    # ------------------------------------------------------------------
    # Plan execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        plan: ExecutionPlan,
        adapters: dict[str, EngineAdapter],
        session_context: dict[str, Any],
    ) -> ChainResult:
        """Execute a plan step by step.

        Execution rules (Section 6.2):
        - Stops on REFUSE — returns the refusal envelope
        - Returns partial results on failure (envelopes 1..N-1)
        - Pauses at approval gates — returns needs_approval=True
        - Passes data between steps via chaining_outputs handoff
        """
        result = ChainResult()

        for i, step in enumerate(plan.steps):
            # --- Approval gate ---
            if step.requires_approval:
                remaining = plan.steps[i:]
                result.needs_approval = True
                result.pending_steps = remaining
                result.approval_prompt = self._build_approval_prompt(
                    result.envelopes, step,
                )
                LOGGER.info(
                    "[ORCH] Approval gate: pausing before step %d (%s). "
                    "%d steps pending.",
                    i, step.engine_id, len(remaining),
                )
                # Store pending steps in session for cross-turn resumption
                session_context["pending_steps"] = remaining
                return result

            # --- Look up adapter ---
            adapter = adapters.get(step.engine_id)
            if adapter is None:
                LOGGER.warning(
                    "[ORCH] No adapter for engine %s at step %d",
                    step.engine_id, i,
                )
                step._completed = False
                result.failed_step = step
                result.envelopes.append(EngineEnvelope(
                    status=Status.ERROR,
                    engine_id=step.engine_id,
                    response_text=(
                        f"The {step.engine_id} engine is not available. "
                        "The remaining chain steps were not executed."
                    ),
                ))
                break

            # --- Execute ---
            try:
                envelope = await adapter.execute(
                    step.parsed_input,
                    session_context,
                )
            except Exception as exc:
                LOGGER.exception(
                    "[ORCH] Engine %s raised at step %d: %s",
                    step.engine_id, i, exc,
                )
                envelope = EngineEnvelope(
                    status=Status.ERROR,
                    engine_id=step.engine_id,
                    response_text=f"Engine error in {step.engine_id}: {exc}",
                    domain_payload={
                        "error_type": type(exc).__name__,
                        "error_detail": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )

            step._completed = True
            step._envelope = envelope
            result.envelopes.append(envelope)

            # --- Stop on REFUSE ---
            if envelope.status == Status.REFUSE:
                result.stopped_by_refuse = True
                LOGGER.info(
                    "[ORCH] Engine %s returned REFUSE at step %d — stopping chain.",
                    step.engine_id, i,
                )
                break

            # --- Stop on ERROR (partial failure) ---
            if envelope.status == Status.ERROR:
                result.failed_step = step
                LOGGER.warning(
                    "[ORCH] Engine %s returned ERROR at step %d — "
                    "returning partial results from steps 0..%d.",
                    step.engine_id, i, i,
                )
                break

            # --- Data handoff to next step ---
            if i + 1 < len(plan.steps):
                next_step = plan.steps[i + 1]
                self._apply_handoff(envelope, next_step, session_context)

            # --- Persist engine context ---
            # Adapters may write keys like oca_case_id into session_context
            # during execute(). Those survive for the next step automatically.

            # --- Check for chaining suggestion (dynamic approval gate) ---
            if i + 1 < len(plan.steps):
                next_step = plan.steps[i + 1]
                chaining = get_chaining_suggestion(
                    step.engine_id, envelope.status.value,
                )
                if (
                    chaining
                    and not chaining.get("auto_chain", False)
                    and next_step.task_mode == TaskMode.DRAFT_ARTIFACT
                    and not next_step.requires_approval
                ):
                    # Registry says this transition requires approval
                    next_step.requires_approval = True
                    remaining = plan.steps[i + 1:]
                    result.needs_approval = True
                    result.pending_steps = remaining
                    result.approval_prompt = self._build_approval_prompt(
                        result.envelopes, next_step,
                    )
                    session_context["pending_steps"] = remaining
                    LOGGER.info(
                        "[ORCH] Dynamic approval gate triggered by %s -> %s "
                        "chaining rule.",
                        step.engine_id, next_step.engine_id,
                    )
                    return result

        # --- Clean up pending steps on completion ---
        if result.is_complete:
            session_context.pop("pending_steps", None)

        return result

    # ------------------------------------------------------------------
    # Envelope merging
    # ------------------------------------------------------------------

    def merge_envelopes(
        self,
        envelopes: list[EngineEnvelope],
    ) -> EngineEnvelope:
        """Merge multiple engine results into a single display envelope.

        Merge rules (Section 6.2):
        - Most conservative verdict wins for the top-level status
        - All citations combined (deduplicated, order preserved)
        - All evidence combined
        - Conflicting verdicts: present BOTH with sources in response_text
        - All recommended_actions combined
        - All authority_basis combined (deduplicated)
        - All assumptions combined
        - All missing_inputs combined (deduplicated)
        """
        if not envelopes:
            return EngineEnvelope(
                status=Status.ERROR,
                engine_id="orchestration",
                response_text="No engine results to merge.",
            )

        if len(envelopes) == 1:
            return envelopes[0]

        # --- Determine most conservative verdict ---
        most_conservative = min(
            envelopes,
            key=lambda e: _VERDICT_SEVERITY.get(e.status, 99),
        )

        # --- Detect conflicting verdicts ---
        unique_verdicts = {e.status for e in envelopes}
        has_conflict = len(unique_verdicts) > 1

        # --- Build merged response text ---
        response_parts: list[str] = []

        if has_conflict:
            response_parts.append(
                "**Multiple engines returned different verdicts.** "
                "The most conservative result is shown below. "
                "Both assessments are presented for engineering review."
            )
            response_parts.append("")

        for envelope in envelopes:
            engine_label = envelope.engine_id.upper()
            response_parts.append(f"--- {engine_label} Result ({envelope.status.value}) ---")
            response_parts.append(envelope.response_text)
            response_parts.append("")

        if has_conflict:
            response_parts.append(
                f"**Display verdict: {most_conservative.status.value}** "
                f"(most conservative, from {most_conservative.engine_id})"
            )

        merged_response = "\n".join(response_parts).rstrip()

        # --- Combine list fields (deduplicated, order preserved) ---
        merged_citations = _dedup_ordered(
            c for e in envelopes for c in e.citations
        )
        merged_authority = _dedup_ordered(
            a for e in envelopes for a in e.authority_basis
        )
        merged_evidence = []
        for e in envelopes:
            merged_evidence.extend(e.evidence)
        merged_assumptions = _dedup_ordered(
            a for e in envelopes for a in e.assumptions
        )
        merged_missing = _dedup_ordered(
            m for e in envelopes for m in e.missing_inputs
        )
        merged_actions = _dedup_ordered(
            a for e in envelopes for a in e.recommended_actions
        )
        merged_lineage = []
        for e in envelopes:
            merged_lineage.extend(e.audit_lineage)

        # --- Combine domain payloads ---
        merged_domain: dict[str, Any] = {}
        for e in envelopes:
            # Namespace each engine's payload to avoid collisions
            merged_domain[f"{e.engine_id}_payload"] = dict(e.domain_payload)
        merged_domain["merged_from"] = [e.engine_id for e in envelopes]
        merged_domain["has_verdict_conflict"] = has_conflict

        return EngineEnvelope(
            status=most_conservative.status,
            engine_id="orchestration",
            engine_version="2.0.0",
            mode=most_conservative.mode,
            response_text=merged_response,
            authority_basis=merged_authority,
            citations=merged_citations,
            evidence=merged_evidence,
            assumptions=merged_assumptions,
            missing_inputs=merged_missing,
            recommended_actions=merged_actions,
            mua_disposition=most_conservative.mua_disposition,
            audit_lineage=merged_lineage,
            domain_payload=merged_domain,
        )

    # ------------------------------------------------------------------
    # Private: plan construction helpers
    # ------------------------------------------------------------------

    def _plan_single_step(
        self,
        parsed: ParsedQuery,
        session_context: dict[str, Any],
    ) -> PlanStep:
        """Build a single-step plan (Phase 1 compatibility path)."""
        from .router import _build_parsed_input

        return PlanStep(
            engine_id=parsed.fine_routing,
            task_mode=parsed.task_mode,
            depends_on=[],
            requires_approval=False,
            parsed_input=_build_parsed_input(parsed),
        )

    def _plan_multi_gas(
        self,
        parsed: ParsedQuery,
        session_context: dict[str, Any],
    ) -> list[PlanStep]:
        """Plan parallel assessments across oxygen and hydrogen domains.

        Example: "Is 316L safe in GOX and GH2?"
        -> [OCA assessment, H2 assessment]
        """
        from .router import _build_parsed_input

        base_input = _build_parsed_input(parsed)
        steps: list[PlanStep] = []

        # OCA step — force gas_service to oxygen
        oca_input = dict(base_input)
        oca_input["gas_service"] = "oxygen"
        oca_input["fine_routing"] = "oca"
        # Build OCA-specific fields if not already present
        if "service_context" not in oca_input:
            oca_input["service_context"] = self._build_oxygen_service_context(parsed)
        if "materials" not in oca_input and parsed.material_designation:
            oca_input["materials"] = [{"material_name": parsed.material_designation}]
        if "components" not in oca_input and parsed.material_designation:
            oca_input["components"] = [
                {
                    "component_class": "line",
                    "geometry_class": "bulk",
                    "design_function": "pressure_boundary",
                    "pressure_boundary_material": parsed.material_designation,
                    "is_rigid_metallic_tubing": True,
                }
            ]
        oca_input["free_text_intake"] = parsed.raw_query

        steps.append(PlanStep(
            engine_id="oca",
            task_mode=TaskMode.ANSWER_ONLY,
            depends_on=[],
            requires_approval=False,
            parsed_input=oca_input,
        ))

        # H2 step — force gas_service to hydrogen
        h2_input = dict(base_input)
        h2_input["gas_service"] = "hydrogen"
        h2_input["fine_routing"] = "h2"
        h2_input["material"] = parsed.material_designation
        h2_input["pressure_psia"] = parsed.pressure_value
        h2_input["question"] = parsed.raw_query

        steps.append(PlanStep(
            engine_id="h2",
            task_mode=TaskMode.ANSWER_ONLY,
            depends_on=[],
            requires_approval=False,
            parsed_input=h2_input,
        ))

        return steps

    def _plan_assessment_then_draft(
        self,
        parsed: ParsedQuery,
        session_context: dict[str, Any],
    ) -> list[PlanStep]:
        """Plan an assessment followed by a draft-generation step.

        Example: "Check 316L in oxygen and write the MUA"
        -> [OCA assessment (answer_only), MUA draft (draft_artifact, requires approval)]
        """
        from .router import _build_parsed_input

        base_input = _build_parsed_input(parsed)

        # Step 1: Assessment
        assessment_engine = self._resolve_assessment_engine(parsed)
        assessment_input = dict(base_input)
        assessment_input["task_mode"] = TaskMode.ANSWER_ONLY.value

        # Ensure engine-specific fields are present
        if assessment_engine == "oca":
            if "service_context" not in assessment_input:
                assessment_input["service_context"] = (
                    self._build_oxygen_service_context(parsed)
                )
            if "materials" not in assessment_input and parsed.material_designation:
                assessment_input["materials"] = [
                    {"material_name": parsed.material_designation}
                ]
            if "components" not in assessment_input and parsed.material_designation:
                assessment_input["components"] = [
                    {
                        "component_class": "line",
                        "geometry_class": "bulk",
                        "design_function": "pressure_boundary",
                        "pressure_boundary_material": parsed.material_designation,
                        "is_rigid_metallic_tubing": True,
                    }
                ]
            assessment_input["free_text_intake"] = parsed.raw_query
        elif assessment_engine == "h2":
            assessment_input["material"] = parsed.material_designation
            assessment_input["pressure_psia"] = parsed.pressure_value
            assessment_input["question"] = parsed.raw_query

        assessment_step = PlanStep(
            engine_id=assessment_engine,
            task_mode=TaskMode.ANSWER_ONLY,
            depends_on=[],
            requires_approval=False,
            parsed_input=assessment_input,
        )

        # Step 2: Draft (requires approval gate)
        # The parsed_input will be filled in via _apply_handoff after the
        # assessment step completes.
        draft_step = PlanStep(
            engine_id=assessment_engine,  # Same engine produces the draft
            task_mode=TaskMode.DRAFT_ARTIFACT,
            depends_on=[assessment_engine],
            requires_approval=True,  # Section 6.2: approval gate before draft
            parsed_input={
                "task_mode": TaskMode.DRAFT_ARTIFACT.value,
                "material_designation": parsed.material_designation,
                "gas_service": parsed.gas_service,
                "pressure_value": parsed.pressure_value,
                "raw_query": parsed.raw_query,
            },
        )

        return [assessment_step, draft_step]

    def _resolve_assessment_engine(self, parsed: ParsedQuery) -> str:
        """Determine which assessment engine to use based on gas service."""
        if parsed.gas_service == "hydrogen":
            return "h2"
        if parsed.gas_service == "oxygen":
            return "oca"
        # Default to OCA for oxygen-centric queries
        return parsed.fine_routing if parsed.fine_routing in ("oca", "h2") else "oca"

    def _build_oxygen_service_context(
        self,
        parsed: ParsedQuery,
    ) -> dict[str, Any]:
        """Build OCA service context from parsed entities.

        Mirrors router._build_oca_service_context but doesn't import it
        to avoid circular dependency.
        """
        raw = parsed.raw_query.lower()
        oxidizer_type = "gox"
        phase = "gas"
        if "lox" in raw or "liquid oxygen" in raw:
            oxidizer_type = "lox"
            phase = "liquid"

        ctx: dict[str, Any] = {
            "oxidizer_type": oxidizer_type,
            "o2_fraction": 1.0,
            "phase": phase,
        }
        if parsed.pressure_value is not None:
            ctx["total_pressure_min_psia"] = parsed.pressure_value
            ctx["total_pressure_max_psia"] = parsed.pressure_value
            if parsed.gas_service == "oxygen":
                ctx["oxygen_partial_pressure_psia"] = parsed.pressure_value

        # Default temperature
        ctx["temp_min_c"] = 20.0
        ctx["temp_max_c"] = 20.0
        if parsed.temperature_value is not None:
            # Simplified: assume Celsius. Full conversion is in router.py.
            ctx["temp_min_c"] = parsed.temperature_value
            ctx["temp_max_c"] = parsed.temperature_value

        return ctx

    # ------------------------------------------------------------------
    # Private: side-effect enforcement
    # ------------------------------------------------------------------

    def _enforce_side_effect_levels(
        self,
        steps: list[PlanStep],
    ) -> list[PlanStep]:
        """Filter or gate steps based on side-effect level policy.

        Per Section 3.3:
        - read_only and transient_generate: allowed without gate
        - persisted_draft: requires approval gate (set requires_approval)
        - workflow_submit: NEVER allowed — step is removed with a warning
        """
        valid_steps: list[PlanStep] = []

        for step in steps:
            engine_entry = get_engine(step.engine_id)

            if engine_entry is None:
                # Unknown engine — let execution handle the missing-adapter error
                valid_steps.append(step)
                continue

            level = engine_entry.get("side_effect_level", "read_only")

            if level in _FORBIDDEN_SIDE_EFFECTS:
                LOGGER.warning(
                    "[ORCH] Step %s has forbidden side_effect_level=%s "
                    "— removed from plan.",
                    step.engine_id, level,
                )
                continue

            if level in _APPROVAL_REQUIRED_SIDE_EFFECTS:
                if not step.requires_approval:
                    LOGGER.info(
                        "[ORCH] Step %s has side_effect_level=%s "
                        "— setting requires_approval=True.",
                        step.engine_id, level,
                    )
                    step.requires_approval = True

            # draft_artifact tasks always require approval regardless of
            # the engine's declared side-effect level, because generating
            # an artifact is a user-visible side effect.
            if step.task_mode == TaskMode.DRAFT_ARTIFACT and not step.requires_approval:
                step.requires_approval = True

            valid_steps.append(step)

        return valid_steps

    # ------------------------------------------------------------------
    # Private: data handoff between steps
    # ------------------------------------------------------------------

    def _apply_handoff(
        self,
        source_envelope: EngineEnvelope,
        target_step: PlanStep,
        session_context: dict[str, Any],
    ) -> None:
        """Transfer data from a completed step's envelope to the next step's input.

        Uses the capability registry's chaining_outputs to determine what
        data flows between steps. Falls back to a standard handoff dict
        when no explicit chaining rule exists.
        """
        chaining = get_chaining_suggestion(
            source_envelope.engine_id,
            source_envelope.status.value,
        )

        handoff_data: dict[str, Any] = {
            "material": source_envelope.domain_payload.get("material"),
            "environment": source_envelope.domain_payload.get("environment"),
            "gaps": list(source_envelope.missing_inputs),
            "verdict": source_envelope.status.value,
            "case_id": source_envelope.domain_payload.get("case_id"),
            "citations": list(source_envelope.citations),
            "assumptions": list(source_envelope.assumptions),
            "recommended_actions": list(source_envelope.recommended_actions),
            "source_engine": source_envelope.engine_id,
            "source_response_text": source_envelope.response_text,
            "domain_payload": dict(source_envelope.domain_payload),
        }

        if chaining:
            # Only pass the fields specified in data_handoff
            handoff_keys = chaining.get("data_handoff", [])
            if handoff_keys:
                filtered = {
                    k: v for k, v in handoff_data.items() if k in handoff_keys
                }
                handoff_data = filtered

        # Merge into target step's parsed_input (don't overwrite existing keys)
        for key, value in handoff_data.items():
            if key not in target_step.parsed_input or target_step.parsed_input[key] is None:
                target_step.parsed_input[key] = value

        # Also persist as "last_assessment" in session for the draft builder
        session_context["last_assessment"] = {
            "engine_id": source_envelope.engine_id,
            "engine_version": source_envelope.engine_version,
            "status": source_envelope.status.value,
            "entities": {
                "material_designation": (
                    target_step.parsed_input.get("material_designation")
                    or source_envelope.domain_payload.get("material")
                ),
                "gas_service": target_step.parsed_input.get("gas_service"),
                "pressure_value": target_step.parsed_input.get("pressure_value"),
            },
            "response_text": source_envelope.response_text,
            "citations": list(source_envelope.citations),
            "assumptions": list(source_envelope.assumptions),
            "recommended_actions": list(source_envelope.recommended_actions),
            "domain_payload": dict(source_envelope.domain_payload),
        }

    # ------------------------------------------------------------------
    # Private: approval gate helpers
    # ------------------------------------------------------------------

    def _build_approval_prompt(
        self,
        completed_envelopes: list[EngineEnvelope],
        next_step: PlanStep,
    ) -> str:
        """Build the user-facing approval prompt for an approval gate.

        Presents the assessment result and asks whether to proceed to
        the draft-generation step.
        """
        if not completed_envelopes:
            return (
                "I need to run an assessment first before drafting. "
                "Would you like me to proceed?"
            )

        last = completed_envelopes[-1]
        verdict = last.status.value.replace("_", " ").title()
        engine_label = last.engine_id.upper()

        if next_step.task_mode == TaskMode.DRAFT_ARTIFACT:
            artifact_type = "MUA"  # Default artifact type
            return (
                f"The {engine_label} assessment returned **{verdict}**. "
                f"Based on this result, would you like me to draft the {artifact_type}?"
            )

        return (
            f"The {engine_label} assessment returned **{verdict}**. "
            f"Would you like me to proceed to the next step "
            f"({next_step.engine_id})?"
        )

    @staticmethod
    def _is_approval_confirmation(text: str) -> bool:
        """Check if the user's message is an approval to continue.

        Recognises common affirmative patterns. Conservative: if unclear,
        returns False so the router falls through to normal interpretation.
        """
        normalised = text.strip().lower()

        # Direct yes/no
        if normalised in (
            "yes", "y", "yep", "yeah", "sure", "ok", "okay",
            "go ahead", "proceed", "do it", "draft it",
            "go", "continue", "yes please", "please",
            "yes, draft it", "yes draft it",
            "yes, please", "yes please",
            "affirmative", "confirmed", "confirm",
        ):
            return True

        # Pattern-based
        affirmative = re.compile(
            r"\b(?:yes|go\s+ahead|proceed|draft|continue|do\s+it|sure|please\s+draft"
            r"|write\s+(?:the\s+)?mua|generate\s+(?:the\s+)?mua"
            r"|create\s+(?:the\s+)?mua)\b",
            re.IGNORECASE,
        )
        return bool(affirmative.search(normalised))


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _dedup_ordered(items) -> list:
    """Deduplicate an iterable while preserving insertion order."""
    seen: set = set()
    result = []
    for item in items:
        # For unhashable items (dicts), convert to string for dedup
        key = str(item) if isinstance(item, dict) else item
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
