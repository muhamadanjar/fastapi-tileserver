"""
Overlay analysis usecase — Clean Architecture.

All DB access goes through injected repos.
File I/O goes through export_service.
Celery enqueueing goes through task_enqueuer (protocol).
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Protocol
from uuid import uuid4

import geopandas as gpd

from app.analysis.geometry_compat import (
    COMPATIBILITY,
    OPERATIONS_REQUIRING_SECOND_LAYER,
    get_compatible_operations,
    is_compatible,
)
from app.analysis.overlay_operations import (
    _get_geometry_type,
    buffer,
    centroid,
    clip,
    difference,
    dissolve,
    intersection,
    simplify,
    spatial_join,
    sym_difference,
    union,
)
from app.domain.models import AnalysisResult, Feature, Layer
from app.infrastructure.db.repository import (
    SyncAnalysisResultRepository,
    SyncLayerRepository,
    SyncUploadSessionRepository,
)

logger = logging.getLogger(__name__)

# Operation dispatch table — maps name to function
OPERATIONS = {
    "intersection": intersection,
    "union": union,
    "dissolve": dissolve,
    "clip": clip,
    "difference": difference,
    "buffer": buffer,
    "sym_difference": sym_difference,
    "simplify": simplify,
    "spatial_join": spatial_join,
    "centroid": centroid,
}

# Non-derivable metadata only; geometry compat read from geometry_compat.COMPATIBILITY
OPERATION_META: dict[str, dict] = {
    "intersection": {"display_name": "Intersection", "description": "Extract overlapping area between two layers", "output_geometry": "depends on input types", "phase": 1, "optional_params": []},
    "union": {"display_name": "Union", "description": "Merge all features from both layers", "output_geometry": "same as input", "phase": 1, "optional_params": []},
    "dissolve": {"display_name": "Dissolve", "description": "Merge features within a layer into one or group by attribute", "output_geometry": "same as input", "phase": 1, "optional_params": ["dissolve_group_by"]},
    "clip": {"display_name": "Clip", "description": "Cut layer A using boundary of layer B", "output_geometry": "same as layer A", "phase": 1, "optional_params": []},
    "difference": {"display_name": "Difference", "description": "Extract parts of layer A that do not overlap with layer B", "output_geometry": "polygon", "phase": 1, "optional_params": []},
    "buffer": {"display_name": "Buffer", "description": "Create zone around features at specified distance", "output_geometry": "polygon", "phase": 1, "optional_params": ["buffer_distance", "buffer_unit"]},
    "sym_difference": {"display_name": "Symmetric Difference", "description": "Parts of either layer that do not overlap the other", "output_geometry": "same as input", "phase": 2, "optional_params": []},
    "simplify": {"display_name": "Simplify", "description": "Reduce vertex count within tolerance", "output_geometry": "same as input", "phase": 2, "optional_params": ["simplify_tolerance"]},
    "spatial_join": {"display_name": "Spatial Join", "description": "Join attributes from B onto A by spatial predicate", "output_geometry": "same as layer A", "phase": 2, "optional_params": ["join_predicate"]},
    "centroid": {"display_name": "Centroid", "description": "Extract centroid point of each feature", "output_geometry": "point", "phase": 2, "optional_params": []},
}


class AnalysisTaskEnqueuer(Protocol):
    """Interface for enqueueing async analysis work."""

    def enqueue(
        self,
        request: dict,
        result_id: str,
        layer_id: str,
        analysis_result_id: str,
    ) -> str: ...


class OverlayAnalysisUseCase:
    """Orchestrate spatial overlay analysis on vector layers.

    Thin interface → deep module: public methods delegate to private helpers
    that handle validation, GeoDataFrame ops, persistence, and file I/O.
    """

    def __init__(
        self,
        layer_repo: SyncLayerRepository,
        analysis_repo: SyncAnalysisResultRepository,
        upload_repo: SyncUploadSessionRepository,
        get_project_features_fn: Callable[[str], list[Feature]],
        export_service,  # AnalysisExportService
        task_enqueuer: AnalysisTaskEnqueuer,
        ephemeral_ttl_hours: int = 24,
    ):
        self.layer_repo = layer_repo
        self.analysis_repo = analysis_repo
        self.upload_repo = upload_repo
        self.get_project_features_fn = get_project_features_fn
        self.export_service = export_service
        self.task_enqueuer = task_enqueuer
        self.ephemeral_ttl_hours = ephemeral_ttl_hours

    # ── Public interface ──────────────────────────────────────────────

    def get_available_operations(self) -> list[dict]:
        """All overlay operations with metadata. Derived from geometry_compat."""
        ops = []
        for name in OPERATIONS:
            compat = COMPATIBILITY[name]
            meta = OPERATION_META[name]
            ops.append({
                "name": name,
                "display_name": meta["display_name"],
                "description": meta["description"],
                "requires_second_layer": name in OPERATIONS_REQUIRING_SECOND_LAYER,
                "compatible_geometry": {k: sorted(v - {None}) for k, v in compat.items()},
                "output_geometry": meta["output_geometry"],
                "phase": meta["phase"],
                "optional_params": meta["optional_params"],
            })
        return ops

    def get_layer_sources(self) -> list[dict]:
        """List layers available as analysis input."""
        sources = []
        for layer in self.layer_repo.list_all():
            if layer.layer_type in ("geojson", "vector", "shp"):
                sources.append({
                    "layer_id": layer.id,
                    "filename": layer.filename,
                    "layer_type": layer.layer_type,
                    "geometry_type": "polygon",  # resolved on validate
                    "fields": list(layer.file_metadata.get("fields", [])) if layer.file_metadata else [],
                })
        return sources

    def validate_analysis(
        self,
        operation: str,
        layer_a_id: str,
        layer_b_id: Optional[str] = None,
    ) -> dict:
        """Validate if analysis is possible. Loads layers for geometry check."""
        errors: list[str] = []
        warnings: list[str] = []
        layer_a_geometry: Optional[str] = None
        layer_b_geometry: Optional[str] = None
        compatible_ops: list[str] = []

        if operation not in OPERATIONS:
            errors.append(f"Unknown operation: {operation}")
            return {"valid": False, "errors": errors}

        gdf_a = self._load_layer(layer_a_id)
        if gdf_a is None:
            errors.append(f"Layer A not found: {layer_a_id}")
            return {"valid": False, "errors": errors}

        layer_a_geometry = _get_geometry_type(gdf_a)
        if gdf_a.empty:
            warnings.append("Layer A has no features")

        if operation in OPERATIONS_REQUIRING_SECOND_LAYER and layer_b_id == layer_a_id:
            errors.append("Cannot use the same layer for both inputs")
            return {"valid": False, "errors": errors}

        if operation in OPERATIONS_REQUIRING_SECOND_LAYER:
            if not layer_b_id:
                errors.append(f"Operation '{operation}' requires a second layer")
                return {"valid": False, "errors": errors}

            gdf_b = self._load_layer(layer_b_id)
            if gdf_b is None:
                errors.append(f"Layer B not found: {layer_b_id}")
                return {"valid": False, "errors": errors}

            layer_b_geometry = _get_geometry_type(gdf_b)
            if gdf_b.empty:
                warnings.append("Layer B has no features")

            if not is_compatible(operation, layer_a_geometry, layer_b_geometry):
                errors.append(
                    f"Incompatible geometry types: {operation} cannot operate on "
                    f"'{layer_a_geometry}' + '{layer_b_geometry}'"
                )

        if layer_a_geometry:
            compatible_ops = get_compatible_operations(layer_a_geometry, layer_b_geometry)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "layer_a_geometry": layer_a_geometry,
            "layer_b_geometry": layer_b_geometry,
            "compatible_operations": compatible_ops,
        }

    def run_analysis(self, request: dict) -> dict:
        """Execute overlay analysis synchronously and persist result."""
        execution = self._execute(request)
        result_id = execution["result_id"]
        result_gdf = execution["result_gdf"]
        bounds = execution["bounds"]

        layer_id = f"layer_analysis_{uuid4().hex[:12]}"
        metadata = {
            "analysis": {
                "ephemeral": True,
                "operation": execution["operation"],
                "result_id": result_id,
                "selected_attributes": execution["selected_attrs"],
            },
            "fields": list(result_gdf.columns) if not result_gdf.empty else [],
        }

        layer = Layer(
            id=layer_id,
            filename=execution["output_name"] or f"{execution['operation']}_result",
            file_type="vector",
            layer_type="geojson",
            tile_url_template=f"/data/uploads/{result_id}/result.geojson",
            bbox_west=bounds[0],
            bbox_south=bounds[1],
            bbox_east=bounds[2],
            bbox_north=bounds[3],
            file_metadata=metadata,
        )
        self.layer_repo.create(layer)

        analysis_result = AnalysisResult(
            id=result_id,
            layer_id=layer_id,
            operation=execution["operation"],
            input_layer_a_id=request["input_layer_a_id"],
            input_layer_b_id=request.get("input_layer_b_id"),
            output_name=execution["output_name"],
            feature_count=execution["feature_count"],
            skipped_null_geometry=execution["skipped_null_geometry"],
            warning=execution["warning"],
            result_file_path=execution["result_file"],
            ephemeral=True,
            status="done",
            bbox_west=bounds[0],
            bbox_south=bounds[1],
            bbox_east=bounds[2],
            bbox_north=bounds[3],
        )
        self.analysis_repo.create(analysis_result)

        return {
            "result_layer_id": layer_id,
            "operation": execution["operation"],
            "feature_count": execution["feature_count"],
            "skipped_null_geometry": execution["skipped_null_geometry"],
            "warning": execution["warning"],
            "bbox": bounds,
            "geojson_url": f"/api/v1/analysis/{layer_id}/preview",
            "async_task_id": None,
        }

    def start_analysis_async(self, request: dict) -> dict:
        """Create pending result rows and enqueue Celery task."""
        errors = self._quick_validate(request)
        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

        layer_id = f"layer_analysis_{uuid4().hex[:12]}"
        layer = Layer(
            id=layer_id,
            filename=request.get("output_name") or f"{request['operation']}_result",
            file_type="vector",
            layer_type="geojson",
            tile_url_template="",  # filled on completion
            file_metadata={
                "analysis": {
                    "ephemeral": True,
                    "operation": request["operation"],
                    "selected_attributes": request.get("selected_attributes"),
                }
            },
        )
        self.layer_repo.create(layer)

        result_id = f"analysis_{uuid4().hex[:16]}"
        analysis_result = AnalysisResult(
            id=result_id,
            layer_id=layer_id,
            operation=request["operation"],
            input_layer_a_id=request["input_layer_a_id"],
            input_layer_b_id=request.get("input_layer_b_id"),
            output_name=request.get("output_name"),
            ephemeral=True,
            status="pending",
        )
        self.analysis_repo.create(analysis_result)

        task_id = self.task_enqueuer.enqueue(request, result_id, layer_id, analysis_result.id)

        analysis_result.celery_task_id = task_id
        self.analysis_repo.update(analysis_result)

        return {
            "result_layer_id": layer_id,
            "result_id": result_id,
            "async_task_id": task_id,
        }

    def execute_pending_analysis(
        self,
        request: dict,
        result_id: str,
        layer_id: str,
        analysis_result_id: str,
    ) -> None:
        """Run an already-pending analysis (called by Celery worker)."""
        result = self.analysis_repo.get_by_id(analysis_result_id)
        if result:
            result.status = "processing"
            result.updated_at = datetime.now(timezone.utc)
            self.analysis_repo.update(result)

        try:
            execution = self._execute(request, result_id=result_id)
        except Exception as exc:
            result = self.analysis_repo.get_by_id(analysis_result_id)
            if result:
                result.status = "failed"
                result.error_message = str(exc)
                result.updated_at = datetime.now(timezone.utc)
                self.analysis_repo.update(result)
            layer = self.layer_repo.get_by_id(layer_id)
            if layer:
                self.layer_repo.session.delete(layer)
                self.layer_repo.session.commit()
            raise

        bounds = execution["bounds"]
        result_gdf = execution["result_gdf"]

        result = self.analysis_repo.get_by_id(analysis_result_id)
        if result:
            result.status = "done"
            result.feature_count = execution["feature_count"]
            result.skipped_null_geometry = execution["skipped_null_geometry"]
            result.warning = execution["warning"]
            result.result_file_path = execution["result_file"]
            result.bbox_west = bounds[0]
            result.bbox_south = bounds[1]
            result.bbox_east = bounds[2]
            result.bbox_north = bounds[3]
            result.updated_at = datetime.now(timezone.utc)
            self.analysis_repo.update(result)

        layer = self.layer_repo.get_by_id(layer_id)
        if layer:
            layer.tile_url_template = f"/data/uploads/{result_id}/result.geojson"
            layer.bbox_west = bounds[0]
            layer.bbox_south = bounds[1]
            layer.bbox_east = bounds[2]
            layer.bbox_north = bounds[3]
            meta = dict(layer.file_metadata or {})
            meta["fields"] = list(result_gdf.columns) if not result_gdf.empty else []
            layer.file_metadata = meta
            self.layer_repo.session.add(layer)
            self.layer_repo.session.commit()

    def get_analysis_status(self, result_id: str) -> Optional[dict]:
        """Return analysis result status for polling."""
        result = self.analysis_repo.get_by_id(result_id)
        if not result:
            return None
        return {
            "result_id": result.id,
            "result_layer_id": result.layer_id,
            "status": result.status,
            "operation": result.operation,
            "feature_count": result.feature_count,
            "warning": result.warning,
            "error_message": result.error_message,
            "bbox": self._bbox_optional(result),
            "geojson_url": f"/api/v1/analysis/{result.layer_id}/preview"
            if result.status == "done"
            else None,
        }

    def save_analysis_result(self, layer_id: str) -> dict:
        """Persist an ephemeral analysis result as permanent layer."""
        result = self.analysis_repo.get_by_layer_id(layer_id)
        if not result:
            raise ValueError(f"Analysis result not found: {layer_id}")

        if not result.ephemeral:
            return {"message": "Already saved", "layer_id": layer_id}

        result.ephemeral = False
        result.updated_at = datetime.now(timezone.utc)
        self.analysis_repo.update(result)

        layer = self.layer_repo.get_by_id(layer_id)
        if layer and layer.file_metadata:
            meta = layer.file_metadata.copy()
            if "analysis" in meta:
                meta["analysis"]["ephemeral"] = False
            layer.file_metadata = meta
            self.layer_repo.session.add(layer)
            self.layer_repo.session.commit()

        return {"message": "Analysis result saved", "layer_id": layer_id}

    def delete_analysis_result(self, layer_id: str) -> dict:
        """Discard an ephemeral analysis result."""
        result = self.analysis_repo.get_by_layer_id(layer_id)
        if not result:
            raise ValueError(f"Analysis result not found: {layer_id}")

        # Delete file
        self.export_service.delete_result(result.result_file_path or "")

        # Delete layer
        layer = self.layer_repo.get_by_id(layer_id)
        if layer:
            self.layer_repo.session.delete(layer)

        # Delete analysis result
        self.analysis_repo.delete(result)

        return {"message": "Analysis result deleted"}

    def cleanup_ephemeral(self, ttl_hours: Optional[int] = None) -> dict:
        """Delete abandoned ephemeral analysis results older than TTL."""
        from sqlmodel import select

        ttl_hours = ttl_hours or self.ephemeral_ttl_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)

        deleted_layers = 0
        deleted_results = 0
        results = self.analysis_repo.list_expired_ephemeral(cutoff)
        for result in results:
            self.export_service.delete_result(result.result_file_path or "")
            layer = self.layer_repo.get_by_id(result.layer_id)
            if layer:
                self.layer_repo.session.delete(layer)
                deleted_layers += 1
            self.analysis_repo.session.delete(result)
            deleted_results += 1
        self.analysis_repo.session.commit()

        return {
            "deleted_layers": deleted_layers,
            "deleted_results": deleted_results,
            "ttl_hours": ttl_hours,
        }

    # ── Private helpers ───────────────────────────────────────────────

    def _load_layer(self, layer_id: str) -> Optional[gpd.GeoDataFrame]:
        """Load a layer as GeoDataFrame via repos (no raw get_sync_session)."""
        layer = self.layer_repo.get_by_id(layer_id)
        if not layer:
            return None

        # Project-backed layer (published survey)
        project_id = (layer.file_metadata or {}).get("project_id")
        if project_id:
            features = self.get_project_features_fn(project_id)
            if features:
                records = [
                    {"geometry": f.geometry, **(f.attributes or {}), "_feature_id": f.id}
                    for f in features
                ]
                return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
            return gpd.GeoDataFrame(
                columns=["geometry"], geometry="geometry", crs="EPSG:4326"
            )

        if not layer.upload_session_id:
            return None

        upload = self.upload_repo.get_by_id(layer.upload_session_id)
        if not upload or not upload.final_path:
            return None

        final_path = upload.final_path
        if final_path.startswith("artifact://"):
            return None

        if os.path.exists(final_path):
            return gpd.read_file(final_path)

        return None

    def _quick_validate(self, request: dict) -> list[str]:
        """Cheap validation before enqueueing async work (no geometry load)."""
        errors: list[str] = []
        operation = request["operation"]
        if operation not in OPERATIONS:
            errors.append(f"Unknown operation: {operation}")
            return errors
        if operation in OPERATIONS_REQUIRING_SECOND_LAYER and not request.get("input_layer_b_id"):
            errors.append(f"Operation '{operation}' requires a second layer")
            return errors
        if (
            request.get("input_layer_a_id") == request.get("input_layer_b_id")
            and operation in OPERATIONS_REQUIRING_SECOND_LAYER
        ):
            errors.append("Cannot use the same layer for both inputs")
            return errors
        # Check layers exist
        for key in ("input_layer_a_id", "input_layer_b_id"):
            lid = request.get(key)
            if not lid:
                continue
            if not self.layer_repo.get_by_id(lid):
                errors.append(f"Layer not found: {lid}")
        return errors

    def _execute(
        self, request: dict, result_id: Optional[str] = None
    ) -> dict:
        """Core operation execution. Loads inputs, runs operation, saves result."""
        if result_id is None:
            result_id = f"analysis_{uuid4().hex[:16]}"

        operation = request["operation"]
        layer_a_id = request["input_layer_a_id"]
        layer_b_id = request.get("input_layer_b_id")
        output_name = request.get("output_name")
        selected_attrs = request.get("selected_attributes")
        buffer_distance = request.get("buffer_distance")
        buffer_unit = request.get("buffer_unit", "meters")
        dissolve_group_by = request.get("dissolve_group_by")
        simplify_tolerance = request.get("simplify_tolerance")
        join_predicate = request.get("join_predicate", "intersects")

        # Validate
        validation = self.validate_analysis(operation, layer_a_id, layer_b_id)
        if not validation["valid"]:
            raise ValueError(f"Validation failed: {'; '.join(validation['errors'])}")

        # Load inputs
        gdf_a = self._load_layer(layer_a_id)
        if gdf_a is None:
            raise ValueError(f"Layer A not found: {layer_a_id}")

        gdf_b = None
        if layer_b_id:
            gdf_b = self._load_layer(layer_b_id)
            if gdf_b is None:
                raise ValueError(f"Layer B not found: {layer_b_id}")

        # Skip null geometries
        skipped_a = 0
        if gdf_a.geometry.isna().any():
            skipped_a = int(gdf_a.geometry.isna().sum())
            gdf_a = gdf_a.dropna(subset=["geometry"])

        skipped_b = 0
        if gdf_b is not None and gdf_b.geometry.isna().any():
            skipped_b = int(gdf_b.geometry.isna().sum())
            gdf_b = gdf_b.dropna(subset=["geometry"])

        # Run operation
        try:
            if operation == "buffer":
                if not buffer_distance:
                    raise ValueError("buffer_distance is required for buffer operation")
                result_gdf = buffer(gdf_a, buffer_distance, buffer_unit)
            elif operation == "dissolve":
                result_gdf = dissolve(gdf_a, dissolve_group_by)
            elif operation == "simplify":
                if not simplify_tolerance:
                    raise ValueError("simplify_tolerance is required for simplify operation")
                result_gdf = simplify(gdf_a, simplify_tolerance)
            elif operation == "spatial_join":
                result_gdf = spatial_join(gdf_a, gdf_b, join_predicate, selected_attrs)
            elif operation == "centroid":
                result_gdf = centroid(gdf_a)
            else:
                result_gdf = OPERATIONS[operation](gdf_a, gdf_b, selected_attrs)
        except Exception as e:
            raise RuntimeError(f"Analysis failed: {str(e)}")

        # Handle empty result
        warning = None
        if result_gdf.empty:
            warning = "Analysis produced empty result — layers may not overlap"

        # Save result via export_service
        result_file = self.export_service.save_geojson(result_gdf, result_id)

        bounds = list(result_gdf.total_bounds) if not result_gdf.empty else [0, 0, 0, 0]

        return {
            "result_id": result_id,
            "operation": operation,
            "output_name": output_name,
            "selected_attrs": selected_attrs,
            "result_file": result_file,
            "result_gdf": result_gdf,
            "feature_count": len(result_gdf),
            "skipped_null_geometry": skipped_a + skipped_b,
            "warning": warning,
            "bounds": bounds,
        }

    @staticmethod
    def _bbox_optional(result: AnalysisResult) -> Optional[list[float]]:
        if result.bbox_west is None:
            return None
        return [result.bbox_west, result.bbox_south, result.bbox_east, result.bbox_north]
