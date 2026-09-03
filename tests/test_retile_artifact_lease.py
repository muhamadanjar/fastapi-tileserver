from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import layers


class _LayerRepo:
    async def get_by_id(self, layer_id):
        return SimpleNamespace(
            id=layer_id,
            upload_session_id="upload-1",
            file_type="vector",
            layer_type="mvt",
        )


class _SessionRepo:
    def __init__(self):
        self.leases = []
        self.started = []

    async def get_by_id(self, upload_id):
        return SimpleNamespace(
            id=upload_id,
            final_path="artifact://artifact-1",
            output_format="mvt",
        )

    async def set_artifact_lease(self, upload_id, lease_id):
        self.leases.append((upload_id, lease_id))

    async def start_tiling(self, upload_id, task_id, output_format, max_zoom):
        self.started.append((upload_id, task_id, output_format, max_zoom))


@pytest.mark.asyncio
async def test_retile_artifact_renews_user_authorized_lease(monkeypatch):
    calls = []

    class _ArtifactClient:
        def create_user_grant(self, artifact_id, authorization):
            calls.append(("grant", artifact_id, authorization))
            return "grant-1"

        def acquire_lease(self, artifact_id, grant_id, reference):
            calls.append(("lease", artifact_id, grant_id, reference))
            return {"lease_id": "lease-1"}

    class _Task:
        @staticmethod
        def delay(*args):
            calls.append(("task", *args))
            return SimpleNamespace(id="task-1")

    session_repo = _SessionRepo()
    monkeypatch.setattr(layers, "UploadArtifactClient", _ArtifactClient)
    monkeypatch.setattr(layers, "process_tiling_task", _Task)

    result = await layers.retile_layer(
        "layer-1", max_zoom=16, authorization="Bearer editor-token",
        repo=_LayerRepo(), session_repo=session_repo,
    )

    assert ("grant", "artifact-1", "Bearer editor-token") in calls
    assert any(call[0] == "lease" and call[1:3] == ("artifact-1", "grant-1") for call in calls)
    assert session_repo.leases == [("upload-1", "lease-1")]
    assert session_repo.started == [("upload-1", "task-1", "mvt", 16)]
    assert result["max_zoom"] == 16
