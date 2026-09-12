"""MapRenderer adapter: bridges domain protocols with existing infrastructure."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable

import mapbox_vector_tile
from PIL import Image

from app.core.config import settings
from app.domain.map_batches import Batch, Dataset, Group, LayerData, MapError
from app.infrastructure.services.geoserver_service import GeoServerService
from app.infrastructure.services.sld_builder import build_sld

logger = logging.getLogger(__name__)

_GEOM_MAP = {
    "Point": "Point", "MultiPoint": "Point",
    "LineString": "LineString", "MultiLineString": "LineString",
    "Polygon": "Polygon", "MultiPolygon": "Polygon",
}

_MAX_ARCHIVE_ENTRIES = 10_000
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


def _normalize_geometry_type(value: str) -> str:
    """Map shapefile Z/M geometry labels to the 2D style families we support."""
    base = value.strip()
    for marker in (" ZM", " Z", " M", " 25D"):
        if base.endswith(marker):
            base = base[:-len(marker)].rstrip()
            break
    return _GEOM_MAP.get(base, base)


def _normalize_style_geometry_keys(style: dict | None) -> dict:
    """Make persisted pre-2D styles safe for SLD and vector-tile renderers."""
    if not style:
        return {}
    return {
        _normalize_geometry_type(str(geometry)): props
        for geometry, props in style.items()
    }


def _validate_archive_member(name: str) -> None:
    """Reject ZIP member names that could escape an extraction directory."""
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise MapError(f"Unsafe ZIP entry: {name}")


def _detect_datasets_from_zip(zip_path: Path) -> tuple[str, list[Dataset]]:
    """Open a ZIP, find all SHP datasets, validate sidecars, return (digest, datasets)."""
    if not zipfile.is_zipfile(zip_path):
        raise MapError("File is not a valid ZIP archive")

    with zipfile.ZipFile(zip_path) as zf:
        members = [entry for entry in zf.infolist() if not entry.is_dir()]
        if len(members) > _MAX_ARCHIVE_ENTRIES:
            raise MapError(f"ZIP contains too many files (maximum {_MAX_ARCHIVE_ENTRIES})")
        normalized_names = [entry.filename.casefold() for entry in members]
        if len(normalized_names) != len(set(normalized_names)):
            raise MapError("ZIP contains duplicate file names")
        total_uncompressed = sum(entry.file_size for entry in members)
        if total_uncompressed > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise MapError("ZIP uncompressed content is too large")
        entries = {entry.filename: entry for entry in members}
        # Security checks
        for entry in entries.values():
            _validate_archive_member(entry.filename)
            if entry.flag_bits & 0x1:
                raise MapError(f"Encrypted ZIP entries are not allowed: {entry.filename}")
            if entry.file_size > 0 and entry.compress_size > 0:
                ratio = entry.file_size / entry.compress_size
                if ratio > 200:
                    raise MapError(f"Suspicious compression ratio in: {entry.filename}")

        # Find all .shp files
        shp_files = sorted(
            [e for name, e in entries.items() if name.lower().endswith(".shp")],
            key=lambda e: e.filename.lower(),
        )
        if not shp_files:
            raise MapError("ZIP must contain at least one .shp file")

        # Group by base name (without extension), check required sidecars
        required = {".shp", ".dbf", ".shx", ".prj"}
        datasets: list[Dataset] = []
        digest = hashlib.sha256()

        for shp_entry in shp_files:
            base_lower = shp_entry.filename.rsplit(".", 1)[0].lower()
            available = {
                name.rsplit(".", 1)[1].lower()
                for name in entries
                if name.rsplit(".", 1)[0].lower() == base_lower
            }
            needed = {ext[1:] for ext in required}
            missing = sorted(needed - available)
            name = shp_entry.filename.rsplit(".", 1)[0]
            # Use filename (not full path) as display name
            display_name = Path(name).stem

            ds = Dataset(
                # MapBatches scopes this stable archive-path fingerprint to the
                # batch before persistence. Keeping the full path here avoids
                # collisions such as a/b.shp versus a_b.shp during inspection.
                id=hashlib.sha256(base_lower.encode()).hexdigest()[:32],
                path=shp_entry.filename,
                name=display_name,
                valid=not missing,
                error=f"Missing sidecars: {', '.join('.' + e for e in missing)}" if missing else None,
            )
            datasets.append(ds)
            digest.update(shp_entry.filename.encode())

        return digest.hexdigest()[:16], datasets


def _inspect_shp_in_zip(zip_path: Path, dataset: Dataset) -> Dataset:
    """Open one SHP from a ZIP and read geometry type + feature count + bbox."""
    try:
        import pyogrio
    except ImportError:
        logger.warning("pyogrio not available; skipping metadata inspection for %s", dataset.path)
        dataset.valid = True
        dataset.error = None
        return dataset

    with tempfile.TemporaryDirectory(prefix="shp_inspect_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            # Extract this dataset's files
            base_lower = dataset.path.rsplit(".", 1)[0].lower()
            for member in zf.infolist():
                if member.is_dir():
                    continue
                _validate_archive_member(member.filename)
                member_lower = member.filename.rsplit(".", 1)[0].lower()
                member_ext = member.filename.rsplit(".", 1)[1].lower() if "." in member.filename else ""
                if member_lower == base_lower and member_ext in {"shp", "dbf", "shx", "prj", "cpg"}:
                    zf.extract(member, tmp_path)

            shp_path = tmp_path / dataset.path
            if not shp_path.exists():
                # Try flattened (no subfolder)
                shp_path = tmp_path / Path(dataset.path).name
            if not shp_path.exists():
                dataset.valid = False
                dataset.error = f"SHP file not found after extraction: {dataset.path}"
                return dataset

            meta = pyogrio.read_info(str(shp_path))
            geom_type = meta.get("geometry_type") or "Unknown"
            # Normalize
            dataset.geometry = _normalize_geometry_type(str(geom_type))
            dataset.feature_count = int(meta.get("features") or 0)

            # Bounding box
            bounds_val = meta.get("total_bounds")
            if bounds_val and len(bounds_val) == 4:
                dataset.bbox = [float(v) for v in bounds_val]

    dataset.valid = True
    dataset.error = None
    return dataset


def _default_style_for_geom(geom: str) -> dict:
    """Return a minimal default style keyed by geometry type."""
    colors = {
        "Point": {"fillColor": "#e31a1c", "strokeColor": "#e31a1c", "pointRadius": 5},
        "LineString": {"strokeColor": "#3388ff", "strokeWidth": 2},
        "Polygon": {"fillColor": "#3388ff", "strokeColor": "#3388ff", "opacity": 0.5},
    }
    return {geom: colors.get(geom, colors["Polygon"])}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#rrggbb' to an (r, g, b) tuple for the raster tiler."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (51, 136, 255)
    try:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (51, 136, 255)


def _style_for_tiler(style: dict) -> dict:
    """Convert hex colors in a style dict to RGB arrays (VectorTiler format)."""
    if not style:
        return {}
    # If already RGB arrays, return as-is
    for geom, props in style.items():
        if props and any(isinstance(v, list) for v in props.values()):
            return style
    out = {}
    for geom, props in style.items():
        p = dict(props)
        for key in ("fillColor", "strokeColor"):
            if key in p and isinstance(p[key], str):
                p[key] = list(_rgb(p[key]))
        out[geom] = p
    return out


def _geoserver_layer_group_xml(name: str, layer_names: list[str]) -> bytes:
    """Serialize a WMS group using GeoServer's single layers/styles containers."""
    from xml.etree.ElementTree import Element, SubElement, tostring

    root = Element("layerGroup")
    SubElement(root, "name").text = name
    SubElement(root, "mode").text = "SINGLE"
    layers = SubElement(root, "layers")
    styles = SubElement(root, "styles")
    for layer_name in layer_names:
        SubElement(layers, "layer").text = layer_name
        # An empty style entry tells GeoServer to retain the layer default.
        SubElement(styles, "style")
    return tostring(root, encoding="utf-8")


def _geom_to_paint_type(geom: str) -> str:
    """Map geometry type to Mapbox paint type."""
    return {"Point": "circle", "LineString": "line"}.get(geom, "fill")


def _group_styles_dir() -> Path:
    d = Path(settings.TILES_DIR) / "_group_styles"
    d.mkdir(parents=True, exist_ok=True)
    return d


class FileBackedMapRenderer:
    """MapRenderer that publishes to GeoServer for WMS and works with file-based sources."""

    def __init__(self, geoserver: GeoServerService | None = None):
        self._gs = geoserver
        self._work_dir = Path(settings.UPLOAD_DIR) / "_batch_work"
        self._work_dir.mkdir(parents=True, exist_ok=True)

    def _get_gs(self) -> GeoServerService:
        if self._gs is None:
            self._gs = GeoServerService(
                url=settings.GEOSERVER_URL,
                username=settings.GEOSERVER_USER,
                password=settings.GEOSERVER_PASSWORD,
                workspace=settings.GEOSERVER_WORKSPACE,
                wms_url=settings.GEOSERVER_WMS_URL,
            )
        return self._gs

    def _resolve_source_path(self, source: dict) -> Path:
        """Materialize the upload to a local path.

        Artifact-backed sources are downloaded once per artifact_id into a
        stable cache directory and reused for every dataset render within the
        same batch (no per-member ZIP duplication).
        """
        final_path = source.get("final_path")
        artifact_id = source.get("artifact_id")
        if final_path and not final_path.startswith("artifact://"):
            return Path(final_path)
        if artifact_id:
            from app.infrastructure.services.upload_artifact_client import UploadArtifactClient
            filename = source.get("filename", "artifact.bin")
            # ponytail: stable cache dir keyed by artifact_id. Cache survives across
            # renders in the same batch and across retries. Evicted only when
            # lease is released. Add when disk pressure requires smarter eviction.
            cache_dir = self._work_dir / f"artifact_{artifact_id}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            dest = cache_dir / Path(filename).name
            if dest.exists() and dest.stat().st_size > 0:
                return dest
            client = UploadArtifactClient()
            try:
                with client.materialize(artifact_id, filename) as tmp:
                    shutil.copyfile(tmp, dest)
            except Exception as exc:
                if dest.exists():
                    dest.unlink()
                raise MapError(f"Failed to download artifact {artifact_id}: {exc}", 502)
            return dest
        raise MapError("Upload source has no resolvable path")

    def inspect(self, source: dict) -> tuple[str, list[Dataset]]:
        zip_path = self._resolve_source_path(source)
        if not zip_path.suffix.lower() == ".zip":
            raise MapError("Batch processing requires a ZIP file")
        digest, datasets = _detect_datasets_from_zip(zip_path)
        # Enrich with metadata
        for ds in datasets:
            if ds.valid:
                try:
                    _inspect_shp_in_zip(zip_path, ds)
                except Exception as exc:
                    logger.warning("inspect failed for %s: %s", ds.path, exc)
                    ds.valid = False
                    ds.error = str(exc)
        # Assign default styles
        for ds in datasets:
            if ds.valid and ds.geometry:
                ds.style = _default_style_for_geom(ds.geometry)
        return digest, datasets

    def render(self, source: dict, batch: Batch, item: Dataset, progress: Callable[[int], None]) -> LayerData:
        """Publish one dataset to GeoServer (for WMS) or import to PostGIS."""
        zip_path = self._resolve_source_path(source)
        style = _normalize_style_geometry_keys(item.style)
        progress(5)

        # Extract the specific dataset from the ZIP
        work_dir = self._work_dir / item.id
        work_dir.mkdir(exist_ok=True)
        extracted_shp = None
        try:
            with zipfile.ZipFile(zip_path) as zf:
                base_lower = item.path.rsplit(".", 1)[0].lower()
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    _validate_archive_member(member.filename)
                    m_lower = member.filename.rsplit(".", 1)[0].lower()
                    m_ext = member.filename.rsplit(".", 1)[1].lower() if "." in member.filename else ""
                    if m_lower == base_lower and m_ext in {"shp", "dbf", "shx", "prj", "cpg"}:
                        zf.extract(member, work_dir)

            # Find the .shp file in work_dir
            shp_files = list(work_dir.rglob("*.shp"))
            if not shp_files:
                raise MapError(f"SHP file not found after extraction: {item.path}")
            extracted_shp = shp_files[0]
            progress(30)

            if batch.output_format == "wms":
                # Publish to GeoServer
                gs = self._get_gs()
                code = item.code or item.id
                result = gs.publish_shp(str(extracted_shp), code)
                progress(80)

                # Apply style if provided
                if style:
                    style_name = f"{code}_style"
                    sld = build_sld(style, style_name)
                    gs.upsert_style(style_name, sld)
                    gs.set_default_style(result["layer_name"], style_name)
                progress(95)

                bbox = result.get("bbox") or item.bbox
                return LayerData(
                    id=item.layer_id, code=code, name=item.name,
                    output_format="wms",
                    upload_id=batch.upload_id,
                    bbox=bbox or [0, 0, 0, 0],
                    style=style,
                    metadata={"geoserver": result},
                    url=result.get("wms_url", ""),
                )
            else:
                # raster/mvt: delegate to tiling service
                from app.infrastructure.services.tiling_service import TilingService
                file_type = "vector"
                output_format = batch.output_format
                progress(30)
                bounds = TilingService.process_tiling(
                    file_type, extracted_shp, item.layer_id,
                    output_format=output_format,
                    style=_style_for_tiler(style),
                    progress_callback=lambda p: progress(30 + int(p.get("percent", 0) * 0.65)),
                    max_zoom=batch.max_zoom,
                )
                progress(98)

                if output_format == "mvt":
                    tile_url = f"/tiles/{item.layer_id}/{{z}}/{{x}}/{{y}}.pbf"
                else:
                    tile_url = f"/tiles/{item.layer_id}/{{z}}/{{x}}/{{y}}.png"

                bbox = bounds or item.bbox
                return LayerData(
                    id=item.layer_id, code=item.code or item.id, name=item.name,
                    output_format=output_format,
                    upload_id=batch.upload_id,
                    bbox=bbox or [0, 0, 0, 0],
                    style=style,
                    metadata={"tile_process": {"status": "done"}},
                    url=tile_url,
                )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def publish(self, group: Group, layers: list[LayerData]) -> None:
        """Publish/update the output that represents a layer group."""
        if not layers:
            return
        if group.output_format == "mvt":
            self._publish_mvt_group(group, layers)
            return
        if group.output_format == "raster":
            # Raster tiles are composed on demand by the public group-tile
            # endpoint. No duplicate tile pyramid is written here.
            return
        if group.output_format != "wms":
            return

        gs = self._get_gs()
        workspace = gs.workspace

        # Build GeoServer layer group
        visible_ids = {member.layer_id for member in group.members if member.visible}
        layer_names = [
            ld.metadata.get("geoserver", {}).get("layer_name", f"{workspace}:{ld.code}")
            for ld in layers if ld.id in visible_ids
        ]
        if not layer_names:
            return

        # Create/update the layer group via REST API
        import requests
        group_url = f"{gs._base_url}/rest/workspaces/{workspace}/layergroups/{group.code}"
        # GeoServer's JSON reader emits a duplicate <layers> field when given
        # a list. XML is unambiguous: one <layers> container, many <layer>
        # values, and one matching <styles> container.
        payload = _geoserver_layer_group_xml(group.code, layer_names)
        headers = {"Content-Type": "text/xml"}

        try:
            resp = requests.get(f"{group_url}.json", auth=gs._auth, timeout=15)
            if resp.status_code == 200:
                resp = requests.put(group_url, data=payload, headers=headers, auth=gs._auth, timeout=30)
            else:
                resp = requests.post(
                    f"{gs._base_url}/rest/workspaces/{workspace}/layergroups",
                    data=payload, headers=headers, auth=gs._auth, timeout=30,
                )
            if resp.status_code not in (200, 201):
                raise MapError(
                    f"GeoServer layer group publish failed ({resp.status_code}): {resp.text[:300]}",
                    502,
                )
        except requests.RequestException as exc:
            raise MapError(f"GeoServer unreachable: {exc}", 502)

    # -- MVT group composite ------------------------------------------------

    def _publish_mvt_group(self, group: Group, layers: list[LayerData]) -> None:
        """Generate composite MVT style.json for a group of vector tile layers.

        Each layer's MVT tiles live at /tiles/{layer_id}/{z}/{x}/{y}.pbf and
        include a source-layer equal to the layer_id. The composite style.json
        references all of them with appropriate paint and layout.
        """
        group_dir = _group_styles_dir() / group.code
        group_dir.mkdir(parents=True, exist_ok=True)

        paint_types = {"Point": "circle", "LineString": "line", "Polygon": "fill"}
        layers_style: list[dict] = []

        for ld in layers:
            style = ld.style or {}
            for geom_key, props in style.items():
                pt = paint_types.get(geom_key, "fill")
                paint: dict = {}
                layout: dict = {"visibility": "visible"}
                member_visible = True
                if hasattr(group, "members"):
                    for m in group.members:
                        if m.layer_id == ld.id:
                            member_visible = m.visible
                            break
                if not member_visible:
                    layout["visibility"] = "none"

                if pt == "fill":
                    paint["fill-color"] = props.get("fillColor", "#3388ff")
                    paint["fill-opacity"] = props.get("opacity", 0.7)
                elif pt == "line":
                    paint["line-color"] = props.get("strokeColor", "#3388ff")
                    paint["line-width"] = props.get("strokeWidth", 2)
                    paint["line-opacity"] = props.get("opacity", 1.0)
                elif pt == "circle":
                    paint["circle-radius"] = props.get("pointRadius", 5)
                    paint["circle-fill-color"] = props.get("fillColor", "#e31a1c")
                    paint["circle-stroke-color"] = props.get("strokeColor", "#e31a1c")

                layers_style.append({
                    "id": f"{ld.id}_{geom_key}",
                    "source": "group",
                    "source-layer": ld.id,
                    "type": pt,
                    "paint": paint,
                    "layout": layout,
                })

        style_path = group_dir / "style.json"
        style_path.write_text(json.dumps({
            "version": 8,
            "name": group.name,
            "sources": {
                "group": {
                    "type": "vector",
                    "tiles": [f"/tiles/_group/{group.code}/{{z}}/{{x}}/{{y}}.pbf"],
                }
            },
            "layers": layers_style,
        }, indent=2))

    def compose_raster_tile(self, group: Group, layers: list[LayerData], z: int, x: int, y: int) -> bytes | None:
        """Alpha-compose visible member PNGs in group order for one tile."""
        visible_ids = {member.layer_id for member in group.members if member.visible}
        canvas: Image.Image | None = None
        for layer in layers:
            if layer.id not in visible_ids:
                continue
            tile_path = Path(settings.TILES_DIR) / layer.id / str(z) / str(x) / f"{y}.png"
            if not tile_path.is_file():
                continue
            with Image.open(tile_path) as tile:
                rgba = tile.convert("RGBA")
                if canvas is None:
                    canvas = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
                if rgba.size != canvas.size:
                    rgba = rgba.resize(canvas.size)
                canvas.alpha_composite(rgba)
        if canvas is None:
            return None
        output = io.BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()

    def compose_mvt_tile(self, group: Group, layers: list[LayerData], z: int, x: int, y: int) -> bytes | None:
        """Merge member vector tiles while retaining each member layer identity."""
        merged: list[dict] = []
        for layer in layers:
            tile_path = Path(settings.TILES_DIR) / layer.id / str(z) / str(x) / f"{y}.pbf"
            if not tile_path.is_file():
                continue
            decoded = mapbox_vector_tile.decode(tile_path.read_bytes())
            for layer_name, payload in decoded.items():
                merged.append({"name": layer_name, "features": payload.get("features", [])})
        if not merged:
            return None
        return mapbox_vector_tile.encode(merged, default_options={"extents": 4096, "y_coord_down": True})

    # -- Legend -----------------------------------------------------------------

    def legend_for_group(self, group: Group, layers: list[LayerData]) -> list[dict]:
        """Return structured legend entries for visible group members only."""
        result: list[dict] = []
        members_by_id = {m.layer_id: m for m in getattr(group, "members", [])}
        for idx, ld in enumerate(layers):
            m = members_by_id.get(ld.id)
            visible = m.visible if m else True
            if not visible:
                continue
            sort_order = idx
            symbols: list[dict] = []
            style = ld.style or {}
            for geom_key, props in style.items():
                entry: dict[str, Any] = {
                    "geometry": geom_key,
                    "label": f"{geom_key} layer",
                    "fillColor": props.get("fillColor", "#3388ff"),
                    "strokeColor": props.get("strokeColor", "#3388ff"),
                    "strokeWidth": props.get("strokeWidth", 1),
                    "opacity": props.get("opacity", 1.0),
                }
                if geom_key == "Point":
                    entry["pointRadius"] = props.get("pointRadius", 5)
                symbols.append(entry)
            result.append({
                "layer_id": ld.id,
                "layer_name": ld.name or ld.id,
                "visible": visible,
                "sort_order": sort_order,
                "symbols": symbols,
            })
        return result

    def remove(self, group: Group) -> None:
        """Remove a GeoServer layer group."""
        if group.output_format == "mvt":
            group_dir = _group_styles_dir() / group.code
            shutil.rmtree(group_dir, ignore_errors=True)
            return
        if group.output_format != "wms":
            return
        gs = self._get_gs()
        import requests
        group_url = f"{gs._base_url}/rest/workspaces/{gs.workspace}/layergroups/{group.code}"
        try:
            resp = requests.delete(group_url, auth=gs._auth, timeout=15)
            if resp.status_code not in (200, 204, 404):
                logger.warning("Failed to delete layer group %s: %s", group.code, resp.status_code)
        except requests.RequestException as exc:
            logger.warning("Failed to delete layer group %s: %s", group.code, exc)
