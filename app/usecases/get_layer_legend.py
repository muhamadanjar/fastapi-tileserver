import asyncio
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import settings
from app.core.exceptions import LayerNotFoundError
from app.domain.models import Layer
from app.domain.schemas import LayerLegendResponse
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository
from app.infrastructure.services.legend_renderer import (
    is_stale,
    raster_fingerprint,
    render_raster_legend,
    render_vector_legend,
    vector_fingerprint,
)
from app.usecases.layer_source import resolve_layer_source_path

# ponytail: strategy-per-type, tambah handler saat layer_type baru muncul.
_ESRI_LEGEND_TYPES = {"esri_mapserver", "esri_imageserver", "esri_featureserver", "esri_tileserver"}
_LOCAL_VECTOR_TYPES = {"mvt", "vector", "geojson", "kml"}
_LOCAL_RASTER_TYPES = {"tile"}


class GetLayerLegendUseCase:
    """Resolve a legend for a layer: upstream-native URL for external services,
    locally pre-rendered PNG for local vector/raster layers."""

    def __init__(self, layer_repo: LayerRepository, session_repo: Optional[UploadSessionRepository] = None):
        self.layer_repo = layer_repo
        self.session_repo = session_repo

    async def execute(self, layer_id: str) -> LayerLegendResponse:
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            raise LayerNotFoundError(layer_id)
        return await self._resolve(layer)

    # ── dispatch ──────────────────────────────────────────────────────

    async def _resolve(self, layer: Layer) -> LayerLegendResponse:
        if layer.layer_type in _ESRI_LEGEND_TYPES:
            return self._esri(layer)
        if layer.layer_type == "wms":
            return self._wms(layer)
        if layer.layer_type == "wmts":
            return self._wmts(layer)
        if layer.layer_type in _LOCAL_VECTOR_TYPES:
            return await self._local_vector(layer)
        if layer.layer_type in _LOCAL_RASTER_TYPES:
            return await self._local_raster(layer)
        return self._unavailable(layer, _reason_for(layer.layer_type))

    # ── external handlers ─────────────────────────────────────────────

    def _wms(self, layer: Layer) -> LayerLegendResponse:
        meta = layer.file_metadata or {}
        layer_name = (meta.get("geoserver") or {}).get("layer_name")
        layer_name = layer_name or meta.get("layers") or meta.get("layer")
        if not layer_name:
            return self._unavailable(layer, "WMS layer name is not configured")
        parts = urlsplit(layer.tile_url_template)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({
            "service": "WMS",
            "request": "GetLegendGraphic",
            "version": "1.3.0",
            "layer": layer_name,
            "format": "image/png",
        })
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=True,
            legend_url=urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "")),
            format="image/png",
        )

    def _wmts(self, layer: Layer) -> LayerLegendResponse:
        meta = layer.file_metadata or {}
        # Coba WMS GetLegendGraphic kalau layer_name tersedia
        layer_name = meta.get("layer") or meta.get("layers")
        if not layer_name:
            return self._unavailable(layer, "WMTS legend requires a layer name in metadata")
        parts = urlsplit(layer.tile_url_template)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({
            "service": "WMS",
            "request": "GetLegendGraphic",
            "version": "1.3.0",
            "layer": layer_name,
            "format": "image/png",
        })
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=True,
            legend_url=urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "")),
            format="image/png",
            detail="Legend via WMS GetLegendGraphic; requires WMS support on the same endpoint",
        )

    def _esri(self, layer: Layer) -> LayerLegendResponse:
        parts = urlsplit(layer.tile_url_template.rstrip("/"))
        service_name = {
            "esri_mapserver": "MapServer",
            "esri_imageserver": "ImageServer",
            "esri_featureserver": "FeatureServer",
            "esri_tileserver": "TileServer",
        }[layer.layer_type]
        marker = f"/{service_name}"
        service_path, separator, _ = parts.path.partition(marker)
        if not parts.scheme or not parts.netloc or not separator:
            return self._unavailable(layer, f"Layer does not point to an Esri {service_name} service")
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=True,
            legend_url=urlunsplit((parts.scheme, parts.netloc, f"{service_path}{marker}/legend", "f=pjson", "")),
            format="application/json",
        )

    # ── local pre-rendered handlers ───────────────────────────────────

    async def _local_vector(self, layer: Layer) -> LayerLegendResponse:
        style = (layer.file_metadata or {}).get("style")
        fp = vector_fingerprint(style)
        out = self._legend_path(layer)
        if is_stale(out, fp):
            await asyncio.to_thread(render_vector_legend, style, out, fp)
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=True,
            legend_url=f"/tiles/{layer.id}/legend.png",
            format="image/png",
            detail="Rendered locally from layer style" if style else "Rendered locally with default style",
        )

    async def _local_raster(self, layer: Layer) -> LayerLegendResponse:
        if not self.session_repo:
            return self._unavailable(layer, "Source file not found; cannot render raster legend")
        source = await resolve_layer_source_path(layer, self.session_repo)
        if not source:
            return self._unavailable(layer, "Source file not found; cannot render raster legend")
        try:
            fp = raster_fingerprint(source)
            out = self._legend_path(layer)
            if is_stale(out, fp):
                await asyncio.to_thread(render_raster_legend, source, out, fp)
        except Exception as exc:
            return self._unavailable(layer, f"Could not render raster legend: {exc}")
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=True,
            legend_url=f"/tiles/{layer.id}/legend.png",
            format="image/png",
            detail="Rendered locally from source raster statistics",
        )

    @staticmethod
    def _legend_path(layer: Layer):
        out = settings.TILES_DIR / layer.id / "legend.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        return out

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _unavailable(layer: Layer, detail: str) -> LayerLegendResponse:
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=False,
            detail=detail,
        )


def _reason_for(layer_type: str) -> str:
    return f"Layer type '{layer_type}' does not expose a server-side legend"