"""Application module: the same interface drives HTTP, workers and behavioral tests."""
from __future__ import annotations

import builtins
from copy import deepcopy
from uuid import uuid4, uuid5, NAMESPACE_URL
import re
import unicodedata

from app.domain.map_batches import (
    Batch, Group, Member, MapError, WorkCancelled, Store, MapRenderer, checked_code,
)


def suggested_code(name: str, identity: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")[:60]
    return f"{stem if stem and stem[0].isalpha() else 'layer-' + stem}-{identity.replace('-', '')[:8]}"


class MapBatches:
    def __init__(self, store: Store, renderer: MapRenderer, enqueue):
        self.store, self.renderer, self.enqueue = store, renderer, enqueue

    def list(self, limit: int = 50):
        with self.store.transaction() as records:
            return records.batch_list(limit)

    def inspect(self, upload_id: str) -> Batch:
        identity = str(uuid5(NAMESPACE_URL, f"tileserver:shapefile-batch:{upload_id}"))
        with self.store.transaction() as records:
            source = records.upload(upload_id)
            if not source["filename"].lower().endswith(".zip"):
                raise MapError("Multi-dataset processing requires a ZIP")
            try:
                previous = records.batch(identity)
            except MapError as exc:
                if exc.status != 404:
                    raise
            else:
                if previous.status != "inspection_failed":
                    return previous
            if source["status"] not in ("uploaded", "done", "failed"):
                raise MapError("Upload is not ready for inspection", 409)
            batch = Batch(identity, upload_id, source["filename"], task_token=str(uuid4()))
            records.save(batch)
        return self._dispatch(batch, "inspect")

    def _dispatch(self, batch: Batch, action: str) -> Batch:
        try:
            self.enqueue(batch.id, batch.task_token, action)
        except Exception:
            with self.store.transaction() as records:
                current = records.batch(batch.id)
                if current.task_token == batch.task_token:
                    current.status = "inspection_failed" if action == "inspect" else "failed"
                    current.error = "Could not queue work; retry is available"
                    records.save(current)
            raise MapError("Could not queue work; retry is available", 503)
        return batch

    def configure_and_start(self, identity: str, configuration: dict) -> Batch:
        with self.store.transaction() as records:
            batch = records.batch(identity)
            if batch.status != "ready":
                raise MapError("Only an inspected, unprocessed batch can be configured", 409)
            output = configuration["output_format"]
            mode = configuration["mode"]
            if output not in ("raster", "mvt", "wms", "postgis") or mode not in ("group", "separate"):
                raise MapError("Unsupported output format or processing mode")
            selections = configuration["datasets"]
            ids = [entry["id"] for entry in selections]
            if not ids or len(set(ids)) != len(ids):
                raise MapError("Select at least one dataset, without duplicates")
            by_id = {item.id: item for item in batch.datasets}
            if any(key not in by_id or not by_id[key].valid for key in ids):
                raise MapError("Only valid inspected datasets can be selected")
            batch.output_format, batch.mode = output, mode
            batch.max_zoom = configuration.get("max_zoom", 14)
            if not 0 <= batch.max_zoom <= 22:
                raise MapError("Maximum zoom must be between 0 and 22")
            for entry in selections:
                item = by_id[entry["id"]]
                item.selected = True
                item.code = checked_code(entry.get("code") or item.code)
                item.name = entry.get("name") or item.name
                item.style = entry.get("style") or item.style
                item.visible = entry.get("visible", True)
                item.status = "pending"
                records.reserve(item.code, item.layer_id)
            # Selection order is the rendering order, bottom to top.
            batch.datasets = [by_id[key] for key in ids] + [item for item in batch.datasets if item.id not in ids]
            if mode == "group":
                group_id = str(uuid5(NAMESPACE_URL, f"tileserver:group:{identity}"))
                name = configuration.get("name") or batch.filename.rsplit(".", 1)[0]
                code = checked_code(configuration.get("code") or suggested_code(name, group_id))
                records.reserve(code, group_id)
                group = Group(group_id, code, name, output, [Member(by_id[key].layer_id, by_id[key].visible) for key in ids])
                records.save(group)
                batch.group_id = group_id
            batch.status, batch.task_token, batch.error = "pending", str(uuid4()), None
            records.save(batch)
        return self._dispatch(batch, "process")

    def cancel(self, identity: str) -> Batch:
        with self.store.transaction() as records:
            batch = records.batch(identity)
            if batch.status not in ("pending", "processing"):
                raise MapError("Batch has no cancellable work", 409)
            batch.status = "cancelled"
            for item in batch.datasets:
                if item.selected and item.status != "done":
                    item.status = "cancelled"
            records.save(batch)
            return batch

    def retry(self, identity: str) -> Batch:
        with self.store.transaction() as records:
            batch = records.batch(identity)
            if batch.status not in ("failed", "cancelled", "inspection_failed"):
                raise MapError("Only failed or cancelled work can be retried", 409)
            action = "inspect" if batch.status == "inspection_failed" else "process"
            batch.status = "inspecting" if action == "inspect" else "pending"
            batch.error, batch.task_token = None, str(uuid4())
            for item in batch.datasets:
                if item.selected and item.status != "done":
                    item.status, item.error, item.progress = "pending", None, 0
            records.save(batch)
        return self._dispatch(batch, action)

    def run(self, identity: str, token: str, action: str) -> None:
        with self.store.transaction() as records:
            batch = records.batch(identity)
            expected = "inspecting" if action == "inspect" else "pending"
            if batch.task_token != token or batch.status != expected:
                return
            source = records.upload(batch.upload_id)
            batch.status = "inspecting_running" if action == "inspect" else "processing"
            records.save(batch)
        if action == "inspect":
            try:
                digest, items = self.renderer.inspect(source)
                for item in items:
                    # Dataset IDs are global database primary keys, so scope the
                    # stable archive path to this batch. The layer identity uses
                    # the same inputs and remains stable across retries.
                    item.id = str(uuid5(NAMESPACE_URL, f"tileserver:dataset:{batch.id}:{item.path.lower()}"))
                    item.layer_id = str(uuid5(NAMESPACE_URL, f"tileserver:layer:{batch.id}:{item.path.lower()}"))
                    item.code = suggested_code(item.name, item.layer_id)
                with self.store.transaction() as records:
                    current = records.batch(identity)
                    if current.task_token == token:
                        current.source_digest, current.datasets, current.status = digest, items, "ready"
                        records.save(current)
            except Exception as exc:
                self._fail(identity, token, str(exc), "inspection_failed")
            return
        try:
            for original in batch.datasets:
                if not original.selected or original.status == "done":
                    continue
                self._progress(identity, token, original.id, 0)
                try:
                    result = self.renderer.render(source, batch, original,
                        lambda value: self._progress(identity, token, original.id, value))
                    with self.store.transaction() as records:
                        current = records.batch(identity)
                        if current.task_token != token:
                            raise WorkCancelled()
                        item = next(item for item in current.datasets if item.id == original.id)
                        records.save(result)
                        item.status, item.progress, item.error = "done", 100, None
                        records.save(current)
                except WorkCancelled:
                    return
                except Exception as exc:
                    with self.store.transaction() as records:
                        current = records.batch(identity)
                        if current.task_token != token or current.status == "cancelled":
                            return
                        item = next(item for item in current.datasets if item.id == original.id)
                        item.status, item.error = "failed", str(exc)
                        records.save(current)
            with self.store.transaction() as records:
                current = records.batch(identity)
                if current.task_token != token or current.status == "cancelled":
                    return
                ready = all(item.status == "done" for item in current.datasets if item.selected)
                publish_error: str | None = None
                if ready and current.group_id:
                    group = records.group(current.group_id)
                    try:
                        self._publish(records, group)
                    except Exception as exc:
                        # Preserve completed member layers. A retry reaches this
                        # stage again without re-rendering them.
                        group.status, group.error = "failed", str(exc)
                        records.save(group)
                        publish_error = str(exc)
                current.status = "done" if ready and not publish_error else "failed"
                current.error = (
                    None if ready and not publish_error
                    else (f"Group publishing failed: {publish_error}" if publish_error
                          else "Some datasets failed; retry only unfinished datasets")
                )
                records.save(current)
        except WorkCancelled:
            return
        except Exception as exc:
            self._fail(identity, token, str(exc), "failed")

    def _progress(self, identity: str, token: str, item_id: str, value: int) -> None:
        with self.store.transaction() as records:
            current = records.batch(identity)
            if current.task_token != token or current.status == "cancelled":
                raise WorkCancelled()
            item = next(item for item in current.datasets if item.id == item_id)
            item.status, item.progress = "processing", max(0, min(99, int(value)))
            records.save(current)

    def _fail(self, identity: str, token: str, error: str, status: str) -> None:
        with self.store.transaction() as records:
            current = records.batch(identity)
            if current.task_token == token and current.status != "cancelled":
                current.status, current.error = status, error
                records.save(current)

    def _publish(self, records, group: Group) -> None:
        if not group.members:
            # A group with no members remains a reusable draft and must not
            # retain a stale public WMS/MVT representation.
            self.renderer.remove(group)
            group.revision += 1
            group.status, group.error = "draft", None
            records.save(group)
            return
        layers = [records.layer(member.layer_id) for member in group.members]
        if any(layer.output_format != group.output_format for layer in layers):
            raise MapError("All group members must use the group's output format")
        group.revision += 1
        self.renderer.publish(group, layers)
        group.status, group.error = ("published" if layers else "draft"), None
        records.save(group)

    def update_group(self, identity: str, name: str | None, members: list[dict], revision: int) -> Group:
        with self.store.transaction() as records:
            group = records.group(identity)
            if group.revision != revision:
                raise MapError("Group changed; reload before saving", 409)
            if len({item["layer_id"] for item in members}) != len(members):
                raise MapError("A layer can occur only once in a group")
            group = deepcopy(group)
            if name is not None:
                group.name = name
            group.members = [Member(**item) for item in members]
            self._publish(records, group)
            return group

    def delete_group(self, identity: str) -> None:
        with self.store.transaction() as records:
            group = records.group(identity)
            self.renderer.remove(group)
            records.remove_group(group.id)

    def deletion_guard(self, layer_id: str) -> None:
        with self.store.transaction() as records:
            groups = records.groups_using(layer_id)
            if groups:
                raise MapError("Remove layer from these groups first: " + ", ".join(group.code for group in groups), 409)
