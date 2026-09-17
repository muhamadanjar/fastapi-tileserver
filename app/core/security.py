from __future__ import annotations

from dataclasses import dataclass
@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    tenant_id: str | None
    permissions: frozenset[str]
