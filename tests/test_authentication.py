import asyncio

import requests
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.presentation.middleware.auth_middleware import JWTAuthenticationMiddleware


def _settings() -> Settings:
    return Settings(AUTH_DISABLED=False, USERMANAGEMENT_API_URL="http://identity")


def _request(path: str, *, method: str = "GET", authorization: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"authorization", authorization.encode())] if authorization else [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


class AllowResponse:
    status_code = 200

    @staticmethod
    def json():
        return {"data": {"allowed": True, "principal": {"id": "user-123"}}}


async def _next_handler(_: Request) -> Response:
    return Response(status_code=204)


def test_default_protected_paths_require_a_bearer_token():
    middleware = JWTAuthenticationMiddleware(lambda _: Response(), settings=_settings())

    assert asyncio.run(middleware.dispatch(_request("/health"), _next_handler)).status_code == 204
    assert asyncio.run(middleware.dispatch(_request("/api/v1/analysis-workspace/references"), _next_handler)).status_code == 204
    assert asyncio.run(middleware.dispatch(_request("/api/v1/layers"), _next_handler)).status_code == 401
    assert asyncio.run(middleware.dispatch(_request("/future-route"), _next_handler)).status_code == 401


def test_workspace_save_requires_tiles_manage_and_allows_valid_bearer():
    middleware = JWTAuthenticationMiddleware(lambda _: Response(), settings=_settings())
    permissions: list[str] = []

    def authorize(_token: str, permission: str):
        permissions.append(permission)
        return AllowResponse()

    middleware._authorize = authorize
    save_path = "/api/v1/analysis-workspace/jobs/job-1/save"

    assert asyncio.run(middleware.dispatch(_request(save_path), _next_handler)).status_code == 401
    assert asyncio.run(
        middleware.dispatch(_request(save_path, method="POST", authorization="Bearer jwt"), _next_handler)
    ).status_code == 204
    assert permissions == ["tiles.manage"]


def test_permission_matrix_uses_manage_for_mutations_and_reference_configuration():
    middleware = JWTAuthenticationMiddleware(lambda _: Response(), settings=_settings())
    permissions: list[str] = []
    middleware._authorize = lambda _token, permission: permissions.append(permission) or AllowResponse()

    for request in (
        _request("/tiles/layer/0/0/0.pbf", authorization="Bearer jwt"),
        _request("/api/v1/layers/layer", method="PATCH", authorization="Bearer jwt"),
        _request("/api/v1/analysis-references/layer", authorization="Bearer jwt"),
    ):
        assert asyncio.run(middleware.dispatch(request, _next_handler)).status_code == 204

    assert permissions == ["tiles.read", "tiles.manage", "tiles.manage"]


def test_permission_denial_is_forbidden():
    middleware = JWTAuthenticationMiddleware(lambda _: Response(), settings=_settings())

    class DenyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"allowed": False, "principal": {"id": "user-123"}}}

    middleware._authorize = lambda *_: DenyResponse()

    response = asyncio.run(
        middleware.dispatch(_request("/api/v1/layers", authorization="Bearer jwt"), _next_handler)
    )
    assert response.status_code == 403


def test_invalid_token_and_authorization_outage_fail_closed():
    middleware = JWTAuthenticationMiddleware(lambda _: Response(), settings=_settings())

    class InvalidTokenResponse:
        status_code = 401

    middleware._authorize = lambda *_: InvalidTokenResponse()
    assert asyncio.run(
        middleware.dispatch(_request("/api/v1/layers", authorization="Bearer expired"), _next_handler)
    ).status_code == 401

    def unavailable(*_):
        raise requests.Timeout()

    middleware._authorize = unavailable
    assert asyncio.run(
        middleware.dispatch(_request("/api/v1/layers", authorization="Bearer jwt"), _next_handler)
    ).status_code == 503
