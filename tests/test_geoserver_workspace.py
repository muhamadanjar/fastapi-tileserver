from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.services.geoserver_service import GeoServerService


def service() -> GeoServerService:
    instance = object.__new__(GeoServerService)
    instance._base_url = "http://geoserver.internal/geoserver"
    instance._auth = ("admin", "secret")
    instance.workspace = "tileserver"
    return instance


def response(status_code: int, text: str = "") -> MagicMock:
    return MagicMock(status_code=status_code, text=text)


def test_ensure_workspace_returns_when_configured_workspace_exists():
    with patch("app.infrastructure.services.geoserver_service.requests.get", return_value=response(200)) as get, patch(
        "app.infrastructure.services.geoserver_service.requests.post"
    ) as post:
        service()._ensure_workspace()

    assert get.call_count == 1
    post.assert_not_called()


def test_ensure_workspace_creates_and_verifies_missing_workspace():
    with patch(
        "app.infrastructure.services.geoserver_service.requests.get",
        side_effect=[response(404), response(200)],
    ), patch(
        "app.infrastructure.services.geoserver_service.requests.post", return_value=response(201)
    ) as post:
        service()._ensure_workspace()

    assert post.call_args.kwargs["json"] == {"workspace": {"name": "tileserver"}}


def test_ensure_workspace_surfaces_authorization_or_proxy_errors_before_datastore_creation():
    with patch("app.infrastructure.services.geoserver_service.requests.get", return_value=response(401, "Unauthorized")):
        with pytest.raises(RuntimeError, match="workspace check failed \(401\)"):
            service()._ensure_workspace()
