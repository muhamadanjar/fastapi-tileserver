"""SQLModel-backed Store/Catalog implementing domain protocols."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import func
from sqlmodel import Session, select

from app.domain.map_batches import (
    Batch, Dataset, Group, LayerData, MapError, Member,
    Catalog, Store, state,
)
from app.domain.models import (
    BatchRecord, DatasetRecord, GroupRecord, GroupMemberRecord,
    CodeReservation, Layer, UploadSession,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _batch_from_record(r: BatchRecord, datasets: list[Dataset] | None = None) -> Batch:
    return Batch(
        id=r.id, upload_id=r.upload_id, filename=r.filename,
        status=r.status, source_digest=r.source_digest, mode=r.mode,
        output_format=r.output_format, max_zoom=r.max_zoom,
        group_id=r.group_id, task_token=r.task_token, error=r.error,
        datasets=datasets or [],
    )


def _group_from_record(r: GroupRecord, members: list[GroupMemberRecord]) -> Group:
    return Group(
        id=r.id, code=r.code, name=r.name, output_format=r.output_format,
        status=r.status, revision=r.revision, error=r.error,
        members=[Member(layer_id=m.layer_id, visible=m.visible) for m in members],
    )


def _dataset_from_record(d: DatasetRecord) -> Dataset:
    return Dataset(
        id=d.id, path=d.path, name=d.name, valid=d.valid, error=d.error,
        geometry=d.geometry, feature_count=d.feature_count,
        bbox=d.bbox or [], style=d.style or {}, selected=d.selected,
        layer_id=d.layer_id or "", code=d.code, visible=d.visible,
        status=d.status, progress=d.progress,
    )


def _layer_data_from_record(layer: Layer) -> LayerData:
    meta = layer.file_metadata or {}
    return LayerData(
        id=layer.id, code=layer.code or "", name=layer.filename,
        output_format=meta.get("output_format", ""),
        upload_id=layer.upload_session_id,
        bbox=[layer.bbox_west or 0, layer.bbox_south or 0,
              layer.bbox_east or 0, layer.bbox_north or 0],
        style=meta.get("style") or {},
        metadata=meta,
        url=layer.tile_url_template,
    )


class SyncCatalog:
    """Catalog backed by a synchronous SQLModel Session."""

    def __init__(self, session: Session):
        self.session = session

    # --- Batch ---
    def batch_list(self, limit: int = 50) -> list[Batch]:
        records = list(
            self.session.exec(
                select(BatchRecord).order_by(BatchRecord.created_at.desc()).limit(limit)
            ).all()
        )
        result = []
        for r in records:
            datasets = [_dataset_from_record(x) for x in self.session.exec(
                select(DatasetRecord).where(DatasetRecord.batch_id == r.id)
            ).all()]
            result.append(_batch_from_record(r, datasets))
        return result

    def batch(self, identity: str) -> Batch:
        r = self.session.get(BatchRecord, identity)
        if r is None:
            r = self.session.exec(
                select(BatchRecord).where(BatchRecord.upload_id == identity)
            ).one_or_none()
        if not r:
            raise MapError(f"Batch {identity} not found", 404)
        datasets = [_dataset_from_record(x) for x in self.session.exec(
            select(DatasetRecord).where(DatasetRecord.batch_id == r.id)
        ).all()]
        return _batch_from_record(r, datasets)

    # --- Group ---
    def group(self, identity: str) -> Group:
        r = self.session.get(GroupRecord, identity)
        if not r:
            raise MapError(f"Group {identity} not found", 404)
        members = list(self.session.exec(
            select(GroupMemberRecord)
            .where(GroupMemberRecord.group_id == identity)
            .order_by(GroupMemberRecord.sorting)
        ).all())
        return _group_from_record(r, members)

    def groups(self) -> list[Group]:
        records = list(self.session.exec(select(GroupRecord)).all())
        result = []
        for r in records:
            members = list(self.session.exec(
                select(GroupMemberRecord)
                .where(GroupMemberRecord.group_id == r.id)
                .order_by(GroupMemberRecord.sorting)
            ).all())
            result.append(_group_from_record(r, members))
        return result

    def groups_using(self, layer_id: str) -> list[Group]:
        member_rows = list(self.session.exec(
            select(GroupMemberRecord).where(GroupMemberRecord.layer_id == layer_id)
        ).all())
        group_ids = {m.group_id for m in member_rows}
        if not group_ids:
            return []
        result = []
        for gid in group_ids:
            r = self.session.get(GroupRecord, gid)
            if r:
                members = list(self.session.exec(
                    select(GroupMemberRecord)
                    .where(GroupMemberRecord.group_id == gid)
                    .order_by(GroupMemberRecord.sorting)
                ).all())
                result.append(_group_from_record(r, members))
        return result

    # --- Layer ---
    def layer(self, identity: str) -> LayerData:
        layer = self.session.get(Layer, identity)
        if not layer:
            raise MapError(f"Layer {identity} not found", 404)
        return _layer_data_from_record(layer)

    # --- Upload ---
    def upload(self, identity: str) -> dict:
        us = self.session.get(UploadSession, identity)
        if not us:
            raise MapError(f"Upload {identity} not found", 404)
        return {
            "id": us.id,
            "filename": us.filename,
            "status": us.status,
            "final_path": us.final_path,
            "artifact_id": us.artifact_id,
            "layer_id": us.layer_id,
        }

    # --- Save ---
    def save(self, value: Batch | Group | LayerData) -> None:
        if isinstance(value, Batch):
            self._save_batch(value)
        elif isinstance(value, Group):
            self._save_group(value)
        elif isinstance(value, LayerData):
            self._save_layer(value)
        else:
            raise MapError(f"Unknown value type: {type(value)}", 500)

    def _save_batch(self, b: Batch) -> None:
        existing = self.session.get(BatchRecord, b.id)
        if existing:
            existing.status = b.status
            existing.source_digest = b.source_digest
            existing.mode = b.mode
            existing.output_format = b.output_format
            existing.max_zoom = b.max_zoom
            existing.group_id = b.group_id
            existing.task_token = b.task_token
            existing.error = b.error
            existing.updated_at = _now()
        else:
            existing = BatchRecord(
                id=b.id, upload_id=b.upload_id, filename=b.filename,
                status=b.status, source_digest=b.source_digest, mode=b.mode,
                output_format=b.output_format, max_zoom=b.max_zoom,
                group_id=b.group_id, task_token=b.task_token, error=b.error,
            )
        self.session.add(existing)
        self.session.flush()

        # Sync datasets
        for item in b.datasets:
            ds = self.session.get(DatasetRecord, item.id)
            if ds:
                ds.path = item.path
                ds.name = item.name
                ds.valid = item.valid
                ds.error = item.error
                ds.geometry = item.geometry
                ds.feature_count = item.feature_count
                ds.bbox = item.bbox
                ds.style = item.style
                ds.selected = item.selected
                ds.layer_id = item.layer_id
                ds.code = item.code
                ds.visible = item.visible
                ds.status = item.status
                ds.progress = item.progress
                ds.updated_at = _now()
            else:
                ds = DatasetRecord(
                    id=item.id, batch_id=b.id, path=item.path, name=item.name,
                    valid=item.valid, error=item.error, geometry=item.geometry,
                    feature_count=item.feature_count, bbox=item.bbox,
                    style=item.style, selected=item.selected,
                    layer_id=item.layer_id or None, code=item.code,
                    visible=item.visible, status=item.status, progress=item.progress,
                )
            self.session.add(ds)
        self.session.flush()

    def _save_group(self, g: Group) -> None:
        existing = self.session.get(GroupRecord, g.id)
        if existing:
            existing.code = g.code
            existing.name = g.name
            existing.output_format = g.output_format
            existing.status = g.status
            existing.revision = g.revision
            existing.error = g.error
            existing.updated_at = _now()
        else:
            existing = GroupRecord(
                id=g.id, code=g.code, name=g.name,
                output_format=g.output_format, status=g.status,
                revision=g.revision, error=g.error,
            )
        self.session.add(existing)
        self.session.flush()

        # Replace members
        old_members = list(self.session.exec(
            select(GroupMemberRecord).where(GroupMemberRecord.group_id == g.id)
        ).all())
        for m in old_members:
            self.session.delete(m)
        for idx, member in enumerate(g.members):
            self.session.add(GroupMemberRecord(
                id=str(uuid.uuid4()), group_id=g.id,
                layer_id=member.layer_id, visible=member.visible,
                sorting=idx,
            ))
        self.session.flush()

    def _save_layer(self, ld: LayerData) -> None:
        # Batch output_format -> Layer.layer_type mapping. `raster` in the
        # batch domain means XYZ PNG tiles (`tile`), `wms` is a GeoServer
        # WMS layer, `mvt` is vector tiles, `postgis` is a DB table.
        _OUTPUT_TO_LAYER_TYPE = {
            "wms": "wms",
            "mvt": "mvt",
            "raster": "tile",
            "postgis": "postgis",
        }
        _OUTPUT_TO_FILE_TYPE = {
            "wms": "external",
            "mvt": "vector",
            "raster": "vector",
            "postgis": "vector",
        }
        mapped_layer_type = _OUTPUT_TO_LAYER_TYPE.get(ld.output_format, "tile")
        mapped_file_type = _OUTPUT_TO_FILE_TYPE.get(ld.output_format, "vector")

        layer = self.session.get(Layer, ld.id)
        if not layer:
            layer = Layer(
                id=ld.id, code=ld.code, filename=ld.name,
                layer_type=mapped_layer_type, file_type=mapped_file_type,
                tile_url_template=ld.url,
                upload_session_id=ld.upload_id,
            )
        else:
            layer.code = ld.code
            layer.filename = ld.name
            layer.tile_url_template = ld.url
            if ld.upload_id and not layer.upload_session_id:
                layer.upload_session_id = ld.upload_id
            # Keep layer_type/file_type consistent with the authoritative
            # output_format stored in LayerData. This fixes the batch-group
            # WMS bug where layers were persisted as `tile`.
            layer.layer_type = mapped_layer_type
            layer.file_type = mapped_file_type
        meta = dict(layer.file_metadata or {})
        meta.update(ld.metadata)
        meta["output_format"] = ld.output_format
        if ld.style:
            meta["style"] = ld.style
        layer.file_metadata = meta
        if ld.bbox and len(ld.bbox) == 4:
            layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north = ld.bbox
        self.session.add(layer)
        self.session.flush()

    # --- Reserve ---
    def reserve(self, code: str, owner: str) -> None:
        existing_layer = self.session.exec(
            select(Layer).where(Layer.code == code, Layer.id != owner)
        ).first()
        existing_group = self.session.exec(
            select(GroupRecord).where(GroupRecord.code == code, GroupRecord.id != owner)
        ).first()
        if existing_layer or existing_group:
            raise MapError(f"Code '{code}' is already taken", 409)
        existing = self.session.exec(
            select(CodeReservation).where(CodeReservation.code == code)
        ).first()
        if existing:
            if existing.owner != owner:
                raise MapError(f"Code '{code}' is already taken", 409)
            return  # same owner, idempotent
        self.session.add(CodeReservation(code=code, owner=owner))
        self.session.flush()

    # --- Remove Group ---
    def remove_group(self, identity: str) -> None:
        members = list(self.session.exec(
            select(GroupMemberRecord).where(GroupMemberRecord.group_id == identity)
        ).all())
        for m in members:
            self.session.delete(m)
        g = self.session.get(GroupRecord, identity)
        if g:
            self.session.delete(g)
        self.session.flush()


class SyncStore:
    """Store that wraps a single Session as a Catalog transaction."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    @contextmanager
    def transaction(self) -> Iterator[SyncCatalog]:
        with self._session_factory() as session:
            cat = SyncCatalog(session)
            try:
                yield cat
                session.commit()
            except Exception:
                session.rollback()
                raise
