from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import requests


class UploadArtifactClientError(RuntimeError):
    pass


class UploadArtifactClient:
    def __init__(self):
        self.base_url = os.getenv("UPLOAD_API_URL", "http://localhost:8010/api/v1").rstrip("/")
        self.token = os.getenv("UPLOAD_API_CALLER_TOKEN") or os.getenv("UPLOAD_API_SERVICE_TOKEN", "")
        if not self.token:
            raise UploadArtifactClientError(
                "UPLOAD_API_CALLER_TOKEN is not configured "
                "(UPLOAD_API_SERVICE_TOKEN is accepted temporarily)"
            )

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def acquire_lease(self, artifact_id: str, grant_id: str, reference: str) -> dict:
        response = requests.put(
            f"{self.base_url}/artifacts/{artifact_id}/leases",
            headers=self.headers,
            json={"grant_id": grant_id, "consumer_reference": reference},
            timeout=15,
        )
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
