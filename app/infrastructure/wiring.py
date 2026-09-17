"""Infrastructure wiring: factory defaults for usecase port parameters.

Usecases accept `Optional[Port] = None`; this module gives them a single place to
resolve a real implementation when none is injected (tests / alternate wiring
pass their own). Keeps concrete infra imports out of the usecase layer
except for these sanctioned defaults.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.infrastructure.services.legend_renderer import (
    is_stale as _is_stale,
    raster_fingerprint as _raster_fp,
    render_raster_legend as _render_raster,
    render_vector_legend as _render_vector,
    vector_fingerprint as _vector_fp,
)
from app.infrastructure.services.nominatim_client import NominatimClient
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient
from app.infrastructure.storage.chunk_storage import ChunkStorage

def default_artifact_client():
    # ponytail: single concrete instantiation point; inject mock for tests.
    return UploadArtifactClient()

def default_nominatim_client():
    return NominatimClient()

def default_chunk_storage():
    return ChunkStorage()

def default_legend_renderer():
    """Bundle infra legend fns behind a tiny adapter object so usecases can
    depend on LegendRendererPort instead of importing 5 infra fns each."""
    class _LegendRenderer:
        is_stale = staticmethod(_is_stale)
        raster_fingerprint = staticmethod(_raster_fp)
        vector_fingerprint = staticmethod(_vector_fp)
        render_raster_legend = staticmethod(_render_raster)
        render_vector_legend = staticmethod(_render_vector)
    return _LegendRenderer()

def default_analysis_reference_source():
    """ponytail: wrap infra fns behind ReferenceSourcePort adapter."""
    from app.infrastructure.services.analysis_reference_source import load_reference as _load, repair_geometry as _repair
    class _RefSrc:
        load_reference = staticmethod(_load)
        repair_geometry = staticmethod(_repair)
    return _RefSrc()

def default_analysis_storage():
    """ponytail: wrap infra fns behind AnalysisStoragePort adapter."""
    from app.infrastructure.services.reference_analysis_files import (
        read_shapefile_archive as _read_zip,
        read_json as _read_json,
        persist_result as _persist_result,
        write_json as _write_json,
        export_results as _export,
    )
    class _Storage:
        read_shapefile_archive = staticmethod(_read_zip)
        read_json = staticmethod(_read_json)
        persist_result = staticmethod(_persist_result)
        write_json = staticmethod(_write_json)
        export_results = staticmethod(_export)
    return _Storage()

if TYPE_CHECKING:
    from app.domain.ports import (
        AnalysisStoragePort,
        ChunkStoragePort,
        LegendRendererPort,
        NominatimClientPort,
        ReferenceSourcePort,
        UploadArtifactClientPort,
    )

    def default_artifact_client() -> UploadArtifactClientPort: ...  # noqa: F811
    def default_nominatim_client() -> NominatimClientPort: ...      # noqa: F811
    def default_chunk_storage() -> ChunkStoragePort: ...            # noqa: F811
    def default_legend_renderer() -> LegendRendererPort: ...        # noqa: F811
    def default_analysis_reference_source() -> ReferenceSourcePort: ...  # noqa: F811
    def default_analysis_storage() -> AnalysisStoragePort: ...      # noqa: F811
