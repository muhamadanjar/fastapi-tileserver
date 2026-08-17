from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jose import JWTError, jwt

from app.core.config import Settings


class TokenVerificationError(ValueError):
    """Raised when a request does not contain a valid internal access token."""


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    tenant_id: str | None
    permissions: frozenset[str]


def verify_access_token(token: str, settings: Settings) -> AuthPrincipal:
    """Verify an unexpired User Management internal access JWT."""
    key = settings.ACCESS_TOKEN_PUBLIC_KEY or settings.ACCESS_TOKEN_SECRET
    if not key:
        raise TokenVerificationError("Access token verification key is not configured")

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=settings.access_token_algorithms,
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise TokenVerificationError("Invalid or expired access token") from exc

    if claims.get("token_type") != "access":
        raise TokenVerificationError("Bearer token must be an access token")

    subject = claims.get("sub") or claims.get("user_id")
    if not subject:
        raise TokenVerificationError("Access token has no subject")

    raw_permissions = claims.get("permissions") or claims.get("scopes") or claims.get("scope") or []
    if isinstance(raw_permissions, str):
        permissions = frozenset(raw_permissions.replace(",", " ").split())
    else:
        permissions = frozenset(str(item) for item in raw_permissions)

    return AuthPrincipal(
        subject=str(subject),
        tenant_id=str(claims["tenant_id"]) if claims.get("tenant_id") else None,
        permissions=permissions,
    )
