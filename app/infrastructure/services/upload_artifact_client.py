from __future__ import annotations

import os
import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import requests
from service_auth import SyncOAuthServiceClient, record_auth_event


class UploadArtifactClientError(RuntimeError):
    pass


class UploadArtifactClient:
    def __init__(self):
        self.base_url = os.getenv("UPLOAD_API_URL", "http://localhost:8010/api/v1").rstrip("/")
        self.legacy_token = os.getenv("UPLOAD_API_SERVICE_TOKEN") or os.getenv("UPLOAD_API_CALLER_TOKEN", "")
        oauth_client_id = os.getenv("OAUTH_CLIENT_ID", "")
        oauth_client_secret = os.getenv("OAUTH_CLIENT_SECRET", "")
        oauth_audience = os.getenv("OAUTH_AUDIENCE", "upload-api")
        oauth_scopes = tuple(
            os.getenv(
                "OAUTH_SCOPES",
                "upload.artifacts.read upload.artifacts.lease",
            ).split()
        )
        self._oauth = None
        if bool(oauth_client_id) != bool(oauth_client_secret):
            raise UploadArtifactClientError(
                "OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET must be configured together"
            )
        if oauth_client_id and (not oauth_audience or not oauth_scopes):
            raise UploadArtifactClientError(
                "OAUTH_AUDIENCE and OAUTH_SCOPES must be configured for OAuth calls"
            )
        if oauth_client_id and oauth_client_secret:
            self._oauth = SyncOAuthServiceClient(
                os.getenv("OAUTH_TOKEN_URL", "http://localhost:8000/oauth/token"),
                oauth_client_id,
                oauth_client_secret,
                oauth_audience,
                oauth_scopes,
            )
        elif self.legacy_token:
            logging.getLogger(__name__).warning(
                "DEPRECATED UPLOAD_API_SERVICE_TOKEN is in use; configure OAuth client credentials"
            )
            record_auth_event(
                "legacy_static_token",
                outcome="configured",
                caller_service="tileserver-api",
                resource_service="upload-api",
            )
        else:
            raise UploadArtifactClientError(
                "OAuth client credentials are not configured and no deprecated Upload token is available"
            )

    @property
    def headers(self) -> dict[str, str]:
        if self._oauth:
            return self._oauth.authorization_header()
        record_auth_event(
            "legacy_static_token",
            outcome="used",
            caller_service="tileserver-api",
            resource_service="upload-api",
        )
        return {"Authorization": f"Bearer {self.legacy_token}"}

    def acquire_lease(self, artifact_id: str, grant_id: str, reference: str) -> dict:
        print(self.headers)
        response = requests.put(
            f"{self.base_url}/artifacts/{artifact_id}/leases",
            headers=self.headers,
            json={"grant_id": grant_id, "consumer_reference": reference},
            timeout=15,
        )
        print("response", response.text)
        if response.status_code >= 400:
            raise UploadArtifactClientError(response.text[:500])
        return response.json()

    def metadata(self, artifact_id: str) -> dict:
        response = requests.get(
            f"{self.base_url}/artifacts/{artifact_id}",
            headers=self.headers,
            timeout=15,
        )
        if response.status_code >= 400:
            raise UploadArtifactClientError(response.text[:500])
        return response.json()

    def release_lease(self, artifact_id: str, lease_id: str) -> None:
        response = requests.delete(
            f"{self.base_url}/artifacts/{artifact_id}/leases/{lease_id}",
            headers=self.headers,
            timeout=15,
        )
        if response.status_code >= 400:
            raise UploadArtifactClientError(response.text[:500])

    @contextmanager
    def materialize(self, artifact_id: str, filename: str) -> Iterator[Path]:
        with tempfile.TemporaryDirectory(prefix="tiles-artifact-") as directory:
            destination = Path(directory) / Path(filename).name
            with requests.get(
                f"{self.base_url}/artifacts/{artifact_id}/content",
                headers=self.headers,
                stream=True,
                allow_redirects=True,
                timeout=(10, 600),
            ) as response:
                if response.status_code >= 400:
                    raise UploadArtifactClientError(
                        f"Artifact download failed with HTTP {response.status_code}: {response.text[:500]}"
                    )
                with destination.open("wb") as output:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if block:
                            output.write(block)
            yield destination
