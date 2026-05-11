"""Identity helpers: build `UserIdentity` from auth claims, with PIV fallback."""

from __future__ import annotations

from typing import Any

from .models import UserIdentity


def _str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_user_identity_from_claims(
    claims: dict[str, Any] | None,
    *,
    auth_method: str = "cognito",
) -> UserIdentity:
    """Construct a `UserIdentity` from raw Cognito claim payload.

    PIV-specific attributes are pulled from the ``custom:`` namespace that
    federated identity providers populate (Launchpad → Cognito mapping).
    Absent those claims, the PIV fields stay empty and the record still
    captures the standard Cognito identity.
    """
    if not claims:
        return UserIdentity(auth_method="anonymous")

    groups_raw = claims.get("cognito:groups") or []
    if isinstance(groups_raw, str):
        groups = [item.strip() for item in groups_raw.split(",") if item.strip()]
    elif isinstance(groups_raw, (list, tuple)):
        groups = [_str(item) for item in groups_raw if _str(item)]
    else:
        groups = []

    us_person_raw = claims.get("custom:us_person_verified")
    us_person_verified: bool | None
    if us_person_raw is None:
        us_person_verified = None
    else:
        us_person_verified = _str(us_person_raw).lower() == "true"

    has_piv = bool(claims.get("custom:edipi") or claims.get("custom:piv_subject"))
    method = auth_method
    if has_piv and method == "cognito":
        method = "cognito+piv"

    return UserIdentity(
        sub=_str(claims.get("sub")),
        username=_str(
            claims.get("cognito:username")
            or claims.get("username")
            or claims.get("preferred_username")
            or claims.get("email"),
        ),
        email=_str(claims.get("email")),
        role=_str(claims.get("custom:role")),
        groups=groups,
        itar_access=_str(claims.get("custom:itar_access")),
        us_person_verified=us_person_verified,
        edipi=_str(claims.get("custom:edipi")),
        piv_subject=_str(claims.get("custom:piv_subject")),
        agency=_str(claims.get("custom:agency")),
        auth_method=method,
    )


def build_user_identity_from_mira_user(user: Any) -> UserIdentity:
    """Construct a `UserIdentity` from a `MIRAUser` dataclass instance."""
    if user is None:
        return UserIdentity(auth_method="anonymous")

    sub = _str(getattr(user, "sub", ""))
    username = _str(getattr(user, "username", ""))
    email = _str(getattr(user, "email", ""))
    role = _str(getattr(user, "role", ""))
    itar_access = _str(getattr(user, "itar_access", ""))
    us_person_verified = getattr(user, "us_person_verified", None)
    groups_raw = getattr(user, "groups", ()) or ()
    groups = [_str(item) for item in groups_raw if _str(item)]
    edipi = _str(getattr(user, "edipi", ""))
    piv_subject = _str(getattr(user, "piv_subject", ""))
    agency = _str(getattr(user, "agency", ""))

    method = "cognito"
    if edipi or piv_subject:
        method = "cognito+piv"

    return UserIdentity(
        sub=sub,
        username=username,
        email=email,
        role=role,
        groups=groups,
        itar_access=itar_access,
        us_person_verified=us_person_verified,
        edipi=edipi,
        piv_subject=piv_subject,
        agency=agency,
        auth_method=method,
    )
