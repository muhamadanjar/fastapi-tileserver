"""Download estimation for Esri layers — feature count, chunk count, confidence."""

from __future__ import annotations

from math import ceil

from app.core.exceptions import EsriDownloadError, ServiceConnectionError
from app.infrastructure.services.esri_client import EsriClient


class EsriEstimator:
    """Estimate download size/complexity for an Esri layer before downloading."""

    def __init__(self, service_url: str, proxy_url: str = "", token: str = ""):
        self.client = EsriClient(service_url, proxy_url=proxy_url, token=token)

    def estimate_layer(
        self,
        layer_id: int,
        layer_info: dict | None = None,
        output_formats: list[str] | None = None,
        chunk_size: int | None = None,
    ) -> dict:
        """Return estimate dict for a single layer."""
        notes: list[str] = []
        layer_info = layer_info or self.client.get_layer_info(layer_id)

        feature_count = None
        confidence = "medium"
        try:
            feature_count = self.client.get_feature_count(layer_id)
        except (EsriDownloadError, ServiceConnectionError) as exc:
            notes.append(f"Feature count unavailable: {exc}")
            confidence = "low"

        geometry_type = layer_info.get("geometryType") or "Unknown"
        sr = layer_info.get("spatialReference") or {}
        spatial_reference = str(sr.get("latestWkid") or sr.get("wkid") or "Unknown") if isinstance(sr, dict) else str(sr or "Unknown")

        cs = chunk_size or 50
        estimated_chunks = max(1, ceil(feature_count / cs)) if feature_count and feature_count > 0 else 0

        if feature_count and feature_count > 100_000:
            notes.append("Large layer (>100k features); consider downloading during off-peak hours.")

        return {
            "layer_id": layer_id,
            "layer_name": layer_info.get("name", f"Layer {layer_id}"),
            "feature_count": feature_count,
            "chunk_size": cs,
            "estimated_chunks": estimated_chunks,
            "geometry_type": geometry_type,
            "spatial_reference": spatial_reference,
            "output_formats": output_formats or ["geojson", "shp"],
            "confidence": confidence,
            "notes": notes,
        }

    def estimate_service(self, output_formats: list[str] | None = None) -> dict:
        """Estimate all layers in a service."""
        layers = self.client.get_layers_from_service()
        estimates = []
        for layer in layers:
            layer_id = layer.get("id")
            if layer_id is None:
                continue
            est = self.estimate_layer(layer_id, layer, output_formats=output_formats)
            estimates.append(est)

        total_features = sum(e["feature_count"] or 0 for e in estimates)
        total_chunks = sum(e["estimated_chunks"] for e in estimates)
        low_confidence = sum(1 for e in estimates if e["confidence"] == "low")

        return {
            "service_url": self.client.service_url,
            "total_layers": len(estimates),
            "total_features": total_features or None,
            "total_chunks": total_chunks,
            "low_confidence_count": low_confidence,
            "layers": estimates,
        }
