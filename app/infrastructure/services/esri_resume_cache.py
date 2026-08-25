"""Resume cache for interrupted Esri layer downloads.

Stores successfully fetched feature chunks as JSON files so that a failed or
cancelled download can resume from where it left off instead of repeating
requests that already completed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from app.core.config import settings


class ResumeCache:
    """File-backed cache for completed download chunks."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        cache_root: Path | None = None,
    ):
        self.enabled = bool(enabled)
        self.cache_root = cache_root or settings.ESRI_RESUME_CACHE_DIR
        if self.enabled:
            self.cache_root.mkdir(parents=True, exist_ok=True)

    def _job_key(self, service_url: str, layer_id: str | int) -> str:
        raw = f"{service_url}|{layer_id}"
        return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]

    def _chunk_key(self, values: Iterable) -> str:
        values = list(values or [])
        if not values:
            return "empty"
        first = str(values[0])
        last = str(values[-1])
        digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        return f"{first}_{last}_{len(values)}_{digest}"

    def _folder(self, service_url: str, layer_id: str | int) -> Path:
        folder = self.cache_root / self._job_key(service_url, layer_id)
        if self.enabled:
            folder.mkdir(parents=True, exist_ok=True)
        return folder

    def objectid_chunk_path(
        self, service_url: str, layer_id: str | int, object_ids: Iterable
    ) -> Path:
        return self._folder(service_url, layer_id) / f"oid_{self._chunk_key(object_ids)}.json"

    def page_path(
        self, service_url: str, layer_id: str | int, offset: int, page_size: int
    ) -> Path:
        return self._folder(service_url, layer_id) / f"page_{offset}_{page_size}.json"

    def read_features(
        self,
        path: Path,
        *,
        service_url: str | None = None,
        geometry_type: str | None = None,
    ) -> list | None:
        if not self.enabled or not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        if not isinstance(data, dict) or data.get("schema") != "tileserver-esri-resume-v1":
            return None

        # Validate service URL to prevent cross-service cache reuse
        if service_url is not None:
            cached_service = str(data.get("service_url") or "").strip().rstrip("/")
            expected_service = str(service_url or "").strip().rstrip("/")
            if not cached_service or cached_service != expected_service:
                return None

        # Validate geometry type to prevent geometry-mismatch cache reuse
        if geometry_type is not None:
            cached_geometry = str(data.get("geometry_type") or "").strip().lower()
            expected_geometry = str(geometry_type or "").strip().lower()
            if cached_geometry and expected_geometry and cached_geometry != expected_geometry:
                return None

        features = data.get("features")
        return features if isinstance(features, list) else None

    def write_features(
        self,
        path: Path,
        *,
        service_url: str,
        layer_id: str | int,
        mode: str,
        features: list,
        geometry_type: str | None = None,
        meta: dict | None = None,
    ) -> None:
        if not self.enabled:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "tileserver-esri-resume-v1",
            "mode": mode,
            "layer_id": layer_id,
            "service_url": str(service_url).strip().rstrip("/"),
            "geometry_type": str(geometry_type or ""),
            "feature_count": len(features or []),
            "meta": meta or {},
            "features": features or [],
        }
        # Atomic write: temp file + rename
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    def clear_layer(self, service_url: str, layer_id: str | int) -> None:
        folder = self._folder(service_url, layer_id)
        if not folder.exists():
            return
        for item in folder.glob("*.json"):
            try:
                item.unlink()
            except OSError:
                pass
