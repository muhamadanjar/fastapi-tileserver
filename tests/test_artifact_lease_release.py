"""Lock the worker's artifact-lease release contract.

After tiling finishes (or retries are exhausted) the lease must be released so
upload_api lifecycle cleanup can reclaim the source artifact.
"""

from unittest.mock import patch

from app.workers.tasks import _release_artifact_lease


def test_missing_ids_skip_the_client_call():
    with patch("app.workers.tasks.UploadArtifactClient") as client:
        _release_artifact_lease(None, "lease-1")
        _release_artifact_lease("artifact-1", None)
        _release_artifact_lease(None, None)
    client.assert_not_called()


def test_release_lease_is_forwarded():
    with patch("app.workers.tasks.UploadArtifactClient") as client:
        _release_artifact_lease("artifact-1", "lease-1")
    client.return_value.release_lease.assert_called_once_with("artifact-1", "lease-1")


def test_release_failure_never_raises():
    with patch("app.workers.tasks.UploadArtifactClient") as client:
        client.return_value.release_lease.side_effect = RuntimeError("upload-api down")
    _release_artifact_lease("artifact-1", "lease-1")  # must not raise
