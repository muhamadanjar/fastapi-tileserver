"""Behavioral tests for the batch inspect -> configure -> process lifecycle.

Uses the real application service (`MapBatches`) and real domain models
against an in-memory Catalog, so the invariants in app/application/map_batches.py
are exercised without a database or GeoServer.
"""
import pytest
from uuid import uuid5, NAMESPACE_URL

from app.application.map_batches import MapBatches
from app.domain.map_batches import Batch, Group, Member, LayerData, Dataset, MapError


# --- In-memory Catalog/Store ------------------------------------------------

class FakeCatalog:
    def __init__(self, store):
        self.s = store

    def batch(self, identity: str) -> Batch:
        if identity not in self.s._batches:
            raise MapError(f"Batch {identity} not found", 404)
        return self.s._batches[identity]

    def group(self, identity: str) -> Group:
        if identity not in self.s._groups:
            raise MapError(f"Group {identity} not found", 404)
        return self.s._groups[identity]

    def layer(self, identity: str) -> LayerData:
        if identity not in self.s._layers:
            raise MapError(f"Layer {identity} not found", 404)
        return self.s._layers[identity]

    def save(self, value):
        if isinstance(value, Batch):
            self.s._batches[value.id] = value
        elif isinstance(value, Group):
            self.s._groups[value.id] = value
        elif isinstance(value, LayerData):
            self.s._layers[value.id] = value
        else:
            raise TypeError(f"Cannot save {type(value)!r}")

    def groups(self) -> list[Group]:
        return list(self.s._groups.values())

    def groups_using(self, layer_id: str) -> list[Group]:
        return [g for g in self.s._groups.values()
                if any(m.layer_id == layer_id for m in g.members)]

    def reserve(self, code: str, owner: str) -> None:
        if code in self.s._reservations and self.s._reservations[code] != owner:
            raise MapError(f"Code {code} is already in use")
        self.s._reservations[code] = owner

    def remove_group(self, identity: str) -> None:
        self.s._groups.pop(identity, None)

    def upload(self, identity: str) -> dict:
        if identity not in self.s._uploads:
            raise MapError(f"Upload {identity} not found", 404)
        return self.s._uploads[identity]


class FakeStore:
    def __init__(self):
        self._batches: dict[str, Batch] = {}
        self._groups: dict[str, Group] = {}
        self._layers: dict[str, LayerData] = {}
        self._uploads: dict[str, dict] = {}
        self._reservations: dict[str, str] = {}

    def transaction(self):
        return _Tx(self)


class _Tx:
    def __init__(self, store):
        self._catalog = FakeCatalog(store)

    def __enter__(self):
        return self._catalog

    def __exit__(self, *exc):
        return False


# --- Fake renderer ----------------------------------------------------------

class FakeRenderer:
    def __init__(self):
        self.published: list[str | None] = []
        self.removed: list[str] = []

    def inspect(self, source: dict) -> tuple[str, list[Dataset]]:
        return "fake_sha256", [
            Dataset(id="roads", path="roads.shp", name="roads", geometry="LineString",
                    feature_count=10, bbox=[0, 0, 1, 1], valid=True,
                    style={"LineString": {"strokeColor": "#3388ff", "strokeWidth": 2}}),
            Dataset(id="parcels", path="parcels.shp", name="parcels", geometry="Polygon",
                    feature_count=5, bbox=[0, 0, 2, 2], valid=True,
                    style={"Polygon": {"fillColor": "#3388ff", "strokeColor": "#3388ff", "opacity": 0.5}}),
        ]

    def render(self, source: dict, batch: Batch, item: Dataset, progress) -> LayerData:
        progress(100)
        return LayerData(
            id=item.layer_id,
            code=item.code,
            name=item.name,
            output_format=batch.output_format,
            upload_id=batch.upload_id,
            bbox=list(item.bbox),
            style=item.style,
            metadata={},
            url=f"/tiles/{item.layer_id}/{{z}}/{{x}}/{{y}}.png",
        )

    def publish(self, group: Group, layers: list[LayerData]) -> None:
        self.published.append(group.id if group else None)

    def remove(self, group: Group) -> None:
        self.removed.append(group.id)

    def legend_for_group(self, group: Group, layers: list[LayerData]) -> list[dict]:
        by_id = {m.layer_id: m for m in group.members}
        return [{
            "layer_id": ld.id,
            "layer_name": ld.name or ld.id,
            "visible": by_id[ld.id].visible if ld.id in by_id else True,
            "sort_order": idx,
            "symbols": [],
        } for idx, ld in enumerate(layers)
          if by_id.get(ld.id, Member(ld.id)).visible]


# --- Helpers ----------------------------------------------------------------

def _make_batch(store: FakeStore, upload_id: str = "upload-1") -> Batch:
    """A ready-to-configure batch with two valid selected-able datasets."""
    store._uploads[upload_id] = {"filename": "multi.zip", "status": "done"}
    batch_id = str(uuid5(NAMESPACE_URL, f"tileserver:shapefile-batch:{upload_id}"))
    batch = Batch(
        id=batch_id, upload_id=upload_id, filename="multi.zip",
        status="ready", task_token="token",
        datasets=[
            Dataset(id="roads", path="roads.shp", name="roads", valid=True,
                    code="roads", layer_id="layer-roads", geometry="LineString",
                    style={"LineString": {"strokeColor": "#3388ff", "strokeWidth": 2}}),
            Dataset(id="parcels", path="parcels.shp", name="parcels", valid=True,
                    code="parcels", layer_id="layer-parcels", geometry="Polygon",
                    style={"Polygon": {"fillColor": "#3388ff", "strokeColor": "#3388ff", "opacity": 0.5}}),
        ],
    )
    store._batches[batch.id] = batch
    return batch


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def renderer():
    return FakeRenderer()


@pytest.fixture
def usecase(store, renderer):
    return MapBatches(store=store, renderer=renderer, enqueue=lambda *a, **kw: None)


# --- Deletion guard ---------------------------------------------------------

class TestDeletionGuard:
    def test_no_groups_passes(self, usecase):
        usecase.deletion_guard("layer-1")  # must not raise

    def test_groups_used_raises(self, store, usecase):
        store._groups["g1"] = Group(id="g1", code="my-group", name="G",
                                    output_format="raster",
                                    members=[Member(layer_id="layer-1")])
        with pytest.raises(MapError) as exc:
            usecase.deletion_guard("layer-1")
        assert exc.value.status == 409
        assert "my-group" in exc.value.message


# --- Inspect ----------------------------------------------------------------

class TestInspect:
    def test_returns_existing_ready_batch(self, store, usecase):
        batch = _make_batch(store)
        result = usecase.inspect("upload-1")
        assert result.id == batch.id
        assert result.status == "ready"

    def test_unknown_upload_raises_404(self, usecase):
        with pytest.raises(MapError) as exc:
            usecase.inspect("nonexistent-upload")
        assert exc.value.status == 404


# --- Configure --------------------------------------------------------------

class TestConfigureAndStart:
    def test_group_mode(self, store, usecase):
        batch = _make_batch(store)
        config = {
            "mode": "group", "output_format": "raster", "max_zoom": 10,
            "name": "Test Group", "datasets": [{"id": "roads"}, {"id": "parcels"}],
        }
        result = usecase.configure_and_start(batch.id, config)
        assert result.mode == "group"
        assert result.group_id is not None
        assert result.status == "pending"
        group = store._groups[result.group_id]
        assert group.code.startswith("test-group-")
        assert [m.layer_id for m in group.members] == ["layer-roads", "layer-parcels"]

    def test_separate_mode_has_no_group(self, store, usecase):
        batch = _make_batch(store)
        result = usecase.configure_and_start(batch.id, {"mode": "separate", "output_format": "mvt",
                                                        "datasets": [{"id": "roads"}]})
        assert result.mode == "separate"
        assert result.group_id is None

    def test_invalid_status_rejected(self, store, usecase):
        batch = _make_batch(store)
        batch.status = "processing"
        with pytest.raises(MapError) as exc:
            usecase.configure_and_start(batch.id, {"mode": "group", "datasets": [{"id": "roads"}]})
        assert exc.value.status == 409

    def test_invalid_dataset_rejected(self, store, usecase):
        batch = _make_batch(store)
        batch.datasets[0].valid = False
        with pytest.raises(MapError) as exc:
            usecase.configure_and_start(batch.id, {"mode": "group", "output_format": "raster",
                                                    "datasets": [{"id": "roads"}]})
        assert "valid" in exc.value.message


# --- Process ----------------------------------------------------------------

class TestRunProcess:
    def test_process_separate_done(self, store, usecase):
        batch = _make_batch(store)
        usecase.configure_and_start(batch.id, {"mode": "separate", "output_format": "raster",
                                               "datasets": [{"id": "roads"}, {"id": "parcels"}]})
        usecase.run(batch.id, batch.task_token, "process")
        assert batch.status == "done"
        assert all(d.status == "done" for d in batch.datasets if d.selected)

    def test_process_group_publishes(self, store, usecase, renderer):
        batch = _make_batch(store)
        usecase.configure_and_start(
            batch.id,
            {"mode": "group", "output_format": "raster", "name": "Test Group",
             "datasets": [{"id": "roads"}, {"id": "parcels"}]},
        )
        usecase.run(batch.id, batch.task_token, "process")
        assert batch.status == "done"
        group = store._groups[batch.group_id]
        assert group.status == "published"
        assert group.revision == 1
        assert batch.group_id in renderer.published

    def test_group_publish_failure_keeps_layers_for_retry(self, store, usecase, renderer):
        batch = _make_batch(store)
        usecase.configure_and_start(
            batch.id,
            {"mode": "group", "output_format": "raster", "datasets": [{"id": "roads"}]},
        )
        original_publish = renderer.publish
        renderer.publish = lambda group, layers: (_ for _ in ()).throw(RuntimeError("GeoServer unavailable"))

        usecase.run(batch.id, batch.task_token, "process")

        assert batch.status == "failed"
        assert batch.datasets[0].status == "done"
        assert store._groups[batch.group_id].status == "failed"
        renderer.publish = original_publish
        usecase.retry(batch.id)
        usecase.run(batch.id, batch.task_token, "process")
        assert batch.status == "done"


# --- Group CRUD -------------------------------------------------------------

class TestGroupCrud:
    def test_update_group_bumps_revision(self, store, usecase, renderer):
        g = Group(id="g1", code="old-1", name="Old", output_format="raster", revision=1,
                  members=[Member(layer_id="layer-a", visible=True)])
        store._groups["g1"] = g
        store._layers["layer-a"] = LayerData(
            id="layer-a", code="a", name="A", output_format="raster",
            upload_id=None, bbox=[], style={}, metadata={}, url="/tiles/a/{z}/{x}/{y}.png")
        result = usecase.update_group("g1", "New", [{"layer_id": "layer-a", "visible": True}], 1)
        assert result.name == "New"
        assert result.revision == 2
        assert "g1" in renderer.published

    def test_update_group_stale_revision_rejected(self, store, usecase):
        g = Group(id="g1", code="old-1", name="Old", output_format="raster", revision=1)
        store._groups["g1"] = g
        with pytest.raises(MapError) as exc:
            usecase.update_group("g1", "New", [], 0)
        assert exc.value.status == 409

    def test_update_group_without_name_preserves_display_name(self, store, usecase):
        g = Group(id="g1", code="old-1", name="Original", output_format="raster", revision=1,
                  members=[Member(layer_id="layer-a", visible=True)])
        store._groups["g1"] = g
        store._layers["layer-a"] = LayerData(
            id="layer-a", code="a", name="A", output_format="raster",
            upload_id=None, bbox=[], style={}, metadata={}, url="")

        result = usecase.update_group("g1", None, [{"layer_id": "layer-a", "visible": False}], 1)

        assert result.name == "Original"

    def test_delete_group_removes_it(self, store, usecase, renderer):
        store._groups["g1"] = Group(id="g1", code="test-1", name="Test",
                                    output_format="raster",
                                    members=[Member(layer_id="layer-a")])
        usecase.delete_group("g1")
        assert "g1" not in store._groups
        assert "g1" in renderer.removed


# --- Legend -----------------------------------------------------------------

class TestLegendForGroup:
    def test_legend_supports_real_models(self, renderer):
        g = Group(id="g1", code="test-1", name="Test", output_format="wms",
                  members=[Member(layer_id="layer-a", visible=True),
                           Member(layer_id="layer-b", visible=False)])
        layers = [
            LayerData(id="layer-a", code="a", name="Layer A", output_format="wms",
                      upload_id=None, bbox=[], style={}, metadata={}, url=""),
            LayerData(id="layer-b", code="b", name="Layer B", output_format="wms",
                      upload_id=None, bbox=[], style={}, metadata={}, url=""),
        ]
        legend = renderer.legend_for_group(g, layers)
        assert len(legend) == 1
        assert legend[0]["layer_id"] == "layer-a"
        assert legend[0]["visible"] is True
