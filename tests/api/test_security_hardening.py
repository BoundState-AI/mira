from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mira.api.auth.cognito import MIRAUser, authorize_owner_or_admin
from mira.api.routers.test_classes import build_rating_filter
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
