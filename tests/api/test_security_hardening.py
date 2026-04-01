from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mira.api.auth.cognito import (
    MIRAUser,
    authorize_owner_or_admin,
    enforce_user_access,
    user_is_approved,
)
from mira.api.routers.test_classes import build_rating_filter
from mira.chat.module_context import extract_module_entities
from mira.chat.models import EngineEnvelope, Status, TaskMode
from mira.chat.response_formatter import (
    _fallback_format,
    _plain_language_summary,
    build_formatter_prompt,
    build_formatter_system_prompt,
    get_formatter_profile,
)
from mira.providers.llm_provider import validate_provider_configuration


def _request_with_user(user: MIRAUser | None):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def test_authorize_owner_or_admin_allows_auth_disabled_request_without_user():
    request = _request_with_user(None)

    assert authorize_owner_or_admin(request, "owner-1", resource_label="session") is None


def test_authorize_owner_or_admin_allows_owner():
    request = _request_with_user(
        MIRAUser(
            sub="user-1",
            username="owner-1",
            email="owner@example.com",
            groups=(),
            role="viewer",
            itar_access="",
            us_person_verified=True,
        )
    )

    user = authorize_owner_or_admin(request, "owner-1", resource_label="session")

    assert user is not None
    assert user.username == "owner-1"


def test_authorize_owner_or_admin_allows_admin():
    request = _request_with_user(
        MIRAUser(
            sub="admin-1",
            username="admin-1",
            email="admin@example.com",
            groups=("mira-admin",),
            role="admin",
            itar_access="full",
            us_person_verified=True,
        )
    )

    user = authorize_owner_or_admin(request, None, resource_label="session")

    assert user is not None
    assert user.is_admin


def test_authorize_owner_or_admin_rejects_non_owner():
    request = _request_with_user(
        MIRAUser(
            sub="user-2",
            username="someone-else",
            email="someone@example.com",
            groups=(),
            role="viewer",
            itar_access="",
            us_person_verified=True,
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        authorize_owner_or_admin(request, "owner-1", resource_label="session")

    assert exc_info.value.status_code == 403


def test_user_is_approved_defaults_open_when_no_allowlist(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MIRA_ALLOWED_GROUPS", raising=False)
    monkeypatch.delenv("MIRA_ALLOWED_USERNAMES", raising=False)
    monkeypatch.delenv("MIRA_ALLOWED_EMAILS", raising=False)

    user = MIRAUser(
        sub="user-1",
        username="someone",
        email="someone@example.com",
        groups=(),
        role="viewer",
        itar_access="",
        us_person_verified=True,
    )

    assert user_is_approved(user) is True


def test_user_is_approved_accepts_matching_group(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIRA_ALLOWED_GROUPS", "mira-user,mira-admin")
    monkeypatch.delenv("MIRA_ALLOWED_USERNAMES", raising=False)
    monkeypatch.delenv("MIRA_ALLOWED_EMAILS", raising=False)

    user = MIRAUser(
        sub="user-1",
        username="someone",
        email="someone@example.com",
        groups=("mira-user",),
        role="viewer",
        itar_access="",
        us_person_verified=True,
    )

    assert user_is_approved(user) is True


def test_enforce_user_access_rejects_authenticated_but_unapproved_user(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIRA_ALLOWED_GROUPS", "mira-user")
    monkeypatch.delenv("MIRA_ALLOWED_USERNAMES", raising=False)
    monkeypatch.delenv("MIRA_ALLOWED_EMAILS", raising=False)

    user = MIRAUser(
        sub="user-2",
        username="someone-else",
        email="someone@example.com",
        groups=("external-authenticated",),
        role="viewer",
        itar_access="",
        us_person_verified=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_user_access(user)

    assert exc_info.value.status_code == 403


def test_build_rating_filter_allows_known_toxicity_rating_type():
    clause, params = build_rating_filter("toxicity_report", "A", "tox_emurating")

    assert clause == "(normalized_payload->>'tox_emurating' = %s)"
    assert params == ["A"]


def test_build_rating_filter_rejects_unknown_toxicity_rating_type():
    with pytest.raises(HTTPException) as exc_info:
        build_rating_filter("toxicity_report", "A", "tox_emurating' OR '1'='1")

    assert exc_info.value.status_code == 400


def test_validate_provider_configuration_rejects_missing_anthropic_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        validate_provider_configuration("anthropic")


def test_validate_provider_configuration_rejects_missing_openai_compat_settings(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        validate_provider_configuration("openai-compat")


def test_get_formatter_profile_uses_manifest_expert_profile():
    profile = get_formatter_profile("galvanic")

    assert profile["display_name"] == "Galvanic Corrosion Assessment"
    assert "galvanic corrosion engineer" in profile["role"]
    assert any("anodic member" in line for line in profile["voice"])


def test_build_formatter_system_prompt_includes_engine_specialist_language():
    envelope = EngineEnvelope(
        status=Status.CONDITIONAL_PASS,
        engine_id="fracture",
        engine_version="1.0.0",
        response_text="Conditional path.",
        mode=TaskMode.ANSWER_ONLY,
    )

    prompt = build_formatter_system_prompt(envelope, {"turn_count": 2})

    assert "Fracture Mechanics Assessment" in prompt
    assert "senior fracture-control engineer" in prompt
    assert "classification path" in prompt
    assert "Turn: 2" in prompt


def test_plain_language_summary_uses_hydrogen_specialist_fallback():
    envelope = EngineEnvelope(
        status=Status.FAIL,
        engine_id="h2",
        engine_version="1.0.0",
        response_text="Fail path.",
        mode=TaskMode.ANSWER_ONLY,
    )

    summary = _plain_language_summary(envelope)

    assert "hydrogen-compatibility" in summary
    assert "embrittlement" in summary or "service risk" in summary


def test_build_formatter_prompt_includes_module_workflow_context():
    envelope = EngineEnvelope(
        status=Status.INSUFFICIENT_DATA,
        engine_id="gpcm",
        engine_version="1.0.0",
        response_text="Need exact evidence.",
        mode=TaskMode.ANSWER_ONLY,
    )
    session_context = {
        "turn_count": 2,
        "module_context": {
            "module": "gpcm",
            "chat_workflow": {
                "current_step": "tailoring_review",
                "active_field_label": "Tailoring",
                "completed_fields": ["Program", "Part Name"],
                "incomplete_fields": ["Tailoring"],
                "next_steps": ["Attach the governing closure artifact."],
                "blockers": ["No tailoring rationale attached"],
            },
        },
    }

    prompt = build_formatter_prompt(envelope, session_context)

    assert "WORKFLOW CONTEXT:" in prompt
    assert "Current step: tailoring_review" in prompt
    assert "Active field: Tailoring" in prompt
    assert "Completed fields: Program, Part Name" in prompt
    assert "Next steps: Attach the governing closure artifact." in prompt
    assert "Blockers: No tailoring rationale attached" in prompt


def test_extract_module_entities_flattens_workflow_context():
    entities = extract_module_entities(
        {
            "module": "gpcm",
            "material": "Kapton",
            "chat_workflow": {
                "current_step": "tailoring_review",
                "active_field": "inputs.tailoring",
                "active_field_label": "Tailoring",
                "completed_fields": ["Program", "Part Name"],
                "incomplete_fields": ["Tailoring"],
                "next_steps": ["Attach the governing closure artifact."],
                "blockers": ["No tailoring rationale attached"],
            },
        }
    )

    assert entities["engine_used"] == "gpcm"
    assert entities["material_designation"] == "Kapton"
    assert entities["current_step"] == "tailoring_review"
    assert entities["active_field"] == "inputs.tailoring"
    assert entities["active_field_label"] == "Tailoring"
    assert entities["completed_fields"] == ["Program", "Part Name"]
    assert entities["incomplete_fields"] == ["Tailoring"]
    assert entities["next_steps"] == ["Attach the governing closure artifact."]
    assert entities["workflow_blockers"] == ["No tailoring rationale attached"]


def test_fallback_format_surfaces_active_field_and_next_steps():
    envelope = EngineEnvelope(
        status=Status.INSUFFICIENT_DATA,
        engine_id="gpcm",
        engine_version="1.0.0",
        response_text="Requirement is unresolved with current evidence.",
        mode=TaskMode.ANSWER_ONLY,
        missing_inputs=["Tailoring rationale"],
    )
    session_context = {
        "module_context": {
            "module": "gpcm",
            "chat_workflow": {
                "current_step": "tailoring_review",
                "active_field_label": "Tailoring",
                "next_steps": ["Attach the governing closure artifact."],
                "blockers": ["No tailoring rationale attached"],
            },
        }
    }

    formatted = _fallback_format(envelope, session_context)

    assert "Current field: Tailoring" in formatted
    assert "Workflow step: tailoring_review" in formatted
    assert "**Next step in this module:**" in formatted
    assert "Attach the governing closure artifact." in formatted
    assert "**Open blockers:**" in formatted
