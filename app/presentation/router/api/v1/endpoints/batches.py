"""API endpoints for multi-SHP batch inspection, configuration, processing, and groups."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.application.map_batches import MapBatches
from app.domain.map_batches import MapError
from app.infrastructure.db.catalog import SyncStore
from app.infrastructure.db.connection import db
from app.infrastructure.db.repository import SyncUploadSessionRepository
from app.infrastructure.services.map_renderer import FileBackedMapRenderer

router = APIRouter(prefix="/batches", tags=["batches"])


def _make_usecase() -> MapBatches:
    from app.workers.tasks import run_batch_task
    store = SyncStore(db.get_session)
    renderer = FileBackedMapRenderer()
    return MapBatches(store=store, renderer=renderer, enqueue=run_batch_task.delay)


def _as_error(exc: MapError, fallback: int = 422) -> HTTPException:
    return HTTPException(status_code=exc.status or fallback, detail=exc.message)


class BatchInspectRequest(BaseModel):
    upload_id: str


class DatasetSelection(BaseModel):
    id: str
    code: Optional[str] = None
    name: Optional[str] = None
    style: Optional[dict] = None
    visible: bool = True


class BatchConfigureRequest(BaseModel):
    mode: str = Field(pattern="^(group|separate)$", description="group or separate")
    output_format: str = Field(pattern="^(raster|mvt|wms|postgis)$", description="raster, mvt, wms, or postgis")
    name: Optional[str] = None
    code: Optional[str] = None        # group code when mode=group
    max_zoom: int = 14
    datasets: list[DatasetSelection] = Field(min_length=1)


class GroupMembersUpdate(BaseModel):
    name: Optional[str] = None
    revision: int = 0
    members: list[dict]  # [{layer_id, visible}]


@router.get("")
async def list_batches(limit: int = 50):
    from starlette.concurrency import run_in_threadpool
    try:
        batches = await run_in_threadpool(_make_usecase().list, max(1, min(limit, 200)))
    except MapError as exc:
        raise _as_error(exc, 400)
    return {"batches": [item.__dict__ for item in batches]}

@router.post("/inspect")
async def inspect_upload(body: BatchInspectRequest):
    from starlette.concurrency import run_in_threadpool
    try:
        result = await run_in_threadpool(_make_usecase().inspect, body.upload_id)
    except MapError as exc:
        raise _as_error(exc, 400)
    return {
        "batch": result.__dict__,
        "datasets": [item.__dict__ for item in result.datasets],
    }


@router.post("/{identity}/configure")
async def configure_batch(identity: str, body: BatchConfigureRequest):
    from starlette.concurrency import run_in_threadpool
    try:
        batch = await run_in_threadpool(
            _make_usecase().configure_and_start,
            identity,
            body.model_dump(exclude_none=True),
        )
    except MapError as exc:
        raise _as_error(exc)
    return {"batch": batch.__dict__}


@router.post("/{identity}/retry")
async def retry_batch(identity: str):
    from starlette.concurrency import run_in_threadpool
    try:
        batch = await run_in_threadpool(_make_usecase().retry, identity)
    except MapError as exc:
        raise _as_error(exc)
    return {"batch": batch.__dict__}


@router.post("/{identity}/cancel")
async def cancel_batch(identity: str):
    from starlette.concurrency import run_in_threadpool
    try:
        batch = await run_in_threadpool(_make_usecase().cancel, identity)
    except MapError as exc:
        raise _as_error(exc)
    _maybe_release_source_after_cancel(identity, batch.upload_id)
    return {"batch": batch.__dict__}


def _maybe_release_source_after_cancel(batch_id: str, upload_id: str) -> None:
    """Best-effort lease release once a cancelled batch no longer needs its source.

    Reference-counted: the pin survives while layers (or another active batch)
    still use the upload. Only the last consumer triggers the release.
    """
    try:
        with db.get_session() as session:
            current = SyncUploadSessionRepository(session).get_by_id(upload_id)
            if not current or not current.artifact_id or not current.artifact_lease_id:
                return
            artifact_id, lease_id = current.artifact_id, current.artifact_lease_id
        from app.workers.tasks import _release_artifact_lease
        _release_artifact_lease(artifact_id, lease_id, upload_id)
    except Exception as exc:
        print(f"[retention] Release check after cancel {batch_id} failed: {exc}")


@router.patch("/{identity}/group")
async def update_group(identity: str, body: GroupMembersUpdate):
    from starlette.concurrency import run_in_threadpool
    try:
        group = await run_in_threadpool(
            _make_usecase().update_group,
            identity,
            body.name,
            body.members,
            body.revision,
        )
    except MapError as exc:
        raise _as_error(exc)
    return {"group": group.__dict__}


@router.get("/groups")
async def list_groups():
    from starlette.concurrency import run_in_threadpool
    store = SyncStore(db.get_session)
    with store.transaction() as records:
        groups = await run_in_threadpool(records.groups)
    return {"groups": [g.__dict__ for g in groups]}


@router.delete("/{identity}/group")
async def delete_group(identity: str):
    from starlette.concurrency import run_in_threadpool
    try:
        await run_in_threadpool(_make_usecase().delete_group, identity)
    except MapError as exc:
        raise _as_error(exc)
    return {"message": "Group deleted"}


@router.get("/groups/{group_id}/legend")
async def group_legend(group_id: str):
    """Structured legend data for dashboard rendering."""
    from starlette.concurrency import run_in_threadpool
    store = SyncStore(db.get_session)
    renderer = FileBackedMapRenderer()
    try:
        with store.transaction() as r:
            group = r.group(group_id)
            layers = [r.layer(member.layer_id) for member in group.members]
    except MapError as exc:
        raise _as_error(exc, 404)
    return await run_in_threadpool(renderer.legend_for_group, group, layers)


@router.get("/{identity}")
async def get_batch(identity: str):
    from starlette.concurrency import run_in_threadpool
    store = SyncStore(db.get_session)
    try:
        with store.transaction() as records:
            batch = records.batch(identity)
    except MapError as exc:
        raise _as_error(exc, 404)
    return {"batch": batch.__dict__}


groups_router = APIRouter(prefix="/groups", tags=["groups"])


@groups_router.get("/layer/{layer_id}/usage")
async def groups_using_layer(layer_id: str):
    """Return groups that reference this layer (blocks layer deletion)."""
    from starlette.concurrency import run_in_threadpool
    store = SyncStore(db.get_session)
    with store.transaction() as records:
        groups = await run_in_threadpool(records.groups_using, layer_id)
    return {"groups": [g.__dict__ for g in groups]}
