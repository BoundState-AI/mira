from __future__ import annotations

import pytest

from mira.api.auth.cognito import validate_auth_configuration


def test_validate_auth_configuration_rejects_production_without_cognito(monkeypatch) -> None:
    monkeypatch.setenv("MIRA_ENV", "production")
    monkeypatch.setenv("MIRA_AUTH_MODE", "none")

    with pytest.raises(RuntimeError, match="not allowed in production"):
        validate_auth_configuration()


def test_validate_auth_configuration_accepts_cognito_in_production(monkeypatch) -> None:
    monkeypatch.setenv("MIRA_ENV", "production")
    monkeypatch.setenv("MIRA_AUTH_MODE", "cognito")
    monkeypatch.setenv("COGNITO_REGION", "us-gov-west-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-gov-west-1_example")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "exampleclientid123")

    validate_auth_configuration()
