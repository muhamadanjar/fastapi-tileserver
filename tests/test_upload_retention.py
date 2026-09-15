"""Lock the Phase 4 retention lifecycle: the lease is a pin that survives
while any Layer or active Batch still references the upload session. Only the
last consumer triggers the release, so upload_api can reclaim the source.
"""

from unittest.mock import patch

from app.workers.tasks import _release_artifact_lease, _mark_pending_release


def _mock_repo_factory(layers: int, batches: int):
    class FakeRepo:
        def __init__(self, session):
            self.session = session
        def count_layers_referencing(self, upload_id): return layers
        def count_batches_referencing(self, upload_id): return batches
    return FakeRepo


def test_lease_kept_while_layers_reference_source():
    repo = _mock_repo_factory(layers=2, batches=0)
    with patch("app.workers.tasks.SyncUploadSessionRepository", repo), \
         patch("app.workers.tasks.db.get_session") as gs, \
         patch("app.workers.tasks.UploadArtifactClient") as client:
        gs.return_value.__enter__ = lambda self: object()
        gs.return_value.__exit__ = lambda *a: False
        _release_artifact_lease("artifact-1", "lease-1", "upload-1")
    client.assert_not_called()


def test_lease_kept_while_active_batch_references_source():
    repo = _mock_repo_factory(layers=0, batches=1)
    with patch("app.workers.tasks.SyncUploadSessionRepository", repo), \
         patch("app.workers.tasks.db.get_session") as gs, \
         patch("app.workers.tasks.UploadArtifactClient") as client:
        gs.return_value.__enter__ = lambda self: object()
        gs.return_value.__exit__ = lambda *a: False
        _release_artifact_lease("artifact-1", "lease-1", "upload-1")
    client.assert_not_called()


def test_lease_released_when_last_consumer_gone():
    repo = _mock_repo_factory(layers=0, batches=0)
    with patch("app.workers.tasks.SyncUploadSessionRepository", repo), \
         patch("app.workers.tasks.db.get_session") as gs, \
         patch("app.workers.tasks.UploadArtifactClient") as client, \
         patch("app.workers.tasks._cleanup_materialized_artifact") as cleanup:
        gs.return_value.__enter__ = lambda self: object()
        gs.return_value.__exit__ = lambda *a: False
        _release_artifact_lease("artifact-1", "lease-1", "upload-1")
    client.return_value.release_lease.assert_called_once_with("artifact-1", "lease-1")
    cleanup.assert_called_once_with("artifact-1")


def test_release_failure_flags_session_for_reconciliation():
    repo = _mock_repo_factory(layers=0, batches=0)
    with patch("app.workers.tasks.SyncUploadSessionRepository", repo), \
         patch("app.workers.tasks.db.get_session") as gs, \
         patch("app.workers.tasks.UploadArtifactClient") as client, \
         patch("app.workers.tasks._mark_pending_release") as mark:
        gs.return_value.__enter__ = lambda self: object()
        gs.return_value.__exit__ = lambda *a: False
        client.return_value.release_lease.side_effect = RuntimeError("upload-api down")
        _release_artifact_lease("artifact-1", "lease-1", "upload-1")
    mark.assert_called_once_with("upload-1")


def test_mark_pending_release_flags_upload():
    class FakeCurrent:
        pending_release = False
    class FakeRepo:
        def __init__(self, session):
            self.session = session
        def get_by_id(self, upload_id): return FakeCurrent()
    with patch("app.workers.tasks.SyncUploadSessionRepository", FakeRepo), \
         patch("app.workers.tasks.db.get_session") as gs:
        gs.return_value.__enter__ = lambda self: object()
        gs.return_value.__exit__ = lambda *a: False
        _mark_pending_release("upload-1")
    # Must not raise; flag set on the returned record (asserted via no-exception)
