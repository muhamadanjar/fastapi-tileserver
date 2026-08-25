import asyncio
from datetime import datetime, timedelta, timezone

from jose import jwt
from starlette.requests import Request
from starlette.responses import Response

from tileserver_api.app.presentation.middleware.auth_middleware import JWTAuthenticationMiddleware
from app.core.config import Settings
from app.core.security import TokenVerificationError, verify_access_token


SECRET = "tileserver-test-shared-secret"


def _settings() -> Settings:
    return Settings(ACCESS_TOKEN_SECRET=SECRET, ACCESS_TOKEN_ALGORITHMS="HS256")


def _token(*, token_type: str = "access", expires_in_minutes: int = 5) -> str:
    return jwt.encode(
        {
            "sub": "user-123",
            "token_type": token_type,
            "scopes": ["tiles.read"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        },
        SECRET,
        algorithm="HS256",
    )


def _request(path: str, authorization: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [(b"authorization", authorization.encode())] if authorization else [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def test_verifies_usermanagement_access_token():
    principal = verify_access_token(_token(), _settings())

    assert principal.subject == "user-123"
    assert principal.permissions == frozenset({"tiles.read"})


def test_rejects_refresh_token():
    try:
        verify_access_token(_token(token_type="refresh"), _settings())
    except TokenVerificationError as exc:
        assert str(exc) == "Bearer token must be an access token"
    else:
        raise AssertionError("Refresh token must not authenticate a Tileserver request")


def test_protected_paths_require_a_bearer_access_token():
    middleware = JWTAuthenticationMiddleware(lambda _: Response(), settings=_settings())

    class AllowResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"allowed": True, "principal": {"id": "user-123"}}}

    middleware._authorize = lambda *_: AllowResponse()

    async def next_handler(_: Request) -> Response:
        return Response(status_code=204)

    health = asyncio.run(middleware.dispatch(_request("/health"), next_handler))
    missing = asyncio.run(middleware.dispatch(_request("/api/v1/layers"), next_handler))
    valid = asyncio.run(
        middleware.dispatch(
            _request("/api/v1/layers", f"Bearer {_token()}"),
            next_handler,
        )
    )

    assert health.status_code == 204
    assert missing.status_code == 401
    assert valid.status_code == 204


def test_permission_denial_is_forbidden():
    middleware = JWTAuthenticationMiddleware(lambda _: Response(), settings=_settings())

    class DenyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"allowed": False, "principal": {"id": "user-123"}}}

    middleware._authorize = lambda *_: DenyResponse()

    async def next_handler(_: Request) -> Response:
        return Response(status_code=204)

    response = asyncio.run(
        middleware.dispatch(_request("/api/v1/layers", "Bearer token"), next_handler)
    )
    assert response.status_code == 403
