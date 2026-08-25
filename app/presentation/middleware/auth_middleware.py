from __future__ import annotations

import asyncio

import requests
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.security import AuthPrincipal


class JWTAuthenticationMiddleware(BaseHTTPMiddleware):
    """Require a current User Management permission decision for protected paths."""

    protected_prefixes = ("/api/v1", "/downloads", "/attachments")

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    @staticmethod
    def _required_permission(request: Request) -> str:
        if request.url.path.startswith(("/tiles", "/downloads", "/attachments")):
            return "tiles.read"
        return "tiles.read" if request.method in {"GET", "HEAD"} else "tiles.manage"

    def _authorize(self, token: str, permission: str) -> requests.Response:
        return requests.post(
            f"{self.settings.USERMANAGEMENT_API_URL.rstrip('/')}/auth/authorize",
            headers={"Authorization": f"Bearer {token}"},
            json={"permission": permission},
            timeout=self.settings.AUTHORIZATION_TIMEOUT_SECONDS,
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.settings.AUTH_DISABLED or request.method == "OPTIONS" or not request.url.path.startswith(self.protected_prefixes):
            return await call_next(request)

        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse({"detail": "Bearer access token is required"}, status_code=401)

        try:
            response = await asyncio.to_thread(
                self._authorize, token, self._required_permission(request)
            )
        except requests.RequestException:
            return JSONResponse(
                {"detail": "Authorization service unavailable"}, status_code=503
            )

        if response.status_code == 401:
            return JSONResponse({"detail": "Invalid or expired access token"}, status_code=401)
        if response.status_code != 200:
            return JSONResponse({"detail": "Authorization service unavailable"}, status_code=503)

        try:
            decision = response.json()["data"]
            if not decision["allowed"]:
                return JSONResponse({"detail": "Permission denied"}, status_code=403)
            principal = decision["principal"]
            request.state.principal = AuthPrincipal(
                subject=str(principal["id"]), tenant_id=None, permissions=frozenset()
            )
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                {"detail": "Authorization service unavailable"}, status_code=503
            )

        return await call_next(request)
