import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from shapely.geometry import shape as _shape
from starlette.background import BackgroundTask

from app.core.config import settings
from app.domain.form_validation import FormValidationError, validate_attributes, validate_form_schema
from app.domain.geometry_validation import GeometryValidationError, validate_geometry
from app.domain.models import Attachment, Feature, GeometryType, Layer, LayerType, Project
from app.domain.schemas import (
    AttachmentResponse, FeatureCreate, FeatureResponse, FeatureUpdate, FormSchemaUpdate,
    ProjectCreate, ProjectResponse, ProjectUpdate, PublishResponse,
)
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import (
    AttachmentRepository, FeatureRepository, LayerRepository, ProjectRepository,
)
from app.infrastructure.services.project_export_service import (
    InvalidStoredGeometryError, build_feature_collection, export_csv, export_shp_zip,
)

router = APIRouter(prefix="/projects", tags=["projects"])

DEFAULT_ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}

DEFAULT_STYLE = {
    "mode": "simple",
    "simple": {
        "Point": {"fillColor": "#2E7DD1", "strokeColor": "#1A4E86", "strokeWidth": 1, "opacity": 1.0, "pointRadius": 6},
        "LineString": {"strokeColor": "#2E7DD1", "strokeWidth": 2, "opacity": 1.0, "strokePattern": "solid"},
        "Polygon": {"fillColor": "#2E7DD1", "strokeColor": "#1A4E86", "strokeWidth": 1, "opacity": 0.6, "fillPattern": "solid"},
    },
}


def get_project_repo(session=Depends(get_async_session)) -> ProjectRepository:
    return ProjectRepository(session)


def get_feature_repo(session=Depends(get_async_session)) -> FeatureRepository:
    return FeatureRepository(session)


def get_attachment_repo(session=Depends(get_async_session)) -> AttachmentRepository:
    return AttachmentRepository(session)


def get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


def _compute_bbox(features: list[Feature]) -> Optional[tuple[float, float, float, float]]:
    try:
        bounds = [_shape(f.geometry).bounds for f in features]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid stored geometry: {exc}")
    if not bounds:
        return None
    return (
        min(b[0] for b in bounds), min(b[1] for b in bounds),
        max(b[2] for b in bounds), max(b[3] for b in bounds),
    )


async def _get_project_or_404(project_id: str, repo: ProjectRepository) -> Project:
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _allowed_extensions(project: Project, field_name: Optional[str]) -> set[str]:
    if field_name:
        for field in project.form_schema:
            if field.get("name") == field_name and field.get("extensions"):
                return {e.lower().lstrip(".") for e in field["extensions"]}
    return DEFAULT_ATTACHMENT_EXTENSIONS


def _attachment_ids_in(feature: Feature, schema: list) -> set[str]:
    file_fields = {f["name"] for f in schema if f.get("type") == "file"}
    return {v for k, v in feature.attributes.items() if k in file_fields and isinstance(v, str)}


async def _delete_attachments_for(
    project: Project,
    attachment_repo: AttachmentRepository,
    referenced_ids: Optional[set[str]] = None,
) -> None:
    """Delete attachment rows+files for a project; if referenced_ids given, only those."""
    for a in await attachment_repo.list_by_project(project.id):
        if referenced_ids is not None and a.id not in referenced_ids:
            continue
        Path(a.stored_path).unlink(missing_ok=True)
        await attachment_repo.delete(a.id)


def _project_response(project: Project, feature_count: int) -> ProjectResponse:
    return ProjectResponse(
        id=project.id, name=project.name, description=project.description,
        geometry_type=project.geometry_type, form_schema=project.form_schema,
        layer_id=project.layer_id, is_published=project.layer_id is not None,
        feature_count=feature_count,
        created_at=project.created_at, updated_at=project.updated_at,
    )


@router.post("", response_model=ProjectResponse)
async def create_project(body: ProjectCreate, repo: ProjectRepository = Depends(get_project_repo)):
    if body.geometry_type not in {g.value for g in GeometryType}:
        raise HTTPException(status_code=422, detail=f"geometry_type must be one of: point, line, polygon")
    try:
        validate_form_schema(body.form_schema)
    except FormValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    project = Project(
        id=str(uuid.uuid4()), name=body.name, description=body.description,
        geometry_type=body.geometry_type, form_schema=body.form_schema,
    )
    await repo.create(project)
    return _project_response(project, 0)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    projects = await repo.list_all()
    out = []
    for p in projects:
        count = len(await feature_repo.list_by_project(p.id))
        out.append(_project_response(p, count))
    return out


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    count = len(await feature_repo.list_by_project(project_id))
    return _project_response(project, count)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, body: ProjectUpdate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    await repo.update(project)
    count = len(await feature_repo.list_by_project(project_id))
    return _project_response(project, count)


@router.put("/{project_id}/schema", response_model=ProjectResponse)
async def replace_schema(
    project_id: str, body: FormSchemaUpdate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    try:
        validate_form_schema(body.form_schema)
    except FormValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    project.form_schema = body.form_schema
    await repo.update(project)
    count = len(await feature_repo.list_by_project(project_id))
    return _project_response(project, count)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
    attachment_repo: AttachmentRepository = Depends(get_attachment_repo),
    layer_repo: LayerRepository = Depends(get_layer_repo),
):
    project = await _get_project_or_404(project_id, repo)
    await feature_repo.delete_by_project(project_id)
    await _delete_attachments_for(project, attachment_repo)
    shutil.rmtree(settings.ATTACHMENTS_DIR / project_id, ignore_errors=True)
    if project.layer_id:
        layer_id = project.layer_id
        project.layer_id = None
        await repo.update(project)
        await layer_repo.delete(layer_id)
    await repo.delete(project_id)


def _feature_response(f: Feature) -> FeatureResponse:
    return FeatureResponse(
        id=f.id, project_id=f.project_id, geometry=f.geometry, attributes=f.attributes,
        created_by=f.created_by, created_at=f.created_at, updated_at=f.updated_at,
    )


@router.post("/{project_id}/features", response_model=FeatureResponse)
async def create_feature(
    project_id: str, body: FeatureCreate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    try:
        validate_geometry(body.geometry, project.geometry_type)
        validate_attributes(project.form_schema, body.attributes)
    except (GeometryValidationError, FormValidationError) as exc:
        detail = getattr(exc, "errors", str(exc))
        raise HTTPException(status_code=422, detail=detail)
    feature = Feature(
        id=str(uuid.uuid4()), project_id=project_id,
        geometry=body.geometry, attributes=body.attributes, created_by=body.created_by,
    )
    await feature_repo.create(feature)
    return _feature_response(feature)


@router.get("/{project_id}/features", response_model=list[FeatureResponse])
async def list_features(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    await _get_project_or_404(project_id, repo)
    return [_feature_response(f) for f in await feature_repo.list_by_project(project_id)]


@router.get("/{project_id}/features/{feature_id}", response_model=FeatureResponse)
async def get_feature(
    project_id: str, feature_id: str,
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    feature = await feature_repo.get_by_id(feature_id)
    if feature is None or feature.project_id != project_id:
        raise HTTPException(status_code=404, detail="Feature not found")
    return _feature_response(feature)


@router.patch("/{project_id}/features/{feature_id}", response_model=FeatureResponse)
async def update_feature(
    project_id: str, feature_id: str, body: FeatureUpdate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    feature = await feature_repo.get_by_id(feature_id)
    if feature is None or feature.project_id != project_id:
        raise HTTPException(status_code=404, detail="Feature not found")
    try:
        if body.geometry is not None:
            validate_geometry(body.geometry, project.geometry_type)
            feature.geometry = body.geometry
        if body.attributes is not None:
            merged = {**feature.attributes, **body.attributes}
            validate_attributes(project.form_schema, merged)
            feature.attributes = merged
    except (GeometryValidationError, FormValidationError) as exc:
        detail = getattr(exc, "errors", str(exc))
        raise HTTPException(status_code=422, detail=detail)
    await feature_repo.update(feature)
    return _feature_response(feature)


@router.delete("/{project_id}/features/{feature_id}", status_code=204)
async def delete_feature(
    project_id: str, feature_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
    attachment_repo: AttachmentRepository = Depends(get_attachment_repo),
):
    feature = await feature_repo.get_by_id(feature_id)
    if feature is None or feature.project_id != project_id:
        raise HTTPException(status_code=404, detail="Feature not found")
    project = await _get_project_or_404(project_id, repo)
    referenced_ids = _attachment_ids_in(feature, project.form_schema)
    await _delete_attachments_for(project, attachment_repo, referenced_ids)
    await feature_repo.delete(feature_id)


@router.post("/{project_id}/attachments", response_model=AttachmentResponse)
async def upload_attachment(
    project_id: str,
    file: UploadFile = File(...),
    field_name: Optional[str] = Form(None),
    repo: ProjectRepository = Depends(get_project_repo),
    attachment_repo: AttachmentRepository = Depends(get_attachment_repo),
):
    project = await _get_project_or_404(project_id, repo)
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in _allowed_extensions(project, field_name):
        raise HTTPException(status_code=422, detail=f"extension .{ext} not allowed")
    if file.size and file.size > settings.ATTACHMENT_MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"attachment exceeds {settings.ATTACHMENT_MAX_SIZE} bytes")
    attachment_id = str(uuid.uuid4())
    stored_name = f"{attachment_id}_{Path(file.filename).name}"
    dest_dir = settings.ATTACHMENTS_DIR / project_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    attachment = Attachment(
        id=attachment_id, project_id=project_id, filename=file.filename or stored_name,
        stored_path=str(dest), content_type=file.content_type, size_bytes=dest.stat().st_size,
    )
    await attachment_repo.create(attachment)
    return AttachmentResponse(
        id=attachment.id, project_id=project_id, filename=attachment.filename,
        url=f"/attachments/{project_id}/{stored_name}",
        content_type=attachment.content_type, size_bytes=attachment.size_bytes,
    )


@router.get("/{project_id}/features.geojson")
async def project_geojson(
    project_id: str, request: Request,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    features = await feature_repo.list_by_project(project_id)
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(build_feature_collection(project, features, base_url))


@router.get("/{project_id}/export")
async def export_project(
    project_id: str, format: str = "geojson",
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    features = await feature_repo.list_by_project(project_id)
    safe_name = project.name.replace(" ", "_")
    if format == "geojson":
        return JSONResponse(
            build_feature_collection(project, features),
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.geojson"'},
        )
    if format == "csv":
        try:
            csv_content = export_csv(project, features)
        except InvalidStoredGeometryError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return PlainTextResponse(
            csv_content, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )
    if format == "shp":
        if not features:
            raise HTTPException(status_code=422, detail="no features to export")
        tmp = tempfile.mkdtemp(prefix="shp_export_")
        try:
            zip_path = export_shp_zip(project, features, Path(tmp))
        except InvalidStoredGeometryError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return FileResponse(
            zip_path, media_type="application/zip", filename=f"{safe_name}.zip",
            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
        )
    raise HTTPException(status_code=422, detail="format must be geojson|csv|shp")


@router.post("/{project_id}/publish", response_model=PublishResponse)
async def publish_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
    layer_repo: LayerRepository = Depends(get_layer_repo),
):
    project = await _get_project_or_404(project_id, repo)
    if project.layer_id is not None:
        raise HTTPException(status_code=409, detail="Project already published")
    features = await feature_repo.list_by_project(project_id)
    geojson_url = f"{settings.API_V1_STR}/projects/{project_id}/features.geojson"
    layer = Layer(
        id=str(uuid.uuid4()),
        layer_type=LayerType.geojson,
        filename=project.name,
        file_type="geojson",
        tile_url_template=geojson_url,
        is_active=True,
        is_visible=True,
        file_metadata={"project_id": project_id, "style": DEFAULT_STYLE},
    )
    bbox = _compute_bbox(features)
    if bbox:
        layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north = bbox
    await layer_repo.create(layer)
    project.layer_id = layer.id
    await repo.update(project)
    return PublishResponse(project_id=project_id, layer_id=layer.id, geojson_url=geojson_url)


@router.delete("/{project_id}/publish", status_code=204)
async def unpublish_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    layer_repo: LayerRepository = Depends(get_layer_repo),
):
    project = await _get_project_or_404(project_id, repo)
    if project.layer_id is None:
        raise HTTPException(status_code=409, detail="Project is not published")
    layer_id = project.layer_id
    project.layer_id = None
    await repo.update(project)
    await layer_repo.delete(layer_id)
