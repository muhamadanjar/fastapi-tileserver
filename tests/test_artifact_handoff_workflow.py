import pytest
from fastapi import HTTPException

from app.domain.schemas import ArtifactTilingRequest
from app.presentation.router.api.v1.endpoints.upload import _artifact_handoff_output_format


def _request(**overrides):
    return ArtifactTilingRequest(
        artifact_id="a" * 36,
        grant_id="b" * 36,
        handoff_id="handoff-1",
        **overrides,
    )


def test_batch_handoff_is_staged_without_an_output_selection():
    assert _artifact_handoff_output_format(_request(workflow="batch")) == "staged"


def test_batch_handoff_rejects_an_output_selection():
    with pytest.raises(HTTPException, match="cannot select an output format"):
        _artifact_handoff_output_format(_request(workflow="batch", output_format="raster"))


def test_layer_handoff_keeps_the_legacy_raster_default():
    assert _artifact_handoff_output_format(_request()) == "raster"
