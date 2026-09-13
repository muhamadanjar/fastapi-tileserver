"""Read existing vector sources without publishing or duplicating a layer."""
import hashlib
from pathlib import Path

import geopandas as gpd
from shapely.geometry import shape
from sqlmodel import select

from app.domain.models import Feature, UploadSession
from app.analysis.reference_intersection import validate_frame
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient


def _read(path):
    layers = gpd.list_layers(path)
    if len(layers) != 1:
        raise ValueError("Sumber acuan harus menunjuk satu dataset vektor; sumber multi-dataset belum dapat dijadikan acuan.")
    return gpd.read_file(path)


def load_reference(session, layer, settings):
    project_id = (layer.file_metadata or {}).get("project_id")
    if project_id:
        records = session.exec(select(Feature).where(Feature.project_id == project_id).order_by(Feature.id)).all()
        if not records:
            raise ValueError("Acuan tidak memiliki fitur.")
        frame = gpd.GeoDataFrame([{**(f.attributes or {}), "geometry": shape(f.geometry), "_feature_id": f.id} for f in records], crs=4326)
    else:
        upload = session.get(UploadSession, layer.upload_session_id) if layer.upload_session_id else None
        if not upload or not upload.final_path:
            raise ValueError("Geometri sumber acuan tidak tersedia. Tile/WMS saja tidak dapat digunakan untuk analisis.")
        if upload.final_path.startswith("artifact://"):
            with UploadArtifactClient().materialize(upload.final_path.removeprefix("artifact://"), upload.filename) as path:
                frame = _read(path)
        else:
            path = Path(upload.final_path)
            if not path.is_file():
                raise ValueError("Berkas sumber acuan tidak tersedia.")
            before = path.stat()
            frame = _read(path)
            after = path.stat()
            if (before.st_mtime_ns, before.st_size, before.st_ino) != (after.st_mtime_ns, after.st_size, after.st_ino):
                raise ValueError("Sumber berubah saat dibaca. Jalankan ulang analisis.")
    frame = validate_frame(frame, label="Acuan", polygon_only=True, max_vertices=settings.ANALYSIS_MAX_VERTICES * 10)
    digest = hashlib.sha256()
    # Hash actual contents, not object-array memory addresses or mutable timestamps.
    digest.update(frame.to_json(drop_id=True).encode())
    return frame, digest.hexdigest()
