"""Page-aware proactive greeting templates.

Frontend posts ``/api/chat/presence`` when a chat panel opens with a non-empty
``chat_workflow.current_step``. We return a single short, contextual line —
templated, no LLM call — that the UI displays and, when voice is enabled,
auto-speaks.

The plumbing for ``chat_workflow`` already exists end-to-end (see
``frontend/src/lib/mira-chat-context.ts``::``buildWorkflowContext`` and
``mira/chat/module_context.py``::``_extract_workflow_entities``). This module
adds the proactive surfacing layer on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_STEP_LABELS: dict[str, str] = {
    "review_decision": "review of the decision",
    "review_precheck": "the OCA precheck review",
    "complete_required_inputs": "completing the required inputs",
    "ready_to_run_screening": "ready to run screening",
    "ready_to_run_compatibility": "ready to run the compatibility check",
    "review_result": "reviewing the result",
    "setup": "setup",
    "environment": "the environment step",
    "materials": "the materials step",
    "analysis": "the analysis step",
    "generate": "the generate step",
    "classification": "classification",
    "part_context": "the part context step",
}


@dataclass(frozen=True)
class PresenceGreeting:
    text: str
    step_key: str | None
    step_label: str | None
    blockers: list[str]


def _humanize_step(step_key: str | None) -> str | None:
    if not step_key:
        return None
    if step_key in _STEP_LABELS:
        return _STEP_LABELS[step_key]
    cleaned = step_key.replace("_", " ").strip()
    return cleaned or None


def build_greeting(module_context: dict[str, Any] | None) -> PresenceGreeting | None:
    """Return a templated greeting from module_context, or ``None`` if not applicable."""
    if not isinstance(module_context, dict):
        return None
    workflow = module_context.get("chat_workflow")
    if not isinstance(workflow, dict):
        return None

    step_key_raw = workflow.get("current_step")
    step_key = str(step_key_raw).strip() if isinstance(step_key_raw, str) else None
    if not step_key:
        return None

    step_label = _humanize_step(step_key)
    if not step_label:
        return None

    blockers_raw = workflow.get("blockers") or []
    blockers: list[str] = []
    if isinstance(blockers_raw, list):
        for entry in blockers_raw:
            if isinstance(entry, str) and entry.strip():
                blockers.append(entry.strip())

    active_field = workflow.get("active_field_label")
    if isinstance(active_field, str) and active_field.strip():
        text = (
            f"I see you're working on {step_label}, and you've got {active_field.strip()} "
            "open. Want help with that?"
        )
    elif blockers:
        primary = blockers[0]
        if len(blockers) == 1:
            text = (
                f"I see you're at {step_label}. Looks like {primary} hasn't been entered yet — "
                "want help with that?"
            )
        else:
            extra = len(blockers) - 1
            text = (
                f"I see you're at {step_label}. Looks like {primary} and "
                f"{extra} other field{'s' if extra != 1 else ''} still need attention — "
                "want help walking through them?"
            )
    else:
        text = f"I see you're at {step_label}. Anything I can help with?"

    return PresenceGreeting(
        text=text,
        step_key=step_key,
        step_label=step_label,
        blockers=blockers,
    )
