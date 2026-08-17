from unittest.mock import patch

import pytest

from app.infrastructure.services.upload_artifact_client import (
    UploadArtifactClient,
    UploadArtifactClientError,
)

OAUTH_ENV = {
    "OAUTH_CLIENT_ID": "tileserver-client",
    "OAUTH_CLIENT_SECRET": "tileserver-secret",
    "OAUTH_TOKEN_URL": "http://identity/oauth/token",
    "OAUTH_AUDIENCE": "upload-api",
    "OAUTH_SCOPES": "upload.artifacts.read upload.artifacts.lease",
    "UPLOAD_API_SERVICE_TOKEN": "",
    "UPLOAD_API_CALLER_TOKEN": "",
}


def test_oauth_credentials_create_audience_scoped_caller():
    with patch.dict("os.environ", OAUTH_ENV, clear=False), patch(
        "app.infrastructure.services.upload_artifact_client.SyncOAuthServiceClient"
    ) as oauth_client:
        oauth_client.return_value.authorization_header.return_value = {
            "Authorization": "Bearer generated"
        }
        caller = UploadArtifactClient()

    oauth_client.assert_called_once_with(
        "http://identity/oauth/token",
        "tileserver-client",
        "tileserver-secret",
        "upload-api",
        ("upload.artifacts.read", "upload.artifacts.lease"),
    )
    assert caller.headers == {"Authorization": "Bearer generated"}


def test_partial_oauth_credentials_are_rejected():
    env = {**OAUTH_ENV, "OAUTH_CLIENT_SECRET": ""}
    with patch.dict("os.environ", env, clear=False):
        with pytest.raises(UploadArtifactClientError, match="configured together"):
            UploadArtifactClient()


def test_legacy_token_is_still_accepted_during_migration():
    env = {
        **OAUTH_ENV,
        "OAUTH_CLIENT_ID": "",
        "OAUTH_CLIENT_SECRET": "",
        "UPLOAD_API_SERVICE_TOKEN": "legacy-token",
    }
    with patch.dict("os.environ", env, clear=False), patch(
        "app.infrastructure.services.upload_artifact_client.record_auth_event"
    ) as auth_event:
        caller = UploadArtifactClient()
        assert caller.headers == {"Authorization": "Bearer legacy-token"}

    assert auth_event.call_args_list[-1].kwargs == {
        "outcome": "used",
        "caller_service": "tileserver-api",
        "resource_service": "upload-api",
    }


def test_revoked_token_fails_upload_call():
    """A revoked service token surfaces as a rejected Upload request (401)."""
    from unittest.mock import MagicMock

    from app.infrastructure.services import upload_artifact_client

    with patch.dict("os.environ", OAUTH_ENV, clear=False), patch(
        "app.infrastructure.services.upload_artifact_client.SyncOAuthServiceClient"
    ) as oauth_client, patch.object(upload_artifact_client.requests, "put") as mock_put:
        oauth_client.return_value.authorization_header.return_value = {
            "Authorization": "Bearer revoked"
        }
        mock_put.return_value = MagicMock(
            status_code=401,
            text="revoked token",
            json=lambda: {"error": "inactive_token"},
        )
        caller = UploadArtifactClient()
        with pytest.raises(UploadArtifactClientError, match="revoked token"):
            caller.acquire_lease("artifact-1", "grant-1", "handoff-1")

    mock_put.assert_called_once()
    headers = mock_put.call_args.kwargs["headers"]
    assert headers == {"Authorization": "Bearer revoked"}
